"""Organisation-parameterised patrol security game: evidence -> payoffs -> optimal coverage.

Payoff construction (every number is shown in the strategy for audit):
  * consequence value V_i and baseline rate r0_i come from the organisation's
    target classes (or a per-target override) entered in the UI;
  * the Bayesian posterior rate (bayes.posterior) at the configured quantile
    gives the attempt probability rho_i over the patrol horizon;
  * attacker gain if uncovered  a_i = (1 - w) * rho_i/max(rho) + w * V_i/max(V),
    where w is the threat profile (0 = thief led by opportunity, 1 = saboteur
    led by consequence);
  * one visit interdicts an attack with probability
    d_i = min(max_detection, (attack_minutes + dwell_i) / horizon_minutes),
    i.e. a randomly timed visit overlapping an attack of that duration;
  * attacker if covered  d_i * (-penalty) + (1 - d_i) * a_i;
    defender loss if uncovered  -V_i/max(V), if covered  -(1 - d_i) V_i/max(V).
The output is advisory: a human approves every plan, and walking-route subsets
follow the shared shadow/active routing decision.
"""
import hashlib
import math

from fastapi import HTTPException

from .. import store
from ..security import auth, authz
from ..engine import routing_decision
from ..fieldstore import canonical
from ..sim import distance_km
from ..tracks import parse_timestamp
from . import bayes, game, geo

HERASAT = {"security_manager", "admin"}


def parameters():
    return store.state["settings"]["patrol_game"]


def fingerprint(params=None):
    return hashlib.sha256(canonical(params or parameters()).encode()).hexdigest()


def require_herasat():
    """Organisation parameters and route subset decisions belong to the security manager."""
    principal = authz.require("manage")
    if not HERASAT & set(principal.roles):
        auth.fail("permission_denied", 403)
    return principal


def approval():
    record = store.field.get("settings", "patrol_game_approval")
    current = fingerprint()
    ok = bool(record) and record["fingerprint"] == current
    return dict(fingerprint=current, approved=ok, approved_by=record["approved_by"] if ok else None,
                approved_at=record["approved_at"] if ok else None)


def approve():
    principal = require_herasat()
    record = dict(id="patrol_game_approval", fingerprint=fingerprint(), approved_by=principal.username,
                  approved_sub=principal.sub, approved_at=store.now())
    store.field.save("settings", record)
    store.audit("تأیید پارامترهای راهبرد گشت", "PATROL-GAME", record["fingerprint"][:16])
    return approval()


def class_key(kind, item):
    if kind == "facility":
        return "facility_unmanned" if item.get("unmanned") else "facility_manned"
    if kind == "segment":
        return "pipeline_segment"
    return f"station:{item.get('sensitivity', '')}"


def class_parameters(key, target_id):
    """(class key used, value, baseline rate per year, always visit) after any per-target override."""
    params = parameters()
    classes = {c["key"]: c for c in params["classes"]}
    key = key if key in classes else "station_default"
    value, rate = classes[key]["value"], classes[key]["prior_rate_per_year"]
    override = next((o for o in params["overrides"] if o["target_id"] == target_id), None)
    always = False
    if override:
        value = override["value"] if override["value"] is not None else value
        rate = override["prior_rate_per_year"] if override["prior_rate_per_year"] is not None else rate
        always = override.get("always_visit", False)
    return key, value, rate, always


def vehicle_target(kind, item, access):
    """A segment or facility as a game target; ease of access scales the baseline rate 0.5x..1.5x."""
    key, value, rate, always = class_parameters(class_key(kind, item), item["id"])
    point = geo.polyline_midpoint(item["points"]) if kind == "segment" else [item["lon"], item["lat"]]
    name = item.get("name") or f"قطعه {item['index'] + 1} از {item['pipeline_id']}"
    return dict(id=item["id"], name=name, kind=kind, target_class=key, value=value, prior_rate=rate * (0.5 + access),
                always_visit=always, lon=point[0], lat=point[1], points=item.get("points"),
                dwell_minutes=store.state["settings"]["intel_plan_dwell_minutes"])


