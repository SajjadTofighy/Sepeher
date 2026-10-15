import os
import sys
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Keep import-time initialization away from the operator's persistent database.
_database_dir = tempfile.TemporaryDirectory(prefix="sepehr-tests-")
os.environ["SEPEHR_TRACK_DB"] = str(Path(_database_dir.name) / "initial.sqlite3")
os.environ["SEPEHR_WORKER"] = "0"
os.environ["SEPEHR_FIELD_DB"] = str(Path(_database_dir.name) / "field.sqlite3")

@pytest.fixture(autouse=True)
def track_database(tmp_path, monkeypatch):
    from app import store
    from app.seed import seed
    from app.tracks import TrackStore
    repository = TrackStore(tmp_path / "tracks.sqlite3")
    repository.seed_missing(seed()["assets"])
    monkeypatch.setattr(store, "tracks", repository)
    return repository


@pytest.fixture(scope="session")
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def token_factory(signing_key):
    import jwt
    def make(sub="operator-a", roles=None, groups=None, **changes):
        claims = dict(sub=sub, preferred_username=sub, iss="https://identity.test/realms/sepehr",
                      aud="sepehr-api", azp="sepehr-web", typ="Bearer", exp=4102444800, nbf=0,
                      realm_access={"roles": roles if roles is not None else ["admin", "auditor", "security_manager"]},
                      groups=groups if groups is not None else ["/zones/Z1", "/contractors/SCHEMATIC"])
        claims.update(changes)
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "fixture-key"})
    return make


@pytest.fixture(autouse=True)
def authenticated_client(monkeypatch, signing_key, token_factory):
    import json
    import jwt
    from fastapi.testclient import TestClient
    from app.security import auth
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update(kid="fixture-key", alg="RS256", use="sig")
    verifier = auth.TokenVerifier("https://identity.test/realms/sepehr", fetch=lambda url: {"keys": [jwk]})
    monkeypatch.setattr(auth, "get_verifier", lambda: verifier)
    monkeypatch.setenv("SEPEHR_AUTH_MODE", "keycloak")
    monkeypatch.setenv("SEPEHR_AUTH_ENFORCE_ALL", "false")
    monkeypatch.setenv("SEPEHR_GIS_ORIGINS", "https://gis.example.org")
    original = TestClient.__init__
    def initialize(self, *args, **kwargs):
        kwargs["headers"] = {"Authorization": "Bearer " + token_factory(), **(kwargs.get("headers") or {})}
        original(self, *args, **kwargs)
    monkeypatch.setattr(TestClient, "__init__", initialize)
    return verifier


@pytest.fixture(autouse=True)
def field_database(tmp_path, monkeypatch, track_database):
    from app import store
    from app.security import hardening
    from app.fieldstore import FieldStore
    from app.seed import seed
    hardening.limiter.reset()
    repository = FieldStore(tmp_path / "field.sqlite3")
    monkeypatch.setattr(store, "field", repository)
    store.state.clear()
    store.state.update(seed())
    store.restore_field_state()
    return repository
