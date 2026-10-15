"""Transparent Bayesian event-rate estimation for patrol targets (Gamma-Poisson).

Each target i has an unknown attempt rate lambda_i (events per year). The
organisation's expert baseline gives the conjugate prior
    lambda_i ~ Gamma(shape = r0_i * s, rate = s),
where r0_i is the baseline rate for the target's class and s the prior strength
in years of equivalent observation. Observed events are discounted with a
half-life (old evidence fades) and weighted by category; the exposure is the
equally discounted observation time. The posterior stays Gamma:
    shape = r0_i * s + sum(w_k * 2^(-age_k / h)),  rate = s + T_discounted.
Credible bounds use the regularized incomplete gamma function implemented here
(series + Lentz continued fraction); no learned weights, no external library.
"""
from datetime import datetime, timezone
import math

from ..core import store
from ..core.tracks import parse_timestamp

YEAR_DAYS = 365.2425
FPMIN = 1e-300


def regularized_lower_gamma(a, x):
    """P(a, x) = gamma(a, x) / Gamma(a), accurate to ~1e-14 (Numerical Recipes 6.2)."""
    if a <= 0:
        raise ValueError("shape must be positive")
    if x <= 0:
        return 0.0
    log_prefix = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        term = total = 1.0 / a
        n = a
        for _ in range(10000):
            n += 1
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return min(1.0, total * math.exp(log_prefix))
    b = x + 1 - a
    c = 1 / FPMIN
    d = 1 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = FPMIN if abs(d) < FPMIN else d
        c = b + an / c
        c = FPMIN if abs(c) < FPMIN else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-16:
            break
    return max(0.0, 1.0 - math.exp(log_prefix) * h)


def gamma_quantile(shape, rate, probability):
    """Inverse CDF of Gamma(shape, rate) by bracketing and bisection on P(shape, x)."""
    if not 0 < probability < 1:
        raise ValueError("probability must be in (0, 1)")
    low, high = 0.0, max(1.0, shape)
    while regularized_lower_gamma(shape, high) < probability:
        high *= 2
    for _ in range(200):
        mid = (low + high) / 2
        if regularized_lower_gamma(shape, mid) < probability:
            low = mid
        else:
            high = mid
        if high - low <= 1e-12 * max(1.0, high):
            break
    return (low + high) / 2 / rate


def decay(age_days, half_life_days):
    return 0.5 ** (max(0.0, age_days) / half_life_days)


def discounted_exposure_years(observed_days, half_life_days):
    """Integral of the same decay over the observation window, in years."""
    if observed_days <= 0:
        return 0.0
    rate = math.log(2) / half_life_days
    return (1 - math.exp(-rate * observed_days)) / rate / YEAR_DAYS


def posterior(prior_rate, prior_years, weighted_events, exposure_years, quantile=0.5, credible=0.9):
    shape = max(prior_rate, 1e-6) * prior_years + weighted_events
    rate = prior_years + exposure_years
    tail = (1 - credible) / 2
    return dict(prior_rate=prior_rate, prior_years=prior_years, weighted_events=weighted_events,
                exposure_years=exposure_years, shape=shape, rate=rate, mean=shape / rate,
                lower=gamma_quantile(shape, rate, tail), upper=gamma_quantile(shape, rate, 1 - tail),
                planning_rate=gamma_quantile(shape, rate, quantile), credible=credible, quantile=quantile)


def attempt_probability(rate_per_year, horizon_hours):
    """Probability of at least one attempt within the horizon at a Poisson rate."""
    return 1 - math.exp(-rate_per_year * horizon_hours / (24 * YEAR_DAYS))


def observation_start(now):
    """Durable start of observation; restarts never reset exposure."""
    record = store.field.get("settings", "risk_observation")
    if record is None:
        record = dict(id="risk_observation", start=now)
        store.field.save("settings", record)
    start = parse_timestamp(record["start"])
    history = store.state["settings"]["patrol_game"].get("history_start")
    if history:
        declared = datetime.fromisoformat(str(history)).replace(tzinfo=timezone.utc)
        start = min(start, declared)
    return start


def events(now):
    """Located, categorised evidence from durable records only; nothing is inferred."""
    stamp = parse_timestamp(now)
    stations = {s["id"]: s for s in store.field.records("stations")}
    rows = {}
    for row in store.field.records("risk_events"):
        rows[row["id"]] = dict(row)
    for incident in store.state["incidents"]:
        row = incident_event(incident)
        rows[row["id"]] = row
    for report in store.field.records("field_reports"):
        if report.get("lon") is not None and report.get("lat") is not None:
            rows[f"report:{report['id']}"] = dict(id=f"report:{report['id']}", source="field_report",
                                                  category=f"report_{report['category']}", time=report["created_at"],
                                                  lon=report["lon"], lat=report["lat"], target_id=None, weight=1.0,
                                                  source_ref=report["id"])
    visits = {v["id"]: v for v in store.field.records("station_visits")}
    for result in store.field.records("station_results"):
        visit = visits.get(result["visit_id"])
        station = stations.get(visit["station_id"]) if visit else None
        if result.get("anomaly") and station:
            rows[f"seal:{result['id']}"] = dict(id=f"seal:{result['id']}", source="station_task", category="seal_anomaly",
                                                time=result["recorded_at"], lon=station["lon"], lat=station["lat"],
                                                target_id=station["id"], weight=1.0, source_ref=result["id"])
    for scan in store.field.rejected_scans("tag_replay"):
        station = stations.get(scan["station_id"])
        if station:
            rows[f"replay:{scan['id']}"] = dict(id=f"replay:{scan['id']}", source="scan", category="tag_replay",
                                                time=scan["received_at"], lon=station["lon"], lat=station["lat"],
                                                target_id=station["id"], weight=1.0, source_ref=scan["id"])
    return [r for r in rows.values() if parse_timestamp(r["time"]) <= stamp]


def incident_event(incident):
    # Incident numbers restart with the in-memory list; the creation time keeps each key unique.
    id = f"incident:{incident['id']}@{incident['created_at']}"
    return dict(id=id, source="incident", category="incident", time=incident["created_at"], lon=incident["lon"],
                lat=incident["lat"], target_id=None, weight=1.0, source_ref=incident["id"])


def persist_incident(incident):
    """Keep incident evidence across restarts and resets."""
    store.field.save("risk_events", incident_event(incident))


def undeclared_history(now, evidence):
    """Imported events older than the observation start inflate the rate unless history_start covers them."""
    start = observation_start(now)
    return any(e["source"] == "import" and parse_timestamp(e["time"]) < start for e in evidence)


def window_days(now):
    return (parse_timestamp(now) - observation_start(now)).total_seconds() / 86400

