"""Sensitive patrol stops require a human check-in; suggestions never dispatch."""

from datetime import timedelta

from fastapi import HTTPException

from ..core.tracks import parse_timestamp as _stamp
from ..core import engine, store
from ..core.models import SafetyEpisode
from ..routers.incidents import patrol_vehicle
from ..core.sim import distance_km
from . import findings, geo

RULE_ID = "intel.safety"



def _memory():
    return store.state["intel"].setdefault("safety", {"episodes": {}})["episodes"]


def _idle(asset_id, rearm_after=None):
    return dict(asset_id=asset_id, state="idle", started_at=None, deadline=None,
                facility_id=None, reason="", rearm_after=rearm_after)


def _sensitive(asset, now):
    point = [asset["lon"], asset["lat"]]
    facilities = store.state["facilities"]
    unmanned = next((f for f in facilities if f["unmanned"] and
                     distance_km(point, [f["lon"], f["lat"]]) * 1000 <= f["radius_m"]), None)
    if unmanned:
        return dict(facility_id=unmanned["id"], reason=f"توقف در {unmanned['name']} بدون سرنشین",
                    source_id=unmanned["id"])
    remote_km = store.state["settings"]["intel_safety_remote_km"]
    near_manned = any(not f["unmanned"] and distance_km(point, [f["lon"], f["lat"]]) <= remote_km for f in facilities)
    if not near_manned:
        pipeline = next((p for p in store.state["pipelines"]
                         if geo.bbox_contains(geo.expand_bbox(geo.bbox(p["points"]), remote_km * 1000), point)
                         and geo.point_polyline_distance_m(point, p["points"]) <= remote_km * 1000), None)
        if pipeline:
            return dict(facility_id=None, reason=f"توقف کنار {pipeline['name']} دور از تأسیسات دارای سرنشین",
                        source_id=pipeline["id"])
    clock = _stamp(now).astimezone(engine.TEHRAN).strftime("%H:%M")
    if not engine.in_schedule(store.state["settings"]["intel_safety_normal_hours"], clock):
        return dict(facility_id=None, reason="توقف خارج از ساعت عادی گشت", source_id=None)
    return None


def _connection_context(asset, now):
    """Use the engine's zone timeout plus applicable connection-policy thresholds."""
    settings = store.state["settings"]
    clock = _stamp(now).astimezone(engine.TEHRAN).strftime("%H:%M")
    choices = []
    for zone in store.state["zones"]:
        if not engine.point_in_polygon(asset["lon"], asset["lat"], zone["points"]):
            continue
        thresholds = [p["threshold"] for p in store.state["policies"]
                      if p["condition"] == "connection_lost" and p["zone"] == zone["id"]
                      and p["status"] in ("shadow", "active") and engine.subject_matches(p, asset)
                      and engine.in_schedule(p["schedule"], clock)]
        threshold = max(thresholds, default=0)
        choices.append((engine.connection_timeout_minutes(settings, zone, threshold), zone, threshold))
    if not choices:
        return {}, 0
    _, zone, threshold = max(choices, key=lambda choice: choice[0])
    return zone, threshold


def _resolve(episode, now):
    if episode.get("finding_id"):
        findings.resolve_finding(episode["finding_id"], now_iso=now)


def _escalate(episode, asset, now, severity, cause, zone, threshold):
    settings = store.state["settings"]
    points = store.observations_since(asset, episode["started_at"])
    points = [p for p in points if _stamp(p["time"]) <= _stamp(now)]
    finding = findings.raise_finding(
        rule_id=RULE_ID, kind="patrol_safety", subject_ids=[asset["id"]], severity=severity,
        summary=f"بررسی فوری سلامت {asset['name']} · {cause}",
        mode=settings["intel_safety_mode"], needs_incident=True, zone_id=zone.get("id"), now_iso=now,
        evidence=dict(rule="توقف حساس و مهلت تأیید سلامت یا قطع ارتباط", thresholds=dict(
            stop_minutes=settings["intel_safety_stop_minutes"], checkin_minutes=settings["intel_safety_checkin_minutes"],
            radius_m=engine.STOP_RADIUS_M, silence_minutes=engine.connection_timeout_minutes(settings, zone, threshold),
            remote_km=settings["intel_safety_remote_km"], normal_hours=settings["intel_safety_normal_hours"],
        ), window_from=episode["started_at"], window_to=now,
            points=[[p["lon"], p["lat"], p["time"]] for p in points], values=dict(
                reason=episode["reason"], cause=cause, deadline=episode["deadline"], last_seen=asset["last_seen"],
                facility_id=episode["facility_id"], geometry=dict(type="Point", coordinates=episode["anchor"]),
                zone_id=zone.get("id"),
            )), sources=[asset["id"], *([episode["source_id"]] if episode.get("source_id") else [])],
    )
    episode.update(state="escalated", finding_id=finding["id"])
    if finding["incident_id"]:
        store.attach_emergency_context(store.lookup("incidents", finding["incident_id"]), "patrol_safety")