def vehicle_targets(rows):
    from .coverage import coverage_items
    items = {item["id"]: (kind, item) for kind, item in coverage_items()}
    return [vehicle_target(*items[row["id"]], next(f["normalized"] for f in row["breakdown"] if f["factor"] == "access"))
            for row in rows]


def station_targets(station_ids):
    targets = []
    for station_id in station_ids:
        station = store.field.get("stations", station_id)
        if station is None:
            raise HTTPException(409, "ایستگاه مسیر پیدا نشد")
        key, value, rate, always = class_parameters(class_key("station", station), station_id)
        targets.append(dict(id=station_id, name=station.get("name", station_id), kind="station", target_class=key,
                            value=value, prior_rate=rate, always_visit=always, lon=station["lon"], lat=station["lat"],
                            points=None, dwell_minutes=station.get("min_dwell_seconds", 0) / 60))
    return targets


def _distance_m(target, event):
    point = [event["lon"], event["lat"]]
    if target.get("points") and len(target["points"]) > 1:
        return geo.point_polyline_distance_m(point, target["points"])
    return distance_km(point, [target["lon"], target["lat"]]) * 1000


def assess(targets, now, evidence=None):
    """Posterior rate per target from durable evidence with a Gaussian spatial kernel and decay."""
    params = parameters()
    weights, sigma, half_life = params["event_weights"], params["spatial_bandwidth_m"], params["half_life_days"]
    exposure = bayes.discounted_exposure_years(bayes.window_days(now), half_life)
    stamp = parse_timestamp(now)
    evidence = bayes.events(now) if evidence is None else evidence
    result = {}
    for target in targets:
        total, ids = 0.0, []
        for event in evidence:
            category = f"import_{event['category']}" if event["source"] == "import" else event["category"]
            base = weights.get(category, 0.0) * event.get("weight", 1.0)
            if base <= 0:
                continue
            if event.get("target_id"):
                spatial = float(event["target_id"] == target["id"])
            elif event.get("lon") is not None:
                distance = _distance_m(target, event)
                spatial = math.exp(-distance ** 2 / (2 * sigma ** 2)) if distance <= 3 * sigma else 0.0
            else:
                spatial = 0.0
            if spatial <= 0:
                continue
            age = (stamp - parse_timestamp(event["time"])).total_seconds() / 86400
            total += base * spatial * bayes.decay(age, half_life)
            ids.append(event["id"])
        estimate = bayes.posterior(target["prior_rate"], params["prior_strength_years"], total, exposure,
                                   params["risk_quantile"], params["credible_level"])
        result[target["id"]] = {**estimate, "event_ids": ids}
    return result


def payoffs(targets, estimates, horizon_hours):
    params = parameters()
    horizon_minutes = max(1.0, horizon_hours * 60)
    rho = {t["id"]: bayes.attempt_probability(estimates[t["id"]]["planning_rate"], horizon_hours) for t in targets}
    rho_max = max(rho.values(), default=0) or 1.0
    v_max = max((t["value"] for t in targets), default=1) or 1.0
    w = params["threat_profile"]
    built, details = [], {}
    for t in targets:
        gain = (1 - w) * rho[t["id"]] / rho_max + w * t["value"] / v_max
        detection = min(params["max_detection"], (params["attack_minutes"] + t["dwell_minutes"]) / horizon_minutes)
        loss = t["value"] / v_max
        built.append(game.Target(t["id"], attacker_covered=-detection * params["capture_penalty"] + (1 - detection) * gain,
                                 attacker_uncovered=gain, defender_covered=-(1 - detection) * loss, defender_uncovered=-loss))
        details[t["id"]] = dict(attempt_probability=rho[t["id"]], attacker_uncovered=gain, detection=detection)
    return built, details, v_max


def outcome(built, coverage, attacker, v_max):
    result = game.evaluate(built, coverage, attacker, parameters()["quantal_rationality"])
    return dict(defender_expected=result["defender_expected"], attacker_expected=result["attacker_expected"],
                attacker_max=result["attacker_max"], expected_loss=-result["defender_expected"] * v_max), result["response"]


def improvement(best, base):
    loss, reference = -best["defender_expected"], -base["defender_expected"]
    return None if reference <= 1e-12 else (reference - loss) / reference


