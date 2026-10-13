# Business Management Software

A business management system for a small manufacturer and trader. It covers one cycle reliably, from start to finish:

> Supplier → Purchase → Stock → Sale → Customer Due → Collection → Cash / Bank / MFS → Expense → Management Dashboard

Around that cycle there are master data, quotations, reservations, returns, approvals, basic attendance and payroll, an audit log, and role-based access.

The specification is in `CLAUDE.md` and `docs/BUSINESS_RULES.md`. Decisions made where the specification was silent are in `docs/ASSUMPTIONS.md`, and per-task history is in `docs/PROGRESS.md`.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (typed), Alembic, Pydantic v2, PyMySQL, PyJWT, bcrypt |
| Database | MySQL 8 (InnoDB, utf8mb4); tests also run on MySQL |
| Frontend | React 19, TypeScript, Vite, Ant Design 6, TanStack Query, React Router, axios, dayjs, Recharts (dashboard chart only) |
| Quality | pytest, ruff; frontend type-checked by `tsc` (strict, no unused locals or parameters) |
| Infrastructure | docker-compose (mysql, backend, frontend), configured with `.env` |

## Architecture

The backend is a modular monolith: one FastAPI app, one database, one module per business area.

```
                        ┌──────────────────────────────────────────────┐
  Browser (React SPA)   │  pages/<module>  →  api/<module>.ts (axios)  │
  Ant Design + Query    │  CrudPage · DocLineItems · MoneyText · Can   │
                        └───────────────────────┬──────────────────────┘
                                                │ JSON  /api/v1  (JWT bearer)
                        ┌───────────────────────▼──────────────────────┐
  FastAPI               │ router.py   thin: auth + require_permission  │
  backend/app/modules/  │ service.py  ALL business logic, 1 tx/posting │
   auth admin master    │ models.py   SQLAlchemy (typed)               │
   parties inventory    │ schemas.py  Pydantic v2 (Decimal → string)   │
   purchase sales money │                                              │
   approvals employees  │ core/: db (atomic) · numbering · audit ·     │
   dashboard            │        security · deps · errors · pagination │
                        └───────────────────────┬──────────────────────┘
                                                │ SQLAlchemy / PyMySQL
                        ┌───────────────────────▼──────────────────────┐
  MySQL 8               │ documents · stock_balances · money_accounts  │
                        │ append-only ledgers (stock / money / party,  │
                        │ UPDATE/DELETE blocked by triggers) · views   │
                        └──────────────────────────────────────────────┘
```

**How modules share logic.** Modules call each other's services rather than copying them:
- sales uses `inventory.stock_out` / `reserve`, `parties.post_party_entry` and `money.money_out`;
- approvals runs each module's own `finalize`.

## Quick start (Docker)

```bash
cp .env.example .env            # optionally set JWT_SECRET (32+ characters) and ports
docker compose up --build       # mysql + backend (runs migrations) + frontend
make seed-demo                  # roles, users, master data + realistic demo business data
```

| What | Where |
|---|---|
| App | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |

**Docker on macOS without Docker Desktop** (what this project is verified with):

```bash
brew install colima docker docker-compose docker-buildx
colima start --cpu 4 --memory 6 --vm-type vz --mount-type virtiofs   # once per boot
```

Compose is a CLI plugin: `~/.docker/config.json` needs `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]`. If Docker Desktop was uninstalled earlier, also remove its leftovers:
- `"credsStore": "desktop"` and `"currentContext": "desktop-linux"` in that file;
- broken links in `~/.docker/cli-plugins`.

**Port clashes:** if MySQL already runs on your machine, set `MYSQL_HOST_PORT=3307` (any free port) in `.env`. Containers still talk to each other on 3306. Stop anything else on ports 8000 and 5173.

`make seed` loads only the base data: roles, users, master data and demo approval rules. Both seeds are idempotent, so they're safe to run again.

### Demo logins

The password for all of them is `Admin@123`.

| Username | Role | Can do |
|---|---|---|
| `admin` | Admin | Everything |
| `owner` | Owner | View everything, approve requests (cannot create documents) |
| `sales` | Sales | Customers, quotations, sales orders, reservations, deliveries, invoices, returns, collections |
| `store` | Purchase/Store | Suppliers, purchase orders, goods receipts and returns, all stock documents |
| `accounts` | Accounts | Collections, supplier payments, expenses, income, transfers, money accounts, payroll; views invoices and statements |

### Without Docker

You need MySQL 8, Python 3.12 and Node 24. Create databases `bms` and `bms_test`.

