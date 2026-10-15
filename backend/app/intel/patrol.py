"""Game-theoretic randomized drafts and coverage-driven compliance, without dispatch."""

import secrets
from copy import deepcopy
from datetime import timedelta, timezone

from fastapi import HTTPException

from ..core.tracks import parse_timestamp
from ..core import engine, store
from ..routers.incidents import eta_minutes, patrol_vehicle
from ..core.sim import distance_km
from . import coverage, findings, patrol_game, risk

MAX_TIME_RETRIES = 64
MAX_SCHEDULE_ATTEMPTS = 32


def weighted_sample(items, count, alpha, rng=None):
    """Sampling without replacement; RNG injection is internal, never an API input."""
    rng = rng if rng is not None else secrets.SystemRandom()
    remaining, selected = list(items), []
    for _ in range(min(count, len(remaining))):
        weights = [item["score"] ** alpha for item in remaining]
        total = sum(weights)
        if total == 0:
            weights, total = [1] * len(remaining), len(remaining)
        ticket, index = rng.random() * total, len(remaining) - 1
        for i, weight in enumerate(weights):
            ticket -= weight
            if ticket < 0:
                index = i
                break
        selected.append(remaining.pop(index))
    return selected


def similar_local_time(a, b, jitter_minutes):
    def seconds(value):
        value = parse_timestamp(value).astimezone(engine.TEHRAN)
        return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1e6
    diff = abs(seconds(a) - seconds(b))
    return min(diff, 86400 - diff) <= jitter_minutes * 60


def _history():
    approved = sorted((p for p in store.state["patrol_plans"] if p["status"] == "approved"), key=lambda p: p["approved_at"])[-3:]
    history = {}
    for plan in approved:
        for patrol in plan["patrols"]:
            for stop in patrol["stops"]:
                history.setdefault(stop["target_id"], []).append(stop["due_at"])
    return history


def _schedule(route, base, start, end, settings, history, rng):
    locations = [base, *[[r["lon"], r["lat"]] for r in route]]
    travel = [eta_minutes(distance_km(a, b)) * 60 for a, b in zip(locations, locations[1:])]
    dwell = settings["intel_plan_dwell_minutes"] * 60
    if (end - start).total_seconds() < sum(travel) + len(route) * dwell:
        raise HTTPException(422, "طول شیفت برای سفر تخمینی و توقف اهداف کافی نیست؛ تعداد ایستگاه‌ها را کم کنید")
    for _ in range(MAX_SCHEDULE_ATTEMPTS):
        result, previous = [], start
        for index, target in enumerate(route):
            earliest = previous + timedelta(seconds=travel[index] + (dwell if index else 0))
            remaining = sum(travel[index + 1:]) + dwell * (len(route) - index)
            latest = end - timedelta(seconds=remaining)
            if latest < earliest:
                break
            for _ in range(MAX_TIME_RETRIES):
                due = earliest + (latest - earliest) * rng.random()
                if not any(similar_local_time(due.isoformat(), old, settings["intel_plan_time_jitter_minutes"])
                           for old in history.get(target["id"], [])):
                    result.append(due.isoformat())
                    previous = due
                    break
            else:
                break
        if len(result) == len(route):
            return result
    raise HTTPException(422, "زمان‌بندی متفاوت از سه برنامه تأییدشده اخیر در این شیفت ممکن نشد؛ بازه شیفت یا حریم زمانی را تغییر دهید")


def _mandatory(rows, stamp):
    statuses = {c["id"]: c for c in coverage.snapshot(stamp)["items"]}
    metadata = {item["id"]: (kind, item) for kind, item in coverage.coverage_items()}
    stale = [r for r in rows if statuses[r["id"]]["status"] == "stale"]
    if stale:
        def overdue(row):
            kind, item = metadata[row["id"]]
            age = (parse_timestamp(stamp) - parse_timestamp(statuses[row["id"]]["last_visit"])).total_seconds() / 3600
            return age - coverage.stale_hours(kind, item)
        return max(stale, key=overdue)
    never = [r for r in rows if statuses[r["id"]]["status"] == "never"]
    return max(never, key=lambda r: r["score"]) if never else None


def _targets(rows, stamp, capacity):
    """Game targets, Bayesian estimates and mandatory ids (most overdue plus always-visit overrides)."""
    targets = patrol_game.vehicle_targets(rows)
    overdue = _mandatory(rows, stamp)
    mandatory = ([overdue["id"]] if overdue else []) + [t["id"] for t in targets if t["always_visit"]
                                                        and (overdue is None or t["id"] != overdue["id"])]
    if len(mandatory) > capacity:
        raise HTTPException(422, "اهداف الزامی بیشتر از ظرفیت توقف خودروهای انتخاب‌شده است")
    return targets, {r["id"]: r["bayes"] for r in rows}, mandatory


