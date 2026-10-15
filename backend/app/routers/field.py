"""Authenticated field foundation. All writes are explicit human requests."""

from datetime import timedelta
from functools import wraps
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer
from fastapi.responses import HTMLResponse

from ..core import store
from ..security import auth, authz
from ..tour import schedule as tour_schedule
from ..core.fieldstore import canonical, pin_hash, pin_matches
from ..core.models import (
    AccessError, ApprovalInput, ApprovalRecord, AuthConfiguration, CheckInInput, CheckInRecord,
    DeviceCertificationInput, DeviceEnrollmentInput, DeviceRecord, EnrolledDevice,
    EnrollmentCode, EnrollmentCodeInput, ExportAuthorization, ExportInput,
    GuardCredentialInput,
    GuardRecord, IdentityInput, PermissionMatrix, Principal, RoleChangeEvent, ScopedInput,
    PinUnlockInput, PinUnlockResult, SecurityDossier, TagInput, TagRecord, TourInput, TourRecord, TourReport, TourRoute, TourRouteInput,
    PatrolStrategy, RouteCoverageInput,
)
from ..core.tracks import parse_timestamp


class FieldRoute(store.StateRoute):
    def __init__(self, path, endpoint, **kwargs):
        original = endpoint
        @wraps(original)
        def endpoint(*args, **kw):
            return run_field(original, *args, **kw)
        super().__init__(path, endpoint, **kwargs)


def run_field(function, *args, **kwargs):
    """Identity check, device binding and one durable transaction for a field operation."""
    try:
        with store.field.transaction():
            field_identity(Request(auth.current_scope.get()))
            return function(*args, **kwargs)
    finally:
        store.restore_field_state(audit=False)


def field_identity(request: Request):
    principal = authz.require("read")
    guard = authz.linked_guard(principal)
    if guard:
        authz.check_scope(guard, principal)
    if "guard" in principal.roles and request.url.path != "/api/v1/devices/enroll":
        device_for(request, principal)
    return principal


def device_for(request, principal):
    device = store.field.device(request.headers.get("X-Device-Id", ""))
    if not device:
        auth.fail("device_required")
    if device["status"] == "revoked":
        auth.fail("device_revoked")
    if not hmac.compare_digest(device["owner_sub"].encode(), principal.sub.encode()):
        auth.fail("device_owner_mismatch", 403)
    stamp = store.now()
    with store.field.connection() as db:
        db.execute("UPDATE devices SET last_seen=? WHERE id=?", (stamp, device["id"]))
    guard = authz.linked_guard(principal)
    if guard:
        store.record_contact(guard["id"], stamp)
    return device


ERROR_RESPONSES = {status: {"model": AccessError} for status in (401, 403, 409, 429, 503)}
router = APIRouter(route_class=FieldRoute, tags=["field"], dependencies=[Depends(HTTPBearer(auto_error=False))], responses=ERROR_RESPONSES)
auth_router = APIRouter(route_class=store.StateRoute, tags=["identity"], responses=ERROR_RESPONSES)


def record(kind, id):
    item = store.field.get(kind, id)
    if item is None:
        raise HTTPException(404, {"code": "record_not_found", "message": "رکورد پیدا نشد"})
    return authz.check_scope(item, own=kind not in ("routes", "tags"))


def filtered(kind):
    principal = authz.require("read")
    return [item for item in store.field.records(kind) if authz.visible(principal, item, own=kind not in ("routes", "tags"))]


def new_id(prefix):
    return prefix + "-" + secrets.token_hex(12)


@auth_router.get("/api/v1/auth/config", response_model=AuthConfiguration)
def configuration():
    issuer = os.environ.get("SEPEHR_OIDC_ISSUER", "").rstrip("/")
    return dict(mode=auth.auth_mode(), issuer=issuer,
                classification_label=store.state["settings"]["classification_label"],
                client_id=os.environ.get("SEPEHR_OIDC_WEB_CLIENT", "sepehr-web"),
                field_client_id=os.environ.get("SEPEHR_OIDC_FIELD_CLIENT", "sepehr-field"),
                admin_url=os.environ.get("SEPEHR_KEYCLOAK_ADMIN_URL", ""),
                idle_seconds=int(os.environ.get("SEPEHR_AUTH_IDLE_SECONDS", "900")))


