"""Position-based policies with shared shadow, silence and deduplication controls.

SOS, reported plate reads and timed mission checkpoints share the policy engine.
"""

import re
from datetime import datetime, timedelta, timezone

from .tracks import parse_timestamp
from .models import Asset
from .sim import distance_km

TEHRAN = timezone(timedelta(hours=3, minutes=30))
STOP_RADIUS_M = 30
STOP_MAX_SPEED_KMH = 1
ANPR_MIN_SENSITIVE_CAMERAS = 2
ANPR_CONDITIONS = {"unknown_vehicle", "camera_event"}
SUPPORTED_CONDITIONS = {"geofence_entry", "after_hours", "long_stop", "connection_lost", "gps_jump", "sos", "missed_checkpoint"} | ANPR_CONDITIONS
TITLES = {
    "geofence_entry": "ورود به محدوده غیرمجاز",
    "after_hours": "تردد خارج از ساعت مجاز",
    "long_stop": "توقف غیرعادی",
    "connection_lost": "قطع ارتباط دستگاه",
    "gps_jump": "جهش غیرممکن GPS",
    "sos": "فعال‌شدن دکمه اضطراری",
    "missed_checkpoint": "نرسیدن به ایستگاه گشت در مهلت",
    "unknown_vehicle": "خودروی سنگین خارج از فهرست مجاز در شب",
    "camera_event": "تکرار پلاک در دوربین‌های حساس",
}


def valid_schedule(value):
    return value == "تمام شبانه‌روز" or bool(re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9][–-](?:[01][0-9]|2[0-3]):[0-5][0-9]", value
    ))


def point_in_polygon(lon, lat, points):
    inside = False
    j = len(points) - 1
    for i in range(len(points)):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_schedule(schedule, hhmm):
    """Tehran wall-clock windows; invalid schedules fail closed."""
    if schedule == "تمام شبانه‌روز":
        return True
    if not valid_schedule(schedule):
        return False
    parts = schedule.replace("-", "–").split("–")
    try:
        start, end = (int(p.strip()[:2]) * 60 + int(p.strip()[3:5]) for p in parts)
    except (ValueError, IndexError):
        return False
    minute = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    return start <= minute < end if start < end else minute >= start or minute < end


def local_clock(asset):
    return asset.get("scenario_clock") or datetime.now(TEHRAN).strftime("%H:%M")


def subject_matches(policy, asset):
    return policy["subject"] == "all" or policy["subject"] == asset["kind"]


def routing_decision(settings, mode, action):
    """Shared routing precedence for policies and findings; never dispatches."""
    shadow = mode == "shadow" or settings.get("shadow_mode", False)
    routed = not shadow and action != "log_only" and not settings.get("maintenance_silence")
    reason = "" if routed else "حالت سایه" if shadow else "فقط ثبت در سوابق" if action == "log_only" else "سکوت مانور/تعمیرات"
    return dict(mode="shadow" if shadow else "active", routed=routed, reason=reason)


def observation_gap_seconds(asset):
    """Maximum continuous-observation gap, shared by stop and coverage rules."""
    return max(asset.get("report_interval", Asset.model_fields["report_interval"].default) * 3, 120)


def within_stop_radius(anchor, point):
    return distance_km(anchor, point) * 1000 <= STOP_RADIUS_M


def continuous_stop(asset, now_iso):
    """Recent continuous observations within 30 m, at current speed at most 1 km/h."""
    points = asset.get("track", [])
    if asset["speed"] > STOP_MAX_SPEED_KMH or not points:
        return None
    last = points[-1]
    end = parse_timestamp(last["time"])
    gap = observation_gap_seconds(asset)
    if (parse_timestamp(now_iso) - end).total_seconds() > gap:
        return None
    first, previous = end, end
    observations = [last]
    for point in reversed(points[:-1]):
        stamp = parse_timestamp(point["time"])
        if (previous - stamp).total_seconds() > gap or not within_stop_radius([last["lon"], last["lat"]], [point["lon"], point["lat"]]):
            break
        first, previous = stamp, stamp
        observations.append(point)
    return dict(started_at=first.isoformat(), end_at=end.isoformat(),
                minutes=(end - first).total_seconds() / 60, points=list(reversed(observations)))


