from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..tracks import parse_timestamp
from ..models import Policy, PolicyInput, PolicyStatus, PolicyTestResult
from ..store import audit, lookup, state, StateRoute
from .. import engine, store

router = APIRouter(route_class=StateRoute, tags=["policies"])


@router.post("/api/v1/policies", status_code=201, response_model=Policy)
def create_policy(p: PolicyInput):
    lookup("zones", p.zone)
    row = dict(
        **p.model_dump(),
        id=f"POL-{len(state['policies']) + 1:02}",
        status="draft",
        version=1,
        matches=0,
        false_positives=0,
        approver=None,
    )
    state["policies"].append(row)
    audit("ساخت پیش‌نویس سیاست", row["id"])
    return row


@router.post("/api/v1/policies/{id}/test", response_model=PolicyTestResult)
def test_policy(id: str):
    row = lookup("policies", id)
    if row["condition"] not in engine.SUPPORTED_CONDITIONS:
        raise HTTPException(422, "آزمون تاریخی این شرط هنوز پشتیبانی نمی‌شود؛ تاریخچه تله‌متری/اتصال موردنیاز است")
    if row["condition"] == "sos":
        raise HTTPException(422, "آزمون گذشته اضطراری به تاریخچه رخداد دستگاه نیاز دارد؛ تاریخچه GPS کافی نیست")
    if row["condition"] in engine.ANPR_CONDITIONS:
        return test_plate_reads(row)
    if row["condition"] == "missed_checkpoint":
        return test_checkpoints(row)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    sandbox = dict(zones=deepcopy(state["zones"]), policies=[{**row, "status": "shadow", "matches": 0}],
                   settings=deepcopy(state["settings"]), alerts=[], engine={})
    samples = 0
    for original in state["assets"]:
        points = store.tracks.observations(original["id"], start, end)
        if len(points) > 100000:
            raise HTTPException(422, "حجم داده برای آزمون محلی بیش از حد است")
        asset = {**original, "track": []}
        for point in points:
            if asset["track"] and row["condition"] == "connection_lost":
                zone = lookup("zones", row["zone"])
                timeout = engine.connection_timeout_minutes(state["settings"], zone, row["threshold"])
                deadline = parse_timestamp(asset["last_seen"]) + timedelta(minutes=timeout)
                if deadline < parse_timestamp(point["time"]):
                    asset["scenario_clock"] = deadline.astimezone(engine.TEHRAN).strftime("%H:%M")
                    engine.evaluate(sandbox, asset, deadline.isoformat(), None, lambda *args: None)
            samples += 1
            asset.update(lon=point["lon"], lat=point["lat"], last_seen=point["time"],
                         speed=point["speed"] if point["speed"] is not None else 0,
                         scenario_clock=parse_timestamp(point["time"]).astimezone(engine.TEHRAN).strftime("%H:%M"))
            asset["track"].append(point)
            engine.evaluate(sandbox, asset, point["time"], None, lambda *args: None)
        if points and row["condition"] == "connection_lost":
            asset["scenario_clock"] = end.astimezone(engine.TEHRAN).strftime("%H:%M")
            engine.evaluate(sandbox, asset, end.isoformat(), None, lambda *args: None)
    result = dict(
        matches=len(sandbox["alerts"]),
        false_positives=None,
        period="۷ روز گذشته؛ تاریخچه ذخیره‌شده",
        samples=samples,
        mock=False,
        assumptions="هندسه، مجوز تردد و فاصله گزارش‌دهی فعلی؛ شامل نقاط نمایشی ذخیره‌شده؛ هشدار کاذب نیازمند بازبینی انسانی است",
    )
    return save_test_result(row, result)


def save_test_result(row, result):
    row["test_result"] = result
    if row["status"] == "draft":
        row["status"] = "tested"
        row["version"] += 1
    audit("آزمون سیاست روی تاریخچه ذخیره‌شده", row["id"], str(result["samples"]))
    return result