@auth_router.get("/api/v1/auth/me", response_model=Principal)
def me():
    return authz.require("read")


@auth_router.get("/api/v1/auth/permissions", response_model=PermissionMatrix)
def permissions():
    authz.require("read")
    return dict(permissions={name: sorted(roles) for name, roles in authz.PERMISSIONS.items()},
                enforce_all=os.environ.get("SEPEHR_AUTH_ENFORCE_ALL", "false").lower() == "true")


@router.get("/api/v1/guards", response_model=list[GuardRecord])
def guards():
    return filtered("guards")


@router.put("/api/v1/guards/{id}/identity", response_model=GuardRecord)
def identity(id: str, payload: IdentityInput):
    authz.require("admin")
    guard = record("guards", id)
    previous = guard.get("keycloak_sub")
    try:
        store.field.set_identity(id, payload.sub)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "این هویت قبلاً به نگهبان دیگری پیوند خورده است")
    if previous and previous != payload.sub:
        with store.field.connection() as db:
            db.execute("UPDATE devices SET status='revoked' WHERE owner_sub=?", (previous,))
    guard["keycloak_sub"] = payload.sub
    store.field.save("guards", guard)
    store.audit("پیوند هویت نگهبان", id, payload.sub)
    return guard


@router.put("/api/v1/guards/{id}/scope", response_model=GuardRecord)
def guard_scope(id: str, payload: ScopedInput):
    authz.require("admin")
    if store.field.get("field_zones", payload.zone_id) is None:
        store.lookup("zones", payload.zone_id)
    guard = record("guards", id)
    guard.update(payload.model_dump())
    store.field.save("guards", guard)
    store.audit("تغییر محوطه و پیمانکار نگهبان", id)
    return guard


@router.put("/api/v1/guards/{id}/credentials", response_model=GuardRecord)
def credentials(id: str, payload: GuardCredentialInput):
    authz.require("admin")
    guard = record("guards", id)
    sub = guard.get("keycloak_sub")
    if not sub:
        auth.fail("guard_not_linked", 403)
    with store.field.connection() as db:
        db.execute("INSERT INTO guard_credentials VALUES(?,?,?) ON CONFLICT(sub) DO UPDATE SET pin_hash=excluded.pin_hash,duress_pin_hash=excluded.duress_pin_hash",
                   (sub, pin_hash(payload.pin), pin_hash(payload.duress_pin)))
        db.execute("DELETE FROM pin_failures WHERE sub=?", (sub,))
    store.audit("تنظیم رمز تأیید حضور نگهبان", id)
    return guard


@router.post("/api/v1/devices/enrollment-codes", response_model=EnrollmentCode, status_code=201)
def enrollment_code(payload: EnrollmentCodeInput):
    authz.require("admin")
    code = secrets.token_urlsafe(32)
    expiry = (parse_timestamp(store.now()) + timedelta(seconds=payload.ttl_seconds)).isoformat()
    with store.field.connection() as db:
        db.execute("INSERT INTO enrollment_codes(hash,owner_sub,expires_at) VALUES(?,?,?)",
                   (hashlib.sha256(code.encode()).hexdigest(), payload.owner_sub, expiry))
    store.audit("صدور کد یک‌بارمصرف ثبت دستگاه", payload.owner_sub)
    return dict(code=code, expires_at=expiry)


@router.post("/api/v1/devices/enroll", response_model=EnrolledDevice, status_code=201)
def enroll(payload: DeviceEnrollmentInput):
    principal = authz.require("read")
    if principal.mode != "keycloak":
        auth.fail("keycloak_token_required")
    stamp = store.now()
    with store.field.connection() as db:
        digest = hashlib.sha256(payload.code.encode()).hexdigest()
        code = db.execute("SELECT * FROM enrollment_codes WHERE hash=?", (digest,)).fetchone()
        if (not code or code["used"] or parse_timestamp(code["expires_at"]) <= parse_timestamp(stamp)
                or not hmac.compare_digest(code["owner_sub"].encode(), principal.sub.encode())):
            auth.fail("invalid_enrollment_code", 403)
        db.execute("UPDATE enrollment_codes SET used=1 WHERE hash=?", (digest,))
        item = dict(id=new_id("DEV"), label=payload.label, owner_sub=principal.sub, status="active",
                    ex_certified=False, device_secret=secrets.token_urlsafe(32), registered_at=stamp, last_seen=stamp)
        db.execute("INSERT INTO devices VALUES(:id,:label,:owner_sub,:status,:ex_certified,:device_secret,:registered_at,:last_seen)", item)
    store.audit("ثبت دستگاه", item["id"])
    return item


