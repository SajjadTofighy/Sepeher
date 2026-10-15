"""Phase-zero access invariants with local RSA keys, fake JWKS and injected clocks."""

from datetime import datetime, timezone
import json
import sqlite3

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import store
from app.security import auth
from app.fieldstore import FieldStore, pin_matches
from app.main import app


@pytest.fixture
def verifier(signing_key, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(jwt.api_jwt, "datetime", FixedDateTime)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    key.update(kid="fixture-key", alg="RS256", use="sig")
    clock = [100.0]
    calls = []
    def fetch(url):
        calls.append(url)
        return {"keys": [key]}
    instance = auth.TokenVerifier("https://identity.test/realms/sepehr", fetch=fetch, clock=lambda: clock[0])
    instance.test_clock, instance.test_calls, instance.test_jwk = clock, calls, key
    return instance


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_valid_token_and_claim_scope(verifier, token_factory):
    principal = verifier.verify(token_factory(sub="guard-a", roles=["guard"]))
    assert principal.sub == "guard-a" and principal.username == "guard-a"
    assert principal.roles == ("guard",)
    assert principal.zone_ids == ("Z1",) and principal.contractor_id == "SCHEMATIC"


@pytest.mark.parametrize("changes", [
    {"iss": "https://other.test/realms/sepehr"}, {"aud": "other-api"}, {"azp": "untrusted-client"},
    {"typ": "JWT"}, {"exp": 1}, {"nbf": 4102444800}, {"sub": ""},
    {"groups": ["/contractors/one", "/contractors/two"]}, {"realm_access": {"roles": "admin"}},
])
def test_invalid_claims(verifier, token_factory, changes):
    with pytest.raises(HTTPException) as denied:
        verifier.verify(token_factory(**changes))
    assert denied.value.status_code == 401


@pytest.mark.parametrize("claim", ["exp", "iss", "aud", "sub", "azp", "typ"])
def test_required_claims(verifier, token_factory, signing_key, claim):
    claims = jwt.decode(token_factory(), options={"verify_signature": False})
    del claims[claim]
    token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "fixture-key"})
    with pytest.raises(HTTPException):
        verifier.verify(token)


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_disallowed_algorithms_never_fetch_keys(verifier, token_factory, algorithm):
    claims = jwt.decode(token_factory(), options={"verify_signature": False})
    token = jwt.encode(claims, "" if algorithm == "none" else "test-only-secret", algorithm=algorithm, headers={"kid": "fixture-key"})
    with pytest.raises(HTTPException):
        verifier.verify(token)
    assert verifier.test_calls == []


def test_bad_signature(verifier, token_factory):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = jwt.decode(token_factory(), options={"verify_signature": False})
    token = jwt.encode(claims, other, algorithm="RS256", headers={"kid": "fixture-key"})
    with pytest.raises(HTTPException):
        verifier.verify(token)


def test_unknown_kid_refreshes_once_and_is_rate_limited(verifier, token_factory, signing_key):
    verifier.verify(token_factory())
    verifier.test_clock[0] += 11
    rotated = dict(verifier.test_jwk, kid="rotated")
    fetches = []
    def fetch(url):
        fetches.append(url)
        return {"keys": [verifier.test_jwk, rotated]}
    verifier.fetch = fetch
    claims = jwt.decode(token_factory(), options={"verify_signature": False})
    valid = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "rotated"})
    assert verifier.verify(valid).sub == "operator-a"
    for kid in ["unknown-one", "unknown-two"]:
        token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": kid})
        with pytest.raises(HTTPException):
            verifier.verify(token)
    assert len(fetches) == 1


def test_unavailable_jwks_retains_cached_key(verifier, token_factory, caplog):
    verifier.verify(token_factory())
    verifier.test_clock[0] += 301
    def offline(url):
        raise OSError("offline")
    verifier.fetch = offline
    assert verifier.verify(token_factory()).sub == "operator-a"
    assert "retaining cached" in caplog.text


@pytest.fixture
def client(field_database):
    with TestClient(app) as client:
        yield client


def link_and_enroll(client, token_factory, sub="guard-a", guard_id="AST-009"):
    assert client.put(f"/api/v1/guards/{guard_id}/identity", json={"sub": sub}).status_code == 200
    response = client.post("/api/v1/devices/enrollment-codes", json={"owner_sub": sub}).json()
    token = token_factory(sub=sub, roles=["guard"])
    enrolled = client.post("/api/v1/devices/enroll", headers=bearer(token), json={"code": response["code"], "label": "دستگاه آزمایشی"})
    assert enrolled.status_code == 201, enrolled.text
    return {**bearer(token), "X-Device-Id": enrolled.json()["id"]}, response["code"]


