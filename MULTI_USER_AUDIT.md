# Multi-User Isolation Audit

## Completed

- Scoped transaction, import, rule, alias, parser-rule, budget, and settings reads to the active user.
- Rebuilt old single-user uniqueness constraints so category rules, merchant aliases, category budgets, and learned SMS parser rules are unique per user instead of globally.
- Tightened older form fallback routes that still accepted raw transaction, import, rule, and alias ids.
- Tightened React API import actions so one user cannot delete, repair, convert, save, AI-parse, or learn from another user's import row.
- Added regression tests for cross-user transaction visibility, transaction edit/delete protection, import delete/save protection, and duplicate rule/budget names across users.

## Caution

- Backups and restores remain whole-database operations. Keep them admin/private unless the app later adds per-user export and deletion tools.
- Public registration should stay disabled until every new feature gets the same ownership tests.