def strategy(targets, resources, horizon_hours, now, mandatory_ids=(), legacy_weights=None, estimates=None):
    """Advisory coverage for the free targets; mandatory targets are visited with certainty.

    Returns (strategy record, marginals of the free targets summing to resources).
    """
    params = parameters()
    model = params["model"]
    rationality = params["quantal_rationality"]
    attacker = "quantal" if model == "quantal" else "stackelberg"
    evidence = bayes.events(now)
    estimates = estimates or assess(targets, now, evidence)
    free = [t for t in targets if t["id"] not in mandatory_ids]
    built, details, v_max = payoffs(free, estimates, horizon_hours)
    resources = max(0.0, min(float(resources), float(len(free))))
    warnings, attacked, response, baselines = [], None, {}, {}
    best = dict(defender_expected=0.0, attacker_expected=0.0, attacker_max=0.0, expected_loss=0.0)
    coverage = {}
    if built:
        weights = legacy_weights or {k: d["attempt_probability"] for k, d in details.items()}
        uniform = {t.id: resources / len(built) for t in built}
        proportional = game.proportional(built, resources, weights)
        optimal, sse_target, _ = game.strong_stackelberg(built, resources)
        if model == "quantal":
            coverage = game.quantal_response(built, resources, rationality)
        elif model == "weighted":
            coverage = proportional
        else:
            coverage, attacked = optimal, sse_target
        best, response = outcome(built, coverage, attacker, v_max)
        baselines = {"uniform": outcome(built, uniform, attacker, v_max)[0],
                     "proportional": outcome(built, proportional, attacker, v_max)[0]}
        if model != "stackelberg":
            baselines["stackelberg"] = outcome(built, optimal, attacker, v_max)[0]
    status = approval()
    if not status["approved"]:
        warnings.append("پارامترهای ارزش و نرخ پایه اهداف هنوز به تأیید مدیر حراست نرسیده‌اند")
    if model == "weighted":
        warnings.append("مدل وزن‌دار قدیمی فعال است؛ احتمال‌های پوشش تقریبی‌اند و راهبرد بهینه فقط برای مقایسه آمده است")
    if bayes.undeclared_history(now, evidence):
        warnings.append("رخدادهای واردشده پیش از آغاز مشاهده‌اند؛ تاریخ آغاز سوابق را در پارامترها تعیین کنید تا نرخ بیش‌برآورد نشود")
    if built and 0 < resources < len(built) and all(c < 1e-9 or c > 1 - 1e-9 for c in coverage.values()):
        warnings.append("راهبرد بهینه در انتخاب هدف قطعی است؛ پیش‌بینی‌ناپذیری فقط از زمان تصادفی بازدید تأمین می‌شود. "
                        "افزودن توقف یا بازبینی ارزش‌ها را بررسی کنید")
    if free and all(estimates[t["id"]]["weighted_events"] == 0 for t in free):
        warnings.append("هیچ رخداد ثبت‌شده‌ای در محدوده اهداف نیست؛ برآورد فقط بر نرخ پایه سازمان تکیه دارد")
    by_id = {t.id: t for t in built}
    rows = []
    for t in targets:
        forced = t["id"] in mandatory_ids
        detail = details.get(t["id"]) or dict(attacker_uncovered=0.0, detection=0.0, attempt_probability=bayes.attempt_probability(
            estimates[t["id"]]["planning_rate"], horizon_hours))
        c = 1.0 if forced else coverage.get(t["id"], 0.0)
        rows.append(dict(id=t["id"], name=t["name"], kind=t["kind"], target_class=t["target_class"], value=t["value"],
                         bayes=estimates[t["id"]], attempt_probability=detail["attempt_probability"],
                         attacker_uncovered=detail["attacker_uncovered"], detection=detail["detection"], coverage=c,
                         attacker_utility=by_id[t["id"]].attacker_utility(c) if t["id"] in by_id else 0.0,
                         attack_probability=response.get(t["id"], 0.0), mandatory=forced, selected=forced))
    record = dict(model=model, resources=resources + len(mandatory_ids), horizon_hours=horizon_hours,
                  threat_profile=params["threat_profile"], targets=rows, attacked_target_id=attacked, outcome=best,
                  baselines=baselines,
                  improvement_vs_uniform=improvement(best, baselines["uniform"]) if baselines else None,
                  improvement_vs_proportional=improvement(best, baselines["proportional"]) if baselines else None,
                  entropy=game.normalized_entropy(coverage) if coverage else 0.0,
                  parameters_fingerprint=status["fingerprint"], parameters_approved=status["approved"],
                  approved_by=status["approved_by"], approved_at=status["approved_at"], warnings=warnings,
                  conformity=None, can_execute=False)
    return record, {t.id: coverage[t.id] for t in built}


