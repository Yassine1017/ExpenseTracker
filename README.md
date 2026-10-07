# Smart Expense Tracker

A private Flask, SQLite, and React expense tracker with manual transactions, SMS imports, budgets, reports, backups, and learned parser rules.

## Local Development

```powershell
pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
$env:FLASK_DEBUG="1"
python app.py
```

Open:

```text
http://127.0.0.1:5000/
```

## Production

See `PRODUCTION.md`.

## Multi-User Later

Public registration is intentionally not enabled yet. See `MULTI_USER_PLAN.md` for the future user-account migration design and readiness checklist.

Basic production command:

```powershell
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

Use `.env.example` as the environment variable checklist.
