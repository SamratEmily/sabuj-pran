# Assumptions

- Validation errors (422) return `{detail, code: "VALIDATION_ERROR", errors: [{loc, msg, type}]}`. `errors` is extra so forms can show field-level messages.
- `created_at` / `updated_at` are stored in the MySQL server time zone (UTC in Docker). "Today" for business dates uses `TIMEZONE` (Asia/Dhaka) in application code.
- The test suite drops and recreates `bms_test` on every run; it refuses any database whose name doesn't end with `_test`.
- `/auth/me`, `PUT /auth/me`, `/auth/change-password` and `/auth/logout` require authentication only, not a permission code: every user manages their own account. (Rule 7 lists no permission for this.)
- JWTs are stateless: logout and password changes do not revoke already-issued tokens; they expire after 60 minutes. Deactivated users are rejected immediately on every request.
- Login with an unknown user or wrong password both return 401 INVALID_CREDENTIALS. The inactive check (403) happens only after the password is verified, so it doesn't reveal which accounts exist.
- Identifier lookup order on login/forgot: username, then email, then mobile. Matching is case-insensitive (MySQL utf8mb4_unicode_ci).
- Re-running the seed only adds missing roles, role permissions and users. It never removes permissions or resets passwords.
- Permission `module` groups resources for the UI (admin, master, parties, sales, purchase, inventory, money, employees, approvals, dashboard).
- Forgot-password returns `reset_token` and logs it whenever APP_ENV is not `production`. Older unused tokens stay valid until they expire.
- CRUD API convention (what `CrudPage` expects): `GET /x` (list with page, page_size, search, filters incl. `is_active`), `POST /x`, `PUT /x/{id}`, `POST /x/{id}/deactivate`, `POST /x/{id}/activate`. Deactivate/activate require `<resource>.delete`.
- `/` shows the management dashboard to users with `dashboard.view` (every seeded role has it) and a welcome page otherwise; Dashboard is also a menu entry.
- "Goods Receipts/Returns" and "Attendance & Payroll" are single menu entries visible with either underlying view permission.
- Numbers display with en-US grouping (1,234,567.50). Quantities trim trailing zeros (12.5).
- Users with `must_change_password` are sent to Change Password before any other page.
- "Admin" for last-admin protection means the role named `Admin`. Deactivating, or changing the role of, the only active Admin is refused (LAST_ADMIN).
- New users default to `must_change_password = true`; admin password resets always set it.
- Usernames are immutable after creation. System roles can't be renamed (code relies on the `Admin` name) or deleted; any role with users (active or not) can't be deleted.
- Role delete is a real delete (roles are configuration, not transactional master data, and deletion is blocked once used).
- Company settings has `invoice_footer_note` but no separate invoice prefix: the invoice prefix lives only in Document Numbering (INV) to avoid two sources of truth. The `timezone` setting is stored and validated; business "today" still uses the `TIMEZONE` env (both default Asia/Dhaka).
- Document sequence prefixes default to `<CODE>-` with 6 digits (e.g. PO-000001). `next_number` can only increase; numbering runs inside the posting transaction, so a rolled-back posting doesn't consume a number.
- Audit log date filters use local (Asia/Dhaka) calendar days.
- API datetimes are UTC with a trailing `Z`.
- Product `purchase_price` is a unit cost (DECIMAL(18,4)); product prices are selling prices (DECIMAL(18,2)).
- Product names are unique (rule "names unique"), case-insensitively via the collation.
- Product codes use the `PRD` document sequence (prefix `P-`, 4 digits) so numbering stays in `core/numbering.py`; codes are editable, and the generator skips codes already taken.
- Several prices may share an effective date; the most recently entered one wins. Prices can be back-dated or scheduled.
- The price list shows active products only.
- API convention: an action that needs user confirmation returns 409 `CONFIRM_REQUIRED` with a human message; the client repeats it with `?force=true`.
- `GET /master/lookups` requires login but no permission code: it only exposes names of active reference data needed by dropdowns across roles.
- Seeded unit names: Kilogram (KG), Piece (PCS), Roll (ROLL), Block (BLK), Meter (M), Packet (PKT).
- Browser verification runs against an isolated database/backend/frontend so it never changes the developer's data.
- Customer/supplier names are not unique (different businesses can share a name); codes are unique.
- Opening due is >= 0 (no opening advances) and its ledger entry is dated the day the party is created.
- Changing the opening due (only allowed before any non-opening entry) is recorded as OPENING_REVERSAL + a new OPENING entry, never by editing the old row.
- Statements require `party_statement.view` (Admin, Owner, Accounts). Sales can manage customers but not view statements, per the seeded roles.
- Ledger append-only is enforced twice: services only insert, and MySQL triggers reject UPDATE/DELETE on `party_ledger`.
- Negative dues (advances/overpayments) are shown as negative; dashboard totals count positive dues only.
- Average cost is kept at 4 decimals (half-up). Inventory value = on_hand * avg_cost may differ from the sum of historical costs by rounding cents.
- An OUT at a specific cost (purchase return at receipt cost, reversal of an IN) recomputes the average from value: (on_hand*avg - qty*cost) / remaining, floored at 0; unchanged if nothing remains. Normal OUTs never change the average. (Decided with the user.)
- `stock_out(reserved_qty=X)`: X of the quantity comes from the caller's own reservation; the rest must be free stock. Sales passes its per-line reserved qty. (Decided with the user.)
- Physical counts snapshot system qty at creation and post counted - snapshot as a delta, so movements after the snapshot stay valid; lines that moved are reported. (Decided with the user.)
- Cost for increases without a given cost (adjustment +, count +): current average, else the product's purchase_price when the item has no average yet in that warehouse.
- The stock ledger is ordered by (txn_date, id); `running_balance` follows that order, `balance_after` is the per-warehouse balance at posting time. Back-dated postings are allowed; stock checks always use the current balance.
- Stock documents: post requires `<resource>.edit`, cancel requires `<resource>.delete`; only drafts can be posted or cancelled (adjustments also cancel from pending_approval or rejected). Each product may appear once per document.
- `/inventory/stock` lists existing balance rows (products never stocked in a warehouse don't appear). low_stock = reorder_level > 0 and on_hand <= reorder_level, per warehouse row.
- Stock documents can't be edited after saving (no update endpoint): fix a draft by cancelling it and creating a new one. "Save draft" then "Post" from the detail page.
- Physical count "Load system quantities" starts counted = system qty, so users only change what differs; products never stocked in that warehouse can be added manually (system qty 0).
- PO header discount is bill-only (decided with the user): stock is valued at gross line cost; the discount only reduces the supplier credit. Each receipt carries round(discount x received-at-PO-cost / subtotal, 2); the receipt completing the PO takes the remainder. A return debits its gross value minus the same proportion of its receipt's discount.
- Receipt unit cost defaults to the PO line cost and may be changed per receipt (decided with the user); stock and supplier credit use the received cost, the discount share uses PO cost.
- Goods are always received into the PO's warehouse. Returns leave the receipt's warehouse and need free stock there.
- Direct purchase = a PO created approved and received in full in the same transaction (GRN is_direct). It needs both `purchase_order.create` and `goods_receipt.create`.
- PO approve requires `purchase_order.edit`; cancel requires `purchase_order.delete` and is only possible before anything is received. Returns don't change the PO status.
- Drafts are edited from the order list (edit drawer); the detail page handles approve/cancel/receive/return.
- Money accounts store a running `balance` (locked FOR UPDATE on every change) that always equals SUM(in) - SUM(out) of the ledger; tests and `v_cash_position` check this.
- An account can only be deactivated with a zero balance. Opening balance is set at creation only (later corrections go through vouchers/transfers).
- Reversal rows keep the original txn_type with the opposite direction and `reversal_of_id`; party reversals use `<TYPE>_REVERSAL` ref types. Reversing a collection/income needs the money to still be in the account (INSUFFICIENT_FUNDS otherwise). Reverse permission = `<resource>.delete`.
- Collections may be linked to an invoice (same customer, amount <= invoice outstanding, else OVERPAYMENT); reversing the collection takes the amount off the invoice again. Collections without an invoice may exceed the due (advance).
- Active money accounts are part of `/master/lookups` (names and types only) so roles without `money_account.view` (e.g. Sales) can choose an account; balances are only shown to users who may view accounts.

## Sales
- Sales order discount is shared across its invoices in proportion to value (round(discount x invoice subtotal / order subtotal, 2)); the invoice completing the order takes the remainder. A sales return gets the same proportion of its invoice's discount; the return completing the invoice takes the remainder.
- One warehouse per sales order: reservations and deliveries use it. Reserving with another warehouse switches the order's warehouse only while nothing is reserved or delivered (WAREHOUSE_LOCKED otherwise). Returns go back into the delivery's warehouse.
- Reservation is partial by design: each line reserves min(free stock, remaining - reserved) under the stock row lock (`inventory.reserve_up_to`); the response lists what is still short. Reserve/release need `reservation.manage` and a confirmed or partially delivered order.
- Delivery takes min(qty, line reserved) from the reservation and the rest from free stock; COGS = average cost at that moment, stored on the delivery line and copied to the invoice line.
- One invoice per delivery. A delivery posted without an invoice ("create invoice" off) can be invoiced later, in full (`POST /sales/deliveries/{id}/invoice`). Delivering with an invoice needs `invoice.create` as well as `delivery.create`.
- Invoice outstanding = total - returns (net) + refunds - paid. Status: paid when outstanding <= 0, partial when something was paid, else unpaid.
- A refund on a sales return can't exceed the return's net total and needs an account; it is money OUT (txn_type REFUND, ref SALES_RETURN) plus a customer debit (SALES_REFUND). Sales returns are not reversible (no requirement).
- Quotations: draft -> sent -> accepted/rejected; edit only in draft; convert from draft, sent or accepted into a new draft sales order (warehouse defaults to the default warehouse).
- Sales order cancel: draft or confirmed only, never after a delivery; releases all reservations. Confirm needs `sales_order.edit` (audited as "approve"); cancel needs `sales_order.delete`.
- "Produced" is a manual informational figure (0..ordered) editable while the order is open; it does not affect stock.
- The Accounts role also gets `invoice.view` so it can pick the invoice a collection pays.

## Approvals
- Where the check runs (decided with the user): purchase orders when the draft is submitted (Approve button); stock adjustments when the draft is posted; expenses and supplier payments at create (they post on create). Drafts stay editable; the amount checked is the final one.
- Amount: PO total (after discount); voucher amount; adjustment value = sum(qty x cost) with increases at their given cost (else current average, else product cost) and decreases at the current average.
- The active rule with the highest min_amount <= amount decides the approver role; no matching rule = no approval. The role is snapshotted on the request, so later rule edits don't move pending requests.
- Deciding needs `approval.approve` AND the request's approver role (Admin may decide any request). Nobody can decide their own request, Admin included. Reject needs a remark.
- Approval runs the module's own finalize in the same transaction (`atomic` is re-entrant); if finalizing fails (e.g. insufficient funds) nothing changes and the request stays pending.
- Rejected documents are final (decided with the user): a rejected PO can only be cancelled; rejected expenses/supplier payments stay as rejected records with nothing posted; a rejected adjustment can be cancelled.
- Cancelling a document while it is pending closes its request (recorded as rejected, "Document cancelled before a decision").
- A direct purchase above a PO threshold receives nothing: it creates the PO pending approval; after approval it is received normally.
- Pending list: requests for the user's role (Admin: all). The menu badge counts requests the user can actually decide (own requests excluded).
- Demo rules (EXPENSE >= 10,000 and PURCHASE_ORDER >= 50,000 by Owner) are added by the seed CLI (`python -m app.seed`), not by the test fixture seed, so tests choose their own rules.

## Employees & payroll
- Employee codes EMP-0001 come from the EMP sequence (blank code on create); codes can be typed manually. Employees are deactivated, never deleted. An employee may be linked to one login user (optional).
- Attendance: one row per employee per date (unique). The daily sheet lists active employees (plus inactive ones already marked that day); unmarked rows show as present but are only stored when saved. Future dates are refused. Edits are allowed at any time; a payroll run takes a snapshot of absent days when generated (cancel and regenerate a draft to pick up corrections).
- Payroll: absence_deduction = round(base / 30 x absent days, 2), capped at the base salary; only "absent" deducts. net = base - absence deduction - other deduction + bonus, never negative (NEGATIVE_NET_PAY). Inactive employees are not included. The base salary is copied onto the run line.
- One live run per month, enforced by a unique `live_month` column (NULL once cancelled), so concurrent generation can't create two. Draft runs can be cancelled (needs `payroll.delete`); paid runs are frozen.
- Paying posts one PAYROLL money OUT (ref PAYROLL / run id) for the total through `money.money_out` (INSUFFICIENT_FUNDS blocks it, nothing changes) and stores the account, date and the "Salary" expense category on the run for expense reporting. It is not an expense voucher, so expense approval rules don't apply to payroll.
- Permissions: generate = `payroll.create`, edit bonus/deduction and pay = `payroll.edit`, cancel = `payroll.delete`; attendance marking = `attendance.edit`. The Accounts role gets payroll CRUD plus employee/attendance view.

## Dashboard
- All figures are live queries over documents, ledgers and the views v_cash_position, v_customer_due, v_supplier_due and v_stock_valuation; "today" and the month start are Asia/Dhaka business dates; month to date = 1st of the month .. today.
- Document values are net of discount: sales = invoice totals minus sales return totals (net credited); purchase = goods receipt totals (net credited to the supplier) minus purchase return totals. Only posted vouchers count (reversed, pending and rejected are ignored). Collections and expenses by their voucher date; payroll counts as an expense on its payment date.
- Net COGS = invoice cogs_total minus returned qty x original COGS (by return date). Other income = posted income vouchers. Estimated profit (MTD) = net sales - net COGS + other income - expenses (vouchers + payroll).
- Customer / supplier due = sum of positive balances only (advances are not netted). Pending orders value = remaining qty x price, reduced by the order discount in the same proportion. Low stock uses the stock screen rule (reorder level > 0 and on hand <= reorder level, per warehouse), lowest cover first, top 5.
- Sections by permission: today's sales (invoice.view), collection (collection.view), expenses (expense.view), purchase (goods_receipt.view), cash/bank/MFS (money_account.view), customer due + top customers (customer.view), supplier due + top suppliers (supplier.view), inventory value (stock.view + goods_receipt.view, since it is a cost figure), low stock (stock.view), pending orders (sales_order.view), profit (invoice.view + expense.view + income.view). The 7-day series shows sales and/or collection per those permissions. Owner (all views) and Admin get everything. The Purchase/Store role now also has dashboard.view (it sees purchase, supplier and stock figures).
- The home route shows the dashboard to users with dashboard.view (a welcome page otherwise). Chart: Recharts 3.10.1 (lighter than Ant Design Charts), the only added frontend library, as requested.

## Demo data & verification
- `python -m app.seed --demo` (`make seed-demo`) runs the base seed + demo approval rules, then `app/demo.py`, which uses only service functions. It is skipped when the marker supplier "Meghna Polymers Ltd" exists (idempotent). Documents are dated within the current month (never before the 1st) so month-to-date figures are meaningful; attendance covers last month's working days (Friday off).
- The demo creates its own funded accounts (Dutch-Bangla Bank, Petty Cash, Rocket) because opening balances can only be set when an account is created; the base accounts stay at zero.
- Dashboard inventory value is sum(on_hand x avg_cost) rounded once (it previously summed per-row rounded view values, which can drift by a few paisa).
- The invoice invariant uses invoice outstanding (total - returns + refunds - paid), since returns and refunds also move the customer ledger; it is compared with the ledger rows that come from invoices (invoice debits, return credits, refund debits, collections linked to an invoice and their reversals), excluding opening dues and unlinked collections (advances).
