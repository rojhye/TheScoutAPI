import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from dotenv import load_dotenv
import psycopg

project_root = Path(__file__).resolve().parent
dotenv_path = project_root / ".env"
print("PROJECT_ROOT:", project_root)
print(".env exists?:", dotenv_path.exists(), "path:", dotenv_path)

# .env 로드 (UTF-8 명시)
load_dotenv(dotenv_path=dotenv_path, override=True, encoding="utf-8")

raw = os.getenv("SUPABASE_DB_URL")
print("RAW URL present?:", bool(raw))
if not raw:
    raise RuntimeError("SUPABASE_DB_URL is missing. Check your .env file content and filename.")

parts = urlsplit(raw)
base = urlunsplit(("postgresql", parts.netloc, parts.path, "", ""))
print("Connecting to:", base)

with psycopg.connect(base, autocommit=True, sslmode="require") as conn:
    with conn.cursor() as cur:
        cur.execute("select 1")
        print("OK:", cur.fetchone())
