import os

from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI
import psycopg

# 1) .env 로드
load_dotenv(find_dotenv())

# 2) 개별 항목으로 DB 설정 읽기
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

missing = [name for name, value in [
    ("DB_HOST", DB_HOST),
    ("DB_NAME", DB_NAME),
    ("DB_USER", DB_USER),
    ("DB_PASSWORD", DB_PASSWORD),
] if not value]

if missing:
    raise RuntimeError(f"DB 설정 누락: {', '.join(missing)} (.env 또는 GitHub Secrets 확인 필요)")


def get_db_conn() -> psycopg.Connection:
    """Supabase Postgres에 직접 연결 (sslmode=require)."""
    return psycopg.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode="require",
        connect_timeout=10,
    )


app = FastAPI(title="TheScout DB API")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.get("/db-ping")
def db_ping() -> dict:
    """DB 연결 상태를 확인하고, 에러가 나면 에러 메시지를 그대로 반환."""
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                (value,) = cur.fetchone()
        return {"db": "ok", "value": value}
    except Exception as e:
        return {"db": "error", "detail": str(e)}