def test_plate_reads(row):
    """Replay accepted reads, never manufacture ANPR from GPS or camera samples."""
    end = parse_timestamp(store.now())
    start = end - timedelta(days=7)
    before = start - timedelta(minutes=state["settings"]["intel_anpr_repeat_window_minutes"])
    reads = sorted((e for e in state["plate_reads"] if e["source"] == "reported"
                    and before <= parse_timestamp(e["time"]) <= end), key=lambda e: e["time"])
    samples = sum(parse_timestamp(e["time"]) >= start for e in reads)
    if not samples:
        raise HTTPException(422, "آزمون این شرط نیازمند خوانش‌های واقعی پلاک است؛ مسیر GPS کافی نیست")
    sandbox = dict(zones=deepcopy(state["zones"]), cameras=deepcopy(state["cameras"]),
                   settings={**deepcopy(state["settings"]), "intel_anpr_enabled": True},
                   policies=[{**row, "status": "shadow", "matches": 0}], plate_reads=[], alerts=[], engine={})
    for event in reads:
        engine.evaluate(sandbox, engine.plate_subject(sandbox, event), event["time"], None, lambda *args: None, event=event)
        sandbox["plate_reads"].append(event)
    result = dict(matches=sum(parse_timestamp(a["time"]) >= start for a in sandbox["alerts"]),
                  false_positives=None, samples=samples, mock=False, period="۷ روز گذشته؛ خوانش‌های واقعی نگهداری‌شده پلاک",
                  assumptions="فقط ورودی ثبت‌شده؛ موقعیت و حساسیت ثبت‌شده دوربین در هر خوانش، فهرست مجاز و بازه‌های فعلی؛ بدون تولید نمونه یا تشخیص تصویر")
    return save_test_result(row, result)


def test_checkpoints(row):
    """Replay retained timed checkpoints, never substitute GPS-only backtesting."""
    end = parse_timestamp(store.now())
    start = end - timedelta(days=7)
    sandbox = dict(zones=deepcopy(state["zones"]), policies=[{**row, "status": "shadow", "matches": 0}],
                   settings=deepcopy(state["settings"]), alerts=[], engine={}, missions=deepcopy(state["missions"]))
    events = []
    for mission in sandbox["missions"]:
        window = timedelta(minutes=engine.checkpoint_window_minutes(sandbox, mission))
        for cp in mission["checkpoints"]:
            if not cp.get("target_id") or not cp.get("due_at") or cp.get("lon") is None or cp.get("lat") is None:
                continue
            deadline = parse_timestamp(cp["due_at"]) + window
            if start <= deadline < end:
                events.append((deadline + timedelta(microseconds=1), mission["asset_id"]))
            else:
                # Ignore out-of-window deadlines in this sandbox; live data is untouched.
                cp["visited"] = True
    for stamp, asset_id in sorted(events):
        asset = lookup("assets", asset_id)
        engine.evaluate(sandbox, asset, stamp.isoformat(), None, lambda *args: None)
    result = dict(matches=len(sandbox["alerts"]), false_positives=None, samples=len(events), mock=False,
                  period="۷ روز گذشته؛ ایستگاه‌های زمان‌دار نگهداری‌شده",
                  assumptions="مأموریت‌ها و بازدیدهای حافظه‌ای فعلی، هندسه سیاست فعلی و پنجره ذخیره‌شده برنامه؛ بدون بازسازی GPS یا یادگیری؛ بازنشانی تاریخچه را پاک می‌کند")
    return save_test_result(row, result)


@router.patch("/api/v1/policies/{id}/status", response_model=Policy)
def policy_status(id: str, p: PolicyStatus):
    row = lookup("policies", id)
    allowed = {
        "draft": [],
        "tested": ["shadow", "draft"],
        "shadow": ["active", "draft"],
        "active": ["shadow", "draft"],
    }
    if p.status not in allowed[row["status"]]:
        raise HTTPException(409, "ابتدا سیاست را آزمایش کنید و به حالت سایه ببرید")
    if p.status in ("shadow", "active") and row["condition"] not in engine.SUPPORTED_CONDITIONS:
        raise HTTPException(422, "این شرط هنوز موتور اجرایی ندارد و فقط پیش‌نویس است")
    row["status"] = p.status
    row["version"] += 1
    row["approver"] = "سرپرست نمایشی" if p.status == "active" else None
    audit("تغییر وضعیت سیاست", id, p.status)
    return row
