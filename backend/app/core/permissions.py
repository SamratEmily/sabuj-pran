"""Single registry of every permission code. Synced into the `permissions` table on startup/seed."""

CRUD_ACTIONS = ("view", "create", "edit", "delete")

# resource -> module (used to group permissions in the UI)
CRUD_RESOURCES: dict[str, str] = {
    "user": "admin",
    "role": "admin",
    "company_setting": "admin",
    "document_sequence": "admin",
    "approval_rule": "approvals",
    "product": "master",
    "category": "master",
    "unit": "master",
    "price": "master",
    "warehouse": "master",
    "expense_category": "master",
    "income_category": "master",
    "payment_method": "master",
    "money_account": "master",
    "customer": "parties",
    "supplier": "parties",
    "quotation": "sales",
    "sales_order": "sales",
    "delivery": "sales",
    "invoice": "sales",
    "sales_return": "sales",
    "purchase_order": "purchase",
    "goods_receipt": "purchase",
    "purchase_return": "purchase",
    "stock": "inventory",
    "stock_transfer": "inventory",
    "stock_adjustment": "inventory",
    "stock_count": "inventory",
    "collection": "money",
    "supplier_payment": "money",
    "expense": "money",
    "income": "money",
    "money_transfer": "money",
    "employee": "employees",
    "attendance": "employees",
    "payroll": "employees",
}

# code -> (module, description)
SPECIAL_PERMISSIONS: dict[str, tuple[str, str]] = {
    "approval.view": ("approvals", "View approval requests"),
    "approval.approve": ("approvals", "Approve or reject requests"),
    "audit_log.view": ("admin", "View audit log"),
    "dashboard.view": ("dashboard", "View management dashboard"),
    "reservation.manage": ("sales", "Reserve and release stock for sales orders"),
    "party_statement.view": ("parties", "View customer/supplier statements"),
}


def _describe(resource: str, action: str) -> str:
    return f"{action.capitalize()} {resource.replace('_', ' ')}"


# code -> (module, description), in a stable order
PERMISSION_DEFINITIONS: dict[str, tuple[str, str]] = {
    f"{resource}.{action}": (module, _describe(resource, action))
    for resource, module in CRUD_RESOURCES.items()
    for action in CRUD_ACTIONS
} | SPECIAL_PERMISSIONS

PERMISSIONS: list[str] = list(PERMISSION_DEFINITIONS)
PERMISSION_SET: frozenset[str] = frozenset(PERMISSIONS)