@router.get("/api/v1/devices", response_model=list[DeviceRecord])
def devices():
    principal = authz.require("read")
    authz.require("admin" if "guard" not in principal.roles else "read")
    return [item for item in store.field.devices() if "admin" in principal.roles or item["owner_sub"] == principal.sub]


@router.post("/api/v1/devices/{id}/revoke", response_model=DeviceRecord)
def revoke_device(id: str):
    authz.require("admin")
    item = store.field.device(id)
    if item is None:
        raise HTTPException(404, "دستگاه پیدا نشد")
    with store.field.connection() as db:
        db.execute("UPDATE devices SET status='revoked' WHERE id=?", (id,))
    store.audit("ابطال دستگاه؛ ابطال نشست کیکلاک باید دستی انجام شود", id)
    return store.field.device(id)


@router.put("/api/v1/devices/{id}/certification", response_model=DeviceRecord)
def certification(id: str, payload: DeviceCertificationInput):
    authz.require("admin")
    if store.field.device(id) is None:
        raise HTTPException(404, "دستگاه پیدا نشد")
    with store.field.connection() as db:
        db.execute("UPDATE devices SET ex_certified=? WHERE id=?", (payload.ex_certified, id))
    store.audit("ثبت وضعیت گواهی دستگاه توسط مدیر", id, str(payload.ex_certified))
    return store.field.device(id)


@router.get("/api/v1/tour/routes", response_model=list[TourRoute])
def routes():
    principal = authz.require("read")
    guard = authz.linked_guard(principal)
    rows = [r for r in filtered("routes") if not guard or "guard" not in principal.roles or r["guard_id"] == guard["id"]]
    return [{**r, 'station_ids': [], 'fixed_first': None, 'fixed_last': None, 'must_precede': []}
            for r in rows] if 'guard' in principal.roles else rows


@router.post("/api/v1/tour/routes", response_model=TourRoute, status_code=201)
def create_route(payload: TourRouteInput):
    authz.require("manage")
    authz.check_scope(payload.model_dump(), own=False)
    guard = record("guards", payload.guard_id)
    if (guard["zone_id"], guard["contractor_id"]) != (payload.zone_id, payload.contractor_id):
        auth.fail("scope_denied", 403)
    for station_id in payload.station_ids:
        station = store.field.get('stations', station_id)
        if not station or (station['zone_id'], station['contractor_id']) != (payload.zone_id, payload.contractor_id):
            raise HTTPException(422, 'ایستگاه مسیر باید در همان حوزه باشد')
    from ..tour.schedule import ordered_stations
    import random
    ordered_stations(payload.model_dump(), random.Random(0))
    item = dict(**payload.model_dump(), id=new_id("ROUTE"), created_at=store.now())
    store.field.save("routes", item)
    store.audit("تعریف مسیر گشت", item["id"])
    return item


@router.put("/api/v1/tour/routes/{id}/coverage", response_model=TourRoute)
def route_coverage(id: str, payload: RouteCoverageInput):
    from ..intel import patrol_game
    return patrol_game.set_route_coverage(record("routes", id), payload)


@router.get("/api/v1/tour/routes/{id}/strategy", response_model=PatrolStrategy)
def route_strategy(id: str, horizon_hours: float = Query(default=2.0, gt=0, le=24), stations_per_tour: int | None = Query(default=None, ge=1, le=500)):
    """Preview of per-station visit probabilities for a walking route; nothing is stored."""
    authz.require("manage")
    from ..intel import patrol_game
    route = record("routes", id)
    if stations_per_tour is not None:
        route = {**route, "stations_per_tour": min(stations_per_tour, len(route["station_ids"]))}
    return patrol_game.route_strategy(route, horizon_hours, store.now())[0]


