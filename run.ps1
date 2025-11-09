Set-Location 
python -m uvicorn app_db:app --host 127.0.0.1 --port 8000 --env-file .env --reload