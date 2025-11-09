# app_db.py
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv, dotenv_values
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import psycopg

# ── .env 로드(경로 고정 + 방어) ─────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
DOTENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=DOTENV_PATH, override=True, encoding="utf-8")
_raw_map = dotenv_values(DOTENV_PATH) if DOTENV_PATH.exists() else {}


def _norm_key(k: str) -> str:
    return k.replace("\ufeff", "").strip().lower()


def _norm_val(v: str | None) -> str | None:
    return None if v is None else v.strip().strip('"').strip("'")


_env = {_norm_key(k): _norm_val(v) for k, v in os.environ.items() if isinstance(k, str)}
_file = {_norm_key(k): _norm_val(v) for k, v in _raw_map.items() if isinstance(k, str)}


def get_cfg(name: str, default: str | None = None) -> str | None:
    k = _norm_key(name)
    return _env.get(k) or _file.get(k) or default


raw_db_url = get_cfg("SUPABASE_DB_URL")
if not raw_db_url:
    raise RuntimeError(f"SUPABASE_DB_URL not found. Checked env and {DOTENV_PATH}")

parts = urlsplit(raw_db_url)
BASE_DSN = urlunsplit(("postgresql", parts.netloc, parts.path, "", ""))

# 선택 설정(현재 미사용 → 언더스코어로 Lint 회피)
_APP_HOST = get_cfg("APP_HOST", "127.0.0.1")
_APP_PORT = int(get_cfg("APP_PORT", "8000"))
_APP_RELOAD = get_cfg("APP_RELOAD", "true").lower() == "true"

# ── FastAPI ────────────────────────────────────────────────────────────────
app = FastAPI(title="TheScout API v1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── DB 연결 의존성 ─────────────────────────────────────────────────────────
def get_conn():
    with psycopg.connect(BASE_DSN, sslmode="require") as conn:
        yield conn


# ── 기본 라우트 ────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "app": "TheScout API v1",
        "health": "/health",
        "version": "/version",
        "db_now": "/db/now",
        "candidates": "/candidates",
    }


@app.get("/health")
def health(conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("select 'ok'")
        return {"status": cur.fetchone()[0]}


@app.get("/version")
def version():
    return {"app": "TheScout API v1"}


@app.get("/db/now")
def db_now(conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("select now()")
        (ts,) = cur.fetchone()
        return {"db_now": ts.isoformat()}


# ── Candidates CRUD ────────────────────────────────────────────────────────
class CandidateIn(BaseModel):
    name: str
    # Optional 대신 | None 문법 권장. Optional 쓰고 있으면 위 typing import 유지.
    email: EmailStr | None = None


@app.get("/candidates")
def list_candidates(conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text, name, email, created_at
            from candidates
            order by created_at desc
            limit 100
        """
        )
        rows = cur.fetchall()
        return [
            {"id": r[0], "name": r[1], "email": r[2], "created_at": r[3].isoformat()} for r in rows
        ]


@app.post("/candidates", status_code=201)
def create_candidate(payload: CandidateIn, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "insert into candidates(name, email) values (%s, %s) returning id::text, created_at",
            (payload.name, payload.email),
        )
        cid, ts = cur.fetchone()
        return {
            "id": cid,
            "name": payload.name,
            "email": payload.email,
            "created_at": ts.isoformat(),
        }


@app.get("/candidates/{cid}")
def get_candidate(cid: str, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            "select id::text, name, email, created_at from candidates where id = %s", (cid,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return {"id": row[0], "name": row[1], "email": row[2], "created_at": row[3].isoformat()}


@app.delete("/candidates/{cid}", status_code=204)
def delete_candidate(cid: str, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("delete from candidates where id = %s", (cid,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Not found")
        return