@router.get("/api/v1/tour", response_model=list[TourRecord])
def tours():
    return filtered("tour")


@router.post("/api/v1/tour", response_model=TourRecord, status_code=201)
def start_tour(payload: TourInput, request: Request):
    principal = authz.require("read")
    if "guard" not in principal.roles:
        auth.fail("guard_role_required", 403)
    device_for(request, principal)
    route = record("routes", payload.route_id)
    guard = authz.linked_guard(principal)
    if route["guard_id"] != guard["id"]:
        auth.fail("scope_denied", 403)
    today = tour_schedule.local_day(store.now()).isoformat()
    if not payload.scheduled_tour_id and any(s['route_id'] == route['id'] and s['status'] == 'approved'
                                                and s['first_date'] <= today <= s['last_date'] for s in store.field.records('tour_schedules')):
        raise HTTPException(409, 'برای این مسیر باید دور تأییدشده از صف انتخاب شود')
    scheduled = None
    if payload.scheduled_tour_id:
        scheduled = record('scheduled_tours', payload.scheduled_tour_id)
        if scheduled['route_id'] != route['id'] or scheduled['guard_id'] != guard['id'] or scheduled['status'] != 'queued':
            raise HTTPException(409, 'دور برنامه‌ریزی‌شده قابل شروع نیست')
        if parse_timestamp(store.now()) > parse_timestamp(scheduled['ends_at']):
            raise HTTPException(409, 'پنجره دور برنامه‌ریزی‌شده سپری شده است')
        if store.field.get('emergency_modes', route['zone_id']) and store.field.get('emergency_modes', route['zone_id'])['active']:
            raise HTTPException(409, 'در وضعیت اضطرار شروع دور مجاز نیست')
        if store.state['settings']['handover_required']:
            handover = next((h for h in store.field.records('shift_handovers') if h['incoming_guard_id'] == guard['id']
                             and h['zone_id'] == route['zone_id'] and h['acknowledged_at']
                             and abs((parse_timestamp(scheduled['due_at']) - parse_timestamp(h['acknowledged_at'])).total_seconds()) <= 86400), None)
            if not handover:
                raise HTTPException(409, 'تحویل شیفت هنوز تأیید نشده است')
            scheduled['handover_id'] = handover['id']
    if any(t["status"] == "active" for t in filtered("tour")):
        raise HTTPException(409, "گشت فعال دیگری وجود دارد")
    item = dict(id=new_id("TOUR"), route_id=route["id"], guard_id=guard["id"], owner_sub=principal.sub,
                zone_id=route["zone_id"], contractor_id=route["contractor_id"], status="active",
                started_at=store.now(), completed_at=None, scheduled_tour_id=payload.scheduled_tour_id)
    store.field.save("tour", item)
    if scheduled:
        scheduled.update(status='active', tour_id=item['id'])
        store.field.save('scheduled_tours', scheduled)
    store.audit("شروع گشت نگهبانی", item["id"])
    return item


@router.get("/api/v1/tour/{id}", response_model=TourRecord)
def tour(id: str):
    return record("tour", id)


@router.post("/api/v1/tour/{id}/complete", response_model=TourRecord)
def complete(id: str):
    principal = authz.require("read")
    item = record("tour", id)
    if "guard" not in principal.roles or item["owner_sub"] != principal.sub:
        auth.fail("permission_denied", 403)
    if item["status"] != "active":
        raise HTTPException(409, "گشت فعال نیست")
    if any(v["tour_id"] == id and v["completed_at"] is None for v in store.field.records("station_visits")):
        raise HTTPException(409, "بازدید باز ایستگاه باید ابتدا تکمیل شود")
    item.update(status="completed", completed_at=store.now())
    store.field.save("tour", item)
    if item.get('scheduled_tour_id'):
        scheduled = store.field.get('scheduled_tours', item['scheduled_tour_id'])
        scheduled['status'] = 'completed'
        store.field.save('scheduled_tours', scheduled)
    store.audit("پایان گشت نگهبانی", id)
    return item


