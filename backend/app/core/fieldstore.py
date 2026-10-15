"""Durable field operations, numbered migrations and append-only audit."""

from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pin_hash(value):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1)
    return canonical({"salt": salt.hex(), "hash": digest.hex()})


def pin_matches(value, encoded):
    data = json.loads(encoded)
    digest = hashlib.scrypt(value.encode(), salt=bytes.fromhex(data["salt"]), n=16384, r=8, p=1)
    return hmac.compare_digest(digest.hex(), data["hash"])


MIGRATIONS = (
    (
        "CREATE TABLE entities (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))",
        "CREATE TABLE guard_links (guard_id TEXT PRIMARY KEY, sub TEXT NOT NULL UNIQUE)",
        "CREATE TABLE guard_credentials (sub TEXT PRIMARY KEY REFERENCES guard_links(sub), pin_hash TEXT NOT NULL, duress_pin_hash TEXT NOT NULL)",
        "CREATE TABLE devices (id TEXT PRIMARY KEY, label TEXT NOT NULL, owner_sub TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','revoked')), ex_certified INTEGER NOT NULL DEFAULT 0, device_secret TEXT NOT NULL, registered_at TEXT NOT NULL, last_seen TEXT)",
        "CREATE TABLE enrollment_codes (hash TEXT PRIMARY KEY, owner_sub TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE audit (sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, prev_hash TEXT NOT NULL, hash TEXT NOT NULL, payload TEXT NOT NULL)",
        "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END",
        "CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END",
    ),
    (
        "CREATE TABLE pin_failures (sub TEXT PRIMARY KEY REFERENCES guard_links(sub), attempts INTEGER NOT NULL, locked_until TEXT)",
    ),
    (
        "CREATE TABLE tag_keys (station_id TEXT NOT NULL, kid TEXT NOT NULL, hmac_key TEXT NOT NULL, meta_key TEXT NOT NULL, file_key TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)), PRIMARY KEY(station_id,kid))",
        "CREATE UNIQUE INDEX tag_one_active_key ON tag_keys(station_id) WHERE active=1",
        "CREATE TABLE tag_counters (station_id TEXT PRIMARY KEY, counter INTEGER NOT NULL CHECK(counter>=0))",
    ),
    (
        "CREATE TABLE scans (id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL, zone_id TEXT NOT NULL, contractor_id TEXT NOT NULL, client_id TEXT, payload TEXT NOT NULL)",
        "CREATE UNIQUE INDEX scans_client_id ON scans(owner_sub,client_id) WHERE client_id IS NOT NULL",
        "CREATE TRIGGER scans_no_update BEFORE UPDATE ON scans BEGIN SELECT RAISE(ABORT, 'scans are append-only'); END",
        "CREATE TRIGGER scans_no_delete BEFORE DELETE ON scans BEGIN SELECT RAISE(ABORT, 'scans are append-only'); END",
    ),
)


class FieldStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.local = threading.local()
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO schema_version VALUES(1,0)")
            version = db.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0]
            if version > len(MIGRATIONS):
                raise RuntimeError("Field database is newer than this application")
            for index in range(version, len(MIGRATIONS)):
                for statement in MIGRATIONS[index]:
                    db.execute(statement)
                db.execute("UPDATE schema_version SET version=? WHERE id=1", (index + 1,))

    @contextmanager
    def connection(self):
        active = getattr(self.local, "connection", None)
        if active is not None:
            yield active
            return
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        if getattr(self.local, "connection", None) is not None:
            yield
            return
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.local.connection = db
            self.local.after_commit = []
            try:
                yield
            finally:
                self.local.connection = None
                callbacks, self.local.after_commit = self.local.after_commit, []
        # Reached only when the outermost transaction committed; a rollback skips the callbacks.
        for callback in callbacks:
            callback()

    def after_commit(self, callback):
        """Run callback once the surrounding transaction commits (immediately when none is open)."""
        if getattr(self.local, "connection", None) is None:
            callback()
        else:
            self.local.after_commit.append(callback)

    def records(self, kind):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM entities WHERE kind=? ORDER BY rowid", (kind,))]

    def get(self, kind, id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM entities WHERE kind=? AND id=?", (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, kind, item):
        with self.connection() as db:
            db.execute("INSERT INTO entities VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
                       (kind, item["id"], canonical(item)))
        return item

    def delete(self, kind, id):
        with self.connection() as db:
            db.execute("DELETE FROM entities WHERE kind=? AND id=?", (kind, id))

    def scans(self):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM scans ORDER BY rowid')]

    def rejected_scans(self, reason):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM scans WHERE json_extract(payload,'$.status')='rejected' "
                "AND json_extract(payload,'$.reason')=? ORDER BY rowid", (reason,))]

    def scan_by_client(self, owner_sub, client_id):
        if client_id is None:
            return None
        with self.connection() as db:
            row = db.execute('SELECT payload FROM scans WHERE owner_sub=? AND client_id=?', (owner_sub, client_id)).fetchone()
        return json.loads(row[0]) if row else None

    def append_scan(self, item):
        with self.connection() as db:
            db.execute('INSERT INTO scans VALUES(?,?,?,?,?,?)',
                       (item['id'], item['owner_sub'], item['zone_id'], item['contractor_id'], item.get('client_id'), canonical(item)))
        return item

    def audits(self):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM audit ORDER BY sequence")]

    def append_audit(self, item):
        with self.transaction(), self.connection() as db:
            last = db.execute("SELECT id, hash FROM audit ORDER BY sequence DESC LIMIT 1").fetchone()
            previous = last["hash"] if last else "0" * 64
            sequence = int(last["id"].split("-")[1]) + 1 if last else 1
            item = dict(item, id=f"AUD-{sequence:04}", prev_hash=previous, previous_hash=previous)
            item["hash"] = hashlib.sha256((previous + canonical(item)).encode()).hexdigest()
            db.execute("INSERT INTO audit(id,prev_hash,hash,payload) VALUES(?,?,?,?)",
                       (item["id"], previous, item["hash"], canonical(item)))
        return item

    def verify_audit(self):
        previous = "0" * 64
        with self.connection() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY sequence").fetchall()
        for sequence, row in enumerate(rows, 1):
            item = json.loads(row["payload"])
            stored_hash = item.pop("hash", None)
            expected = hashlib.sha256((previous + canonical(item)).encode()).hexdigest()
            if (row["sequence"] != sequence or item.get("id") != f"AUD-{sequence:04}"
                    or item.get("prev_hash") != previous or item.get("previous_hash") != previous
                    or row["prev_hash"] != previous or row["hash"] != stored_hash or expected != stored_hash):
                return False
            previous = stored_hash
        return True

    def devices(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM devices ORDER BY registered_at,id")]

    def device(self, id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM devices WHERE id=?", (id,)).fetchone()
        return dict(row) if row else None

    def links(self):
        with self.connection() as db:
            return {row["guard_id"]: row["sub"] for row in db.execute("SELECT * FROM guard_links")}

    def set_identity(self, guard_id, sub):
        with self.connection() as db:
            # Reassignment removes previous PINs and revokes devices in the router.
            old = db.execute("SELECT sub FROM guard_links WHERE guard_id=?", (guard_id,)).fetchone()
            if old and old[0] != sub:
                db.execute("DELETE FROM guard_credentials WHERE sub=?", (old[0],))
                db.execute("DELETE FROM pin_failures WHERE sub=?", (old[0],))
            db.execute("INSERT INTO guard_links VALUES(?,?) ON CONFLICT(guard_id) DO UPDATE SET sub=excluded.sub", (guard_id, sub))
