# app_db.py
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv, dotenv_values
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import psycopg


# ──────────────────────────────────────────────────────────────
# 환경변수(.env) 로드 — 경로 고정 + BOM/대소문자/공백 방어
# ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
DOTENV_PATH = PROJECT_ROOT / ".env"

# 1) 표준 로드(UTF-8)
load_dotenv(dotenv_path=DOTENV_PATH, override=True, encoding="utf-8")

# 2) 실패 대비: 파일 직접 파싱
raw_map = dotenv_values(DOTENV_PATH) if DOTENV_PATH.exists() else {}


def _norm_key(k: str) -> str:
    # BOM 제거, 앞뒤 공백 제거, 소문자로 통일
    return k.replace("\ufeff", "").strip().lower()


def _norm_val(v: str | None) -> str | None:
    if v is None:
        return None
    return v.strip().strip('"').strip("'")


# 프로세스 환경 + 파일 값 모두 정규화해 병합
env_map = {_norm_key(k): _norm_val(v) for k, v in os.environ.items() if isinstance(k, str)}
file_map = {_norm_key(k): _norm_val(v) for k, v in raw_map.items() if isinstance(k, str)}


def get_cfg(name: str, default: str | None = None) -> str | None:
    k = _norm_key(name)
    return env_map.get(k) or file_map.get(k) or default


raw_db_url = get_cfg("SUPABASE_DB_URL")
if not raw_db_url:
    raise RuntimeError(f"SUPABASE_DB_URL not found. Checked env and {DOTENV_PATH}")

# 드라이버/쿼리 제거하여 DSN 정규화
# 예: postgresql+asyncpg://...?... → postgresql://... (쿼리 제거)
_parts = urlsplit(raw_db_url)
BASE_DSN = urlunsplit(("postgresql", _parts.netloc, _parts.path, "", ""))

# 선택적 앱 설정 (없으면 기본값 사용)
APP_HOST = get_cfg("APP_HOST", "127.0.0.1")
APP_PORT = int(get_cfg("APP_PORT", "8000"))
APP_RELOAD = get_cfg("APP_RELOAD", "true").lower() == "true"


# ──────────────────────────────────────────────────────────────
# FastAPI 본체 + CORS
# ──────────────────────────────────────────────────────────────
app = FastAPI(title="TheScout API v1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 필요 시 특정 도메인으로 제한
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────
# DB 연결 의존성(요청마다 짧게 연결). 추후 풀/ORM로 리팩터 권장.
# ──────────────────────────────────────────────────────────────
def get_conn():
    with psycopg.connect(BASE_DSN, sslmode="require") as conn:
        yield conn


# ──────────────────────────────────────────────────────────────
# 라우트
# ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "app": "TheScout API v1",
        "health": "/health",
        "version": "/version",
        "db_now": "/db/now",
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


from fastapi import HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional


class CandidateIn(BaseModel):
    name: str
    email: Optional[EmailStr] = None


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
        # rowcount가 0이면 없던 것
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Not found")
        return
