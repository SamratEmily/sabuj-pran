# Business rules (single source of truth)

## Costing
Weighted average cost per product per warehouse.
- Stock IN at cost c, qty q: new_avg = (on_hand*avg + q*c) / (on_hand + q).
- Stock OUT uses current avg_cost; avg_cost does not change on OUT.
- Available = on_hand - reserved.
- Inventory value = sum(on_hand * avg_cost).

## Stock posting
| Event | Stock effect | Cost used |
|---|---|---|
| Goods receipt / direct purchase | IN | receipt unit cost |
| Purchase return | OUT | original receipt unit cost |
| Delivery | OUT (consumes reservation first) | current avg_cost (stored as COGS on delivery item) |
| Sales return | IN | COGS recorded on the original delivery item |
| Transfer | OUT source, IN destination | source avg_cost |
| Adjustment (+/-) | IN / OUT | + : given cost or current avg; - : current avg |
| Physical count posting | adjustment for each variance | as adjustment |

## Party ledger (customers and suppliers)
Table party_ledger: party_type (customer|supplier), party_id, entry_date, debit, credit, ref_type, ref_id, note.
- Customer due = SUM(debit) - SUM(credit). Invoice = debit. Collection = credit. Sales return = credit. Refund paid to customer = debit. Opening due = debit.
- Supplier due = SUM(credit) - SUM(debit). Goods receipt = credit. Supplier payment = debit. Purchase return = debit. Opening due = credit.

## Money ledger
Table money_transactions (append-only): account_id, direction (in|out), amount, txn_type, ref_type, ref_id, txn_date, note.
- Account balance = SUM(in) - SUM(out). Account opening balance is posted as txn_type OPENING (in).
- Customer collection = IN. Supplier payment = OUT. Expense = OUT. Other income = IN. Transfer = OUT from source + IN to destination. Payroll payment = OUT. Customer refund = OUT.

## Document flows
- Quotation: draft -> sent -> accepted | rejected | converted (to Sales Order).
- Sales Order: draft -> confirmed -> partially_delivered -> delivered | cancelled. Items track: ordered, reserved, produced (manual number, default 0, no production module), delivered, remaining = ordered - delivered.
- Reservation reserves min(available, remaining - already reserved) from a chosen warehouse. Delivery consumes reservation first. Cancel releases reservations.
- Delivery: against a Sales Order, qty <= remaining. Posts stock OUT, stores COGS, and (default on) creates an Invoice for the delivered lines in the same transaction.
- Invoice: customer ledger debit. status unpaid | partial | paid from paid_amount. Collections may optionally be linked to an invoice.
- Sales Return: against an Invoice line, qty <= delivered - already returned. Stock IN at COGS, customer ledger credit, optional refund.
- Purchase Order: draft -> pending_approval (if rule) -> approved -> partially_received -> received | cancelled.
- Goods Receipt: against a PO (qty <= remaining) or direct (no PO). Stock IN, supplier ledger credit.
- Purchase Return: against a goods receipt line, qty <= received - already returned.
- Approvals: rules by document_type + min_amount + approver role. Applies to PURCHASE_ORDER, EXPENSE, SUPPLIER_PAYMENT, STOCK_ADJUSTMENT. Requester cannot approve their own request. While pending, nothing is posted.

## Dashboard metric definitions
- Today's Sales = sum of invoice totals dated today minus sales returns dated today.
- Today's Collection = customer collections dated today.
- Today's Expenses = expenses dated today (includes payroll payments).
- Today's Purchase = goods receipt value dated today minus purchase returns dated today.
- Cash / Bank / MFS = sum of account balances by account type.
- Customer Due / Supplier Due = sums of positive balances per party ledger rules.
- Inventory Value = sum(on_hand * avg_cost).
- Pending Orders = count and remaining value of sales orders in confirmed or partially_delivered.
- Estimated Profit (month to date) = net sales - COGS (net of returns) + other income - expenses.

## Roles (seeded)
Admin (all permissions), Owner (view everything + approve), Sales, Purchase/Store, Accounts.