@router.post("/api/v1/tour/{id}/check-in", response_model=CheckInRecord, status_code=201)
def check_in(id: str, payload: CheckInInput, request: Request):
    principal = authz.require("read")
    item = record("tour", id)
    if "guard" not in principal.roles or item["owner_sub"] != principal.sub:
        auth.fail("permission_denied", 403)
    if item["status"] != "active":
        raise HTTPException(409, "گشت فعال نیست")
    device = device_for(request, principal)
    stamp = store.now()
    pin_status = verify_field_pin(principal, payload.pin, id, stamp)
    if pin_status == 'invalid':
        from starlette.responses import JSONResponse
        return JSONResponse({"detail": {"code": "invalid_pin", "message": "رمز معتبر نیست"}}, status_code=403)
    if pin_status == 'duress':
        from ..field import safety as field_safety
        field_safety.record_duress(item, device, stamp)
    result = dict(id=new_id("CHECK"), tour_id=id, guard_id=item["guard_id"], owner_sub=principal.sub,
                  device_id=device["id"], time=stamp, zone_id=item["zone_id"], contractor_id=item["contractor_id"])
    store.field.save("checkins", result)
    store.audit("تأیید حضور آنلاین", id)
    return result


def verify_field_pin(principal, pin, tour_id, stamp):
    with store.field.connection() as db:
        credential = db.execute("SELECT * FROM guard_credentials WHERE sub=?", (principal.sub,)).fetchone()
        failure = db.execute("SELECT * FROM pin_failures WHERE sub=?", (principal.sub,)).fetchone()
        if failure and failure["locked_until"] and parse_timestamp(failure["locked_until"]) > parse_timestamp(stamp):
            auth.fail("pin_rate_limited", 429)
        if not credential:
            auth.fail("pin_not_configured", 403)
        normal = pin_matches(pin, credential["pin_hash"])
        duress = pin_matches(pin, credential["duress_pin_hash"])
        if not normal and not duress:
            # Commit failed-attempt counters independently of the failed request.
            # This endpoint returns a response rather than raising to retain its transaction.
            attempts = (failure["attempts"] if failure else 0) + 1
            until = (parse_timestamp(stamp) + timedelta(minutes=5)).isoformat() if attempts >= 5 else None
            db.execute("INSERT INTO pin_failures VALUES(?,?,?) ON CONFLICT(sub) DO UPDATE SET attempts=excluded.attempts,locked_until=excluded.locked_until",
                       (principal.sub, attempts, until))
            store.audit("رد تأیید حضور با رمز نامعتبر", tour_id)
            return 'invalid'
        db.execute("DELETE FROM pin_failures WHERE sub=?", (principal.sub,))
    return 'duress' if duress else 'normal'


@router.post('/api/v1/tour/unlock', response_model=PinUnlockResult)
def unlock(payload: PinUnlockInput, request: Request):
    principal = authz.require('read')
    item = record('tour', payload.tour_id)
    if 'guard' not in principal.roles or item['owner_sub'] != principal.sub or item['status'] != 'active':
        auth.fail('permission_denied', 403)
    device = device_for(request, principal)
    stamp = store.now()
    status = verify_field_pin(principal, payload.pin, item['id'], stamp)
    if status == 'invalid':
        from starlette.responses import JSONResponse
        return JSONResponse({"detail": {"code": "invalid_pin", "message": "رمز معتبر نیست"}}, status_code=403)
    if status == 'duress':
        from ..field import safety as field_safety
        field_safety.record_duress(item, device, stamp)
    store.audit('بازکردن قفل اپ میدانی', item['id'])
    return dict(unlocked=True, checked_at=stamp)


@router.get("/api/v1/tour/tags/list", response_model=list[TagRecord])
def tags():
    return filtered("tags")


@router.post("/api/v1/tour/tags", response_model=TagRecord, status_code=201)
def create_tag(payload: TagInput):
    authz.require("manage")
    authz.check_scope(payload.model_dump(), own=False)
    item = dict(**payload.model_dump(), id=new_id("TAG"), status="active", key_version=1)
    store.field.save("tags", {**item, "key": secrets.token_urlsafe(32)})
    store.audit("ثبت تگ", item["id"])
    return item