def connection_timeout_minutes(settings, zone, threshold=0):
    coverage = zone.get("coverage", "normal")
    return max(threshold, settings[f"{coverage}_coverage_timeout"])


def connection_lost(asset, now_iso, settings, zone, threshold=0):
    seconds = (parse_timestamp(now_iso) - parse_timestamp(asset["last_seen"])).total_seconds()
    return seconds >= connection_timeout_minutes(settings, zone, threshold) * 60


def checkpoint_window_minutes(state, mission):
    saved = mission.get("plan_window_minutes")
    return saved if saved is not None else state["settings"]["intel_plan_window_minutes"]


def missed_checkpoints(state, asset, zone, now_iso):
    """Timed target checkpoints in the policy zone, regardless of tracker location."""
    if any(item['zone_id'] == zone['id'] and item['active'] for item in state.get('field_emergency_modes', [])):
        return []
    stamp = parse_timestamp(now_iso)
    rows = []
    for mission in state.get("missions", []):
        if mission["asset_id"] != asset["id"] or mission["status"] == "completed":
            continue
        window = timedelta(minutes=checkpoint_window_minutes(state, mission))
        for index, cp in enumerate(mission["checkpoints"]):
            if (cp["visited"] or cp.get('excused_reason') or not cp.get("target_id") or not cp.get("due_at")
                    or cp.get("lon") is None or cp.get("lat") is None):
                continue
            if (point_in_polygon(cp["lon"], cp["lat"], zone["points"])
                    and stamp > parse_timestamp(cp["due_at"]) + window):
                rows.append((mission, index, cp))
    return rows


def plate_subject(state, event):
    """A registered camera location, not a fabricated tracker or fleet asset."""
    camera = next(c for c in state["cameras"] if c["id"] == event["camera_id"])
    return dict(id=camera["id"], name=f"پلاک {event['plate']} · {camera['name']}", kind="vehicle",
                lon=event["lon"], lat=event["lat"], field=camera["zone"])


def plate_reads_in_window(state, event):
    end = parse_timestamp(event["time"])
    start = end - timedelta(minutes=state["settings"]["intel_anpr_repeat_window_minutes"])
    return sorted([read for read in [*state.get("plate_reads", []), event]
                   if read.get("source") == "reported" and read["plate"] == event["plate"] and read["sensitive"]
                   and start <= parse_timestamp(read["time"]) <= end], key=lambda read: read["time"])


def _plate_finding(state, policy, event, zone, now_iso, record_finding):
    reads = plate_reads_in_window(state, event) if policy["condition"] == "camera_event" else [event]
    return record_finding(rule_id=f"engine.{policy['id']}.v{policy['version']}", kind=policy["condition"],
        subject_ids=[event["camera_id"], f"plate:{event['plate']}", event["id"]],
        summary=f"{TITLES[policy['condition']]} · پلاک {event['plate']}",
        severity=policy["severity"], mode=policy["status"], action=policy["action"], needs_incident=True,
        zone_id=zone["id"], policy_id=policy["id"], now_iso=now_iso,
        evidence=dict(rule=TITLES[policy["condition"]], thresholds=dict(
            night_hours=state["settings"]["intel_anpr_night_hours"],
            repeat_window_minutes=state["settings"]["intel_anpr_repeat_window_minutes"], minimum_sensitive_cameras=ANPR_MIN_SENSITIVE_CAMERAS,
            policy_schedule=policy["schedule"]), window_from=reads[0]["time"], window_to=event["time"],
            points=[[r["lon"], r["lat"], r["time"]] for r in reads], values=dict(
                plate=event["plate"], vehicle_class=event["vehicle_class"], source="reported",
                camera_ids=sorted({r["camera_id"] for r in reads}), event_ids=list(dict.fromkeys(r["id"] for r in reads)),
                allowlisted=False, received_at=event["received_at"])),
        sources=list(dict.fromkeys([policy["id"], *[r["id"] for r in reads], *[r["camera_id"] for r in reads]])))


