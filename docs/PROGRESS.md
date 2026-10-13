# Progress

## 2026-10-12 — Task 1: project foundation
Done:
- Repo layout, docker-compose (mysql 8.4 + healthcheck, backend runs `alembic upgrade head` then uvicorn --reload, Vite frontend), init SQL creating `bms` and `bms_test`, `.env.example`, Makefile, README quick start.
- Backend core: config (pydantic-settings), db (engine, SessionLocal, get_db, Base with naming convention, TimestampMixin), errors (AppError + {detail, code} handlers), pagination (Page[T], page params, paginate), main (CORS, /api/v1, GET /api/v1/health).
- Alembic reads the URL from settings, autogenerates from `app/models.py`; empty initial revision `0001`.
- Tests: conftest recreates `bms_test` and migrates it with Alembic, per-test rollback `db` session, `client` fixture; health + 404 error-shape tests.
- Frontend: Vite React TS with Ant Design, TanStack Query, React Router, axios, dayjs; `api/client.ts` (token header, 401 -> /login); home page showing /health status; placeholder /login.

Verified (Docker not installed on the dev machine, so checked against local MySQL 9.6 with Python 3.12):
`alembic upgrade head`, `alembic check`, uvicorn + `curl /api/v1/health` -> {"status":"ok","db":true}, CORS preflight, `pytest` (2 passed), `ruff check`, `ruff format --check`, `npm run build`.
Not verified: `docker compose up --build`.

Next: auth module (users, roles, permissions, JWT login, `require_permission`, audit log, numbering).