@store.state_locked
def preview(resources, horizon_hours):
    """Current optimal coverage for the given vehicle stops and horizon; nothing is stored."""
    stamp = store.now()
    rows = risk.snapshot(stamp)["items"]
    capacity = min(len(rows), resources)
    targets, estimates, mandatory = _targets(rows, stamp, capacity)
    alpha = store.state["settings"]["intel_risk_alpha"]
    record, _ = patrol_game.strategy(targets, capacity - len(mandatory), horizon_hours, stamp, mandatory,
                                     {r["id"]: r["score"] ** alpha for r in rows}, estimates)
    record["conformity"] = patrol_game.conformity(store.state["patrol_plans"])
    return record


@store.state_locked
def create(payload, rng=None):
    rng = rng if rng is not None else secrets.SystemRandom()
    stamp = store.now()
    start, end = payload.shift_start.astimezone(timezone.utc), payload.shift_end.astimezone(timezone.utc)
    if start < parse_timestamp(stamp):
        raise HTTPException(422, "آغاز شیفت برنامه پیشنهادی باید در آینده باشد")
    assets = [store.lookup("assets", id) for id in payload.asset_ids]
    if any(not patrol_vehicle(a) for a in assets):
        raise HTTPException(422, "فقط خودروهای واحد گشت را برای برنامه انتخاب کنید")
    settings = deepcopy({key: value for key, value in store.state["settings"].items()
                         if key.startswith(("intel_risk_", "intel_plan_"))})
    rows = risk.snapshot(stamp)["items"]
    if not rows:
        raise HTTPException(422, "قطعه یا تأسیساتی برای برنامه گشت موجود نیست")
    warnings = []
    count = min(len(rows), payload.stops_per_patrol * len(assets))
    if count < payload.stops_per_patrol * len(assets):
        warnings.append("تعداد اهداف موجود کمتر از ظرفیت درخواست‌شده است")
    targets, estimates, mandatory_ids = _targets(rows, stamp, count)
    by_id = {r["id"]: r for r in rows}
    free_count = count - len(mandatory_ids)
    weights = {r["id"]: r["score"] ** settings["intel_risk_alpha"] for r in rows}
    horizon = (end - start).total_seconds() / 3600
    strategy, marginals = patrol_game.strategy(targets, free_count, horizon, stamp, mandatory_ids, weights, estimates)
    if strategy["model"] == "weighted":
        sampled = weighted_sample([r for r in rows if r["id"] not in mandatory_ids], free_count, settings["intel_risk_alpha"], rng)
        chosen = {r["id"] for r in sampled}
        for row in strategy["targets"]:
            row["selected"] = row["mandatory"] or row["id"] in chosen
    else:
        sampled = [by_id[id] for id in patrol_game.sample(strategy, marginals, free_count, rng)]
    strategy["conformity"] = patrol_game.conformity(store.state["patrol_plans"])
    warnings.extend(strategy["warnings"])
    selected = [by_id[id] for id in mandatory_ids] + sampled
    patrols = []
    for asset in assets:
        base = asset.get("patrol_base")
        if base is None:
            base = [asset["lon"], asset["lat"]]
            warnings.append(f"پایگاه {asset['name']} ناموجود؛ موقعیت فعلی مبنای این پیش‌نویس است")
        patrols.append(dict(asset_id=asset["id"], base=list(base), stops=[]))
    for target in selected:
        available = [p for p in patrols if len(p["stops"]) < payload.stops_per_patrol]
        nearest = min(available, key=lambda p: distance_km(p["base"], [target["lon"], target["lat"]]))
        nearest["stops"].append(target)
    history = _history()
    for patrol in patrols:
        ordered, remaining, point = [], patrol["stops"], patrol["base"]
        while remaining:
            target = min(remaining, key=lambda r: distance_km(point, [r["lon"], r["lat"]]))
            remaining.remove(target)
            ordered.append(target)
            point = [target["lon"], target["lat"]]
        times = _schedule(ordered, patrol["base"], start, end, settings, history, rng)
        patrol["stops"] = [dict(target_id=r["id"], **{k: deepcopy(r[k]) for k in ("kind", "name", "field", "lon", "lat", "score", "breakdown", "finding_id")},
                               due_at=due, mandatory=r["id"] in mandatory_ids) for r, due in zip(ordered, times)]
    id = f"PPL-{len(store.state['patrol_plans']) + 1:04}"
    source_ids = [r["finding_id"] for r in selected]
    finding = findings.raise_finding(rule_id=f"intel.patrol_plan.{id}", kind="patrol_plan", severity="info",
        subject_ids=payload.asset_ids, summary=f"پیشنهاد برنامه گشت {id}؛ نیازمند تأیید اپراتور",
        sources=source_ids, now_iso=stamp, evidence=dict(
        rule="نمونه‌گیری وزن‌دار و زمان‌بندی تصادفی محدود" if strategy["model"] == "weighted"
        else "راهبرد بازی امنیتی استکلبرگ، نمونه‌گیری شانه‌ای با احتمال‌های دقیق و زمان‌بندی تصادفی محدود",
        thresholds={**settings, "patrol_game": deepcopy(patrol_game.parameters())},
        window_from=start.isoformat(), window_to=end.isoformat(),
        points=[[s["lon"], s["lat"], s["due_at"]] for p in patrols for s in p["stops"]],
        values=dict(plan_id=id, patrols=patrols, mandatory_target_ids=mandatory_ids,
                    mandatory_target_id=mandatory_ids[0] if mandatory_ids else None,
                    parameters_fingerprint=strategy["parameters_fingerprint"], outcome=strategy["outcome"],
                    baselines=strategy["baselines"], entropy=strategy["entropy"])))
    plan = dict(id=id, status="draft", shift_start=start.isoformat(), shift_end=end.isoformat(), created_at=stamp,
                approved_at=None, discarded_at=None, patrols=patrols, settings_snapshot=settings, mission_ids=[],
                warnings=warnings, finding_id=finding["id"], strategy=strategy, can_execute=False)
    store.state["patrol_plans"].append(plan)
    store.audit("ساخت پیش‌نویس برنامه گشت", id, actor="اپراتور")
    return plan


