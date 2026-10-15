"""Durable GPS history. SQLite is independent of the resettable demo state."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import threading


def parse_timestamp(value):
    """Parse operational times once; offsets and Z denote the same instant."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise ValueError("Position timestamp must include a timezone")
    return dt.astimezone(timezone.utc)


def utc_timestamp(value):
    return parse_timestamp(value).isoformat(timespec="microseconds")


class TrackConflict(ValueError):
    pass


QUALITY_COLUMNS = (
    ("received_at", "TEXT"),
    ("accuracy_m", "REAL"),
    ("fix_source", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("sequence", "INTEGER"),
    ("auth", "TEXT"),
    ("flags", "TEXT NOT NULL DEFAULT '[]'"),
    ("live", "INTEGER NOT NULL DEFAULT 1"),
)
DETAIL = "lon,lat,time,speed,source,received_at,accuracy_m,fix_source,sequence,auth,flags,live"


def _detail(row):
    item = dict(row)
    item["flags"] = json.loads(item["flags"] or "[]")
    item["live"] = bool(item["live"])
    return item


class TrackStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread: opening/closing per statement dominated ingestion cost.
        self.local = threading.local()
        # Per-asset write counter: readers skip re-reading an unchanged track. Every write in
        # this process goes through append/seed_missing, so the counter cannot miss a change.
        self.versions = {}
        self.versions_lock = threading.Lock()
        # Called with (asset_id, stored row, new version) after each committed insert.
        self.listeners = []
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS positions (
                asset_id TEXT NOT NULL, time TEXT NOT NULL,
                lon REAL NOT NULL, lat REAL NOT NULL, speed REAL,
                source TEXT NOT NULL DEFAULT 'reported',
                PRIMARY KEY (asset_id, time)
            )""")
            # Additive migration: older databases keep every row; unknown quality stays NULL, never 0 m.
            present = {row[1] for row in db.execute("PRAGMA table_info(positions)")}
            for name, kind in QUALITY_COLUMNS:
                if name not in present:
                    db.execute(f"ALTER TABLE positions ADD COLUMN {name} {kind}")
            db.execute("CREATE INDEX IF NOT EXISTS positions_by_source ON positions(asset_id, source, live, time)")

    @contextmanager
    def connection(self):
        db = getattr(self.local, "db", None)
        if db is None:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            self.local.db = db
        with db:  # commits on success, rolls back on error; the connection stays open
            yield db

    def version(self, asset_id):
        return self.versions.get(asset_id, 0)

    def _bump(self, asset_id):
        with self.versions_lock:
            self.versions[asset_id] = self.versions.get(asset_id, 0) + 1

    def seed_missing(self, assets):
        with self.connection() as db:
            for asset in assets:
                if db.execute("SELECT 1 FROM positions WHERE asset_id=? LIMIT 1", (asset["id"],)).fetchone():
                    continue
                db.executemany(
                    "INSERT OR IGNORE INTO positions(asset_id,time,lon,lat,source) VALUES(?,?,?,?, 'demo')",
                    [(asset["id"], utc_timestamp(p["time"]), p["lon"], p["lat"]) for p in asset["track"]],
                )
                self._bump(asset["id"])

    def append(self, asset_id, lon, lat, time, speed=None, *, received_at=None, accuracy_m=None,
               fix_source="unknown", sequence=None, auth=None, flags=(), live=True):
        """Store one observation; returns (point, created). A same-instant retry is idempotent."""
        timestamp = utc_timestamp(time)
        with self.connection() as db:
            # A retry is harmless; conflicting coordinates at the same instant are rejected.
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT lon,lat,speed FROM positions WHERE asset_id=? AND time=?", (asset_id, timestamp)).fetchone()
            if existing:
                if tuple(existing) != (lon, lat, speed):
                    raise TrackConflict("برای این زمان، موقعیت متفاوتی قبلاً ثبت شده است")
                created = False
            else:
                db.execute(
                    "INSERT INTO positions(asset_id,time,lon,lat,speed,received_at,accuracy_m,fix_source,sequence,auth,flags,live)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (asset_id, timestamp, lon, lat, speed, received_at and utc_timestamp(received_at), accuracy_m,
                     fix_source, sequence, auth, json.dumps(sorted(flags)), int(live)))
                created = True
        if created:
            self._bump(asset_id)
            row = dict(lon=lon, lat=lat, time=timestamp, speed=speed, source="reported",
                       received_at=received_at and utc_timestamp(received_at), accuracy_m=accuracy_m,
                       fix_source=fix_source, sequence=sequence, auth=auth, flags=sorted(flags), live=bool(live))
            for listener in self.listeners:
                listener(asset_id, row, self.version(asset_id))
        return dict(lon=lon, lat=lat, time=timestamp), created

    def _source_clause(self, source):
        return ("", []) if source is None else (" AND source=?", [source])

    def read(self, asset_id, since=None, until=None, limit=500, source=None):
        clauses, params = ["asset_id=?"], [asset_id]
        for column, value in (("time>=?", since), ("time<=?", until)):
            if value is not None:
                clauses.append(column)
                params.append(utc_timestamp(value))
        if source is not None:
            clauses.append("source=?")
            params.append(source)
        with self.connection() as db:
            rows = db.execute(
                "SELECT lon,lat,time FROM positions WHERE " + " AND ".join(clauses) + " ORDER BY time DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def detailed(self, asset_id, since=None, until=None, limit=500, source=None):
        """History with observation quality for evidence and replay (raw, not only live-accepted)."""
        clauses, params = ["asset_id=?"], [asset_id]
        for column, value in (("time>=?", since), ("time<=?", until)):
            if value is not None:
                clauses.append(column)
                params.append(utc_timestamp(value))
        if source is not None:
            clauses.append("source=?")
            params.append(source)
        with self.connection() as db:
            rows = db.execute(f"SELECT {DETAIL} FROM positions WHERE " + " AND ".join(clauses)
                              + " ORDER BY time DESC LIMIT ?", [*params, limit]).fetchall()
        return [_detail(row) for row in reversed(rows)]

    def latest(self, asset_id):
        """Newest live-accepted observation; real reports always take precedence over demo seed rows."""
        with self.connection() as db:
            for source in ("reported", "demo"):
                row = db.execute(f"SELECT {DETAIL} FROM positions WHERE asset_id=? AND source=? AND live=1"
                                 " ORDER BY time DESC LIMIT 1", (asset_id, source)).fetchone()
                if row:
                    return _detail(row)
        return None

    def previous_reported(self, asset_id, before):
        """Nearest earlier live-accepted real report, the reference for plausibility checks."""
        with self.connection() as db:
            row = db.execute(f"SELECT {DETAIL} FROM positions WHERE asset_id=? AND source='reported' AND live=1"
                             " AND time<? ORDER BY time DESC LIMIT 1", (asset_id, utc_timestamp(before))).fetchone()
        return _detail(row) if row else None

    def observations(self, asset_id, since, until):
        with self.connection() as db:
            rows = db.execute(
                "SELECT lon,lat,time,speed,source FROM positions WHERE asset_id=? AND time>=? AND time<=? ORDER BY time LIMIT 100001",
                (asset_id, utc_timestamp(since), utc_timestamp(until)),
            ).fetchall()
        return [dict(row) for row in rows]