## 2026-10-12 — Task 2: auth + security backend
Done:
- Tables (migration `0002`): users, roles, permissions, role_permissions, password_reset_tokens, audit_logs (indexed on created_at, entity_type, user_id).
- `core/permissions.py`: registry of 150 codes (36 resources x view/create/edit/delete + 6 special). `sync_permissions` inserts missing codes (never deletes) and grants them to Admin; runs on app startup and in the seed.
- `core/security.py` (bcrypt, JWT HS256 60 min, reset tokens stored as sha256), `core/deps.py` (`get_current_user`, `require_permission` -> 403 PERMISSION_DENIED, unknown codes fail at import), `core/audit.py` (`log_audit`, joins the caller's transaction).
- `/api/v1/auth`: login (username/email/mobile), me, PUT me, change-password, forgot-password, reset-password, logout. Login/logout/profile/password changes are audited.
- `app/seed.py` (`python -m app.seed`, `make seed`): Admin, Owner, Sales, Purchase/Store, Accounts + demo users (password Admin@123).
- DB sessions use UTC (`SET time_zone='+00:00'`); production refuses a JWT_SECRET under 32 chars.

Verified locally (no Docker): `alembic upgrade head`, `alembic check`, seed run twice (no duplicates), live login/me/forgot via curl, `pytest` 23 passed, `ruff check`, `ruff format --check`.

Next: admin module (user + role management endpoints using `require_permission`), then document numbering and master data.

## 2026-10-12 — Task 3: frontend shell + reusable components
Done:
- Auth: `hooks/useAuth.tsx` (AuthProvider: token in localStorage, user + permissions via TanStack Query `['auth','me']`, login/logout, any 401 clears the session), `usePermission`, `<Can>`, `routes/guards.tsx` (ProtectedRoute incl. must_change_password redirect, GuestOnlyRoute, RequirePermission -> 403 page).
- Screens: Login, Forgot Password (dev token + link to reset), Reset Password, My Profile, Change Password.
- Layout: collapsible sidebar + header (name, role, profile/password/logout menu). Menu and routes both come from `routes/navigation.tsx` and are filtered by permissions; 37 module routes render "Coming soon".
- Components: CrudPage, DocLineItems, MoneyText, QtyText, StatusTag, PageHeader, ConfirmButton, DateText, ErrorState, ComingSoon. Hooks: `useList`, `useRecord`, `useSave`, `useRecordAction`.
- Global errors: mutation errors -> notification (unless `meta.silent`), background refetch errors -> notification, first-load errors -> page error state. 422 `errors[]` and business codes map onto form fields (`utils/forms.ts`).
- `utils/decimal.ts`: exact BigInt decimal maths/formatting for line amounts and totals (no floats).

Verified: `npm run build`, `npm run lint`. Headless Chrome against the running backend: admin sees all 10 menu groups; sales sees Dashboard, Sales, Inventory (stock only), Money (Collections), Customers, Master Data (Products); sales opening /admin/users gets "No access"; logged-out deep link -> /login; wrong password shows inline error; forgot-password shows the dev reset link; no console errors.
Not yet exercised: CrudPage and DocLineItems against real endpoints (no CRUD/product endpoints exist yet).

Next: admin module (users, roles & permissions) as the first CrudPage screens, then document numbering and master data.

## 2026-10-12 — Task 4: Administration module
Done (backend, `modules/admin`, migration `0003`):
- Users: list (search, role, active), create, update, deactivate/activate, admin password reset (sets must_change_password). Blocks deactivating yourself and removing/demoting the last active Admin (Admin role row locked FOR UPDATE).
- Roles: list (user/permission counts), create, update (system roles can't be renamed), delete (not system, no users). Permissions grouped by module; GET/PUT role permissions as a full replacement; Admin must keep all.
- Audit log: filters (local date range, user, entity, action, entity_id, summary search), newest first, facets endpoint.
- Company settings (single row, timezone validated) and document sequences (17 seeded; next_number only upward).
- `core/numbering.py` `next_document_number` (row lock, zero-padded, increments in the caller's transaction). `core/dates.py` (Asia/Dhaka day bounds), `core/schemas.UtcDateTime` (datetimes serialized with "Z"), `deps.Allow(code)`.
- All endpoints permission-guarded; every write audited.
Done (frontend): Users (CrudPage + drawer + reset-password modal), Roles & Permissions (role list + module/resource checkbox matrix with module select-all), Audit Log (filters + before/after diff), Document Numbering (CrudPage modal with live preview), Company Settings. CrudPage gained `creatable`, `searchable`, `rowActions`, `errorFields`, and now resets the form on every open (fixed stale values carried into "New").

Verified: pytest 39 passed (incl. last-admin, permission replacement applies on next request, 20-thread numbering with no duplicates — and confirmed that test fails without the row lock), ruff check/format, `npm run build`, `npm run lint`. Headless Chrome against the running app: create user in drawer, duplicate username shown on the field, deactivate, edit A/edit B/new show correct values, roles matrix select-all + undo, audit diff expand, numbering preview, company settings load; no console errors. Left behind in the dev DB: deactivated user `uitest`.

Next: master data (products, categories, units, warehouses, price list, payment methods, money accounts) using CrudPage.

## 2026-10-12 — Task 5: Master Data
Done (backend, `modules/master`, migration `0004`):
- Categories, units, expense/income categories, payment methods via one shared CRUD service + router factory (list/search/active filter, create, update, deactivate/activate). Names (and unit short codes, warehouse codes, product codes) unique; duplicates -> 409 `<FIELD>_TAKEN`.
- Warehouses: exactly one default (rows locked when switching; first warehouse becomes default; default can't be unset or deactivated; inactive can't become default).
- Products: code auto-generated from the `PRD` document sequence (P-0001…, skips manually used codes), category/unit must be active, type raw_material|finished_good|trading, purchase_price DECIMAL(18,4), reorder_level DECIMAL(18,3), optional initial sale price. List shows current sale price.
- Product prices: append-only history; current = latest effective_from <= today (Asia/Dhaka), ties -> newest row; future dates are "scheduled". `/master/prices` price list, `/master/products/{id}/prices` history + add.
- Deactivating a unit/category used by active products returns 409 CONFIRM_REQUIRED; repeat with `?force=true`.
- `GET /master/lookups` (active categories, units, warehouses, payment methods, expense/income categories) for any logged-in user.
- `core/schemas.py` Money/Qty/UnitCost types: precision validated, serialized as fixed-place strings.
- Seed: units (KG, PCS, ROLL, BLK, M, PKT), Raw Materials / Finished Goods categories, Main Warehouse (default), 6 expense + 1 income category, 5 payment methods, 6 demo products with prices.
Done (frontend): Product List, Product Categories, Units, Product Price List (history drawer + add price), Warehouses, Expense/Income Categories, Payment Methods. `useLookups()` (cached, invalidated by master saves). CrudPage: `invalidates`, and a confirm-then-force flow for CONFIRM_REQUIRED. DocLineItems now searches `/master/products` and prefills `current_price`.

Verified: pytest 49 passed, ruff check/format, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy (fresh `bms_ui` DB, backend :8001, frontend :5174, dropped afterwards): product list with prices, create product with auto code P-0007, schedule a future price (history shows Current/Scheduled), deactivate in-use unit -> confirm dialog -> deactivated -> reactivated, warehouses/payment methods render; no console errors.

Next: parties (customers, suppliers, opening dues, party ledger + statements).

## 2026-10-12 — Task 6: Parties (customers, suppliers, ledger, statements)
Done (backend, `modules/parties`, migration `0005`):
- customers / suppliers (code CUS-0001 / SUP-0001 from document sequences via `numbering.next_free_code`, contact fields, informational `opening_due`, notes, is_active). CRUD under `/customers` and `/suppliers` (permissions `customer.*` / `supplier.*`); list returns current `due` (from the views) and `has_transactions`.
- `party_ledger`: append-only (UPDATE/DELETE blocked by MySQL triggers), check constraint "exactly one of debit/credit > 0", index (party_type, party_id, entry_date).
- Service: `post_party_entry` (validates sides, precision, party exists; joins caller's transaction), `get_balance` (customer debit-credit, supplier credit-debit; optional `before`), `get_statement` (opening before `from`, running balance, totals, closing), `total_due` (sum of positive dues, for the dashboard).
- Opening due > 0 posts an OPENING entry in the create transaction. Editing it before any other entry posts OPENING_REVERSAL + new OPENING; afterwards 400 OPENING_LOCKED.
- Views `v_customer_due`, `v_supplier_due`. `GET /{customers|suppliers}/{id}/statement?from=&to=` (permission `party_statement.view`).
- Fix: decimal API types now stringify only in JSON; `model_dump()` keeps `Decimal` (services were receiving strings; master-data change detection was affected). Regression test added.
- docker-compose MySQL: `--log-bin-trust-function-creators=1` so the app user can create the ledger triggers.
Done (frontend): Customers and Suppliers (CrudPage: due/payable column, search, active filter, add/edit drawer with opening due locked once transactions exist, Statement action), Statement page (date range + presets, opening row, running balance, totals/closing, Print with print CSS hiding the app chrome).

Verified: pytest 64 passed (opening entry, mixed-entry balances for both sides, statement opening/running/closing, invalid debit/credit combos, triggers block UPDATE/DELETE, opening-edit lock, code generation), ruff, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy: lists with dues, opening due locked for a party with transactions, create with opening due, statement figures, print media hides sidebar/header/buttons, Sales user sees no statement action and gets "No access" on the URL; no console errors.

Next: inventory (stock balances, stock ledger, weighted average cost, adjustments, transfers, physical count).

## 2026-10-13 — Task 7: Inventory engine (backend only)
Done (`modules/inventory`, migration `0006`):
- Tables: stock_balances (unique product+warehouse, DB check 0 <= reserved <= on_hand, avg >= 0), stock_transactions (append-only via triggers; one-side check; `reversal_of_id` unique), transfers / adjustments / counts with items; view `v_stock_valuation`.
- Engine (caller's transaction, no commits): `stock_in` (weighted average, 4 dp half-up), `stock_out` (returns unit cost; `reserved_qty` consumes the caller's reservation; optional `unit_cost` recomputes avg from value for purchase returns/reversals), `reserve`/`release`, `transfer` (source avg cost), `reverse_transaction` (opposite row, once only). Balance rows locked FOR UPDATE; created race-safely (plain read, then INSERT ... ON DUPLICATE KEY UPDATE, then lock); multi-row work locks in sorted order.
- Documents: create (draft, numbered TRF/ADJ/CNT) -> post (one transaction, header locked, all-or-nothing) / cancel. `create_adjustment` + `finalize_adjustment` kept separate for approvals (`adjustment_requires_approval` hook). Counts snapshot system qty at create and post the variance as a delta, reporting lines that moved since.
- Endpoints `/inventory/stock` (filters + low_stock + total_value), `/inventory/ledger` (opening + running balance, paginated), transfers/adjustments/counts create/list/detail/post/cancel. Post = `<resource>.edit`, cancel = `<resource>.delete`.
- Tests: `conftest` gained `recreate_database` / `drop_database` / `migrate`; concurrency tests run in a throwaway `*_conc_test` database (committed ledger rows can't be deleted).

Verified: pytest 100 passed (36 new: weighted-average math, limits, reservations, purchase-return value recompute, reversal, triggers, transfer rollback mid-way, count variance, double post, permissions, stock/ledger endpoints, 300-operation random invariant check, 3 concurrency tests). Concurrency test confirmed to fail (20/20 "succeed" = oversell) without FOR UPDATE. ruff check/format, alembic check, curl smoke test on the running app.

Next: inventory frontend screens, or purchase (PO, goods receipt, purchase return) which will call `stock_in` / `stock_out(unit_cost=receipt cost)` and the supplier ledger.

## 2026-10-13 — Task 8: Inventory frontend
Done:
- Screens: Current Stock (filters warehouse/category/search/low-stock, total value in header, product links to ledger), Product Stock Ledger (product picker, warehouse, date range in the URL; opening row, running balance, links to source documents, closing balance), Stock Transfers, Stock Adjustments, Physical Count (list + create drawer via CrudPage; "Save draft" opens the detail page), shared document detail page with Post / Cancel and inline backend errors.
- Components: `ProductSelect` (extracted), `DocLineItems` gained `showPrice={false}`, `qtyLabel`, `availableIn` (live available qty, red when exceeded), `extraColumns` (before/after qty), `newLineDefaults`, `validateQtyLines` / `validateCountLines` (also catch duplicate products). `CrudPage` gained `editable`, `saveLabel`, `onSaved`. `decimal.subtract`.
- Physical count: "Load system quantities" fills every stocked product of the warehouse; counted qty defaults to system qty; variance column highlighted red/green; detail shows "moved since snapshot".
- Backend: `/inventory/stock` `product_id` filter; ledger `closing_balance`; INSUFFICIENT_STOCK / reserve errors name the product and warehouse.

Verified: pytest 100 passed, ruff, `npm run build`, `npm run lint`. Headless Chrome walk-through on an isolated copy (fresh DB, dropped afterwards): opening-stock adjustment (3 lines, one using the purchase-price fallback) -> total value 124,500.00; Current Stock -> ledger link; transfer with an unstocked line shows Available 0 in red and posting shows "Insufficient stock of P-0002 PVC Resin in Main Warehouse: available 0, requested 5" inline; cancel; valid transfer posted; count with -2 / +5 variances posted; ledger 100 -> 70 -> 68 with closing 68; Sales sees only Current Stock / Stock Ledger and gets "No access" on transfers; no console errors.

Next: purchase (PO, goods receipt, purchase return) on top of the inventory engine and supplier ledger.

## 2026-10-13 — Task 9: Purchase (backend + frontend)
Done (backend, `modules/purchase`, migration `0007`):
- Tables: purchase_orders (+items with received_qty), goods_receipts (+items with returned_qty; subtotal/discount/total), purchase_returns (+items). DB checks: total = subtotal - discount, 0 <= received <= ordered, 0 <= returned <= received.
- `create_po` / `update_po` (draft only) / `approve_po` (-> approved, or pending_approval via `po_requires_approval` hook) / `finalize_po_approval` (for the approvals module) / `cancel_po` (nothing received).
- `receive_goods`: locks the PO, qty <= remaining, editable unit cost (default PO cost), stock_in PURCHASE_IN, received_qty, status (partially_received/received), supplier ledger credit = net total, one transaction. Discount is bill-only: each receipt takes its share (completing receipt takes the remainder so shares add up exactly).
- `direct_purchase`: PO + full receipt in one transaction (is_direct).
- `purchase_return`: qty <= received - returned, stock_out PURCHASE_RETURN_OUT at the receipt cost (avg recomputed from value), supplier ledger debit = net of the receipt's discount share.
- `core/db.atomic()` (moved from inventory) wraps every posting.
- Endpoints under `/purchase` (orders CRUD/approve/cancel/receive, direct, receipts, returns).
Done (frontend): Purchase Order list + create/edit drawer (drafts only, DocLineItems with 4-dp unit cost, discount + totals preview, "Direct purchase: receive immediately"), Purchase Order detail (status steps, ordered/received/remaining, supplier current due, Approve / Cancel / Receive goods dialog with partial qty and editable cost, receipt cards with Return dialog showing returnable and in-stock qty), Goods Receipts & Returns tabs. CrudPage gained `canEditRow` and `submit`.

Verified: pytest 112 passed (12 new: full receipt, two partial receipts with changed cost and exact discount shares, over-receipt and other rejections, direct purchase, return stock/due, return at receipt cost vs average, over-return and insufficient stock, cancel/edit rules, rollback when stock_in or the ledger fails incl. no number consumed, permissions/audit), ruff, alembic check, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy: PO 2,362.50 - 62.50 = 2,300.00; partial receipt 642.54 (discount 17.46), rest 1,657.46 (45.04); over-return blocked; return debited 321.27; direct purchase 480.00; supplier statement closing 2,458.73 matches; no console errors.

Next: money (accounts, supplier payments, customer collections, expenses) or sales.

## 2026-10-13 — Task 10: Money (backend + frontend)
Done (backend, `modules/money`, migration `0008`):
- money_accounts (cash/bank/mfs, payment method, stored `balance` with DB check >= 0; opening balance posts an OPENING IN in the same txn; deactivation requires a zero balance). Seeded: Cash in Hand, City Bank, bKash, Nagad.
- money_transactions: append-only (triggers), direction/amount/type checks, balance_after, `reversal_of_id` (unique).
- Engine: `money_in` / `money_out` (account row FOR UPDATE; INSUFFICIENT_FUNDS names the account, balance and need), `reverse_ref` (opposite rows, accounts locked in id order, refunds first), `ledger_balance`.
- Vouchers: customer collections (money IN + customer credit; advances allowed; `invoice_id` rejected with INVOICES_NOT_AVAILABLE until sales exists - TODO in model/service), supplier payments (OUT + supplier debit), expenses (OUT), other income (IN): one shared create -> finalize path with `requires_approval` hook and `finalize_voucher` for approvals; transfers (OUT + IN atomically, different accounts). Reversal of any posted voucher/transfer adds opposite money (and party) rows and marks it reversed; never edits.
- View `v_cash_position`; `/money/position` totals by type; `/money/accounts/{id}/ledger` with opening/running/closing.
- `/master/lookups` now includes active money accounts (Sales can pick an account for collections).
Done (frontend): Money Accounts (cash/bank/MFS/total cards, add/edit, opening balance on create, link to ledger), Account Ledger, Customer Collections / Supplier Payments (party due shown when selected), Expenses, Other Income, Fund Transfers (one generic VoucherPage; account balance hint on payments; Reverse with reason). CrudPage gained `dateRangeFilter` and `headerExtra`.

Verified: pytest 127 passed (15 new: opening posting, collection/payment party effects, advances, invoice guard, negative balance blocked with nothing posted, expense/income, transfer validation, transfer rollback when the IN leg fails, reversals restore balances and dues, reversal blocked when money already spent, ledger running balance, ledger sum == balance == view after mixed ops, append-only, permissions, 20-thread payment concurrency). ruff, alembic check, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy: final position cash 0 / bank 7,000 / MFS 2,050 / total 9,050 as computed by hand; INSUFFICIENT_FUNDS shown on the field; blocked and successful reversals; account ledger and customer statement agree.

Next: sales (quotation, sales order, reservation, delivery + invoice, sales return, refund) - then wire collections to invoices.

## 2026-10-13 — Task 11: Sales (backend + frontend)
Done (backend, `modules/sales`, migration `0009`):
- Tables: quotations(+items), sales_orders(+items with ordered/reserved/produced/delivered), deliveries(+items with COGS), invoices(+items, paid/returned/refunded amounts, status), sales_returns(+items). FK customer_collections.invoice_id -> invoices.
- Quotations: create/edit (draft), send/accept/reject, `convert_to_sales_order`.
- Sales orders: create/edit (draft), confirm, cancel (releases reservations, blocked after delivery), manual produced qty.
- `reserve_order` (partial, per-line result) / `release_reservation` via the inventory engine (new `inventory.reserve_up_to`).
- `deliver`: reservation first then free stock (`inventory.stock_out`), COGS stored, SO status, optional invoice + customer ledger debit, all one transaction. Invoicing a delivery later.
- `sales_return`: stock IN at original COGS into the delivery warehouse, customer credit, optional refund (money OUT + customer debit).
- Money wired in: collections linked to an invoice update paid_amount/status (`sales/payments.py`), reversal restores them; VoucherOut has `invoice_number`.
- Endpoints under `/sales` (quotations, orders, reserve/release/deliver/produced, deliveries, invoices, returns) with customer/status/date filters.
Done (frontend): Quotations (list + drawer, send/accept/reject, Convert to Sales Order from the row or the edit drawer), Sales Orders (list + drawer with available stock per line), Sales Order Details (Ordered/Available/Reserved/Produced/Delivered/Remaining, Confirm/Reserve/Release/Deliver/Cancel, reservation result, deliver dialog with create-invoice toggle, deliveries + invoices), Invoices list, printable Invoice view (Collect payment opens the collection form prefilled, Sales return), Sales Returns list + return dialog (refund + account). Customer due shown when choosing a customer. Shared `PartyDue`; CrudPage gained `openWith` and `formFooterExtra`; collection form gained an optional invoice picker.

Verified: pytest 143 passed (16 new: quotation conversion, partial reservation + top-up + release, warehouse lock, delivery consumes reservation, over-delivery and insufficient stock, multi-step deliveries with statuses and exact discount shares, COGS = average at the time, invoice posts due, collections drive invoice status incl. overpayment/other customer/reversal, later invoicing, return at original COGS reduces due, refund moves money, refund without funds rolls back everything, cancel rules + produced, full rollback when stock_out or the ledger fails incl. numbers not consumed, permissions/audit). ruff, alembic check + downgrade/upgrade, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy: QT -> SO 1,150.00; partial reservation (P-0001 short 4); two deliveries invoiced 766.67 + 383.33 (= 1,150.00); collection 300 via prefilled form (overpayment shown on the field); return 76.67 with 50.00 refund (blocked first from an empty bank account); customer due 823.33 and statement agree; cash 250.00; no console errors.

Next: approvals (PO / expense / supplier payment / stock adjustment rules), then employees/payroll and the dashboard.

## 2026-10-13 — Task 12: Approvals (backend + frontend)
Done (backend, `modules/approvals`, migration `0010`):
- approval_rules (document type, min amount, approver role, is_active) and approvals (document, number, amount, rule + approver role snapshot, status pending/approved/rejected, requester, decider, remark). `rejected` added to the status checks of purchase_orders, the voucher tables and stock_adjustments.
- Handler registry: each module registers its existing finalize + a new reject at import (`finalize_po_approval`/`reject_po`, `finalize_voucher`/`reject_voucher` for expenses and supplier payments, `finalize_adjustment`/`reject_adjustment`). `maybe_require_approval` replaced the three stub hooks; `approve`/`reject` lock the request, check role/self/double decisions and run the handler in one transaction (`atomic` made re-entrant).
- Retrofit: `approve_po` (submit), `direct_purchase`, `create_voucher` (expense/supplier payment) and new `submit_adjustment` (post endpoint) send documents for approval and post nothing while pending; cancel closes the pending request.
- Endpoints `/approvals/rules` (CRUD, deactivate/activate), `/approvals/pending`, `/approvals/pending/count`, `/approvals/history` (filters), `POST /approvals/{id}/approve|reject`.
- Seed CLI adds the demo rules (EXPENSE >= 10,000, PURCHASE_ORDER >= 50,000 -> Owner).
Done (frontend): Approval Rules (CrudPage), Approvals page (Pending tab with Approve/Reject + remark modal, History tab with filters), document links, pending-count badge in the menu (dot on the collapsed group), `ApprovalNotice` banner on PO and adjustment pages (approver role / rejection reason), rejected status in PO steps, filters and cancel rules, "needs approval" messages after saving. CrudPage gained `initialSearch` (links to a voucher number).

Verified: pytest 155 passed (12 new: below threshold posts at once, expense / supplier payment / PO / adjustment pending with balances, ledgers and stock untouched, approval posts exactly once, double approval, self-approval, wrong role, Admin, rejection (remark required, nothing posted, rejected PO final then cancelled, rejected adjustment cancelled), highest rule wins, finalize failure keeps the request pending, pending list scope, rules CRUD/deactivation). With rule matching disabled 10 of the 12 fail. ruff, alembic check + downgrade/upgrade, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy: 12,000 expense pending with cash unchanged (20,000), admin can't decide own request, Owner approves -> cash 8,000; PO 60,000 pending, Owner rejects (remark required) -> PO shows "Rejected by Business Owner ... Reason" and can only be cancelled; history lists both; menu badge/dot; self-approval 403; no console errors.

Next: employees (attendance, payroll paid through money) and the management dashboard.

## 2026-10-13 — Task 13: Employees, attendance, basic payroll
Done (backend, `modules/employees`, migration `0011` incl. the EMP code sequence):
- employees (EMP-0001 codes, designation/department, joining date, base salary, optional user link, deactivate/activate), attendance (unique employee+date; present/absent/leave/late), payroll_runs (PRL number, month, draft/paid/cancelled, total, unique live month) + payroll_items.
- Attendance sheet for a date (pre-filled present) and bulk/per-row upsert. Payroll generate (absent-only deduction base/30/day), edit bonus/other deduction while draft, cancel draft, pay = one PAYROLL money OUT via `money.money_out` + run marked paid in one transaction.
- Endpoints under `/employees` (CRUD, `/attendance`, `/payroll`, `/payroll/{id}/pay|cancel`).
Done (frontend): Employees list + add/edit drawer, Attendance & Payroll page (daily sheet with status buttons, "All present", save; payroll month picker, generate, editable bonus/deduction columns, save, Pay dialog with account balance, paid details, recent runs).

Verified: pytest 161 passed (6 new: codes/user link/permissions, attendance sheet, deduction math incl. leave/late/other months/inactive and rounding, one run per month and regenerate after cancel, pay posts exactly one PAYROLL row and reduces the balance with insufficient funds leaving everything untouched, paid run frozen, payroll permissions). ruff, alembic check + downgrade/upgrade, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy: added EMP-0003; attendance saved; September payroll 28,000 (2 absences) + 19,000 (leave/late + 1,000 bonus) + 25,000 = 72,000, paid from cash 100,000 -> 28,000, one PAYROLL ledger row; no console errors.

Next: management dashboard.

## 2026-10-13 — Task 14: Management dashboard
Done (backend, `modules/dashboard`, no tables): `GET /api/v1/dashboard/summary` (dashboard.view). Today's sales / collection / expenses (incl. payroll) / purchase, cash / bank / MFS, customer and supplier due (positive balances), inventory value, pending orders count + remaining value, estimated profit month to date, top 5 customers and suppliers by due, low stock (top 5), last-7-days sales vs collection. Computed live from documents, ledgers and the four SQL views (v_stock_valuation now mapped in inventory models), Asia/Dhaka dates. Role-aware: only sections the user's permissions allow are returned.
Done (frontend): Dashboard page as the home route (and /dashboard): grouped metric cards (Today, Money, Dues, Stock & Orders, Profit) hidden when not returned, top-due tables (statement links when allowed), low-stock list, 7-day line chart (Recharts), auto-refresh every 60 s + Refresh button.

Verified: pytest 163 passed (2 new: a fixed-date data set through the real endpoints - purchase with discount + return, three sales orders incl. discount, partial delivery, draft, a sales return with refund, collections incl. an advance and a reversed one, supplier payment, expenses incl. reversed / yesterday / last month, other income, payroll paid today - with every metric asserted against hand-calculated values (today 1,386 / 1,200 / 3,300 / 1,805; cash 7,396, bank 20; dues 740 / 1,725; inventory 900; pending 2 worth 670; profit -2,464; series); and role sections: Sales gets no cash balances, costs or profit, Owner gets everything, Accounts gets money but not stock). ruff, alembic check, `npm run build`, `npm run lint`. Headless Chrome on an isolated copy: admin dashboard figures match the hand calculation (sales 200, cash 5,150, inventory 1,700, pending 400, profit 5,150), refresh picks up a new expense, Sales user sees only sales/customer/orders/stock cards; no console errors.

All modules in CLAUDE.md are now implemented. Next: end-to-end review of the full cycle and the docker-compose run.

## 2026-10-13 — Task 15: Demo data, end-to-end cycle, invariants, negative tests
Done:
- `python -m app.seed --demo` / `make seed-demo` (idempotent, services only, `app/demo.py`): depot warehouse, 3 funded accounts, 3 suppliers + 4 customers with opening dues, reorder levels, PO-1 above the approval threshold approved by the Owner and fully received + purchase return, PO-2 partially received, 2 supplier payments, transfer, adjustment, quotation -> reserved order, partially delivered + invoiced + partly collected order with a sales return, fully delivered and paid order, an opening-due collection, expenses, other income, a 15,000 expense pending approval, 5 employees with last month's attendance. Dashboard after seeding: every headline figure non-zero (e.g. sales 13,913.65, collection 44,300, purchase 39,600, inventory 69,460, 2 pending orders).
- `tests/e2e/test_business_cycle.py`: the full cycle over HTTP as store -> accounts -> sales -> accounts -> owner, asserting stock on hand/reserved/available and average cost, supplier and customer due, account balances, invoice status and every dashboard metric at each step.
- `tests/test_invariants.py` (on the demo data): stock ledger == balances (no negative, reserved <= on hand, reservations == open order lines), money ledger == balances == view, statements == due views, invoices reconcile with the invoice-related customer ledger and paid_amount == linked collections, document lines reconcile (delivered / received), dashboard inventory value == sum(on_hand x avg_cost).
- `tests/test_negative.py`: 29 role/endpoint 403s across Sales, Purchase/Store, Accounts and Owner (+ allowed-path sanity checks, 401), over-receipt, insufficient stock (delivery, adjustment), over-delivery, negative money (expense, supplier payment, transfer) and pending approval posting nothing - each asserting no ledger rows were written.
- Code fix found by the invariants: dashboard inventory value now rounds once instead of summing per-row rounded values.

Verified: pytest 208 passed; mutation checks (removing a balance update, removing the invoice return bookkeeping) make the seed / invariants fail; ruff, alembic check, `npm run build`, `npm run lint`.

## 2026-10-13 — Task 16: Final audit, README, clean-state check
Done:
- Screen audit: `docs/SCREEN_CHECKLIST.md` lists every required screen (6.1 to 14.8 plus the extra screens), checked in headless Chrome on a fresh demo database: every page loads without console errors; lists have search + pagination (ledgers use product/account pickers); every add/edit form opens, shows validation messages when saved empty, and opens pre-filled for editing.
- UI walk-through of the full cycle as store -> accounts -> sales -> accounts -> owner -> admin on the demo data, with fixes: statement print clipped the balance column (print CSS for wide tables); duplicate "Invoice" heading and stacked header on the printed invoice (company details now seeded; fixed columns); collapsed sidebar kept a group pop-up open over the page; responsive `Descriptions` span warnings (span "filled"); invoice picker not linked to its label; "Choose one" validation message; search added to Approval Rules and the Pending approvals tab (backend search for rules). Phone width (390 px): no horizontal overflow on the main pages.
- Security: all 190 endpoints inspected; 181 require a permission, 4 public (health, login, forgot, reset), 5 login-only (own profile, change password, logout, lookups) as documented. 422 responses don't echo input; passwords are never in responses, audit rows or logs. JWT secret from env (32+ characters in production). CORS limited to `CORS_ORIGINS` with explicit methods/headers (was `*`); an unknown origin is refused. Reset token is only returned outside production (checked with APP_ENV=production).
- Code quality: ruff clean; frontend `tsc` strict clean (ESLint can't run: typescript-eslint supports TypeScript up to 6.0 and the project uses TypeScript 7). Removed the unused `components/index.ts` barrel, `ComingSoon` and `useRecord`; menu leaves now require an element. No TODO/FIXME or console.log left.
- Docker config fixes: `.env.example` had `MYSQL_USER=root` with an empty password (the MySQL image refuses root as MYSQL_USER, and it didn't match DATABASE_URL `bms:bms`), now `bms`/`bms`; the MySQL init script now also grants `bms_conc_test` (the concurrency tests' throwaway database).
- README rewritten (overview, stack, architecture diagram, quick start, demo logins, tests, click-path demo, design decisions, assumptions/out of scope).

Clean-state check: Docker isn't installed on this machine, so `docker compose down -v / up --build` couldn't be run. Instead: a fresh non-root MySQL user with exactly the init script's grants and a fresh database, with `log_bin_trust_function_creators=1` as docker-compose sets (restored to 0 afterwards). Migrations applied from empty, `alembic check` clean, `seed --demo` created data and skipped on the second run, all 208 tests passed as that user (incl. concurrency tests), the app ran with APP_ENV=production and all five demo users logged in to their role-specific dashboards with no console errors.

## 2026-10-13 — Task 17: Docker working end to end
- Installed Colima, the Docker CLI, docker-compose and docker-buildx with Homebrew; Colima runs Docker Engine 29.5.2 in a VM (4 CPU, 6 GB, vz + virtiofs).
- Fixed a broken leftover Docker Desktop setup (backups kept):
  - `~/.docker/config.json` pointed at the missing `desktop` credential helper and `desktop-linux` context (backed up as `config.json.bak-desktop`; the plugin directory is added);
  - 15 broken `~/.docker/cli-plugins` links into the removed Docker.app (moved to `cli-plugins.bak-desktop/`);
  - the stale `desktop-linux` context was removed.
- Project `.env` (backed up as `.env.bak-before-docker`, now git-ignored):
  - `MYSQL_USER` was `root` with an empty password, now `bms`/`bms` to match `DATABASE_URL`;
  - `MYSQL_HOST_PORT` 3306 -> 3307, because a local MySQL already listens on 3306;
  - `JWT_SECRET` replaced with 64 random hex characters.
- The local (non-Docker) dev servers on ports 8000 / 5173 were stopped; the containers use those ports now.

Verified from a clean state:
- `docker compose down -v` + `up --build -d`: mysql healthy; migrations 0001 -> 0011 applied as the non-root `bms` user (including the ledger triggers); backend and frontend up.
- `make seed-demo` created the demo data and skipped on a second run.
- `make test`: 208 passed in the container, including the concurrency tests on `bms_conc_test`.
- `make lint`: ruff + tsc clean; `alembic check` clean.
- Browser smoke on http://localhost:5173: all five demo users log in to their role dashboards with no console errors.
