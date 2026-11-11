"""Role-based access control. Roles map to permissions; endpoints check permissions, never role names.

Roles
  accountant        Nhân viên kế toán
  chief_accountant  Kế toán trưởng (supervises a team of accountants)
  customer          Khách hàng (sees only their own invoices and payments)
  admin             Admin (users, roles, audit log; no financial data)
"""

ACCOUNTANT = "accountant"
CHIEF = "chief_accountant"
CUSTOMER = "customer"
ADMIN = "admin"

ROLES = (ACCOUNTANT, CHIEF, CUSTOMER, ADMIN)

ROLE_LABEL = {
    ACCOUNTANT: "Nhân viên kế toán",
    CHIEF: "Kế toán trưởng",
    CUSTOMER: "Khách hàng",
    ADMIN: "Quản trị",
}

_STAFF = frozenset({
    "invoice:read_all", "payment:read_all", "summary:read_all",
    "prediction:read", "forecast:read", "obligation:write",
    "draft:create", "draft:read_own",
    "task:read_own", "task:update",
})

PERMISSIONS: dict[str, frozenset[str]] = {
    ACCOUNTANT: _STAFF,
    CHIEF: _STAFF | {"draft:read_team", "draft:decide", "task:read_team", "task:assign"},
    CUSTOMER: frozenset({"invoice:read_own", "payment:read_own", "summary:read_own"}),
    ADMIN: frozenset({"user:manage", "audit:read"}),
}


def permissions_of(role: str) -> frozenset[str]:
    return PERMISSIONS.get(role, frozenset())


def has_permission(role: str, permission: str) -> bool:
    return permission in permissions_of(role)