- **MySQL setting:** with binary logging on, set `log_bin_trust_function_creators=1` so the app user can create the ledger triggers.
- **Backend** (`backend/`):
  1. `python -m venv .venv && .venv/bin/pip install -r requirements.txt`
  2. Set `DATABASE_URL`, `TEST_DATABASE_URL` and `JWT_SECRET`.
  3. `.venv/bin/alembic upgrade head`
  4. `.venv/bin/python -m app.seed --demo`
  5. `.venv/bin/uvicorn app.main:app --reload`
- **Frontend** (`frontend/`): `npm ci && npm run dev`

## Tests

```bash
make test                    # docker: pytest inside the backend container
make lint                    # ruff + frontend type check
# locally:
cd backend && .venv/bin/pytest && .venv/bin/ruff check .
cd frontend && npm run build # tsc --noEmit + vite build
```

The suite has 208 tests, all on MySQL. The test database is dropped and recreated on each run.

**Per module:** every posting service is tested, including rollback when any step fails.

**Concurrency:** these run against a throwaway `bms_conc_test` database:
- 20 threads oversell stock;
- 20 threads overdraw an account;
- document numbering.

**`tests/e2e/test_business_cycle.py`:** the full cycle over HTTP, with each step done by the role that owns it. After every step it checks stock (on hand, reserved, available, average cost), dues, account balances, invoice status and the dashboard figures.

**`tests/test_invariants.py`:** checks on the demo data that:
- the stock and money ledgers match the stored balances;
- statements match the due views;
- invoices reconcile with the customer ledger;
- document lines reconcile;
- inventory value = Σ on hand × average cost.

**`tests/test_negative.py`:**
- a 403 matrix per role;
- refused postings: over-receipt, insufficient stock, over-delivery, negative money balance;
- pending approval posts nothing.

## Business cycle demo (click path)

After `make seed-demo`, log in as each user in turn:

1. **store** (Purchase → Purchase Orders):
   1. **New purchase order:** supplier *Bengal Plastics Supply*, product *P-0003 Packing Film*, qty 5, Save. You land on the order.
   2. **Approve** it.
   3. **Receive goods:** the quantity is pre-filled; click Receive. In Inventory → Current Stock, Packing Film rises and its average cost is updated.
2. **accounts** (Money → Supplier Payments):
   1. **New payment** to *Bengal Plastics Supply*; the amount owed is shown.
   2. Choose *Petty Cash* (the balance is shown), amount 2,000, Post.
3. **sales** (Sales → Sales Orders):
   1. **New sales order:** customer *Sadia Enterprise* (their current due is shown), product *P-0006 Concrete Block* (the price is pre-filled and available stock is shown), qty 20, Save.
   2. On the order: **Confirm**, then **Reserve** (a reservation result appears), then **Deliver** with "Create invoice" on.
   3. Open the invoice → **Collect payment** (the form is pre-filled for that invoice) → *Petty Cash*, 500. The invoice is now **Partial**.
4. **accounts** (Money → Collections):
   1. **New collection:** *Sadia Enterprise*.
   2. Under **Against invoice**, pick the invoice; its outstanding amount is shown.
   3. Choose *Dutch-Bangla Bank*, enter the rest, Post. The invoice is now **Paid**.
   4. Money → Expenses → **New expense** (e.g. Utilities 1,000).
5. **owner**:
   1. The menu badge shows one pending approval: the demo's 15,000 office renovation expense. Open Administration → Pending Approvals → **Approve** (remark optional). The expense posts.
   2. **Dashboard:** today's sales / collection / expenses / purchase, cash / bank / MFS, dues, inventory value, pending orders, month-to-date profit, top dues, low stock (PVC Resin, Water Tank) and the 7-day chart.
6. **admin**:
   1. Open the invoice and **Print**.
   2. Open Customers → *Sadia Enterprise* → **Statement** and **Print**. Both fit an A4 page with the menu hidden.
   3. Administration → **Audit Log** shows every step above.

To see a request refused: as **sales**, try delivering more than the order's remaining quantity (the Deliver button is disabled and the API returns OVER_DELIVERY). As **accounts**, pay an expense larger than an account's balance (INSUFFICIENT_FUNDS appears on the Amount field).

## Key design decisions

**Modular monolith.**
- Each area is a module with `models / schemas / service / router`.
- Routers are thin: authentication + `require_permission("<resource>.<action>")` + calling the service.
- All business rules live in services.
- Modules call each other's services instead of duplicating logic.

**Exact numbers.**
- Money is DECIMAL(18,2), quantity DECIMAL(18,3), unit cost DECIMAL(18,4).
- Python `Decimal` is used throughout, never float.
- The API sends decimals as strings.

**Append-only ledgers.**
- `stock_transactions`, `money_transactions` and `party_ledger` are only ever inserted into. MySQL triggers reject UPDATE and DELETE.
- Corrections are reversing entries, for example voucher reversal or stock reversal.
- Stored balances (`stock_balances`, `money_accounts.balance`) are kept in step and are checked against the ledgers by tests.

