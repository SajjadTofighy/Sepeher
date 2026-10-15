import time
import os
import threading
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from inspect import iscoroutinefunction
from pathlib import Path
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.routing import APIRoute

from . import engine, sim
from .seed import seed
from .tracks import TrackStore, parse_timestamp
from .fieldstore import FieldStore

state = seed()
field = FieldStore(os.environ.get("SEPEHR_FIELD_DB", str(Path(__file__).resolve().parents[1] / "data" / "field.sqlite3")))
tracks = TrackStore(os.environ.get("SEPEHR_TRACK_DB", str(Path(__file__).resolve().parents[1] / "data" / "tracks.sqlite3")))
tracks.seed_missing(state["assets"])

state_lock = threading.Lock()
_lock_context = threading.local()


@contextmanager
def locked_state():
    """One lock, with nested calls in the same synchronous thread sharing ownership."""
    if getattr(_lock_context, "held", False):
        yield
        return
    with state_lock:
        _lock_context.held = True
        try:
            yield
        finally:
            _lock_context.held = False


def state_locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with locked_state():
            return function(*args, **kwargs)
    return wrapped


class StateRoute(APIRoute):
    """Serialize sync API state access and snapshot results before releasing the lock."""
    def __init__(self, path, endpoint, **kwargs):
        if not iscoroutinefunction(endpoint):
            original = endpoint

            @wraps(original)
            def endpoint(*args, **kw):
                with locked_state():
                    result = original(*args, **kw)
                    return deepcopy(result) if isinstance(result, (dict, list)) else result

        super().__init__(path, endpoint, **kwargs)


def plan_for(asset, at=None):
    """Lazily created synthetic motion plan, anchored on the last stored position."""
    plans = state.setdefault("sim", {})
    if asset["id"] not in plans:
        plans[asset["id"]] = sim.new_plan(asset, [asset["lon"], asset["lat"]], now=at)
    return plans[asset["id"]]


@state_locked
def refresh_track(asset, at=None):
    latest = None if asset.get("synthetic") else tracks.latest(asset["id"])
    source = _observation_source(asset, latest)
    if source == "reported":
        asset["track"] = tracks.read(asset["id"])
        asset.update(lon=latest["lon"], lat=latest["lat"], last_seen=latest["time"])
        if latest["speed"] is not None:
            asset["speed"] = latest["speed"]
        return
    if latest:
        asset.update(lon=latest["lon"], lat=latest["lat"])
    if source == "offline":
        asset["track"] = tracks.read(asset["id"])
        return
    # Demo-sourced assets move along a deterministic patrol beat until real GPS arrives.
    sim.apply(asset, plan_for(asset, at=at), now=at)


@state_locked
def observations_since(asset, since_iso):
    """Return only the observation stream selected by refresh_track's precedence.

    The reported stream is bounded to the same latest 500 points the engine sees;
    demo SQLite seed history must not leak into an online simulated beat.
    """
    latest = None if asset.get("synthetic") else tracks.latest(asset["id"])
    points = tracks.read(asset["id"]) if _observation_source(asset, latest) != "simulated" else asset.get("track", [])
    since = parse_timestamp(since_iso)
    return [dict(p) for p in points if parse_timestamp(p["time"]) >= since]


def _observation_source(asset, latest):
    if latest and latest["source"] == "reported":
        return "reported"
    return "offline" if asset["status"] == "offline" else "simulated"


def observation_source(asset):
    """Identify precedence changes so incremental consumers can reset their cursors."""
    latest = None if asset.get("synthetic") else tracks.latest(asset["id"])
    return _observation_source(asset, latest)


@state_locked
def refresh_tracks(now_iso=None, evaluate=True):
    at = parse_timestamp(now_iso).timestamp() if now_iso else None
    for asset in state["assets"]:
        refresh_track(asset, at=at)
    stamp = now_iso or now()
    from .intel.shift_report import observe_trackers
    observe_trackers(stamp)
    if evaluate:
        evaluate_policies(stamp)
    for incident in state["incidents"]:
        plan = state.get("sim", {}).get(incident.get("assigned_to") or "")
        if (
            incident["status"] in ("assigned", "en_route")
            and plan
            and sim.arrived(plan, now=at)
            and not incident.get("arrived_at")
        ):
            incident["arrived_at"] = stamp
            incident["timeline"].append(
                dict(time=stamp, action="گشت به محل رسید (موقعیت ردیاب)", actor="سرویس موقعیت")
            )


