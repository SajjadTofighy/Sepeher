"""Spatial mission commands: a human order with a per-recipient receipt chain, never a device action.

Lifecycle of each recipient (one state machine per addressed guard):

    dispatched -> delivered -> acknowledged -> in_progress -> completed
    terminal exceptions: rejected, failed, expired (not acknowledged before expires_at), cancelled

* delivered is recorded only when the guard's enrolled device actually fetched the command;
  "stored on the server" is never reported as "seen".
* acknowledgement is the guard's explicit act; a device without a human app cannot receive.
* every action carries an event_id: a retry (double tap, offline resend) is a no-op, not a second act.
* a receipt after a terminal state is kept in the timeline as history and never revives the command.
* every transition and its audit record commit in one field-store transaction.
"""
from datetime import timedelta
import hashlib
import json
import secrets

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ..core import engine, store
from ..core.sim import distance_km
from ..core.tracks import parse_timestamp
from ..intel import geo
from ..security import auth, authz

KIND = "mission_commands"
TERMINAL = {"completed", "rejected", "failed", "expired", "cancelled"}
PROGRESS = ("dispatched", "delivered", "acknowledged", "in_progress", "completed")
# One completion closes the order for everybody, except where each guard must act personally.
EACH_RECIPIENT = {"presence"}
TRANSITIONS = {
    "acknowledge": ({"dispatched", "delivered"}, "acknowledged"),
    "reject": ({"dispatched", "delivered"}, "rejected"),
    "start": ({"acknowledged"}, "in_progress"),
    "complete": ({"acknowledged", "in_progress"}, "completed"),
    "fail": ({"acknowledged", "in_progress"}, "failed"),
}
LABELS = {"acknowledge": "پذیرش مأموریت", "reject": "رد مأموریت", "start": "شروع اجرای مأموریت",
          "complete": "تکمیل مأموریت", "fail": "اعلام عدم امکان اجرای مأموریت"}


def _ring(geometry):
    ring = geometry["coordinates"][0]
    return ring[:-1] if len(ring) > 3 and ring[0] == ring[-1] else ring


def relation(geometry, radius_m, lon, lat):
    """(distance to the geometry in metres, inside?) using the shared geometry helpers."""
    point = [lon, lat]
    if geometry["type"] == "Point":
        distance = distance_km(point, geometry["coordinates"]) * 1000
        return distance, distance <= radius_m
    if geometry["type"] == "LineString":
        distance = geo.point_polyline_distance_m(point, geometry["coordinates"])
        return distance, distance <= radius_m
    ring = _ring(geometry)
    if engine.point_in_polygon(lon, lat, ring):
        return 0.0, True
    distance = geo.point_polyline_distance_m(point, [*ring, ring[0]])
    return distance, distance <= radius_m


def _receivers():
    """Assets that can receive a human order: guards linked to an account (they have the field app)."""
    linked = {g["id"] for g in store.field.records("guards") if g.get("keycloak_sub")}
    return linked


