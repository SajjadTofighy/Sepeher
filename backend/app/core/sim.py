"""Synthetic live motion for demo-sourced assets. A reported GPS position always wins.

Every asset follows a deterministic, piecewise motion plan so the same instant always
yields the same coordinates (polling, replay and tests stay consistent):

  patrol loop around a base point  ->  optional straight-line dispatch  ->  parked at target
"""

import math
import time
from datetime import datetime, timezone

TRAIL_SECONDS = 1800
TRAIL_STEP = 30
EARTH_RADIUS_M = 6_371_000


def _loop_offset(theta, radius, aspect, phase, lat):
    """Organic closed patrol beat (not a perfect circle), in degrees."""
    r = radius * (1 + 0.22 * math.sin(2 * theta + phase) + 0.12 * math.cos(3 * theta - phase))
    return (r * math.cos(theta) / math.cos(math.radians(lat)), r * aspect * math.sin(theta))


def new_plan(asset, base, now=None):
    """Plan whose loop passes through `base`; the trail starts half an hour in the past."""
    now = time.time() if now is None else now
    seed = sum(map(ord, asset["id"]))
    person = asset["kind"] == "person"
    plan = dict(
        radius=0.003 if person else 0.012 + (seed % 5) * 0.002,
        period=1800 if person else 900 + (seed % 4) * 150,
        aspect=0.6 + (seed % 3) * 0.2,
        phase=(seed % 7) * 0.9,
        direction=1 if seed % 2 else -1,
        t0=now - TRAIL_SECONDS,
        routes=[],
    )
    dx, dy = _loop_offset(0, plan["radius"], plan["aspect"], plan["phase"], base[1])
    plan["center"] = [base[0] - dx, base[1] - dy]
    return plan


def position(plan, t):
    route = next((r for r in reversed(plan["routes"]) if t >= r["start"]), None)
    if route:
        p = min(1.0, (t - route["start"]) / route["duration"])
        return [route["from"][i] + (route["to"][i] - route["from"][i]) * p for i in (0, 1)]
    theta = plan["direction"] * 2 * math.pi * (t - plan["t0"]) / plan["period"]
    dx, dy = _loop_offset(theta, plan["radius"], plan["aspect"], plan["phase"], plan["center"][1])
    return [plan["center"][0] + dx, plan["center"][1] + dy]


def distance_km(a, b):
    lat1, lat2 = map(math.radians, [a[1], b[1]])
    dp, dl = lat2 - lat1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
    return EARTH_RADIUS_M / 1000 * 2 * math.asin(math.sqrt(min(1, h)))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def apply(asset, plan, now=None):
    """Write live position, speed and recent trail into the public asset record."""
    now = time.time() if now is None else now
    lon, lat = position(plan, now)
    before = position(plan, now - 5)
    asset.update(lon=lon, lat=lat, last_seen=iso(now))
    route = next((r for r in reversed(plan["routes"]) if now >= r["start"]), None)
    if route:
        # Routes are time-compressed for presentation; show the modelled road speed instead.
        moving = now < route["start"] + route["duration"]
        asset["speed"] = route.get("display_kmh", 45) if moving else 0
    else:
        asset["speed"] = round(distance_km(before, [lon, lat]) * 720)
    start = max(plan["t0"], now - TRAIL_SECONDS)
    steps = int((now - start) // TRAIL_STEP)
    asset["track"] = [
        dict(lon=p[0], lat=p[1], time=iso(t))
        for t in [start + k * TRAIL_STEP for k in range(steps)] + [now]
        for p in [position(plan, t)]
    ]


def dispatch(plan, target, seconds, now=None, display_kmh=45):
    """Freeze the loop and drive straight to target; the patrol parks on arrival."""
    now = time.time() if now is None else now
    route = {
        "from": position(plan, now),
        "to": list(target),
        "start": now,
        "duration": max(1.0, seconds),
        "display_kmh": display_kmh,
    }
    plan["routes"].append(route)
    return route


def arrived(plan, now=None):
    now = time.time() if now is None else now
    return bool(plan["routes"]) and now >= plan["routes"][-1]["start"] + plan["routes"][-1]["duration"]
