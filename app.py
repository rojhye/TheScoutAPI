"""
FastAPI v0 skeleton for TheScout MVP
- Endpoints per §7 of the build plan
- In-memory store for quick start; swap with Postgres/Supabase later
- Env var: OPENAI_API_KEY (optional now)
Run: uvicorn app:app --reload
"""
from __future__ import annotations
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from uuid import uuid4
import time

app = FastAPI(title="TheScout API (v0)", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------
# In-memory storage
# -----------------
DB: Dict[str, Dict] = {
    "users": {},
    "roles": {},
    "candidates": {},
    "candidate_submissions": {},
    "matches": {},
    "events": {},
}

def _id() -> str:
    return uuid4().hex

# -----------------
# Models
# -----------------
class RTI(BaseModel):
    must: List[str] = []
    nice: List[str] = []
    knockout: List[str] = []
    weights: Dict[str, float] = Field(default_factory=lambda: {"must": 0.6, "nice": 0.3, "bonus": 0.1})
    compensation: Dict[str, str] = Field(default_factory=dict)
    screen_questions: List[str] = Field(default_factory=list)

class RoleCreate(BaseModel):
    project_id: Optional[str] = None
    title: str
    level: Optional[str] = None
    location: Optional[str] = None
    jd_raw: str

class Role(RoleCreate):
    id: str
    rti_json: RTI
    share_token: Optional[str] = None

class RTIUpdate(BaseModel):
    rti_json: RTI

class CandidateProfile(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    skills: List[str] = []
    years_exp: Optional[float] = None
    latest_project: Optional[str] = None
    visa_status: Optional[str] = None
    notice_period: Optional[str] = None
    location: Optional[str] = None
    expected_comp: Optional[str] = None

class CandidateIntake(BaseModel):
    profile: CandidateProfile
    resume_url: Optional[str] = None
    consent_bool: bool = True

class MatchResult(BaseModel):
    candidate_id: str
    score_int: int
    rationale: List[str] = []
    flags: List[str] = []

# -----------------
# Utilities
# -----------------
DEFAULT_RTI = RTI(
    must=["3y+ backend", "Python", "Korean C1"],
    nice=["FastAPI", "AWS", "ML ops"],
    knockout=["No work authorization"],
    weights={"must": 0.6, "nice": 0.3, "bonus": 0.1},
    screen_questions=[
        "Latest backend project?",
        "Visa status?",
        "Notice period?",
    ],
)


def draft_rti(jd_raw: str) -> RTI:
    """Very naive RTI draft. Replace with LLM later."""
    text = jd_raw.lower()
    must = []
    if "python" in text:
        must.append("Python")
    if "backend" in text:
        must.append("3y+ backend")
    nice = [s for s in ["FastAPI", "AWS", "Postgres"] if s.lower() in text]
    return RTI(
        must=list(dict.fromkeys(must or DEFAULT_RTI.must)),
        nice=list(dict.fromkeys(nice or DEFAULT_RTI.nice)),
        knockout=DEFAULT_RTI.knockout,
        weights=DEFAULT_RTI.weights,
        screen_questions=DEFAULT_RTI.screen_questions,
    )


def compute_score(rti: RTI, prof: CandidateProfile) -> MatchResult:
    # Knockouts
    flags = []
    if prof is None:
        return MatchResult(candidate_id="", score_int=0, rationale=["No profile"], flags=["KO: empty profile"]) 
    if not prof.email:
        flags.append("Missing email")
    # Simple rules engine
    rules_hits = 0
    rules_total = max(1, len(rti.must))
    skills = set((prof.skills or []))
    rationale = []
    for m in rti.must:
        if any(m.lower() in s.lower() for s in skills):
            rules_hits += 1
            rationale.append(f"+ {m} (must)")
        else:
            rationale.append(f"- {m} (missing)")
    rules_score = rules_hits / rules_total
    # Cosine placeholder → treat as overlap ratio of nice-to-have
    nice_hits = sum(1 for n in rti.nice if any(n.lower() in s.lower() for s in skills))
    nice_score = nice_hits / max(1, len(rti.nice))
    score = int(round(100 * (0.7 * rules_score + 0.3 * nice_score)))
    if not prof.consent_bool if hasattr(prof, 'consent_bool') else False:
        flags.append("No consent")
        score = 0
    return MatchResult(candidate_id="", score_int=score, rationale=rationale, flags=flags)

# -----------------
# Endpoints
# -----------------
@app.post("/roles", response_model=Role)
def create_role(payload: RoleCreate):
    role_id = _id()
    rti = draft_rti(payload.jd_raw)
    role = Role(id=role_id, rti_json=rti, **payload.dict())
    DB["roles"][role_id] = role.dict()
    return role

@app.put("/roles/{role_id}/rti", response_model=Role)
def update_rti(role_id: str, payload: RTIUpdate):
    role = DB["roles"].get(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    role["rti_json"] = payload.rti_json.dict()
    DB["roles"][role_id] = role
    return Role(**role)

@app.get("/roles/{role_id}/share", response_model=Dict[str, str])
def get_share(role_id: str):
    role = DB["roles"].get(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    token = role.get("share_token") or uuid4().hex[:12]
    role["share_token"] = token
    DB["roles"][role_id] = role
    return {"share_token": token}

@app.post("/apply/{share_token}", response_model=Dict[str, str])
def apply_to_role(share_token: str, payload: CandidateIntake):
    # find role by token
    role_id = next((rid for rid, r in DB["roles"].items() if r.get("share_token") == share_token), None)
    if not role_id:
        raise HTTPException(404, "Role token invalid")
    cand_id = _id()
    DB["candidates"][cand_id] = payload.profile.dict()
    sub_id = _id()
    DB["candidate_submissions"][sub_id] = {
        "id": sub_id,
        "role_id": role_id,
        "candidate_id": cand_id,
        "resume_url": payload.resume_url,
        "profile_json": payload.profile.dict(),
        "consent_bool": payload.consent_bool,
        "ts": int(time.time()),
    }
    return {"candidate_id": cand_id}

@app.post("/match/{role_id}", response_model=Dict[str, int])
def match_role(role_id: str):
    role = DB["roles"].get(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    rti = RTI(**role["rti_json"]) if isinstance(role["rti_json"], dict) else role["rti_json"]
    # find submissions for this role
    subs = [s for s in DB["candidate_submissions"].values() if s["role_id"] == role_id]
    count = 0
    for s in subs:
        prof = CandidateProfile(**s["profile_json"])
        mr = compute_score(rti, prof)
        mr_dict = mr.dict()
        mr_id = _id()
        mr_dict.update({"candidate_id": s["candidate_id"], "id": mr_id, "role_id": role_id})
        DB["matches"][mr_id] = mr_dict
        count += 1
    return {"scored": count}

@app.get("/shortlist/{role_id}", response_model=List[MatchResult])
def shortlist(role_id: str, min_score: int = 0):
    rows = [m for m in DB["matches"].values() if m.get("role_id") == role_id and m.get("score_int", 0) >= min_score]
    rows.sort(key=lambda x: x.get("score_int", 0), reverse=True)
    return [MatchResult(candidate_id=r["candidate_id"], score_int=r["score_int"], rationale=r.get("rationale", []), flags=r.get("flags", [])) for r in rows]

# Health
@app.get("/health")
def health():
    return {"ok": True}