def evaluate(state, asset, now_iso, create_incident, audit, event=None, record_finding=None):
    """Entry fires on zone transitions; persistent conditions fire once until cleared."""
    inside_now = {z["id"] for z in state["zones"] if point_in_polygon(asset["lon"], asset["lat"], z["points"])}
    memory = state.setdefault("engine", {}).setdefault("inside", {})
    entered = inside_now - set(memory.get(asset["id"], [])) if event is None else set()
    if event is None:
        memory[asset["id"]] = sorted(inside_now)
    fired = []
    clock = parse_timestamp(event["time"]).astimezone(TEHRAN).strftime("%H:%M") if event else local_clock(asset)
    settings = state["settings"]
    plate_event = bool(event and event["type"] == "plate_read")
    if plate_event and (not settings.get("intel_anpr_enabled", False) or event.get("source") != "reported"):
        return []
    for policy in state["policies"]:
        conditions = ANPR_CONDITIONS if plate_event else {"sos"}
        if (event is not None and policy["condition"] not in conditions) or (event is None and policy["condition"] in ANPR_CONDITIONS):
            continue
        subject_key = f"plate:{event['plate']}" if plate_event else asset["id"]
        key = f"{policy['id']}:{policy['version']}:{subject_key}"
        latches = state["engine"].setdefault("matched", {})
        if (
            policy["condition"] not in SUPPORTED_CONDITIONS
            or policy["status"] not in ("shadow", "active")
            or not subject_matches(policy, asset)
            or not in_schedule(policy["schedule"], parse_timestamp(now_iso).astimezone(TEHRAN).strftime("%H:%M") if policy["condition"] == "missed_checkpoint" else clock)
        ):
            latches[key] = False
            continue
        zone = next(z for z in state["zones"] if z["id"] == policy["zone"])
        # SOS is an explicit emergency, even outside a protected zone. Use the
        # actual containing zone (or field) for the incident's location label.
        if policy["condition"] == "sos":
            zone = next((z for z in state["zones"] if z["id"] in inside_now), dict(id=None, name=asset["field"]))
        contexts = [(key, None)]
        if policy["condition"] == "missed_checkpoint":
            contexts = [(f"{key}:{mission['id']}:{index}", (mission, index, cp))
                        for mission, index, cp in missed_checkpoints(state, asset, zone, now_iso)]
        for context_key, checkpoint in contexts:
            matched = checkpoint is not None or condition_matches(state, policy, asset, zone, inside_now, entered, now_iso, event=event)
            previous = latches.get(context_key, False)
            if plate_event:
                last_matches = state["engine"].setdefault("anpr_last_match", {})
                last = last_matches.get(context_key)
                stamp = parse_timestamp(event["time"])
                if last and stamp - parse_timestamp(last) > timedelta(minutes=settings["intel_anpr_repeat_window_minutes"]):
                    previous = False
                if matched:
                    last_matches[context_key] = event["time"]
            latches[context_key] = matched
            if not matched or (policy["condition"] not in ("geofence_entry", "sos") and previous):
                continue
            routing = routing_decision(settings, policy["status"], policy["action"])
            if plate_event and record_finding is None:
                # Historical replay counts real input only and never writes findings/incidents.
                routing = routing_decision(settings, "shadow", policy["action"])
            alert = dict(
                id=f"ALR-{len(state['alerts']) + 1:04}",
                time=now_iso,
                policy_id=policy["id"],
                policy=policy["name"],
                asset_id=asset["id"],
                zone=zone["name"],
                severity=policy["severity"],
                **routing,
                clock=parse_timestamp(now_iso).astimezone(TEHRAN).strftime("%H:%M") if checkpoint else clock,
                incident_id=None,
            )
            if checkpoint:
                mission, index, cp = checkpoint
                alert.update(mission_id=mission["id"], target_id=cp["target_id"], checkpoint_index=index, due_at=cp["due_at"])
            policy["matches"] += 1
            if plate_event:
                alert.update(event_id=event["id"], camera_id=event["camera_id"], plate=event["plate"], finding_id=None)
                if record_finding is not None:
                    finding = _plate_finding(state, policy, event, zone, now_iso, record_finding)
                    alert.update(finding_id=finding["id"], incident_id=finding["incident_id"])
            elif routing["routed"]:
                subject = {**asset, "lon": checkpoint[2]["lon"], "lat": checkpoint[2]["lat"]} if checkpoint else asset
                alert["incident_id"] = _route(state, policy, subject, zone, alert, now_iso, create_incident)
            state["alerts"].insert(0, alert)
            audit("هشدار موتور سیاست", alert["id"], f"{policy['id']} · {alert['mode']}")
            fired.append(alert)
    return fired


