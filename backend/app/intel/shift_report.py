"""Read-only shift aggregates and boundary audit; no detection or routing rules.

Small timestamp journals retain existing coverage updates and observed tracker
statuses. They are operational facts, not stored reports or inferred outages.
"""

from datetime import datetime, timedelta, timezone
from bisect import bisect_left

from fastapi import HTTPException

from ..core.tracks import parse_timestamp as stamp
from ..core import engine, store
from ..core.models import SEVERITY_LABELS as SEVERITIES
from . import coverage

KINDS = {"coverage_gap": "شکاف پوشش", "patrol_safety": "ایمنی گشت", "hazard_approach": "نزدیک‌شدن به خطر", "risk_assessment": "ارزیابی ریسک",
         "pressure_drop": "افت فشار گزارش‌شده", "unknown_vehicle": "خودروی سنگین ناشناس در شب", "camera_event": "تکرار پلاک در دوربین‌های حساس"}
DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")



def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


def _fa(value):
    return str(value).translate(DIGITS)


def _memory(now):
    return store.state.setdefault("report_history", dict(
        coverage_visits={}, tracker_statuses={}, history_since=store.state.get("data_since", now),
        cursor=store.state.get("data_since", now), audited=[],
    ))


def shift_windows(first_day, last_day):
    """Concrete Tehran intervals, including next-day ends and 24-hour schedules."""
    day = first_day
    while day <= last_day:
        for schedule in store.state["settings"]["intel_shifts"]:
            start, end = ("00:00", "00:00") if schedule == "تمام شبانه‌روز" else schedule.replace("-", "–").split("–")
            a, b = [datetime.combine(day, datetime.strptime(t, "%H:%M").time(), engine.TEHRAN) for t in (start, end)]
            if b <= a:
                b += timedelta(days=1)
            yield a, b
        day += timedelta(days=1)


def last_completed_shift(now):
    local = stamp(now).astimezone(engine.TEHRAN)
    windows = shift_windows(local.date() - timedelta(days=2), local.date())
    return max((pair for pair in windows if pair[1] <= local), key=lambda pair: (pair[1], pair[0]))


def record_coverage_visit(item_id, visit):
    memory = _memory(store.now())
    rows = memory["coverage_visits"].setdefault(item_id, [])
    # Backfill can replay identical observations after geometry/settings edits.
    if not rows or stamp(visit["last_visit"]) > stamp(rows[-1]["last_visit"]):
        rows.append(dict(visit))
    else:
        index = bisect_left(rows, stamp(visit["last_visit"]), key=lambda r: stamp(r["last_visit"]))
        if index == len(rows) or stamp(rows[index]["last_visit"]) != stamp(visit["last_visit"]):
            rows.insert(index, dict(visit))


def observe_trackers(now):
    memory = _memory(now)
    for asset in store.state["assets"]:
        rows = memory["tracker_statuses"].setdefault(asset["id"], [])
        if not rows or rows[-1]["status"] != asset["status"]:
            rows.append(dict(time=now, status=asset["status"]))


@store.state_locked
def tick(now):
    """Audit completed boundaries once; retain only cursors and provenance keys."""
    memory = _memory(now)
    previous, current = stamp(memory["cursor"]), stamp(now)
    if current <= previous:
        return
    windows = shift_windows(previous.astimezone(engine.TEHRAN).date() - timedelta(days=1),
                            current.astimezone(engine.TEHRAN).date())
    for start, end in sorted(windows, key=lambda pair: (pair[1], pair[0])):
        key = f"{_iso(start)}/{_iso(end)}"
        if previous < end <= current and key not in memory["audited"]:
            store.audit("تولید گزارش شیفت", "SHIFT", key, actor="سامانه")
            memory["audited"].append(key)
    memory["cursor"] = now
    # Keep the last known fact before retention, so the retained period has a baseline.
    cutoff = current - timedelta(days=store.state["settings"]["retention_days"])
    if cutoff > stamp(memory["history_since"]):
        for collection, time_key in (("coverage_visits", "last_visit"), ("tracker_statuses", "time")):
            for id, rows in memory[collection].items():
                older = [row for row in rows if stamp(row[time_key]) < cutoff]
                memory[collection][id] = older[-1:] + [row for row in rows if stamp(row[time_key]) >= cutoff]
        memory["history_since"] = _iso(cutoff)


