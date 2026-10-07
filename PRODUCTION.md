# Production Setup

This app can still run locally with Flask, but for a reliable private deployment you should run it with a production server such as Waitress.

## 1. Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Build the React frontend

```powershell
cd frontend
npm install
npm run build
cd ..
```

## 3. Set environment variables

Use `.env.example` as the checklist. For local PowerShell testing:

```powershell
$env:FLASK_SECRET_KEY="replace-with-a-long-random-secret"
$env:EXPENSE_TRACKER_API_KEY="replace-with-a-long-random-api-key"
$env:DATABASE_PATH="C:\Users\Computia.ME\Documents\ExpenseTracker\expense_tracker.db"
$env:BACKUP_DIR="C:\Users\Computia.ME\Documents\ExpenseTracker\backups"
$env:SESSION_COOKIE_SECURE="0"
```

When hosted behind HTTPS, set:

```powershell
$env:SESSION_COOKIE_SECURE="1"
```

## 4. Run locally for development

```powershell
$env:FLASK_DEBUG="1"
python app.py
```

Open:

```text
http://127.0.0.1:5000/
```

## 5. Run with Waitress

```powershell
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

This is better than Flask debug mode for a private hosted app.

## 6. iPhone Shortcut URL

After deployment, update the Shortcut URL from the local/ngrok URL to:

```text
https://your-domain.com/import-message
```

Keep the header:

```text
X-API-Key
```

Use the API key shown in Settings.

## 7. Backups

Use Settings to create backups before major changes. The restore tool creates a safety backup before replacing the database.

Store backups outside the public web directory.

## 8. Recommended next hosting setup

- Small VPS
- HTTPS reverse proxy
- Stable domain
- Waitress serving Flask
- SQLite database on persistent disk
- Regular manual or scheduled backups

## 9. Multi-user caution

Do not enable public registration until the checklist in `MULTI_USER_PLAN.md` is complete. Multi-user support requires per-user ownership for transactions, imports, budgets, rules, aliases, parser rules, backups, and API keys.