def create_route(client, guard_id="AST-009", zone="Z1", contractor="SCHEMATIC"):
    response = client.post("/api/v1/tour/routes", json={"name": "مسیر آزمایشی", "guard_id": guard_id, "zone_id": zone, "contractor_id": contractor})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_protected_routes_and_explicit_demo(client, monkeypatch):
    for path in ("/tour", "/guards", "/devices", "/media", "/messages", "/reports/tour", "/audit/verify"):
        assert client.get("/api/v1" + path, headers={"Authorization": ""}).status_code == 401
    assert "X-Sepehr-Demo" not in client.get("/api/v1/health").headers
    monkeypatch.setenv("SEPEHR_AUTH_MODE", "demo")
    response = client.get("/api/v1/guards", headers={"Authorization": ""})
    assert response.status_code == 200 and response.headers["X-Sepehr-Demo"] == "1"
    assert client.get("/api/v1/unknown", headers={"Authorization": ""}).headers["X-Sepehr-Demo"] == "1"
    assert client.get("/api/v1/guards", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_enforce_all_switch_and_guard_legacy_denial(client, token_factory, monkeypatch):
    assert client.get("/api/v1/assets", headers={"Authorization": ""}).status_code == 200
    monkeypatch.setenv("SEPEHR_AUTH_ENFORCE_ALL", "true")
    assert client.get("/api/v1/assets", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/v1/assets", headers=bearer(token_factory(roles=["guard"]))).status_code == 403


def test_unlinked_guard_and_admin_only_identity(client, token_factory):
    denied = client.get("/api/v1/tour", headers=bearer(token_factory(sub="unlinked", roles=["guard"])))
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "guard_not_linked"
    assert client.put("/api/v1/guards/AST-009/identity", headers=bearer(token_factory(roles=["shift_supervisor"])), json={"sub": "new"}).status_code == 403
    assert not any(g.get("keycloak_sub") == "unlinked" for g in store.field.records("guards"))
    client.put("/api/v1/guards/AST-009/identity", json={"sub": "private-sub"})
    public_assets = client.get("/api/v1/assets", headers={"Authorization": ""}).json()
    assert all(a["keycloak_sub"] is None for a in public_assets)


def test_guard_scope_and_own_records(client, token_factory):
    headers, _ = link_and_enroll(client, token_factory)
    route_id = create_route(client)
    started = client.post("/api/v1/tour", headers=headers, json={"route_id": route_id})
    assert started.status_code == 201, started.text
    own = started.json()
    for id, zone, contractor, owner in [("other-zone", "Z2", "SCHEMATIC", "guard-a"), ("other-contractor", "Z1", "OTHER", "guard-a"), ("other-owner", "Z1", "SCHEMATIC", "guard-b")]:
        store.field.save("tour", {**own, "id": id, "zone_id": zone, "contractor_id": contractor, "owner_sub": owner})
        assert client.get("/api/v1/tour/" + id, headers=headers).status_code == 403
    listed = client.get("/api/v1/tour?zone_id=Z2&contractor_id=OTHER", headers=headers).json()
    assert [t["id"] for t in listed] == [own["id"]]
    assert [g["id"] for g in client.get("/api/v1/guards", headers=headers).json()] == ["AST-009"]
    for kind, payload in [("messages", {"text": "آزمایش"}), ("media", {"caption": "آزمایش", "media_type": "image"})]:
        assert client.post("/api/v1/" + kind, headers=headers, json={"tour_id": own["id"], **payload}).status_code == 201
        assert client.post("/api/v1/" + kind, headers=headers, json={"tour_id": "other-owner", **payload}).status_code == 403
        assert len(client.get("/api/v1/" + kind, headers=headers).json()) == 1


def test_device_revocation_ownership_one_time_code_and_expiry(client, token_factory, monkeypatch):
    stamp = ["2026-10-08T00:00:00+00:00"]
    monkeypatch.setattr(store, "now", lambda: stamp[0])
    headers, code = link_and_enroll(client, token_factory)
    assert client.post("/api/v1/devices/enroll", headers=headers, json={"code": code, "label": "تکراری"}).status_code == 403
    assert client.get("/api/v1/tour", headers={"Authorization": headers["Authorization"]}).status_code == 401
    client.put("/api/v1/guards/AST-010/identity", json={"sub": "guard-b"})
    other = {**headers, **bearer(token_factory(sub="guard-b", roles=["guard"]))}
    assert client.get("/api/v1/tour", headers=other).status_code == 403
    assert client.post("/api/v1/devices/" + headers["X-Device-Id"] + "/revoke").status_code == 200
    denied = client.get("/api/v1/tour", headers=headers)
    assert denied.status_code == 401 and denied.json()["detail"]["code"] == "device_revoked"
    listed = client.get("/api/v1/devices").json()
    assert all("device_secret" not in d for d in listed)
    expiry = client.post("/api/v1/devices/enrollment-codes", json={"owner_sub": "guard-a", "ttl_seconds": 30}).json()
    stamp[0] = "2026-10-08T00:01:00+00:00"
    assert client.post("/api/v1/devices/enroll", headers=headers, json={"code": expiry["code"], "label": "منقضی"}).status_code == 403


def test_checkin_pin_hash_duress_and_rate_limit(client, token_factory, monkeypatch):
    monkeypatch.setattr(store, "now", lambda: "2026-10-08T00:00:00+00:00")
    headers, _ = link_and_enroll(client, token_factory)
    assert client.put("/api/v1/guards/AST-009/credentials", json={"pin": "123456", "duress_pin": "654321"}).status_code == 200
    route = create_route(client)
    tour = client.post("/api/v1/tour", headers=headers, json={"route_id": route}).json()
    path = "/api/v1/tour/" + tour["id"] + "/check-in"
    normal = client.post(path, headers=headers, json={"pin": "123456"})
    duress = client.post(path, headers=headers, json={"pin": "654321"})
    assert normal.status_code == duress.status_code == 201
    assert normal.json().keys() == duress.json().keys() and "duress" not in json.dumps(duress.json())
    with store.field.connection() as db:
        credential = dict(db.execute("SELECT * FROM guard_credentials").fetchone())
    assert pin_matches("123456", credential["pin_hash"])
    assert "123456" not in credential["pin_hash"]
    assert "654321" not in json.dumps(store.field.audits())
    for _ in range(5):
        assert client.post(path, headers=headers, json={"pin": "000000"}).status_code == 403
    assert client.post(path, headers=headers, json={"pin": "123456"}).status_code == 429


def test_two_person_approval_classification_and_replay(client, token_factory):
    original = client.get("/api/v1/settings").json()
    assert client.put("/api/v1/settings", json={**original, "classification_label": "جدید"}).status_code == 409
    request = client.post("/api/v1/approvals", json={"action": "change_classification", "target_id": "SETTINGS", "classification_label": "خیلی محرمانه"}).json()
    path = "/api/v1/approvals/" + request["id"] + "/approve"
    same = client.post(path)
    assert same.status_code == 403 and same.json()["detail"]["code"] == "two_person_required"
    second = bearer(token_factory(sub="operator-b", roles=["admin"]))
    assert client.post(path, headers=second).status_code == 200
    assert client.post(path, headers=second).status_code == 409
    assert client.get("/api/v1/settings").json()["classification_label"] == "خیلی محرمانه"
    assert client.get("/api/v1/health").headers["X-Classification"].startswith("UTF-8''")
    assert {a["sub"] for a in store.field.audits() if a["target"] == request["id"]} == {"operator-a", "operator-b"}


def test_sensitive_target_changes_and_stale_approvals(client, token_factory):
    second = bearer(token_factory(sub="operator-b"))
    tag = client.post("/api/v1/tour/tags", json={"label": "تگ آزمایشی", "zone_id": "Z1", "contractor_id": "SCHEMATIC"}).json()
    requests = [client.post("/api/v1/approvals", json={"action": "rotate_tag_key", "target_id": tag["id"]}).json() for _ in range(2)]
    old_key = store.field.get("tags", tag["id"])["key"]
    assert client.post("/api/v1/approvals/" + requests[0]["id"] + "/approve", headers=second).status_code == 200
    updated = store.field.get("tags", tag["id"])
    assert updated["key_version"] == 2 and updated["key"] != old_key
    assert client.post("/api/v1/approvals/" + requests[1]["id"] + "/approve", headers=second).status_code == 409
    revoke = client.post("/api/v1/approvals", json={"action": "revoke_tag", "target_id": tag["id"]}).json()
    assert client.post("/api/v1/approvals/" + revoke["id"] + "/approve", headers=second).status_code == 200
    assert store.field.get("tags", tag["id"])["status"] == "revoked"
    route = create_route(client)
    delete = client.post("/api/v1/approvals", json={"action": "delete_route", "target_id": route}).json()
    assert client.post("/api/v1/approvals/" + delete["id"] + "/approve", headers=second).status_code == 200
    assert store.field.get("routes", route) is None
    assert "key" not in client.get("/api/v1/tour/tags/list").json()[0]


def test_audit_append_only_tampering_persistence_and_identity_reassignment(client, token_factory, field_database, monkeypatch):
    headers, _ = link_and_enroll(client, token_factory)
    route = create_route(client)
    tour = client.post("/api/v1/tour", headers=headers, json={"route_id": route}).json()
    assert client.get("/api/v1/audit/verify").json()["valid"]
    with store.field.connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE audit SET hash='tampered'")
    restored = FieldStore(field_database.path)
    monkeypatch.setattr(store, "field", restored)
    store.state["field_tour"] = []
    store.restore_field_state()
    assert store.state["field_tour"][0]["id"] == tour["id"]
    assert store.lookup("assets", "AST-009")["keycloak_sub"] == "guard-a"
    assert restored.device(headers["X-Device-Id"])["status"] == "active"
    assert restored.verify_audit()
    assert client.put("/api/v1/guards/AST-009/identity", json={"sub": "new-identity"}).status_code == 200
    assert restored.device(headers["X-Device-Id"])["status"] == "revoked"
    with restored.connection() as db:
        db.execute("DROP TRIGGER audit_no_update")
        db.execute("UPDATE audit SET payload=? WHERE sequence=1", (json.dumps({"tampered": True}),))
    assert not client.get("/api/v1/audit/verify").json()["valid"]


def test_auditor_only_verification_and_exports_are_audited(client, token_factory):
    staff = bearer(token_factory(roles=["admin"]))
    assert client.get("/api/v1/audit/verify", headers=staff).status_code == 403
    assert client.get("/api/v1/audit/role-changes", headers=staff).status_code == 403
    result = client.post("/api/v1/exports", json={"name": "report.json"})
    assert result.status_code == 200
    assert store.field.audits()[-1]["id"] == result.json()["audit_id"]
    guard = bearer(token_factory(roles=["guard"]))
    assert client.post("/api/v1/exports", headers=guard, json={"name": "report.json"}).status_code == 403


def test_role_changes_from_service_client_are_filtered_and_audited(client, monkeypatch):
    from app.routers import field
    monkeypatch.setenv("SEPEHR_OIDC_INTERNAL_ISSUER", "https://internal.test/realms/sepehr")
    monkeypatch.setenv("SEPEHR_AUDIT_CLIENT_SECRET", "test-only-secret")
    requests = []
    class Response:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(self.data).encode()
    def open_url(req, timeout):
        requests.append(req)
        if len(requests) == 1:
            return Response({"access_token": "service-token"})
        return Response([{"time": 0, "operationType": "CREATE", "resourcePath": "users/user-a/role-mappings/realm", "authDetails": {"userId": "admin-a"}},
                         {"time": 0, "operationType": "UPDATE", "resourcePath": "users/user-b", "authDetails": {}}])
    monkeypatch.setattr(field, "urlopen", open_url)
    result = client.get("/api/v1/audit/role-changes")
    assert result.status_code == 200 and len(result.json()) == 1
    assert result.json()[0]["actor_id"] == "admin-a"
    assert requests[1].get_header("Authorization") == "Bearer service-token"
    assert store.field.audits()[-1]["target"] == "KEYCLOAK-ADMIN-EVENTS"


def test_demo_metadata_on_internal_errors(client, monkeypatch):
    import app.main as main
    monkeypatch.setenv("SEPEHR_AUTH_MODE", "demo")
    def failed():
        raise RuntimeError("test-only failure")
    monkeypatch.setattr(main, "refresh_tracks", failed)
    result = client.get("/api/v1/assets", headers={"Authorization": ""})
    assert result.status_code == 500 and result.headers["X-Sepehr-Demo"] == "1"
    assert result.json()["detail"]["code"] == "internal_error"
    assert "test-only failure" not in result.text