**Weighted-average costing.**
- Receipts update the average to 4 decimals (rounded half-up).
- Deliveries record the cost of goods sold at the current average.
- Returns move stock at their original cost: purchase returns at the receipt cost, sales returns at the original COGS. The average is then recomputed from value.

**Transactions and row locking.**
- Every posting (stock, money, party ledger) runs in one transaction (`core.db.atomic`, which can be nested). All of it is saved or none of it.
- Balance rows, document headers and number sequences are locked with `SELECT … FOR UPDATE` in a fixed order.
- Negative stock, negative account balances, over-receipt and over-delivery are refused with clear error codes.

**No stored procedures.** All logic is in Python services. The database only adds:
- constraints;
- the append-only triggers;
- four read views: `v_stock_valuation`, `v_customer_due`, `v_supplier_due`, `v_cash_position`.

**Approvals.**
- **Rules:** a rule is a document type (purchase order, expense, supplier payment, stock adjustment) + a minimum amount + an approver role. If several rules match, the one with the highest minimum applies.
- **Registration:** each module registers its own finalize and reject functions with the approvals service.
- **While pending:** a document that needs approval becomes `pending_approval` and posts nothing.
- **Approving:** runs the module's finalize in the same transaction as the decision, so it posts exactly once.
- **Who can decide:** nobody can approve their own request, and only the rule's role (or Admin) can decide.

**Document numbers** (PO-000001, INV-000001, …) come only from `core/numbering.py`. Numbers are taken inside the posting transaction, so a rolled-back posting doesn't use one up.

**Audit log.** Login, create, update, deactivate, post, approve, reject and cancel all write an `audit_logs` row.

**Security.**
- **Permissions:** every endpoint except health, login and forgot/reset password requires a JWT and a permission. Your own profile, password change, logout and dropdown lookups need only a login.
- **Passwords:** stored as bcrypt hashes and never returned or logged.
- **Configuration:** the JWT secret comes from the environment (32 or more characters required in production), and CORS is limited to `CORS_ORIGINS`.
- **Reset tokens:** returned only when `APP_ENV` is not `production`.

## Assumptions and out-of-scope

**Out of scope:** production/manufacturing, fixed assets, a separate reports module, VAT/Mushak, a Bangla UI, multi-company, microservices and CI/CD.

**Main assumptions.** The full list is in `docs/ASSUMPTIONS.md`.

*Production and approvals*
- **"Produced"** on a sales order line is a manual, informational number (0 up to the ordered quantity), because no production module was specified. It doesn't affect stock.
- **Approval checkpoints:**
  - purchase orders are checked when submitted (Approve);
  - stock adjustments when posted;
  - expenses and supplier payments when created.
  - Rejected documents are final: a purchase order or adjustment can then only be cancelled.

*Purchasing and sales*
- **Purchase order discounts are bill-only.** Stock is valued at the line cost, and the discount only reduces what is owed to the supplier.
- **Discount shares:**
  - each receipt (and each invoice of a sales order) gets a proportional share of the order discount, and the last one takes the remainder;
  - returns get their document's share the same way.
- **Receipt cost** defaults to the order line cost and can be changed per receipt.
- **Reservation is partial by design:** an order reserves what is available. Delivery uses the reserved stock first, then free stock.
- **Invoices:**
  - one invoice per delivery;
  - a delivery made without an invoice can be invoiced later;
  - a collection can be linked to an invoice, and can't exceed what is outstanding on it;
  - an unlinked collection can exceed the due (it becomes an advance).

*Money*
- **Opening balances:** an account's opening balance can only be set when the account is created.
- **Deactivation:** an account can only be deactivated at zero balance.
- **Reversals:** vouchers are reversed with opposite entries, never edited.

*Payroll*
- **Absence deduction:** base salary / 30 per absent day; leave and late don't deduct.
- **One run per month:** enforced by the database.
- **Paying:** one payroll payment out of the chosen account, counted as a Salary expense on the dashboard. It isn't an expense voucher, so expense approval rules don't apply.

*Dashboard and dates*
- **Dashboard figures** are computed live from documents and ledgers.
- **Role sections:** each role only sees the sections its permissions allow; Owner and Admin see everything.
- **Dues:** customer and supplier due count positive balances only.
- **Dates:** "Today" and month-to-date use Asia/Dhaka. Stored timestamps are UTC.

## Project layout

```
backend/   app/core, app/modules/<module>, app/seed.py, app/demo.py, alembic/, tests/ (incl. e2e/)
frontend/  src/api, src/components, src/hooks, src/layouts, src/pages/<module>, src/routes, src/styles
docs/      BUSINESS_RULES.md, ASSUMPTIONS.md, PROGRESS.md, SCREEN_CHECKLIST.md
docker/    mysql/init (databases + grants)
```