def sample(record, marginals, count, rng):
    """Comb-sample count free targets with exactly the planned marginals; marks them selected."""
    chosen = game.comb_sample(marginals, count, rng) if count > 0 and marginals else []
    for row in record["targets"]:
        row["selected"] = row["mandatory"] or row["id"] in chosen
    return chosen


def conformity(plans):
    """Do approved plans visit targets as often as their marginals predict?

    Each target's visit count is Poisson-binomial with mean sum(c) and variance
    sum(c(1-c)); the statistic sums squared standardized deviations.
    """
    expected, variance, observed, count = {}, {}, {}, 0
    for plan in plans:
        record = plan.get("strategy")
        if plan["status"] != "approved" or not record or record["model"] == "weighted":
            continue
        count += 1
        for t in record["targets"]:
            if t["mandatory"]:
                continue
            expected[t["id"]] = expected.get(t["id"], 0.0) + t["coverage"]
            variance[t["id"]] = variance.get(t["id"], 0.0) + t["coverage"] * (1 - t["coverage"])
            observed[t["id"]] = observed.get(t["id"], 0) + int(t["selected"])
    if count < 5:
        return None
    chi, worst, dof = 0.0, 0.0, 0
    for id, mean in expected.items():
        if variance[id] > 1e-9:
            z = (observed[id] - mean) / math.sqrt(variance[id])
            chi += z * z
            worst = max(worst, abs(z))
            dof += 1
    return dict(plans=count, chi_square=chi, degrees_of_freedom=max(0, dof - 1), max_standardized_deviation=worst)


def known_target(id):
    from .coverage import coverage_items
    return any(item["id"] == id for _, item in coverage_items()) or store.field.get("stations", id) is not None


def list_events():
    return sorted(bayes.events(store.now()), key=lambda e: e["time"], reverse=True)


@store.state_locked
def import_events(payload):
    """Append-only ledger: source_ref is the idempotency key; changing a recorded event is refused."""
    authz.require("approval")
    now = store.now()
    rows, created, unchanged = [], 0, 0
    for event in payload.events:
        if event.time > parse_timestamp(now):
            raise HTTPException(422, "زمان رخداد تاریخی نمی‌تواند در آینده باشد")
        if event.target_id and not known_target(event.target_id):
            raise HTTPException(422, "شناسه هدف رخداد در لایه‌ها یا ایستگاه‌ها پیدا نشد")
        id = "import:" + hashlib.sha256(event.source_ref.encode()).hexdigest()[:20]
        item = dict(id=id, source="import", category=event.category, time=event.time.isoformat(), lon=event.lon,
                    lat=event.lat, target_id=event.target_id, weight=event.weight, source_ref=event.source_ref,
                    description=event.description)
        existing = store.field.get("risk_events", id)
        if existing:
            if canonical(existing) != canonical(item):
                raise HTTPException(409, f"رخداد {event.source_ref} قبلاً با محتوای دیگری ثبت شده و قابل تغییر نیست")
            unchanged += 1
        else:
            store.field.save("risk_events", item)
            created += 1
        rows.append(item)
    store.audit("ورود رخدادهای تاریخی ریسک", "RISK-EVENTS", f"{created} جدید · {unchanged} تکراری")
    return dict(created=created, unchanged=unchanged, events=rows)


def route_mandatory(route, targets):
    fixed = {route.get("fixed_first"), route.get("fixed_last")} - {None}
    return [t["id"] for t in targets if t["id"] in fixed or t["always_visit"]]


