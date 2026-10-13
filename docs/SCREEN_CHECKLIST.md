# Screen checklist

Every screen required by the specification, where it lives, and how it was checked.

**Last checked:** 2026-10-13, on a fresh database seeded with `python -m app.seed --demo`, using headless Chrome (scripted browser).

**What "Works" means:**
- The page loads for a user who holds the permission.
- It shows data, and there are no console errors.
- Lists have search and pagination.
- Forms open, show validation messages when saved empty, and open pre-filled for editing.
- The pages that need it print cleanly.

"Drawer" / "Modal" means the add/edit form opens from the list page, which is how `CrudPage` works.

| # | Screen | Route / where | Permission | Status | Notes |
|---|---|---|---|---|---|
| 6.1 | Login | `/login` | public | Works | Username, email or mobile + password; inline errors; redirects to a forced password change when required |
| 6.2 | Forgot Password | `/forgot-password` (+ `/reset-password`) | public | Works | Outside production the reset link/token is shown; in production only the generic message (checked with `APP_ENV=production`) |
| 6.3 | My Profile | `/profile` | logged in | Works | Edits own name/email/mobile |
| 6.4 | Change Password | `/profile/password` | logged in | Works | Forced after an admin reset (`must_change_password`) |
| 7.1 | Owner / Management Dashboard | `/` (home) and `/dashboard` | `dashboard.view` | Works | 11 headline metrics in groups, top dues, low stock, 7-day chart, refreshes every 60 s; each role only sees the sections it is allowed |
| 8.1 | Product List | `/master/products` (+ drawer) | `product.*` | Works | Search, category/type filters, current price |
| 8.2 | Product Categories | `/master/categories` | `category.*` | Works | |
| 8.3 | Units | `/master/units` | `unit.*` | Works | |
| 8.4 | Product Price List | `/master/prices` | `price.*` | Works | Price history per product; scheduled and back-dated prices |
| 8.5 | Expense Categories | `/master/expense-categories` | `expense_category.*` | Works | |
| 8.6 | Income Categories | `/master/income-categories` | `income_category.*` | Works | |
| 8.7 | Payment Methods | `/master/payment-methods` | `payment_method.*` | Works | |
| 8.8 | Company Settings | `/admin/company` | `company_setting.*` | Works | Name, address, phone and footer appear on the printed invoice |
| 9.1 | Customer List | `/customers` | `customer.*` | Works | Current due column; statement link |
| 9.2 | Customer Add/Edit | `/customers` (drawer) | `customer.create/edit` | Works | Opening due posts an OPENING ledger entry |
| 9.5 | Supplier List | `/suppliers` | `supplier.*` | Works | |
| 9.6 | Supplier Add/Edit | `/suppliers` (drawer) | `supplier.create/edit` | Works | |
| — | Customer / Supplier Statement | `/customers/:id/statement`, `/suppliers/:id/statement` | `party_statement.view` | Works | Printable: running balance and closing balance fit on A4 |
| 10.1 | Quotation List | `/sales/quotations` | `quotation.*` | Works | Send / accept / reject / convert actions per row |
| 10.2 | Create/Edit Quotation | `/sales/quotations` (drawer) | `quotation.create/edit` | Works | Customer due shown; "Convert to Sales Order" in the row and in the edit drawer |
| 10.3 | Sales Order List | `/sales/orders` | `sales_order.*` | Works | |
| 10.4 | Create/Edit Sales Order | `/sales/orders` (drawer) | `sales_order.create/edit` | Works | Available stock per line; drafts only |
| 10.5 | Sales Order Details | `/sales/orders/:id` | `sales_order.view` | Works | Ordered / Available / Reserved / Produced (manual) / Delivered / Remaining; Confirm, Reserve, Release, Deliver (+ invoice), Cancel; deliveries and invoices |
| — | Invoice List / Invoice View | `/sales/invoices`, `/sales/invoices/:id` | `invoice.view` | Works | Printable with company letterhead; "Collect payment" opens a pre-filled collection; "Sales return" |
| — | Sales Returns | `/sales/returns` | `sales_return.*` | Works | Return dialog with optional refund |
| 11.1 | Purchase Order List | `/purchase/orders` | `purchase_order.*` | Works | |
| 11.2 | Create/Edit PO | `/purchase/orders` (drawer) | `purchase_order.create/edit` | Works | 4-decimal unit cost, bill discount, "Direct purchase" option |
| 11.3 | PO Details | `/purchase/orders/:id` | `purchase_order.view` | Works | Approve (or pending approval), receive dialog, receipts with returns |
| — | Goods Receipts & Returns | `/purchase/receipts` | `goods_receipt.view` / `purchase_return.view` | Works | |
| 12.1 | Current Stock | `/inventory/stock` | `stock.view` | Works | On hand / reserved / available / avg cost / value, low-stock filter |
| 12.2 | Product Stock Ledger | `/inventory/ledger` | `stock.view` | Works | Pick a product (+ warehouse, dates) instead of free-text search; paginated |
| — | Transfers / Adjustments / Physical Count | `/inventory/transfers` (`/adjustments`, `/counts`) + detail pages | `stock_*` | Works | |
| — | Money: Accounts, Collections, Supplier Payments, Expenses, Income, Transfers, Account Ledger | `/money/*` | `money_account.*`, `collection.*`, … | Works | Account Ledger picks one account instead of searching |
| 13.1 | Employee List | `/employees` | `employee.*` | Works | |
| 13.2 | Employee Add/Edit | `/employees` (drawer) | `employee.create/edit` | Works | Optional link to a login user |
| 13.3 | Attendance / Basic Payroll | `/employees/payroll` (two tabs) | `attendance.*`, `payroll.*` | Works | Daily sheet (pre-filled present); month payroll with editable bonus/deduction and Pay |
| 14.1 | User List | `/admin/users` | `user.*` | Works | |
| 14.2 | User Add/Edit | `/admin/users` (drawer) | `user.create/edit` | Works | Admin password reset; last-Admin protection |
| 14.3 | Roles | `/admin/roles` | `role.*` | Works | Combined page with 14.4 |
| 14.4 | Permissions | `/admin/roles` (permission matrix per role) | `role.edit` | Works | Grouped by module |
| 14.5 | Approval Rules | `/admin/approval-rules` (modal) | `approval_rule.*` | Works | Search added in this pass |
| 14.6 | Pending Approvals | `/admin/approvals` (Pending / History tabs) | `approval.view`, `approval.approve` | Works | Badge count in the menu; search added on the Pending tab in this pass |
| 14.7 | Audit Log | `/admin/audit-log` | `audit_log.view` | Works | Filters by user / action / entity / date |
| 14.8 | Document Numbering / System Configuration | `/admin/numbering` (+ 8.8 Company Settings) | `document_sequence.*` | Works | Prefix, padding, next number (can only increase) |

## Fixed during this pass

**Printing**
- **Statement** cut off the balance column on A4: wide tables now fit the page.
- **Invoice** printed "Invoice" twice when no company name was set. The demo seed now fills in company details, and the header layout no longer stacks at print width.

**Layout and display**
- **Collapsed sidebar** (phones, or collapsed by hand): the active group's pop-up stayed open over the page.
- **Order, PO and statement details** sections warned and broke layout at narrow or print widths, because of fixed column spans.

**Forms and labels**
- **Invoice picker** on the collection form wasn't linked to its label (accessibility).
- **"Choose one"** validation message on the supplier/customer field now names the field.

**Search**
- **Approval Rules** list and **Pending approvals** tab had no search.

## Known limitations (not bugs)

- **Narrow screens:** on phone width (390 px) every checked page fits without horizontal scrolling, but the collapsed sidebar still takes about 80 px. The app is designed for desktop use.
- **Ledger pages:** the Product Stock Ledger and Account Ledger are per product / per account, so they use pickers instead of a free-text search box.