def preview(geometry, radius_m, principal=None):
    principal = principal or authz.require("manage")
    store.refresh_tracks()
    receivers = _receivers()
    groups = dict(eligible=[], needs_review=[], outside=[], cannot_receive=[])
    for asset in store.state["assets"]:
        if not authz.visible(principal, asset, own=False):
            continue
        state = asset.get("position_state", "unknown")
        known = state != "unknown"
        distance, inside = relation(geometry, radius_m, asset["lon"], asset["lat"]) if known else (None, None)
        row = dict(asset_id=asset["id"], name=asset["name"], position_state=state,
                   lon=asset["lon"] if known else None, lat=asset["lat"] if known else None,
                   observed_at=asset.get("last_seen") if known else None,
                   distance_m=round(distance, 1) if distance is not None else None, inside=inside,
                   can_receive=asset["id"] in receivers, reason="")
        if not row["can_receive"]:
            row["reason"] = "بدون حساب نگهبان و اپ میدانی؛ فرمان انسانی قابل تحویل نیست"
            groups["cannot_receive"].append(row)
        elif state != "fresh":
            # Old or unknown positions are never counted as "in the area"; the operator decides.
            row["reason"] = {"stale": "موقعیت کهنه", "no_fix": "ارتباط دارد ولی موقعیت ندارد",
                             "simulated": "موقعیت شبیه‌سازی‌شده", "unknown": "موقعیت نامعلوم"}.get(state, state)
            groups["needs_review"].append(row)
        elif inside:
            groups["eligible"].append(row)
        else:
            groups["outside"].append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: (r["distance_m"] is None, r["distance_m"] or 0, r["asset_id"]))
    membership = sorted((r["asset_id"], group) for group, rows in groups.items() for r in rows)
    snapshot_id = hashlib.sha256(json.dumps(membership).encode()).hexdigest()[:32]
    return dict(snapshot_id=snapshot_id, computed_at=store.now(), **groups)


def overall(command):
    statuses = [r["status"] for r in command["recipients"]]
    active = [s for s in statuses if s not in TERMINAL]
    if active:
        return max(active, key=PROGRESS.index)
    for status in ("completed", "failed"):
        if status in statuses:
            return status
    if all(s == "rejected" for s in statuses):
        return "rejected"
    return "expired" if "expired" in statuses else "cancelled"


def _event(command, action, *, asset_id=None, before=None, after=None, event_id=None, applied=True, detail="", actor=None):
    principal = auth.current_principal.get()
    command["timeline"].append(dict(time=store.now(), actor=actor or (principal.username if principal else "سامانه"),
                                    asset_id=asset_id, action=action, from_status=before, to_status=after,
                                    event_id=event_id, applied=applied, detail=detail))


def _save(command, audit_action, detail=""):
    command["status"] = overall(command)
    command["revision"] += 1
    with store.field.transaction():
        store.field.save(KIND, command)
        store.audit(audit_action, command["id"], detail)
    return command


def _view(command):
    now = parse_timestamp(store.now())
    due = command.get("due_at")
    return {**command, "overdue": bool(due) and command["status"] not in TERMINAL and now > parse_timestamp(due)}


def expire_due(now=None):
    """Unacknowledged recipients expire at expires_at; accepted work continues to its own end."""
    stamp = parse_timestamp(now or store.now())
    for command in store.field.records(KIND):
        if command["status"] in TERMINAL or stamp < parse_timestamp(command["expires_at"]):
            continue
        changed = False
        for recipient in command["recipients"]:
            if recipient["status"] in ("dispatched", "delivered"):
                _event(command, "انقضای مهلت پذیرش", asset_id=recipient["asset_id"], before=recipient["status"],
                       after="expired", actor="سامانه")
                recipient.update(status="expired", finished_at=stamp.isoformat())
                changed = True
        if changed:
            _save(command, "انقضای فرمان مأموریت", command["id"])