@store.state_locked
def snapshot(window_from=None, window_to=None, now=None):
    now = now or store.now()
    current = stamp(now)
    if (window_from is None) != (window_to is None):
        raise HTTPException(422, "ابتدا و انتهای بازه گزارش را با هم وارد کنید")
    start, end = last_completed_shift(now) if window_from is None else (stamp(window_from), stamp(window_to))
    if start.tzinfo is None or end.tzinfo is None or start >= end or end > current:
        raise HTTPException(422, "بازه گزارش باید دارای منطقه زمانی، آغاز قبل از پایان و پایان حداکثر زمان جاری باشد")
    if "data_source_id" not in store.state:
        store.begin_data_epoch(store.state.get("data_since", now))
    data_since = stamp(store.state["data_since"])
    effective_start = max(start, data_since)
    memory = _memory(now)
    epoch_id = store.state["data_source_id"]
    partial = start < data_since
    notes = ["داده‌های عملیاتی فقط از آغاز سرور یا آخرین بازنشانی موجودند؛ بخش قبلی بازه در شمارش نیست."] if partial else []
    sections = {}

    def in_window(value):
        return value is not None and effective_start <= stamp(value) < end

    def line(text, sources=()):
        return dict(text=text, source_ids=list(dict.fromkeys(sources)) or [epoch_id])

    def section(key, title, counts, lines, extra_notes=()):
        sections[key] = dict(title=title, partial=partial or bool(extra_notes), notes=notes + list(extra_notes), counts=counts, lines=lines)

    incidents = store.state["incidents"]
    opened = [i for i in incidents if in_window(i["created_at"])]
    def closed_at(i):
        return next((e["time"] for e in i["timeline"] if e["action"].startswith("خاتمه حادثه")), None)
    closed = [i for i in incidents if in_window(closed_at(i))]
    still_open = [i for i in incidents if end > data_since and stamp(i["created_at"]) < end
                  and (closed_at(i) is None or stamp(closed_at(i)) >= end)]
    incident_counts = dict(opened=len(opened), closed=len(closed), still_open=len(still_open))
    incident_lines = [line(f"حوادث ثبت‌شده در بازه: {_fa(len(opened))} مورد.", [i["id"] for i in opened]),
                      line(f"حوادث خاتمه‌یافته در بازه: {_fa(len(closed))} مورد.", [i["id"] for i in closed]),
                      line(f"حوادث باز در پایان شیفت: {_fa(len(still_open))} مورد.", [i["id"] for i in still_open])]
    for severity, label in SEVERITIES.items():
        rows = [i for i in opened if i["severity"] == severity]
        incident_counts[f"severity_{severity}"] = len(rows)
        incident_lines.append(line(f"حوادث ثبت‌شده با اهمیت {label}: {_fa(len(rows))} مورد.", [i["id"] for i in rows]))
    values, measured, samples, cycle_sources = store.cycle_times(_iso(effective_start), _iso(end), include_sources=True)
    for k, label in enumerate(store.CYCLE_STEPS):
        incident_counts[f"cycle_{k}_minutes"] = values[k]
        incident_counts[f"cycle_{k}_samples"] = samples[k]
        text = f"میانگین زمان تا {label}: {_fa(values[k])} دقیقه از {_fa(samples[k])} پرونده." if measured[k] else f"میانگین زمان تا {label}: اندازه‌گیری موجود نیست."
        incident_lines.append(line(text, cycle_sources[k]))
    section("incidents", "حوادث و زمان چرخه", incident_counts, incident_lines)

    # The latest visit may be after the report end; use the journal, never clamp
    # a future visit's age to zero or substitute today's coverage for yesterday.
    coverage_notes = []
    visits = {}
    for id, rows in memory["coverage_visits"].items():
        index = bisect_left(rows, end, key=lambda r: stamp(r["last_visit"]))
        if index:
            visits[id] = rows[index - 1]
    settings_changed = any(e["action"] in ("ورود لایه‌های هوشمندی", "ذخیره تنظیمات نمایشی") and stamp(e["time"]) >= end
                           for e in store.state["audit"])
    available = end > data_since and bool(store.state["intel"].get("coverage")) and not settings_changed
    if start < stamp(memory["history_since"]):
        coverage_notes.append("بخشی از تاریخچه بازدید خارج از دوره نگهداری حافظه‌ای است.")
        available = False
    if not available:
        coverage_notes.append("وضعیت پوشش در پایان این بازه قابل بازسازی نیست؛ مقدار ناموجود جایگزین داده تاریخی نمی‌شود.")
        coverage_counts = dict(percent_ok=None, stale=None, never=None)
        coverage_lines = [line("پوشش پایان شیفت: داده کافی موجود نیست.")]
    else:
        result = coverage.snapshot(_iso(end), visits=visits)
        stale = [r for r in result["items"] if r["status"] == "stale"]
        never = [r for r in result["items"] if r["status"] == "never"]
        coverage_counts = dict(percent_ok=result["totals"]["percent_ok"], stale=len(stale), never=len(never))
        coverage_lines = [line(f"پوشش مناسب در پایان شیفت: {_fa(coverage_counts['percent_ok'])} درصد.", [r["id"] for r in result["items"]]),
                          line(f"موارد با بازدید دیرکرده: {_fa(len(stale))}؛ بدون بازدید ثبت‌شده: {_fa(len(never))}.", [r["id"] for r in stale + never])]
        records = {i["id"]: i for _, i in coverage.coverage_items()}
        for row in stale + never:
            item = records[row["id"]]
            label = item.get("name") or f"قطعه {_fa(item['index'] + 1)} از {item['pipeline_id']}"
            coverage_lines.append(line(f"{label}: {'بازدید دیرکرده' if row['status'] == 'stale' else 'بازدید ثبت نشده'}.", [row["id"], *([row["last_asset_id"]] if row["last_asset_id"] else [])]))
    section("coverage", "پوشش پایان شیفت", coverage_counts, coverage_lines, coverage_notes)

    offline, offline_at_end, unknown = [], [], []
    tracker_start = max(effective_start, stamp(memory["history_since"]))
    for asset in store.state["assets"]:
        history = [r for r in memory["tracker_statuses"].get(asset["id"], []) if stamp(r["time"]) < end] if end > tracker_start else []
        if not history:
            unknown.append(asset)
        else:
            if history[-1]["status"] == "offline":
                offline_at_end.append(asset)
            if any(row["status"] == "offline" and (index + 1 == len(history) or stamp(history[index + 1]["time"]) > tracker_start)
                   for index, row in enumerate(history)) and tracker_start < end:
                offline.append(asset)
    connection_ids = {p["id"] for p in store.state["policies"] if p["condition"] == "connection_lost"}
    alerts = [a for a in store.state["alerts"] if a["policy_id"] in connection_ids and in_window(a["time"])]
    tracker_notes = ["وضعیت بعضی ردیاب‌ها در پایان بازه مشاهده نشده است؛ قطعی از زمان آخرین پیام حدس زده نمی‌شود."] if unknown or start < stamp(memory["history_since"]) else []
    section("trackers", "ردیاب‌های قطع و هشدار ارتباط", dict(offline=len(offline) if not unknown else None, offline_known=len(offline), offline_at_end=len(offline_at_end) if not unknown else None, connection_lost=len(alerts)),
            [line(f"ردیاب‌های با وضعیت قطع ثبت‌شده در بازه: {_fa(len(offline))} مورد.", [a["id"] for a in offline]),
             line(f"ردیاب‌های با وضعیت قطع ثبت‌شده در پایان شیفت: {_fa(len(offline_at_end))} مورد.", [a["id"] for a in offline_at_end]),
             line(f"هشدارهای قطع ارتباط در بازه: {_fa(len(alerts))} مورد.", [a["id"] for a in alerts]),
             *[line(f"ردیاب قطع: {a['name']}.", [a["id"]]) for a in offline]], tracker_notes)

    commands = [c for c in store.state["commands"] if c["status"] == "timed_out" and in_window(c["updated_at"])]
    section("commands", "فرمان‌های بدون پاسخ", dict(timed_out=len(commands)),
            [line(f"فرمان‌های پایان‌یافته بدون پاسخ در بازه: {_fa(len(commands))} مورد.", [c["id"] for c in commands]),
             *[line(f"فرمان {c['id']} برای {c['asset_id']}: مهلت پاسخ پایان یافته است.", [c["id"], c["asset_id"]]) for c in commands]])

    checkpoints = [(m, cp) for m in store.state["missions"] for cp in m["checkpoints"] if in_window(cp.get("due_at"))]
    visited, missed, pending, unrecorded = [], [], [], []
    for mission, cp in checkpoints:
        window = timedelta(minutes=engine.checkpoint_window_minutes(store.state, mission))
        due = stamp(cp["due_at"])
        entry = (mission, cp)
        if cp["visited"] and cp.get("visited_at") and due - window <= stamp(cp["visited_at"]) <= due + window and stamp(cp["visited_at"]) < end:
            visited.append(entry)
        elif cp["visited"] and not cp.get("visited_at"):
            unrecorded.append(entry)
        elif due + window < end:
            missed.append(entry)
        else:
            pending.append(entry)
    compliance_lines = [line(f"ایستگاه‌های سررسیدشده در بازه: {_fa(len(checkpoints))}؛ بازدیدشده: {_fa(len(visited))}؛ ازدست‌رفته: {_fa(len(missed))}؛ مهلت باز در پایان شیفت: {_fa(len(pending))}.", [m["id"] for m, _ in checkpoints])]
    for label, rows in (("بازدیدشده", visited), ("ازدست‌رفته", missed), ("مهلت باز", pending), ("زمان بازدید ناموجود", unrecorded)):
        compliance_lines.extend(line(f"{m['name']} · {cp['name']}: {label}.", [m["id"], *([cp["target_id"]] if cp.get("target_id") else [])]) for m, cp in rows)
    section("compliance", "پایبندی برنامه گشت", dict(due=len(checkpoints), visited=len(visited), missed=len(missed), pending=len(pending), unknown=len(unrecorded)), compliance_lines,
            ["برای بعضی ایستگاه‌ها زمان بازدید ثبت نشده است."] if unrecorded else [])

    confirmations = [e for e in store.state["audit"] if e["action"] == "تأیید سلامت گشت" and in_window(e["time"])]
    escalations = [f for f in store.state["findings"] if f["kind"] == "patrol_safety" and in_window(f["created_at"])]
    section("safety", "ایمنی گشت", dict(confirmed=len(confirmations), escalated=len(escalations)),
            [line(f"دوره‌های ایمنی تأییدشده: {_fa(len(confirmations))} مورد.", [e["id"] for e in confirmations]),
             line(f"دوره‌های ایمنی تشدیدشده: {_fa(len(escalations))} مورد.", [f["id"] for f in escalations])])

    findings = [f for f in store.state["findings"] if in_window(f["created_at"])]
    finding_counts = dict(total=len(findings), shadow=sum(f["mode"] == "shadow" for f in findings))
    finding_lines = [line(f"یافته‌های ثبت‌شده در بازه: {_fa(len(findings))}؛ حالت سایه: {_fa(finding_counts['shadow'])} مورد.", [f["id"] for f in findings])]
    for kind in sorted({f["kind"] for f in findings}):
        rows = [f for f in findings if f["kind"] == kind]
        shadow = sum(f["mode"] == "shadow" for f in rows)
        finding_counts[kind] = len(rows)
        finding_counts[f"{kind}_shadow"] = shadow
        finding_lines.append(line(f"{KINDS.get(kind, kind)}: {_fa(len(rows))} یافته؛ سایه: {_fa(shadow)}؛ فعال: {_fa(len(rows) - shadow)}.", [f["id"] for f in rows]))
    section("findings", "یافته‌ها به تفکیک نوع و حالت", finding_counts, finding_lines)
    headlines = [incident_lines[0], incident_lines[1], incident_lines[2], coverage_lines[0], compliance_lines[0], sections["safety"]["lines"][1]]
    return dict(window_from=_iso(start), window_to=_iso(end), generated_at=now, timezone="Asia/Tehran",
                data_since=store.state["data_since"], data_source_id=epoch_id,
                partial=any(s["partial"] for s in sections.values()), headlines=headlines, sections=sections, can_execute=False)
