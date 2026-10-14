"""Server-side permission data and claim-derived field scope."""

import os
from .auth import current_principal, fail

STAFF = {"shift_supervisor", "security_officer", "security_manager", "admin"}
READERS = STAFF | {"guard", "auditor"}
PERMISSIONS = {
    "read": READERS,
    "station_read": READERS,
    "manage": STAFF,
    "admin": {"admin"},
    "audit": {"auditor"},
    "approval": {"admin", "security_officer", "security_manager"},
    "export": {"admin", "auditor", "security_officer", "security_manager", "shift_supervisor"},
    "legacy_read": STAFF | {"auditor"},
    "legacy_write": STAFF,
}
MANDATORY = ("/api/v1/tour", "/api/v1/guards", "/api/v1/devices", "/api/v1/media",
             "/api/v1/messages", "/api/v1/reports/tour", "/api/v1/approvals", "/api/v1/exports",
             "/api/v1/auth", "/api/v1/audit", "/api/v1/demo")


def under(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def protected(path):
    return (any(under(path, prefix) for prefix in MANDATORY)
            or (path.startswith("/api/v1/") and os.environ.get("SEPEHR_AUTH_ENFORCE_ALL", "false").lower() == "true"))


def require(permission, principal=None):
    principal = principal or current_principal.get()
    if principal is None:
        fail("authentication_required")
    if not set(principal.roles) & PERMISSIONS[permission]:
        fail("permission_denied", 403)
    return principal


def authorize_path(principal, path, method):
    if not path.startswith("/api/v1/"):
        return
    if (path.startswith('/api/v1/assets/') and path.endswith('/positions:batch')
            and len(path.split('/')) == 6 and method == 'POST'):
        require('read', principal)
        return
    if path in ("/api/v1/audit/verify", "/api/v1/audit/role-changes") or under(path, "/api/v1/audit"):
        require("audit", principal)
    elif under(path, "/api/v1/exports"):
        require("export", principal)
    elif under(path, "/api/v1/approvals"):
        require("approval", principal)
    elif under(path, "/api/v1/demo"):
        require("admin", principal)
    elif any(under(path, prefix) for prefix in MANDATORY):
        require("read", principal)
    else:
        # Guard tokens may never expose unscopeable legacy operational data.
        require("legacy_read" if method == "GET" else "legacy_write", principal)


def visible(principal, record, *, own=True):
    if "admin" in principal.roles or principal.mode == "demo":
        return True
    if (record.get("zone_id") not in principal.zone_ids
            or not principal.contractor_id or record.get("contractor_id") != principal.contractor_id):
        return False
    if own and "guard" in principal.roles:
        return record.get("owner_sub", record.get("keycloak_sub")) == principal.sub
    return True


def check_scope(record, principal=None, *, own=True):
    principal = principal or require("read")
    if not visible(principal, record, own=own):
        fail("scope_denied", 403)
    return record


def linked_guard(principal=None):
    from . import store
    principal = principal or require("read")
    guards = store.field.records("guards")
    found = next((g for g in guards if g.get("keycloak_sub") == principal.sub), None)
    if "guard" in principal.roles and found is None:
        fail("guard_not_linked", 403)
    return found


def legacy_asset(asset):
    """New identity fields never leak through the optionally public legacy API."""
    principal = current_principal.get()
    if principal and "admin" in principal.roles:
        return asset
    return {**asset, "keycloak_sub": None, "contractor_id": None, "zone_id": None}