@router.get("/api/v1/reports/tour", response_model=TourReport)
def tour_report():
    authz.require("export")
    store.audit("دریافت گزارش گشت نگهبانی", "TOUR-REPORT")
    visits = filtered("station_visits")
    ids = {v["id"] for v in visits}
    return dict(classification_label=store.state["settings"]["classification_label"], generated_at=store.now(),
                tours=filtered("tour"), checkins=filtered("checkins"), station_visits=visits,
                task_results=[r for r in store.field.records("station_results") if r["visit_id"] in ids])


def target_for(payload):
    if payload.action == "change_classification":
        if payload.target_id != "SETTINGS":
            raise HTTPException(422, "مرجع طبقه‌بندی باید SETTINGS باشد")
        return {"classification_label": store.state["settings"]["classification_label"]}
    if payload.action in ("rotate_tag_key", "revoke_tag") and store.field.get("stations", payload.target_id):
        return authz.check_scope(store.field.get("stations", payload.target_id), own=False)
    return record("routes" if payload.action == "delete_route" else "tags", payload.target_id)


def fingerprint(item):
    return hashlib.sha256(canonical(item).encode()).hexdigest()


@router.post("/api/v1/approvals", response_model=ApprovalRecord, status_code=201)
def request_approval(payload: ApprovalInput):
    principal = authz.require("approval")
    target = target_for(payload)
    if payload.action == "change_classification":
        authz.require("admin")
    if payload.action in ("rotate_tag_key", "revoke_tag") and (target.get("tag_status") == "revoked" or target.get("status") == "revoked"):
        raise HTTPException(409, "تگ ابطال‌شده قابل تغییر نیست")
    item = dict(**payload.model_dump(), id=new_id("APPROVAL"), requested_by=principal.sub,
                approved_by=None, status="pending", requested_at=store.now(), decided_at=None,
                expected_version=fingerprint(target))
    if payload.action != "change_classification":
        item.update(zone_id=target["zone_id"], contractor_id=target["contractor_id"])
    store.field.save("approvals", item)
    store.audit("درخواست تأیید دونفره", item["id"], payload.action)
    return item


@router.get("/api/v1/approvals", response_model=list[ApprovalRecord])
def approvals():
    principal = authz.require("approval")
    return [a for a in store.field.records("approvals") if (a["action"] == "change_classification" and "admin" in principal.roles) or authz.visible(principal, a, own=False)]


@router.post("/api/v1/approvals/{id}/approve", response_model=ApprovalRecord)
def approve(id: str):
    return decide(id, True)


@router.post("/api/v1/approvals/{id}/reject", response_model=ApprovalRecord)
def reject(id: str):
    return decide(id, False)


def decide(id, accepted):
    principal = authz.require("approval")
    item = store.field.get("approvals", id)
    if not item:
        raise HTTPException(404, "درخواست پیدا نشد")
    if principal.sub == item["requested_by"]:
        auth.fail("two_person_required", 403)
    if item["status"] != "pending":
        raise HTTPException(409, "درخواست قبلاً تعیین تکلیف شده است")
    payload = ApprovalInput.model_validate({key: item[key] for key in ApprovalInput.model_fields if key in item})
    if payload.action == "change_classification":
        authz.require("admin")
    else:
        authz.check_scope(item, own=False)
    target = target_for(payload)
    if fingerprint(target) != item["expected_version"]:
        raise HTTPException(409, "مرجع درخواست تغییر کرده است؛ درخواست جدید لازم است")
    if accepted:
        if payload.action == "delete_route":
            if any(t["route_id"] == target["id"] and t["status"] == "active" for t in store.field.records("tour")):
                raise HTTPException(409, "مسیر دارای گشت فعال قابل حذف نیست")
            store.field.delete("routes", target["id"])
        elif payload.action == "change_classification":
            store.field.save("settings", dict(id="classification", classification_label=payload.classification_label))
            store.state["settings"]["classification_label"] = payload.classification_label
        elif "tag_status" in target:
            from ..tour.tags import change_station_tag
            change_station_tag(target, payload.action)
        else:
            if payload.action == "revoke_tag":
                target["status"] = "revoked"
            else:
                target.update(key=secrets.token_urlsafe(32), key_version=target["key_version"] + 1)
            store.field.save("tags", target)
    item.update(status="approved" if accepted else "rejected", approved_by=principal.sub, decided_at=store.now())
    store.field.save("approvals", item)
    store.audit("تأیید دونفره و اعمال تغییر" if accepted else "رد درخواست دونفره", id, payload.action)
    return item