@store.state_locked
def tick(now):
    episodes = _memory()
    for asset in store.state["assets"]:
        if not patrol_vehicle(asset):
            continue
        episode = episodes.setdefault(asset["id"], _idle(asset["id"]))
        since = episode["started_at"] or ( _stamp(now) - timedelta(hours=24)).isoformat()
        points = [p for p in store.observations_since(asset, since) if _stamp(p["time"]) <= _stamp(now)]
        # Look at every new observation, so a drive out and back between worker
        # ticks ends the old episode rather than inheriting its timer.
        if episode["state"] != "idle":
            new_points = [p for p in points if _stamp(p["time"]) > _stamp(episode["last_observation"])]
            if any(not engine.within_stop_radius(episode["anchor"], [p["lon"], p["lat"]]) for p in new_points):
                _resolve(episode, now)
                episodes[asset["id"]] = _idle(asset["id"], asset["last_seen"])
                store.audit("پایان توقف ایمنی با حرکت گشت", asset["id"])
                continue
            if new_points:
                episode["last_observation"] = new_points[-1]["time"]
        if episode["state"] in ("confirmed", "escalated"):
            continue
        if episode["state"] == "check_pending":
            zone, threshold = _connection_context(asset, now)
            if engine.connection_lost(asset, now, store.state["settings"], zone, threshold):
                _escalate(episode, asset, now, "critical", "قطع ارتباط هنگام انتظار تأیید سلامت", zone, threshold)
            elif _stamp(now) >= _stamp(episode["deadline"]):
                _escalate(episode, asset, now, "high", "پایان مهلت تأیید سلامت", zone, threshold)
            continue
        if episode.get("rearm_after"):
            points = [p for p in points if _stamp(p["time"]) >= _stamp(episode["rearm_after"])]
        stopped = engine.continuous_stop({**asset, "track": points}, now)
        if not stopped:
            if episode["state"] == "stopped":
                episodes[asset["id"]] = _idle(asset["id"])
            continue
        sensitive = _sensitive(asset, now)
        if not sensitive:
            if episode["state"] == "stopped":
                episodes[asset["id"]] = _idle(asset["id"])
            continue
        if episode["state"] == "idle":
            episode.update(state="stopped", started_at=stopped["started_at"],
                           anchor=[asset["lon"], asset["lat"]], last_observation=stopped["end_at"], **sensitive)
        else:
            episode["started_at"] = stopped["started_at"]
        if stopped["minutes"] >= store.state["settings"]["intel_safety_stop_minutes"]:
            episode.update(state="check_pending", deadline=( _stamp(now) + timedelta(
                minutes=store.state["settings"]["intel_safety_checkin_minutes"])).isoformat())
            store.audit("آغاز مهلت تأیید سلامت گشت", asset["id"], episode["reason"])


@store.state_locked
def snapshot():
    episodes = _memory()
    return dict(episodes=[SafetyEpisode.model_validate(episodes.get(asset["id"], _idle(asset["id"]))).model_dump()
                          for asset in store.state["assets"] if patrol_vehicle(asset)])


@store.state_locked
def confirm(asset_id, note=None, now=None):
    store.lookup("assets", asset_id)
    now = now or store.now()
    # A late confirmation must not erase an overdue timeout or a tracker loss.
    tick(now)
    episode = _memory().get(asset_id)
    if not episode or episode["state"] != "check_pending":
        raise HTTPException(409, "این گشت مهلت تأیید سلامت باز ندارد")
    episode.update(state="confirmed", confirmed_at=now, note=(note or "").strip())
    store.audit("تأیید سلامت گشت", asset_id, episode["note"])
    return SafetyEpisode.model_validate(episode).model_dump()
