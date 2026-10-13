# Business Management Software (company test)

## Goal
Implement ONLY the functionality listed below. Anything not listed is out of scope. Do not add Production, Assets, a separate Reports module, VAT/Mushak, Bangla UI, multi-company, microservices, or CI/CD.
Priority: the full cycle must work reliably:
Supplier -> Purchase -> Stock -> Sale -> Customer Due -> Collection -> Cash/Bank/MFS -> Expense -> Management Dashboard.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x (typed), Alembic, Pydantic v2, PyMySQL, PyJWT, bcrypt, pytest, ruff.
- Database: MySQL 8 (InnoDB, utf8mb4). Tests also run on MySQL (database `bms_test`), never SQLite.
- Frontend: React + TypeScript + Vite, Ant Design, TanStack Query, React Router, axios, dayjs. Use Ant Design Form for forms.
- Infra: docker-compose (mysql, backend, frontend). Config via .env.

## Architecture: modular monolith
```
backend/app/
  core/      config.py, db.py, security.py, deps.py (auth + require_permission), audit.py, numbering.py, errors.py, pagination.py, permissions.py
  modules/<module>/  models.py, schemas.py, service.py, router.py
  main.py    registers all routers under /api/v1
```
Modules: auth, admin, master, parties, inventory, purchase, money, sales, approvals, employees, dashboard.
```
frontend/src/ api/, components/, hooks/, layouts/, pages/<module>/, routes/, utils/
```

## Hard rules (never break)
1. Routers are thin. ALL business logic lives in service.py. Services take a SQLAlchemy Session and the acting user.
2. Money: DECIMAL(18,2). Quantity: DECIMAL(18,3). Unit cost: DECIMAL(18,4). Use Python Decimal. Never float. API returns decimals as strings.
3. Stock and money ledgers are APPEND-ONLY. Never UPDATE or DELETE ledger rows. Corrections are reversing entries.
4. Every posting (anything touching stock, money, party ledger) runs in ONE database transaction. All succeed or none.
5. When changing stock_balances, money balances, or document sequences, lock the row with SELECT ... FOR UPDATE.
6. Block negative stock and negative money-account balance with a clear error. Block over-delivery and over-receipt.
7. Every endpoint (except login/forgot/reset/health) requires auth AND a permission via `require_permission("<resource>.<action>")`. Frontend hides what the user cannot do, but the backend is the real guard.
8. Write an audit_logs row for: login, create, update, delete/deactivate, post, approve, reject, cancel.
9. Master data is never hard-deleted once used; use is_active.
10. Document numbers come only from core/numbering.py (e.g. PO-000001).
11. Every posting service has pytest tests. Run `pytest` and `ruff check` before saying a task is done.
12. Do not invent features. If a requirement is ambiguous, follow docs/BUSINESS_RULES.md; if still ambiguous choose the simplest option and record it in docs/ASSUMPTIONS.md.
13. After each task, append a short entry to docs/PROGRESS.md (what was done, what is next).

## API conventions
- Prefix /api/v1. JSON only.
- List endpoints: query params `page`, `page_size`, `search`, plus filters. Response `{ "items": [], "total": 0, "page": 1, "page_size": 20 }`.
- Errors: `{ "detail": "human readable", "code": "MACHINE_CODE" }` with proper HTTP status (400 business rule, 401, 403, 404, 409, 422).
- Dates: ISO 8601. Server timezone for "today" = Asia/Dhaka.

## Frontend conventions
- One generic `CrudPage`, `DocLineItems` editable table, `MoneyText`, `StatusTag`, `PageHeader`, `Can`, `usePermission` reused everywhere. Do not copy-paste table/form code per screen.
- Every page has loading, empty, and error states. Every form shows backend validation errors.
- Server state via TanStack Query only.