@state_locked
def evaluate_policies(stamp, coverage_ready=False):
    # Process arriving GPS before testing checkpoint deadlines in the same tick.
    if not coverage_ready and any(cp.get("target_id") for m in state["missions"] for cp in m["checkpoints"]):
        from .intel import coverage
        coverage.tick(stamp)
    for asset in state["assets"]:
        engine.evaluate(state, asset, stamp, create_incident, audit)


def update_mission_progress(mission):
    total = len(mission["checkpoints"])
    visited = sum(c["visited"] for c in mission["checkpoints"])
    mission["progress"] = round(visited / total * 100) if total else 0
    if total and visited == total:
        mission["status"] = "completed"


def next_incident_id():
    return f"INC-{824 + len(state['incidents'])}"


@state_locked
def create_incident(title, severity, zone, asset, description, first_action, zone_id=None, policy_id=None, actor="موتور سیاست"):
    item = dict(
        id=next_incident_id(),
        title=title,
        severity=severity,
        status="detected",
        zone=zone,
        zone_id=zone_id,
        asset_id=asset["id"],
        lon=asset["lon"],
        lat=asset["lat"],
        created_at=now(),
        assigned_to=None,
        policy_id=policy_id,
        description=description,
        timeline=[dict(time=now(), action=first_action, actor=actor)],
    )
    state["incidents"].insert(0, item)
    from .intel.bayes import persist_incident
    persist_incident(item)
    policy = next((p for p in state["policies"] if p["id"] == policy_id), None)
    if policy and policy["condition"] == "sos":
        attach_emergency_context(item, "sos")
    audit("ثبت دستی حادثه فرایندی" if actor == "اپراتور" else "تشکیل خودکار پرونده حادثه" if actor == "موتور سیاست" else "ثبت اعلام خطر نگهبان", item["id"], policy_id or "", actor=actor)
    return item


@state_locked
def attach_emergency_context(incident, kind):
    from .routers.incidents import nearby_patrols

    incident.update(kind=kind, emergency_contacts=deepcopy(state["settings"]["intel_emergency_contacts"]),
                    backup_patrols=nearby_patrols(incident))
    return incident


def now():
    return datetime.now(timezone.utc).isoformat()


def lookup(collection, id):
    found = next((x for x in state[collection] if x["id"] == id), None)
    if not found:
        raise HTTPException(404, "رکورد پیدا نشد")
    return found


@state_locked
def audit(action, target, detail="", actor="اپراتور نمایشی"):
    from .security.auth import current_principal
    principal = current_principal.get()
    item = field.append_audit(dict(
        time=now(),
        actor=principal.username if principal else actor,
        sub=principal.sub if principal else None,
        username=principal.username if principal else None,
        action=action,
        target=target,
        detail=detail,
    ))
    station_settings = field.get("settings", "station_sensitivity")
    if station_settings:
        state["settings"]["station_sensitivity_labels"] = station_settings["station_sensitivity_labels"]
    state["audit"] = field.audits()
    return item


@state_locked
def restore_field_state():
    """SQLite is authoritative; reset and restart never discard field operations."""
    links = field.links()
    for asset in state["assets"]:
        if asset["kind"] == "person":
            existing = field.get("guards", asset["id"])
            if existing is None:
                existing = dict(id=asset["id"], name=asset["name"], keycloak_sub=None,
                                zone_id=asset.get("zone_id"), contractor_id=asset.get("contractor_id"))
                field.save("guards", existing)
            existing["keycloak_sub"] = links.get(asset["id"])
            asset.update({key: existing.get(key) for key in ("keycloak_sub", "zone_id", "contractor_id")})
            field.save("guards", existing)
    for kind in ("guards", "tour", "routes", "tags", "messages", "media", "checkins", "approvals", "stations", "station_tasks", "station_visits", "station_results", "field_zones", "seal_changes", "shift_patterns", "tour_schedules", "scheduled_tours", "shift_handovers", "emergency_modes", "field_safety_events", "musters", "scan_reviews", "field_reports", "media_uploads", "device_reports"):
        state["field_" + kind] = field.records(kind)
    setting = field.get("settings", "classification")
    if setting:
        state["settings"]["classification_label"] = setting["classification_label"]
    station_settings = field.get("settings", "station_sensitivity")
    if station_settings:
        state["settings"]["station_sensitivity_labels"] = station_settings["station_sensitivity_labels"]
    tour_settings = field.get('settings', 'tour_phase_two')
    if tour_settings:
        state['settings'].update({k: v for k, v in tour_settings.items() if k != 'id'})
    state["audit"] = field.audits()


