"""Spatial mission commands: recipient snapshot, receipt chain, idempotency, expiry, scope and durability."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import store
from app.core.fieldstore import FieldStore
from app.main import app
from test_auth_access import bearer, link_and_enroll

AREA = dict(type="Polygon", coordinates=[[[49.70, 30.70], [49.72, 30.70], [49.72, 30.72], [49.70, 30.72], [49.70, 30.70]]])


@pytest.fixture
def ops(monkeypatch, token_factory):
    clock = dict(now=datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(store, "now", lambda: clock["now"].isoformat())
    with TestClient(app) as client:
        client.post("/api/v1/demo/reset")
        guards = {}
        for sub, asset in (("guard-a", "AST-009"), ("guard-b", "AST-010"), ("guard-c", "AST-011")):
            guards[asset], _ = link_and_enroll(client, token_factory, sub=sub, guard_id=asset)
        client.clock = clock
        client.guards = guards
        yield client


def place(client, asset, lon, lat):
    point = dict(lon=lon, lat=lat, time=(client.clock["now"] - timedelta(seconds=10)).isoformat(), accuracy_m=5)
    assert client.post(f"/api/v1/assets/{asset}/positions", json=point).status_code == 201


def preview(client, geometry=AREA, radius_m=0):
    response = client.post("/api/v1/mission-commands/preview", json=dict(geometry=geometry, radius_m=radius_m))
    assert response.status_code == 200, response.text
    return response.json()


def send(client, recipients, key="cmd-key-0001", type="visit_point", ttl=15, snapshot=None, **extra):
    body = dict(idempotency_key=key, type=type, title="بازدید از حصار شمالی", instructions="بررسی آسیب حصار",
                geometry=AREA, recipients=recipients, snapshot_id=snapshot or preview(client)["snapshot_id"],
                ack_ttl_minutes=ttl, **extra)
    return client.post("/api/v1/mission-commands", json=body)


def act(client, asset, id, action, event_id, note=""):
    return client.post(f"/api/v1/tour/mission-commands/{id}/events", headers=client.guards[asset],
                       json=dict(event_id=event_id, action=action, note=note))


def test_preview_separates_fresh_inside_from_stale_outside_and_unreachable(ops):
    place(ops, "AST-009", 49.71, 30.71)
    place(ops, "AST-011", 49.80, 30.80)
    result = preview(ops)
    assert [r["asset_id"] for r in result["eligible"]] == ["AST-009"] and result["eligible"][0]["inside"]
    assert [r["asset_id"] for r in result["outside"]] == ["AST-011"] and result["outside"][0]["distance_m"] > 1000
    review = {r["asset_id"]: r for r in result["needs_review"]}
    assert "AST-010" in review and review["AST-010"]["position_state"] in ("simulated", "unknown", "stale")
    assert all(not r["can_receive"] for r in result["cannot_receive"]) and any(r["asset_id"] == "AST-001" for r in result["cannot_receive"])
    # A stale position is never counted as inside, even if its last coordinates are in the area.
    ops.clock["now"] += timedelta(minutes=30)
    later = preview(ops)
    assert "AST-009" in [r["asset_id"] for r in later["needs_review"]] and later["snapshot_id"] != result["snapshot_id"]
    line = preview(ops, dict(type="LineString", coordinates=[[49.70, 30.71], [49.72, 30.71]]), radius_m=50)
    assert line["eligible"] == []  # nobody has a fresh position any more
    with pytest.raises(AssertionError):
        preview(ops, dict(type="Polygon", coordinates=[[[49.7, 30.7], [49.7, 30.7], [49.7, 30.7]]]))


def test_send_is_idempotent_and_rejects_changed_recipients(ops):
    place(ops, "AST-009", 49.71, 30.71)
    snapshot = preview(ops)["snapshot_id"]
    first = send(ops, ["AST-009", "AST-010"], snapshot=snapshot)
    assert first.status_code == 201, first.text
    command = first.json()
    assert command["status"] == "dispatched" and command["can_execute"] is False
    assert {r["asset_id"]: r["snapshot"]["position_state"] for r in command["recipients"]}["AST-009"] == "fresh"
    again = send(ops, ["AST-009", "AST-010"], snapshot=snapshot)
    assert again.status_code == 200 and again.json()["id"] == command["id"]
    assert len(ops.get("/api/v1/mission-commands").json()) == 1
    assert send(ops, ["AST-009"], snapshot=snapshot).status_code == 409  # same key, different order
    place(ops, "AST-011", 49.711, 30.711)  # someone entered the area after the preview
    changed = send(ops, ["AST-009"], key="cmd-key-0002", snapshot=snapshot)
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "recipients_changed"
    assert "AST-011" in [r["asset_id"] for r in changed.json()["detail"]["preview"]["eligible"]]
    assert send(ops, ["AST-001"], key="cmd-key-0003").status_code == 422  # a vehicle has no field app


def test_receipt_chain_double_tap_and_one_of_completion(ops):
    place(ops, "AST-009", 49.71, 30.71)
    command = send(ops, ["AST-009", "AST-010"]).json()
    # Stored on the server is not "seen": delivery is recorded only when the device fetches it.
    assert all(r["status"] == "dispatched" for r in command["recipients"])
    inbox = ops.get("/api/v1/tour/mission-commands", headers=ops.guards["AST-009"]).json()
    assert len(inbox) == 1 and [r["asset_id"] for r in inbox[0]["recipients"]] == ["AST-009"]
    mine = inbox[0]["recipients"][0]
    assert mine["status"] == "delivered" and mine["delivered_device_id"] == ops.guards["AST-009"]["X-Device-Id"]
    assert act(ops, "AST-009", command["id"], "start", "evt-start-0").status_code == 409  # not acknowledged yet
    assert act(ops, "AST-009", command["id"], "acknowledge", "evt-ack-001").status_code == 200
    # Double tap / offline resend of the same act is a no-op, not a second transition.
    repeat = act(ops, "AST-009", command["id"], "acknowledge", "evt-ack-001")
    assert repeat.status_code == 200
    detail = ops.get(f"/api/v1/mission-commands/{command['id']}").json()
    assert sum(e["event_id"] == "evt-ack-001" for e in detail["timeline"]) == 1 and detail["status"] == "acknowledged"
    assert act(ops, "AST-009", command["id"], "complete", "evt-done-01", note="x").status_code == 422
    done = act(ops, "AST-009", command["id"], "complete", "evt-done-01", note="حصار سالم است")
    assert done.status_code == 200 and done.json()["status"] == "completed"
    final = ops.get(f"/api/v1/mission-commands/{command['id']}").json()
    statuses = {r["asset_id"]: r["status"] for r in final["recipients"]}
    assert statuses == {"AST-009": "completed", "AST-010": "cancelled"}  # one completion closes a visit order
    audit = [e["action"] for e in store.state["audit"]]
    assert "پذیرش مأموریت" in audit and "تکمیل مأموریت" in audit
    assert store.state["audit"] == store.field.audits() and store.field.verify_audit()


def test_presence_requires_each_recipient(ops):
    command = send(ops, ["AST-009", "AST-010"], type="presence").json()
    for asset, tag in (("AST-009", "a"), ("AST-010", "b")):
        assert act(ops, asset, command["id"], "acknowledge", f"evt-ack-{tag}-1").status_code == 200
    assert act(ops, "AST-009", command["id"], "complete", "evt-done-a1", note="حاضرم در محل").status_code == 200
    middle = ops.get(f"/api/v1/mission-commands/{command['id']}").json()
    assert middle["status"] == "acknowledged" and {r["status"] for r in middle["recipients"]} == {"completed", "acknowledged"}
    assert act(ops, "AST-010", command["id"], "complete", "evt-done-b1", note="حاضرم در محل").json()["status"] == "completed"


def test_expiry_and_late_receipt_never_revive_a_closed_order(ops):
    command = send(ops, ["AST-009"], ttl=5).json()
    ops.clock["now"] += timedelta(minutes=6)
    expired = ops.get(f"/api/v1/mission-commands/{command['id']}").json()
    assert expired["status"] == "expired" and expired["recipients"][0]["status"] == "expired"
    late = act(ops, "AST-009", command["id"], "acknowledge", "evt-late-01")
    assert late.status_code == 409 and late.json()["detail"]["code"] == "command_closed"
    after = ops.get(f"/api/v1/mission-commands/{command['id']}").json()
    record = next(e for e in after["timeline"] if e["event_id"] == "evt-late-01")
    assert record["applied"] is False and after["status"] == "expired"
    # Accepted work is not expired by the acknowledgement deadline.
    accepted = send(ops, ["AST-009"], key="cmd-key-0004", ttl=5).json()
    assert act(ops, "AST-009", accepted["id"], "acknowledge", "evt-ack-002").status_code == 200
    ops.clock["now"] += timedelta(minutes=6)
    assert ops.get(f"/api/v1/mission-commands/{accepted['id']}").json()["status"] == "acknowledged"


def test_cancel_uses_revision_and_rejections_need_reasons(ops):
    command = send(ops, ["AST-009", "AST-010"]).json()
    assert act(ops, "AST-010", command["id"], "reject", "evt-rej-001", note="").status_code == 422
    assert act(ops, "AST-010", command["id"], "reject", "evt-rej-001", note="در مأموریت دیگری هستم").status_code == 200
    current = ops.get(f"/api/v1/mission-commands/{command['id']}").json()
    stale = ops.post(f"/api/v1/mission-commands/{command['id']}/cancel", json=dict(reason="لغو آزمون", revision=command["revision"]))
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "revision_conflict"
    cancelled = ops.post(f"/api/v1/mission-commands/{command['id']}/cancel", json=dict(reason="لغو آزمون", revision=current["revision"]))
    assert cancelled.status_code == 200
    assert {r["asset_id"]: r["status"] for r in cancelled.json()["recipients"]} == {"AST-009": "cancelled", "AST-010": "rejected"}
    assert cancelled.json()["status"] == "cancelled"
    assert ops.post(f"/api/v1/mission-commands/{command['id']}/cancel", json=dict(reason="دوباره", revision=cancelled.json()["revision"])).status_code == 409


def test_scope_roles_and_non_recipients(ops, token_factory):
    command = send(ops, ["AST-009"]).json()
    assert act(ops, "AST-010", command["id"], "acknowledge", "evt-other-1").status_code == 403
    assert ops.post("/api/v1/mission-commands/preview", headers=ops.guards["AST-009"],
                    json=dict(geometry=AREA)).status_code == 403
    other_zone = bearer(token_factory(sub="sup-z2", roles=["shift_supervisor"], groups=["/zones/Z2", "/contractors/SCHEMATIC"]))
    assert ops.get(f"/api/v1/mission-commands/{command['id']}", headers=other_zone).status_code == 403
    assert ops.get("/api/v1/mission-commands", headers=other_zone).json() == []
    assert all(r["asset_id"] != "AST-009" for group in ("eligible", "needs_review", "outside")
               for r in ops.post("/api/v1/mission-commands/preview", headers=other_zone, json=dict(geometry=AREA)).json()[group])


def test_failed_write_rolls_back_command_and_audit_together(ops, monkeypatch):
    command = send(ops, ["AST-009"]).json()
    before_audit = list(store.state["audit"])
    original = store.field.save

    def broken(kind, item):
        if kind == "mission_commands":
            raise RuntimeError("disk full")
        return original(kind, item)

    monkeypatch.setattr(store.field, "save", broken)
    assert act(ops, "AST-009", command["id"], "acknowledge", "evt-ack-003").status_code == 500
    monkeypatch.setattr(store.field, "save", original)
    stored = store.field.get("mission_commands", command["id"])
    assert stored["recipients"][0]["status"] == "dispatched" and stored["revision"] == command["revision"]
    assert store.state["audit"] == before_audit == store.field.audits()
    assert act(ops, "AST-009", command["id"], "acknowledge", "evt-ack-003").status_code == 200  # retry succeeds


def test_commands_survive_restart(ops, field_database):
    command = send(ops, ["AST-009"]).json()
    assert act(ops, "AST-009", command["id"], "acknowledge", "evt-ack-004").status_code == 200
    reopened = FieldStore(field_database.path)
    assert reopened.get("mission_commands", command["id"])["recipients"][0]["status"] == "acknowledged"
    assert ops.post("/api/v1/demo/reset").status_code == 200
    assert ops.get(f"/api/v1/mission-commands/{command['id']}").json()["status"] == "acknowledged"
