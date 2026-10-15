"""Fixed, explainable risk factors plus a transparent Bayesian event rate. No learned weights."""

import math

from ..tracks import parse_timestamp
from .. import store
from ..models import FindingEvidence
from ..sim import distance_km
from . import coverage, geo, patrol_game
from .findings import raise_finding

ACCESS_SCALE_M = 1000


def _access(item):
    raw, values = {}, []
    for key in ("road_distance_m", "village_distance_m", "heavy_vehicle_access"):
        value = item.get(key)
        raw[key] = value if value is not None else "داده ناموجود"
        values.append(0.5 if value is None else float(value) if key == "heavy_vehicle_access"
                      else max(0, 1 - value / ACCESS_SCALE_M))
    return raw, sum(values) / len(values)


def _incidents(kind, item, stamp):
    radius = store.state["settings"]["intel_risk_incident_radius_m"]
    half_life = store.state["settings"]["intel_risk_half_life_days"]
    total, sources, times = 0.0, [], []
    for incident in store.state["incidents"]:
        created = parse_timestamp(incident["created_at"])
        if created > stamp:
            continue
        point = [incident["lon"], incident["lat"]]
        distance = (geo.point_polyline_distance_m(point, item["points"]) if kind == "segment"
                    else distance_km(point, [item["lon"], item["lat"]]) * 1000)
        if distance <= radius:
            days = (stamp - created).total_seconds() / 86400
            total += math.exp(-math.log(2) * days / half_life)
            sources.append(incident["id"])
            times.append(created)
    return total, sources, times


@store.state_locked
def snapshot(now=None):
    now = now or store.now()
    stamp = parse_timestamp(now)
    statuses = {row["id"]: row for row in coverage.snapshot(now)["items"]}
    weights = store.state["settings"]["intel_risk_weights"]
    items = coverage.coverage_items()
    targets = [patrol_game.vehicle_target(kind, item, _access(item)[1]) for kind, item in items]
    estimates = patrol_game.assess(targets, now)
    rows = []
    for (kind, item), target in zip(items, targets):
        status = statuses[item["id"]]
        incidents, incident_ids, times = _incidents(kind, item, stamp)
        access_raw, access = _access(item)
        # Use the unrounded coverage visit time for threshold arithmetic.
        age = (stamp - parse_timestamp(status["last_visit"])).total_seconds() / 3600 if status["last_visit"] else None
        staleness = min(1, max(0, age) / coverage.stale_hours(kind, item)) if age is not None else 1
        exposure = int(kind == "facility" and item["unmanned"])
        factors = [("incidents", incidents, min(1, incidents)), ("access", access_raw, access),
                   ("staleness", age if age is not None else "بازدید نشده", staleness), ("exposure", exposure, exposure)]
        breakdown = [dict(factor=factor, raw=raw, normalized=normalized, weight=weights[factor],
                          contribution=weights[factor] * normalized) for factor, raw, normalized in factors]
        score = sum(f["contribution"] for f in breakdown)
        point, name, estimate = [target["lon"], target["lat"]], target["name"], estimates[item["id"]]
        evidence = dict(rule="جمع وزن‌دار عوامل ثابت ریسک", thresholds=dict(
            weights=weights, incident_radius_m=store.state["settings"]["intel_risk_incident_radius_m"],
            half_life_days=store.state["settings"]["intel_risk_half_life_days"],
            stale_hours=coverage.stale_hours(kind, item), access_scale_m=ACCESS_SCALE_M),
            window_from=min(times, default=stamp).isoformat(), window_to=now,
            points=[[*point, now]], values=dict(score=score, breakdown=breakdown, coverage_status=status["status"],
                                                target_class=target["target_class"], value=target["value"], bayes=estimate))
        finding = raise_finding(rule_id="intel.risk", kind="risk_assessment", severity="info", subject_ids=[item["id"]],
                                summary=f"ارزیابی ریسک {name}", evidence=evidence, sources=[item["id"], *incident_ids], now_iso=now)
        # A latched assessment keeps its ID but always exposes the current arithmetic.
        finding.update(evidence=FindingEvidence.model_validate(evidence).model_dump(mode="json"),
                       updated_at=now, sources=[item["id"], *incident_ids])
        rows.append(dict(id=item["id"], kind=kind, name=name, field=item["field"], lon=point[0], lat=point[1],
                         score=score, breakdown=breakdown, finding_id=finding["id"], target_class=target["target_class"],
                         value=target["value"], bayes=estimate))
    return dict(items=rows, max_score=sum(weights.values()), computed_at=now)