@auth_router.post("/api/v1/exports", response_model=ExportAuthorization)
def authorize_export(payload: ExportInput):
    principal = authz.require("export")
    if payload.media_id is not None:
        from ..field import media as field_media
        media = store.field.get("media", payload.media_id)
        if media is None or not field_media.may_view(principal, media):
            raise HTTPException(404, "رسانه پیدا نشد")
        if field_media.restricted(media):
            store.audit("رد خروجی رسانه محدود", media["id"], media["category"])
            raise HTTPException(403, {"code": "media_export_denied", "message": "رسانه خسارت، مهمات و پهپاد قابل خروجی نیست"})
    item = store.audit("مجوز خروجی طبقه‌بندی‌شده", payload.name)
    return dict(classification_label=store.state["settings"]["classification_label"], audit_id=item["id"], generated_at=item["time"])


@auth_router.get("/api/v1/audit/security-dossier", response_model=SecurityDossier)
def security_dossier():
    """Auditor-only evidence package for the AFTA security-assessment inquiry."""
    authz.require("audit")
    from ..security import dossier
    result = dossier.build()
    entry = store.audit("دریافت پرونده شواهد ارزیابی امنیتی (افتا)", "SECURITY-DOSSIER")
    return dict(result, audit_id=entry["id"])


@auth_router.get("/api/v1/audit/security-dossier/letter", response_class=HTMLResponse,
                 responses={200: {"content": {"text/html": {"schema": {"type": "string"}}}}})
def security_letter():
    """Printable AFTA inquiry draft built from the same dossier; auditor-only and audited."""
    authz.require("audit")
    from ..security import afta_letter, dossier
    html = afta_letter.render_letter(dossier.build())
    store.audit("تولید پیش‌نویس استعلام افتا", "SECURITY-DOSSIER")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@auth_router.get("/api/v1/audit/role-changes", response_model=list[RoleChangeEvent])
def role_changes():
    authz.require("audit")
    issuer = os.environ.get("SEPEHR_OIDC_INTERNAL_ISSUER", os.environ.get("SEPEHR_OIDC_ISSUER", "")).rstrip("/")
    secret = os.environ.get("SEPEHR_AUDIT_CLIENT_SECRET", "")
    if not issuer or not secret:
        raise HTTPException(503, "کلاینت سرویس ممیزی کیکلاک تنظیم نشده است")
    try:
        data = urlencode({"grant_type": "client_credentials", "client_id": "sepehr-audit", "client_secret": secret}).encode()
        req = URLRequest(issuer + "/protocol/openid-connect/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=5) as response:
            token = json.load(response)["access_token"]
        realm_base = issuer.rsplit("/realms/", 1)
        url = realm_base[0] + "/admin/realms/" + realm_base[1] + "/admin-events?first=0&max=100"
        with urlopen(URLRequest(url, headers={"Authorization": "Bearer " + token}), timeout=5) as response:
            events = json.load(response)
    except Exception:
        raise HTTPException(503, "دریافت رخدادهای نقش از کیکلاک ممکن نیست")
    from datetime import datetime, timezone
    result = [dict(time=datetime.fromtimestamp(e["time"] / 1000, timezone.utc).isoformat(),
                   operation=e["operationType"], resource_path=e.get("resourcePath", ""),
                   actor_id=e.get("authDetails", {}).get("userId"))
              for e in events if "role-mappings" in e.get("resourcePath", "") or e.get("resourcePath", "").startswith("roles")]
    store.audit("مشاهده رخدادهای تغییر نقش کیکلاک", "KEYCLOAK-ADMIN-EVENTS")
    return result