@store.state_locked
def approve(id):
    plan = store.lookup("patrol_plans", id)
    if plan["status"] == "approved":
        return plan
    if plan["status"] != "draft":
        raise HTTPException(409, "برنامه کنارگذاشته‌شده قابل تأیید نیست")
    if parse_timestamp(plan["shift_end"]) <= parse_timestamp(store.now()):
        raise HTTPException(409, "شیفت برنامه پایان یافته است؛ پیش‌نویس تازه بسازید")
    missions = []
    for patrol in plan["patrols"]:
        if not patrol["stops"]:
            continue
        asset = store.lookup("assets", patrol["asset_id"])
        if not patrol_vehicle(asset):
            raise HTTPException(409, "تجهیز برنامه دیگر عضو واحد گشت نیست")
        missions.append(dict(id=f"MSN-{101 + len(store.state['missions']) + len(missions)}", name=f"برنامه {id} · {asset['name']}",
            asset_id=asset["id"], zone="، ".join(dict.fromkeys(s["field"] for s in patrol["stops"])), status="active", progress=0,
            plan_id=id, plan_window_minutes=plan["settings_snapshot"]["intel_plan_window_minutes"],
            checkpoints=[dict(name=s["name"], visited=False, target_id=s["target_id"], lon=s["lon"], lat=s["lat"], due_at=s["due_at"], visited_at=None)
                         for s in patrol["stops"]]))
    store.state["missions"].extend(missions)
    plan.update(status="approved", approved_at=store.now(), mission_ids=[m["id"] for m in missions])
    findings.acknowledge(plan["finding_id"])
    store.audit("تأیید برنامه گشت و ایجاد مأموریت", id, "، ".join(plan["mission_ids"]), actor="اپراتور")
    return plan


@store.state_locked
def discard(id):
    plan = store.lookup("patrol_plans", id)
    if plan["status"] == "discarded":
        return plan
    if plan["status"] != "draft":
        raise HTTPException(409, "برنامه تأییدشده قابل کنارگذاشتن نیست")
    plan.update(status="discarded", discarded_at=store.now())
    findings.resolve_finding(plan["finding_id"])
    store.audit("کنارگذاشتن پیش‌نویس برنامه گشت", id, actor="اپراتور")
    return plan


@store.state_locked
def record_visit(target_id, asset_id, visited_at):
    visit = parse_timestamp(visited_at)
    for mission in store.state["missions"]:
        if mission["asset_id"] != asset_id or mission["status"] == "completed":
            continue
        window = timedelta(minutes=engine.checkpoint_window_minutes(store.state, mission))
        for cp in mission["checkpoints"]:
            if cp["visited"] or cp.get("target_id") != target_id or not cp.get("due_at"):
                continue
            due = parse_timestamp(cp["due_at"])
            if due - window <= visit <= due + window:
                cp.update(visited=True, visited_at=visited_at)
                store.update_mission_progress(mission)
                store.audit("بازدید ایستگاه از پوشش گشت", mission["id"], target_id, actor="موتور پوشش گشت")