@state_locked
def refresh_commands():
    for c in state["commands"]:
        if c["status"] in ["executed", "timed_out"]:
            continue
        elapsed = time.time() - c["epoch"]
        a = lookup("assets", c["asset_id"])
        dest = (
            "timed_out"
            if a["status"] == "offline" and elapsed >= c["timeout_seconds"]
            else "executed"
            if a["status"] != "offline" and elapsed >= 6
            else "delivered"
            if a["status"] != "offline" and elapsed >= 2
            else "sent"
        )
        if dest != c["status"]:
            c["status"] = dest
            c["updated_at"] = now()
            if dest == "executed" and c["command"] == "interval":
                a["report_interval"] = c["interval_seconds"]
            audit("تغییر وضعیت فرمان", c["id"], dest)


CYCLE_STEPS = ("تأیید حادثه", "ارجاع به گشت", "حضور در محل", "خاتمه حادثه")
BASELINE_CYCLE = [1.2, 2.8, 4.2, 18.5]


def cycle_times(window_from=None, window_to=None, *, include_sources=False):
    """Average minutes from alert registration to each lifecycle step, from real timelines."""
    totals = [[] for _ in CYCLE_STEPS]
    sources = [[] for _ in CYCLE_STEPS]
    for incident in state["incidents"]:
        start = parse_timestamp(incident["created_at"])
        for k, label in enumerate(CYCLE_STEPS):
            hit = next((e for e in incident["timeline"] if e["action"].startswith(label)), None)
            if hit and ((window_from is not None and parse_timestamp(hit["time"]) < parse_timestamp(window_from))
                        or (window_to is not None and parse_timestamp(hit["time"]) >= parse_timestamp(window_to))):
                continue
            if hit:
                totals[k].append((parse_timestamp(hit["time"]) - start).total_seconds() / 60)
                sources[k].append(incident["id"])
    measured = [bool(t) for t in totals]
    values = [round(sum(t) / len(t), 1) if t else (BASELINE_CYCLE[k] if window_from is None and window_to is None else None)
              for k, t in enumerate(totals)]
    result = values, measured, [len(t) for t in totals]
    return (*result, sources) if include_sources else result


@state_locked
def begin_data_epoch(stamp=None):
    """Operational history starts here; durable GPS does not imply other history."""
    state["data_since"] = stamp or now()
    entry = audit("آغاز دوره داده‌های عملیاتی", "DATA-EPOCH", state["data_since"], actor="سامانه")
    state["data_source_id"] = entry["id"]
    from .intel.shift_report import observe_trackers
    observe_trackers(state["data_since"])


def summary():
    from .intel.coverage import snapshot

    coverage = snapshot(now())["totals"]
    active = [x for x in state["incidents"] if x["status"] != "closed"]
    cycle, measured, samples = cycle_times()
    zones = {}
    for x in active:
        zones[x["zone"]] = zones.get(x["zone"], 0) + 1
    hot = max(zones.items(), key=lambda kv: kv[1])[0] if zones else ""
    alerts = state.get("alerts", [])
    return dict(
        online=sum(x["status"] != "offline" for x in state["assets"]),
        total=len(state["assets"]),
        offline=sum(x["status"] == "offline" for x in state["assets"]),
        warning=sum(x["status"] == "warning" for x in state["assets"]),
        maintenance=sum(
            x["status"] == "offline" or x.get("data_package", "active") != "active"
            for x in state["assets"]
        ),
        critical=sum(x["severity"] == "critical" for x in active),
        open_incidents=len(active),
        closed_incidents=len(state["incidents"]) - len(active),
        missions=sum(x["status"] == "active" for x in state["missions"]),
        policy_alerts=len(alerts),
        shadow_alerts=sum(a["mode"] == "shadow" for a in alerts),
        active_policies=sum(p["status"] == "active" for p in state["policies"]),
        hot_zone=hot,
        coverage=coverage["percent_ok"],
        response_minutes=cycle[2],
        availability=99.4,
        trend=[12, 9, 14, 8, 11, 7, len(active)],
        cycle=cycle,
        cycle_measured=measured,
        cycle_samples=samples,
        fields=[
            dict(name=n, events=v, coverage=coverage["by_field"].get(n, 0))
            for n, v in [("آغاجاری", 12), ("کرنج", 8), ("پارسی", 5)]
        ],
        mock=True,
    )