def route_strategy(route, horizon_hours, now):
    """Station coverage for a walking route that visits stations_per_tour stations per tour."""
    targets = station_targets(route["station_ids"])
    mandatory = route_mandatory(route, targets)
    per_tour = route.get("stations_per_tour") or len(targets)
    record, marginals = strategy(targets, max(0, per_tour - len(mandatory)), horizon_hours, now, mandatory)
    if len(mandatory) > per_tour:
        record["warnings"].append("تعداد ایستگاه‌های الزامی از ظرفیت هر دور بیشتر است؛ همه ایستگاه‌های الزامی بازدید می‌شوند")
    return record, marginals, mandatory


def select_route_stations(route, horizon_hours, rng, now, key):
    """Optimized subset for one walking tour, applied only when Herasat's decision is routed.

    Returns (station ids to visit, proposed ids, finding id, warnings). Any blocked
    condition keeps the full route and still records the proposal as a finding.
    """
    from . import findings
    params = parameters()
    record, marginals, mandatory = route_strategy(route, horizon_hours, now)
    free_count = max(0, (route.get("stations_per_tour") or len(route["station_ids"])) - len(mandatory))
    chosen = set(sample(record, marginals, min(free_count, len(marginals)), rng)) | set(mandatory)
    proposed = [id for id in route["station_ids"] if id in chosen]
    decision = routing_decision(store.state["settings"], route.get("subset_mode", "shadow"), "apply_subset")
    blocked = []
    if not params["allow_subset_tours"]:
        blocked.append("بازدید زیرمجموعه ایستگاه‌ها در پارامترهای سازمان مجاز نشده است")
    if not record["parameters_approved"]:
        blocked.append("پارامترهای راهبرد گشت تأیید نشده‌اند")
    if not decision["routed"]:
        blocked.append(f"انتخاب بهینه در {decision['reason']} فقط ثبت شد")
    applied = not blocked
    finding = findings.raise_finding(
        rule_id=f"intel.tour_subset.{key}", kind="tour_subset", severity="info", subject_ids=[route["id"]],
        summary=f"پیشنهاد {len(proposed)} از {len(route['station_ids'])} ایستگاه برای دور {key}",
        sources=[route["id"]], now_iso=now, mode=route.get("subset_mode", "shadow"), action="apply_subset",
        evidence=dict(rule="راهبرد بازی امنیتی استکلبرگ برای ایستگاه‌های مسیر و نمونه‌گیری شانه‌ای",
                      thresholds=dict(model=params["model"], stations_per_tour=route.get("stations_per_tour"),
                                      horizon_hours=horizon_hours, parameters_fingerprint=record["parameters_fingerprint"]),
                      window_from=now, window_to=now,
                      points=[[s["lon"], s["lat"], now] for s in map(lambda id: store.field.get("stations", id), proposed)],
                      values=dict(applied=applied, blocked=blocked, proposed_station_ids=proposed, mandatory=mandatory,
                                  marginals=marginals, outcome=record["outcome"], baselines=record["baselines"])))
    return (proposed if applied else list(route["station_ids"])), proposed, finding["id"], ([] if applied else blocked)


def set_route_coverage(route, payload):
    """Herasat's per-route decision: visit every station, or an optimized subset per tour."""
    require_herasat()
    if payload.coverage_mode == "optimized":
        if payload.stations_per_tour >= len(route["station_ids"]):
            raise HTTPException(422, "تعداد ایستگاه هر دور باید از کل ایستگاه‌های مسیر کمتر باشد")
        mandatory = route_mandatory(route, station_targets(route["station_ids"]))
        if payload.stations_per_tour < len(mandatory):
            raise HTTPException(422, "تعداد ایستگاه هر دور از ایستگاه‌های الزامی مسیر کمتر است")
    route.update(coverage_mode=payload.coverage_mode, stations_per_tour=payload.stations_per_tour,
                 subset_mode=payload.subset_mode)
    store.field.save("routes", route)
    store.audit("تصمیم پوشش ایستگاه‌های مسیر", route["id"],
                f"{payload.coverage_mode} · {payload.stations_per_tour or 'همه'} · {payload.subset_mode}")
    return route