def condition_matches(state, policy, asset, zone, inside, entered, now_iso, event=None):
    condition = policy["condition"]
    if condition == "sos":
        return bool(event and event["type"] == "sos" and event["asset_id"] == asset["id"] and "sos" in asset["capabilities"])
    if condition in ANPR_CONDITIONS:
        if (not event or event["type"] != "plate_read" or event.get("source") != "reported"
                or not state["settings"].get("intel_anpr_enabled", False) or zone["id"] not in inside
                or event["plate"] in state["settings"]["intel_vehicle_allowlist"]):
            return False
        if condition == "unknown_vehicle":
            clock = parse_timestamp(event["time"]).astimezone(TEHRAN).strftime("%H:%M")
            return event["vehicle_class"] == "heavy" and in_schedule(state["settings"]["intel_anpr_night_hours"], clock)
        return event["sensitive"] and len({r["camera_id"] for r in plate_reads_in_window(state, event)}) >= ANPR_MIN_SENSITIVE_CAMERAS
    if condition == "missed_checkpoint":
        return bool(missed_checkpoints(state, asset, zone, now_iso))
    if zone["id"] not in inside:
        return False
    if condition == "geofence_entry":
        return zone["id"] in entered and not asset.get("authorized", True)
    if condition == "after_hours":
        # The policy schedule defines the prohibited window, as for entry rules.
        return not asset.get("authorized", True) and asset["speed"] > 0
    if condition == "connection_lost":
        return connection_lost(asset, now_iso, state["settings"], zone, policy["threshold"])
    points = asset.get("track", [])
    if len(points) < 2:
        return False
    if condition == "gps_jump":
        a, b = points[-2:]
        seconds = (parse_timestamp(b["time"]) - parse_timestamp(a["time"])).total_seconds()
        return seconds > 0 and distance_km([a["lon"], a["lat"]], [b["lon"], b["lat"]]) / seconds * 3600 > policy["threshold"]
    if condition == "long_stop":
        stopped = continuous_stop(asset, now_iso)
        return stopped is not None and stopped["minutes"] >= policy["threshold"]
    return False


def route_incident(state, asset, now_iso, create_incident, *, dedupe_key,
                   duplicate_action, actor, **details):
    """Single incident creation/deduplication owner after routing_decision permits it.

    Policies and findings provide their existing identity and evidence context;
    manual operator creation is intentionally outside automatic routing.
    """
    window = timedelta(seconds=state["settings"]["dedupe_seconds"])
    stamp = parse_timestamp(now_iso)
    for incident in state["incidents"]:
        if (
            all(incident.get(key) == value for key, value in dedupe_key.items())
            and incident["status"] != "closed"
            and stamp - parse_timestamp(incident["created_at"]) <= window
        ):
            incident["timeline"].append(
                dict(time=now_iso, action=duplicate_action, actor=actor)
            )
            return incident
    incident = create_incident(asset=asset, actor=actor, **details)
    incident.update(dedupe_key)
    return incident


def _route(state, policy, asset, zone, alert, now_iso, create_incident):
    action = {
        "create_incident": "ایجاد پرونده",
        "notify": "اعلان به اتاق کنترل",
        "suggest_patrol": "پیشنهاد نزدیک‌ترین گشت",
    }.get(policy["action"], policy["action"])
    return route_incident(
        state, asset, now_iso, create_incident,
        dedupe_key=dict(policy_id=policy["id"], asset_id=asset["id"]),
        duplicate_action="هشدار تکراری در همین پرونده ادغام شد", actor="موتور سیاست",
        title=TITLES[policy["condition"]],
        severity=policy["severity"],
        zone=zone["name"],
        zone_id=zone["id"],
        policy_id=policy["id"],
        description=(
            f"{asset['name']} · {TITLES[policy['condition']]} · ساعت {alert['clock']} · {zone['name']}. "
            f"منطبق با سیاست {policy['id']} «{policy['name']}» (نسخه {policy['version']}، بازه {policy['schedule']})."
            + (f" مأموریت {alert['mission_id']} · هدف {alert['target_id']} · مهلت {alert['due_at']}." if alert.get("mission_id") else "")
        ),
        first_action=f"کشف خودکار توسط موتور سیاست · اقدام: {action}",
    )["id"]