def _fingerprint(payload):
    data = payload.model_dump(mode="json", exclude={"snapshot_id"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def create(payload):
    principal = authz.require("manage")
    fingerprint = _fingerprint(payload)
    existing = next((c for c in store.field.records(KIND)
                     if c["created_by_sub"] == principal.sub and c["idempotency_key"] == payload.idempotency_key), None)
    if existing:
        if existing["payload_fingerprint"] != fingerprint:
            raise HTTPException(409, {"code": "idempotency_conflict",
                                      "message": "این کلید یکتایی قبلاً برای فرمان دیگری استفاده شده است"})
        return _view(existing), False
    geometry = payload.geometry.model_dump()
    current = preview(geometry, payload.radius_m, principal)
    if current["snapshot_id"] != payload.snapshot_id:
        raise HTTPException(409, {"code": "recipients_changed",
                                  "message": "وضعیت یا محل مخاطبان از زمان پیش‌نمایش تغییر کرده است؛ دوباره بازبینی کنید",
                                  "preview": current})
    candidates = {r["asset_id"]: r for group in ("eligible", "needs_review", "outside") for r in current[group]}
    unknown = [id for id in payload.recipients if id not in candidates]
    if unknown:
        raise HTTPException(422, f"مخاطب قابل تحویل یا در حوزه شما نیست: {', '.join(unknown)}")
    assets = [store.lookup("assets", id) for id in payload.recipients]
    scopes = {(a.get("zone_id"), a.get("contractor_id")) for a in assets}
    if len(scopes) > 1:
        raise HTTPException(422, "همه مخاطبان یک فرمان باید در یک حوزه و پیمانکار باشند")
    zone_id, contractor_id = scopes.pop()
    stamp = store.now()
    command = dict(
        id="MCMD-" + secrets.token_hex(8), revision=0, type=payload.type, title=payload.title.strip(),
        instructions=payload.instructions.strip(), priority=payload.priority, geometry=geometry,
        radius_m=payload.radius_m, status="dispatched", created_at=stamp, created_by=principal.username,
        created_by_sub=principal.sub, idempotency_key=payload.idempotency_key, payload_fingerprint=fingerprint,
        expires_at=(parse_timestamp(stamp) + timedelta(minutes=payload.ack_ttl_minutes)).isoformat(),
        due_at=payload.due_at.isoformat() if payload.due_at else None, zone_id=zone_id, contractor_id=contractor_id,
        recipients=[dict(asset_id=a["id"], name=a["name"], status="dispatched", snapshot=candidates[a["id"]],
                         delivered_at=None, delivered_device_id=None, acknowledged_at=None, started_at=None,
                         finished_at=None, note=None, evidence=None) for a in assets],
        timeline=[], can_execute=False)
    _event(command, "ثبت و ارسال فرمان مأموریت", after="dispatched",
           detail=f"{len(assets)} مخاطب؛ {sum(candidates[a['id']]['position_state'] != 'fresh' for a in assets)} با موقعیت غیرتازه")
    return _view(_save(command, "ثبت فرمان مأموریت مکانی", f"{payload.type} · {len(assets)} مخاطب")), True


def visible_commands(principal, status=None):
    expire_due()
    rows = [c for c in store.field.records(KIND) if authz.visible(principal, c, own=False)]
    if status == "active":
        rows = [c for c in rows if c["status"] not in TERMINAL]
    elif status:
        rows = [c for c in rows if c["status"] == status]
    return [_view(c) for c in sorted(rows, key=lambda c: c["created_at"], reverse=True)]


def lookup(id, principal=None):
    command = store.field.get(KIND, id)
    if command is None:
        raise HTTPException(404, "فرمان مأموریت پیدا نشد")
    authz.check_scope(command, principal, own=False)
    return command


def cancel(id, payload):
    principal = authz.require("manage")
    expire_due()
    command = lookup(id, principal)
    if command["revision"] != payload.revision:
        raise HTTPException(409, {"code": "revision_conflict", "message": "فرمان هم‌زمان تغییر کرده است؛ دوباره بارگذاری کنید"})
    if command["status"] in TERMINAL:
        raise HTTPException(409, "فرمان پایان‌یافته قابل لغو نیست")
    for recipient in command["recipients"]:
        if recipient["status"] not in TERMINAL:
            _event(command, "لغو فرمان", asset_id=recipient["asset_id"], before=recipient["status"],
                   after="cancelled", detail=payload.reason)
            recipient.update(status="cancelled", finished_at=store.now())
    return _view(_save(command, "لغو فرمان مأموریت", payload.reason))


def _own(command, guard):
    recipient = next((r for r in command["recipients"] if r["asset_id"] == guard["id"]), None)
    if recipient is None:
        auth.fail("scope_denied", 403)
    return recipient


def _guard_view(command, guard):
    """A guard sees the order and only their own receipt, not the other recipients."""
    return {**_view(command), "recipients": [r for r in command["recipients"] if r["asset_id"] == guard["id"]],
            "timeline": [e for e in command["timeline"] if e["asset_id"] in (None, guard["id"])]}


def inbox(principal, device):
    """The device fetching its inbox is the delivery receipt for dispatched orders."""
    guard = authz.linked_guard(principal)
    if guard is None:
        auth.fail("guard_not_linked", 403)
    expire_due()
    rows = []
    for command in store.field.records(KIND):
        recipient = next((r for r in command["recipients"] if r["asset_id"] == guard["id"]), None)
        if recipient is None:
            continue
        if recipient["status"] == "dispatched":
            _event(command, "تحویل فرمان روی دستگاه", asset_id=guard["id"], before="dispatched", after="delivered",
                   detail=device["id"])
            recipient.update(status="delivered", delivered_at=store.now(), delivered_device_id=device["id"])
            _save(command, "تحویل فرمان مأموریت به دستگاه", f"{guard['id']} · {device['id']}")
        if recipient["status"] not in TERMINAL:
            rows.append(_guard_view(command, guard))
    return sorted(rows, key=lambda c: (c["priority"] != "urgent", c["created_at"]))


def act(id, payload, principal, device):
    guard = authz.linked_guard(principal)
    if guard is None:
        auth.fail("guard_not_linked", 403)
    expire_due()
    command = store.field.get(KIND, id)
    if command is None:
        raise HTTPException(404, "فرمان مأموریت پیدا نشد")
    recipient = _own(command, guard)
    if any(e.get("event_id") == payload.event_id for e in command["timeline"]):
        return _guard_view(command, guard)  # retry of an already recorded act
    allowed, target = TRANSITIONS[payload.action]
    before = recipient["status"]
    if before in TERMINAL:
        # Late receipt: history, not a state change.
        _event(command, f"{LABELS[payload.action]} پس از پایان", asset_id=guard["id"], before=before, after=before,
               event_id=payload.event_id, applied=False, detail=payload.note)
        _save(command, "ثبت رسید دیرهنگام فرمان مأموریت", f"{guard['id']} · {payload.action}")
        # Returned, not raised: an exception would roll back the field transaction and lose the record.
        return JSONResponse(status_code=409, content={"detail": {
            "code": "command_closed", "message": "این فرمان قبلاً پایان یافته است؛ اقدام شما فقط در سابقه ثبت شد"}})
    if before not in allowed:
        raise HTTPException(409, {"code": "invalid_transition",
                                  "message": f"اقدام «{LABELS[payload.action]}» از وضعیت فعلی مجاز نیست"})
    stamp = store.now()
    if before == "dispatched" and payload.action == "acknowledge":
        recipient.update(delivered_at=stamp, delivered_device_id=device["id"])
    field = {"acknowledged": "acknowledged_at", "in_progress": "started_at"}.get(target, "finished_at")
    recipient.update(status=target, **{field: stamp})
    if payload.note:
        recipient["note"] = payload.note.strip()
    if payload.lon is not None:
        recipient["evidence"] = [payload.lon, payload.lat]
    _event(command, LABELS[payload.action], asset_id=guard["id"], before=before, after=target,
           event_id=payload.event_id, detail=payload.note)
    if target == "completed" and command["type"] not in EACH_RECIPIENT:
        for other in command["recipients"]:
            if other is not recipient and other["status"] not in TERMINAL:
                _event(command, "بستن به‌دلیل انجام توسط نگهبان دیگر", asset_id=other["asset_id"],
                       before=other["status"], after="cancelled", detail=guard["id"], actor="سامانه")
                other.update(status="cancelled", finished_at=stamp)
    _save(command, LABELS[payload.action], f"{guard['id']} · {before}→{target}")
    return _guard_view(command, guard)
