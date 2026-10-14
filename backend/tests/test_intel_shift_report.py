"""Shift boundaries and aggregates use an injected clock, never fabricated history."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main, sim, store
from app.intel import coverage, shift_report, worker
from app.models import RuntimeSettings, ShiftReport
from app.seed import seed


@pytest.fixture
def case(track_database, monkeypatch):
    start = datetime(2099, 1, 1, 2, 30, tzinfo=timezone.utc)  # Tehran 06:00
    clock = SimpleNamespace(t=start.timestamp())
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    monkeypatch.setattr(main, "now", lambda: sim.iso(clock.t))
    store.state.clear()
    store.state.update(seed())
    store.state.update(incidents=[], missions=[], policies=[], alerts=[], findings=[], commands=[], audit=[])
    store.state["assets"] = store.state["assets"][:2]
    store.state["assets"][0]["status"] = "online"
    store.state["assets"][1]["status"] = "offline"
    store.state["segments"] = []
    facility = deepcopy(store.state["facilities"][0])
    store.state["facilities"] = [facility]
    store.begin_data_epoch()
    clock.t += 9 * 3600
    return SimpleNamespace(clock=clock, start=start, end=start + timedelta(hours=8), facility=facility,
                           asset=store.state["assets"][0], client=TestClient(main.app))


def report(case):
    result = shift_report.snapshot(case.start, case.end)
    ShiftReport.model_validate(result)
    return result


def incident(id, created, closed=None, severity="high"):
    timeline = [] if closed is None else [dict(time=closed.isoformat(), action="خاتمه حادثه", actor="اپراتور")]
    row = dict(id=id, created_at=created.isoformat(), severity=severity, status="closed" if closed else "detected", timeline=timeline)
    store.state["incidents"].append(row)
    return row


def visit(case, at):
    coverage._record_visit(case.facility, dict(time=at.isoformat(), lon=case.facility["lon"], lat=case.facility["lat"]), case.asset["id"], store.now())


def test_last_completed_shift_and_midnight(case):
    a, b = shift_report.last_completed_shift(case.end.isoformat())
    assert (a.hour, b.hour) == (6, 14)
    assert a.astimezone(timezone.utc) == case.start
    # At 05:59 the 22–06 shift is not completed; at 06:00 it is.
    local = datetime(2099, 1, 2, 6, tzinfo=shift_report.engine.TEHRAN)
    a, b = shift_report.last_completed_shift((local - timedelta(minutes=1)).isoformat())
    assert (a.hour, b.hour) == (14, 22)
    a, b = shift_report.last_completed_shift(local.isoformat())
    assert (a.hour, b.hour) == (22, 6) and b.date() > a.date()
    assert (b - a).total_seconds() == 8 * 3600
    case.clock.t = local.timestamp()
    response = case.client.get("/api/v1/reports/shift")
    assert response.status_code == 200
    assert response.json()["window_to"] == local.astimezone(timezone.utc).isoformat()


def test_incidents_boundary_cycle_and_severity(case):
    before = case.start - timedelta(hours=1)
    incident("INC-BEFORE", before, case.start + timedelta(minutes=30))
    incident("INC-START", case.start, case.end + timedelta(minutes=1), "critical")
    incident("INC-END", case.end)
    incident("INC-CLOSED-AT-END", before, case.end)
    result = report(case)
    counts = result["sections"]["incidents"]["counts"]
    assert (counts["opened"], counts["closed"], counts["still_open"]) == (1, 1, 2)
    assert counts["severity_critical"] == 1 and counts["severity_high"] == 0
    assert counts["cycle_3_minutes"] == 90 and counts["cycle_3_samples"] == 1
    assert counts["cycle_0_minutes"] is None
    assert store.cycle_times()[0][0] == store.BASELINE_CYCLE[0]
    assert result["sections"]["incidents"]["lines"][2]["source_ids"] == ["INC-START", "INC-CLOSED-AT-END"]


def test_all_sections_count_existing_facts_and_sources(case):
    when = case.start + timedelta(hours=1)
    visit(case, when)
    offline = store.state["assets"][1]
    store.state["policies"] = [dict(id="P-CONNECTION", condition="connection_lost")]
    store.state["alerts"] = [dict(id="ALR-WINDOW", policy_id="P-CONNECTION", time=when.isoformat()),
                             dict(id="ALR-END", policy_id="P-CONNECTION", time=case.end.isoformat())]
    store.state["commands"] = [dict(id="CMD-TIMEOUT", asset_id=offline["id"], status="timed_out", updated_at=when.isoformat()),
                               dict(id="CMD-LATE", status="timed_out", updated_at=case.end.isoformat())]
    store.state["missions"] = [dict(id="MSN-TEST", name="گشت آزمون", asset_id=case.asset["id"], status="active", progress=0,
                                   checkpoints=[dict(name="رسیده", target_id=case.facility["id"], due_at=when.isoformat(), visited=True, visited_at=when.isoformat()),
                                                dict(name="نرسیده", due_at=when.isoformat(), visited=False),
                                                dict(name="مهلت باز", due_at=(case.end - timedelta(minutes=10)).isoformat(), visited=False),
                                                dict(name="قدیمی", visited=False)])]
    store.state["findings"] = [dict(id="FND-SAFETY", kind="patrol_safety", mode="shadow", created_at=when.isoformat()),
                               dict(id="FND-COVERAGE", kind="coverage_gap", mode="active", created_at=when.isoformat()),
                               dict(id="FND-END", kind="coverage_gap", mode="shadow", created_at=case.end.isoformat())]
    case.clock.t = when.timestamp()
    confirm = store.audit("تأیید سلامت گشت", case.asset["id"])
    case.clock.t = (case.end + timedelta(hours=1)).timestamp()
    result = report(case)
    sections = result["sections"]
    assert sections["coverage"]["counts"] == dict(percent_ok=100, stale=0, never=0)
    assert sections["trackers"]["counts"] == dict(offline=1, offline_known=1, offline_at_end=1, connection_lost=1)
    assert sections["commands"]["counts"]["timed_out"] == 1
    assert sections["compliance"]["counts"] == dict(due=3, visited=1, missed=1, pending=1, unknown=0)
    assert sections["safety"]["counts"] == dict(confirmed=1, escalated=1)
    assert sections["safety"]["lines"][0]["source_ids"] == [confirm["id"]]
    assert sections["findings"]["counts"] == dict(total=2, shadow=1, coverage_gap=1, coverage_gap_shadow=0, patrol_safety=1, patrol_safety_shadow=1)
    actual_ids = {row["id"] for key in ("incidents", "assets", "facilities", "segments", "missions", "alerts", "commands", "findings", "audit") for row in store.state[key]}
    for line in result["headlines"] + [line for s in sections.values() for line in s["lines"]]:
        assert line["text"] and line["source_ids"] and set(line["source_ids"]) <= actual_ids
    assert result["can_execute"] is False
    assert not result["partial"]


def test_coverage_and_offline_reconstructed_at_end_not_today(case):
    visit(case, case.end - timedelta(hours=13))
    visit(case, case.end + timedelta(minutes=1))
    store.state["assets"][1]["status"] = "online"
    shift_report.observe_trackers((case.end + timedelta(minutes=1)).isoformat())
    result = report(case)
    assert result["sections"]["coverage"]["counts"] == dict(percent_ok=0, stale=1, never=0)
    assert result["sections"]["trackers"]["counts"]["offline"] == 1
    assert coverage.snapshot(store.now())["totals"]["percent_ok"] == 100
    store.state["report_history"]["coverage_visits"].clear()
    assert report(case)["sections"]["coverage"]["counts"]["never"] == 1


def test_late_checkpoint_visit_does_not_rewrite_shift_end(case):
    due = case.end - timedelta(hours=1)
    store.state["missions"] = [dict(id="MSN-LATE", name="گشت", checkpoints=[
        dict(name="ایستگاه", due_at=due.isoformat(), visited=True, visited_at=(case.end + timedelta(minutes=1)).isoformat())])]
    counts = report(case)["sections"]["compliance"]["counts"]
    assert counts["missed"] == 1 and counts["visited"] == 0


def test_data_since_partial_reset_and_no_invented_history(case):
    case.clock.t = (case.start + timedelta(hours=2)).timestamp()
    store.state.pop("report_history", None)
    store.begin_data_epoch()
    case.clock.t = (case.end + timedelta(hours=1)).timestamp()
    incident("INC-UNOBSERVED", case.start)
    incident("INC-OBSERVED", case.end - timedelta(hours=1))
    result = report(case)
    assert result["data_since"] == (case.start + timedelta(hours=2)).isoformat()
    assert result["partial"] and all(s["partial"] and s["notes"] for s in result["sections"].values())
    assert result["sections"]["incidents"]["counts"]["opened"] == 1
    case.client.post("/api/v1/demo/reset")
    result = report(case)
    assert result["data_since"] == store.now()
    assert result["sections"]["coverage"]["counts"]["percent_ok"] is None
    assert result["sections"]["incidents"]["counts"]["opened"] == 0
    assert result["sections"]["incidents"]["counts"]["still_open"] == 0


def test_shift_boundary_audit_once_with_worker_and_midnight(case, monkeypatch):
    # Existing detectors need not run to verify the worker's reporting hook.
    monkeypatch.setattr(store, "refresh_tracks", lambda **kw: None)
    monkeypatch.setattr(store, "evaluate_policies", lambda *args, **kw: None)
    for capability in worker.capabilities:
        monkeypatch.setattr(capability, "tick", lambda now: None)
    local_end = datetime(2099, 1, 2, 6, tzinfo=shift_report.engine.TEHRAN)
    case.clock.t = (local_end - timedelta(seconds=1)).timestamp()
    store.state["report_history"]["cursor"] = store.now()
    worker.tick(store.now())
    case.clock.t = local_end.timestamp()
    worker.tick(store.now())
    worker.tick(store.now())
    case.clock.t += 1
    worker.tick(store.now())
    entries = [e for e in store.state["audit"] if e["action"] == "تولید گزارش شیفت"]
    assert len(entries) == 1
    a, b = shift_report.last_completed_shift(local_end.isoformat())
    assert entries[0]["detail"] == f"{a.astimezone(timezone.utc).isoformat()}/{b.astimezone(timezone.utc).isoformat()}"
    assert not any("sections" in value for value in store.state["report_history"].values() if isinstance(value, dict))


def test_api_validation_settings_and_assistant(case):
    assert case.client.get("/api/v1/reports/shift", params={"from": case.start.isoformat()}).status_code == 422
    assert case.client.get("/api/v1/reports/shift", params={"from": case.end.isoformat(), "to": case.start.isoformat()}).status_code == 422
    assert case.client.get("/api/v1/reports/shift", params={"from": "2099-01-01T06:00:00", "to": case.end.isoformat()}).status_code == 422
    assert case.client.get("/api/v1/reports/shift", params={"from": case.start.isoformat(), "to": sim.iso(case.clock.t + 1)}).status_code == 422
    assert RuntimeSettings(intel_shifts=["۲۲:۰۰-۰۶:۰۰"]).intel_shifts == ["22:00–06:00"]
    with pytest.raises(ValidationError):
        RuntimeSettings(intel_shifts=["25:00–06:00"])
    answer = case.client.post("/api/v1/assistant", json={"question": "گزارش شیفت و پوشش"}).json()
    assert "حوادث ثبت‌شده" in answer["answer"] and answer["sources"] and not answer["can_execute"]


def test_recovered_tracker_still_counted_in_window(case):
    case.asset["status"] = "offline"
    shift_report.observe_trackers((case.start + timedelta(minutes=10)).isoformat())
    case.asset["status"] = "online"
    shift_report.observe_trackers((case.start + timedelta(minutes=20)).isoformat())
    counts = report(case)["sections"]["trackers"]["counts"]
    assert counts["offline"] == 2 and counts["offline_at_end"] == 1


def test_backfill_order_and_unknown_coverage_after_settings_change(case):
    # Different patrol streams can be backfilled out of global time order.
    visit(case, case.end + timedelta(minutes=10))
    visit(case, case.end - timedelta(hours=13))
    assert report(case)["sections"]["coverage"]["counts"]["stale"] == 1
    store.audit("ذخیره تنظیمات نمایشی", "SETTINGS")
    section = report(case)["sections"]["coverage"]
    assert section["partial"] and section["counts"]["percent_ok"] is None
    assert section["notes"]


def test_multiple_boundaries_and_retention_do_not_store_reports(case):
    case.clock.t = (case.start + timedelta(hours=25)).timestamp()
    shift_report.tick(store.now())
    first = [e for e in store.state["audit"] if e["action"] == "تولید گزارش شیفت"]
    assert len(first) == 3
    shift_report.tick(store.now())
    assert [e for e in store.state["audit"] if e["action"] == "تولید گزارش شیفت"] == first
    # Observed facts have bounded retention; old reports explicitly become partial.
    visit(case, case.start + timedelta(hours=1))
    store.state["settings"]["retention_days"] = 7
    case.clock.t = (case.start + timedelta(days=9)).timestamp()
    shift_report.tick(store.now())
    section = report(case)["sections"]["coverage"]
    assert section["partial"] and section["counts"]["percent_ok"] is None
