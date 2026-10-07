# Multi-User Preparation Plan

This app should stay single-user until the private app is reliable enough to protect more than one person's finance data. This document is the internal plan for adding users later without activating public registration today.

## Current Status

The current app is a private single-user expense tracker. It has:

- password-protected access
- one app-wide Shortcut API key
- one SQLite database
- manual transactions
- SMS imports
- review queue
- budgets
- reports
- backups and restore

This is good for a personal setup, but public registration should wait.

## Registration Go/No-Go Checklist

Only build registration after these are true:

- Import review queue works well with real messages.
- Backup and restore have been tested with real backups.
- API key protection is stable.
- You know at least one friend will actually use the app.
- The app is hosted online with HTTPS.
- Flask is running with a production server such as Waitress.
- Session cookies use `SESSION_COOKIE_SECURE=1`.
- A backup exists before any user-data migration.

## Future Data Model

The important change is that every private object needs an owner.

### New `users` table

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    api_key TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
```

### Add `user_id` to private tables

These tables should receive a `user_id` column:

- `transactions`
- `imported_messages`
- `category_rules`
- `category_budgets`
- `merchant_aliases`
- `sms_parser_rules`
- future notification or prediction tables

Suggested migration pattern:

```sql
ALTER TABLE transactions ADD COLUMN user_id INTEGER;
ALTER TABLE imported_messages ADD COLUMN user_id INTEGER;
ALTER TABLE category_rules ADD COLUMN user_id INTEGER;
ALTER TABLE category_budgets ADD COLUMN user_id INTEGER;
ALTER TABLE merchant_aliases ADD COLUMN user_id INTEGER;
ALTER TABLE sms_parser_rules ADD COLUMN user_id INTEGER;
```

Then create one owner user and assign existing rows to that user.

```sql
UPDATE transactions SET user_id = 1 WHERE user_id IS NULL;
UPDATE imported_messages SET user_id = 1 WHERE user_id IS NULL;
UPDATE category_rules SET user_id = 1 WHERE user_id IS NULL;
UPDATE category_budgets SET user_id = 1 WHERE user_id IS NULL;
UPDATE merchant_aliases SET user_id = 1 WHERE user_id IS NULL;
UPDATE sms_parser_rules SET user_id = 1 WHERE user_id IS NULL;
```

After the app is fully updated, future migrations should enforce `NOT NULL` ownership.

## Backend Architecture Changes

### Authentication

Replace the current single password setting with:

- `/login`
- `/logout`
- optional invite-only `/register`
- password hashing with Werkzeug, already used by the app
- session stores `user_id`, not only `logged_in`

### API Keys

Move from one app-wide API key to one API key per user.

The iPhone Shortcut should send:

```text
X-API-Key: user's personal key
```

The backend finds the matching user from the API key, then imports the SMS under that user's `user_id`.

### Query Safety

Every private query must filter by the current user.

Example:

```sql
SELECT *
FROM transactions
WHERE user_id = ?
ORDER BY date DESC;
```

Never rely on frontend filtering for user privacy.

## Frontend Architecture Changes

React should receive the current user from an endpoint such as:

```text
GET /api/session
```

That endpoint can return:

```json
{
  "authenticated": true,
  "user": {
    "id": 1,
    "email": "owner@example.com",
    "display_name": "Owner"
  }
}
```

Future pages:

- Account settings
- Regenerate personal API key
- Invite user
- Register from invite
- Admin user list, only if needed

## Backup and Restore Changes

For single-user mode, full-database backup is simple and useful.

For multi-user mode, decide between:

- full server backup, admin only
- per-user export, safer for users
- per-user delete/export tools if the app becomes public

Do not let a normal user restore the whole database.

## Deployment Requirements

Before multi-user:

- HTTPS domain
- stable server
- production WSGI server
- secure cookies
- database backups outside the web directory
- environment variables for secrets
- no Flask debug mode online

## Recommended Rollout

1. Keep the app single-user.
2. Finish reliability: imports, review queue, backups, and parser rules.
3. Add `users` table in a test copy of the database.
4. Add `user_id` filters in backend APIs.
5. Migrate existing rows to the owner user.
6. Add invite-only registration.
7. Test with one friend.
8. Only then consider public registration.

