"""Durable GPS history. SQLite is independent of the resettable demo state."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


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


class TrackStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS positions (
                asset_id TEXT NOT NULL, time TEXT NOT NULL,
                lon REAL NOT NULL, lat REAL NOT NULL, speed REAL,
                source TEXT NOT NULL DEFAULT 'reported',
                PRIMARY KEY (asset_id, time)
            )""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed_missing(self, assets):
        with self.connection() as db:
            for asset in assets:
                if db.execute("SELECT 1 FROM positions WHERE asset_id=? LIMIT 1", (asset["id"],)).fetchone():
                    continue
                db.executemany(
                    "INSERT OR IGNORE INTO positions(asset_id,time,lon,lat,source) VALUES(?,?,?,?, 'demo')",
                    [(asset["id"], utc_timestamp(p["time"]), p["lon"], p["lat"]) for p in asset["track"]],
                )

    def append(self, asset_id, lon, lat, time, speed=None):
        timestamp = utc_timestamp(time)
        with self.connection() as db:
            # A retry is harmless; conflicting coordinates at the same instant are rejected.
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT lon,lat,speed FROM positions WHERE asset_id=? AND time=?", (asset_id, timestamp)).fetchone()
            if existing:
                if tuple(existing) != (lon, lat, speed):
                    raise TrackConflict("برای این زمان، موقعیت متفاوتی قبلاً ثبت شده است")
            else:
                db.execute("INSERT INTO positions(asset_id,time,lon,lat,speed) VALUES(?,?,?,?,?)", (asset_id, timestamp, lon, lat, speed))
        return dict(lon=lon, lat=lat, time=timestamp)

    def read(self, asset_id, since=None, until=None, limit=500):
        clauses, params = ["asset_id=?"], [asset_id]
        for column, value in (("time>=?", since), ("time<=?", until)):
            if value is not None:
                clauses.append(column)
                params.append(utc_timestamp(value))
        with self.connection() as db:
            rows = db.execute(
                "SELECT lon,lat,time FROM positions WHERE " + " AND ".join(clauses) + " ORDER BY time DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def latest(self, asset_id):
        with self.connection() as db:
            row = db.execute("SELECT lon,lat,time,speed,source FROM positions WHERE asset_id=? ORDER BY time DESC LIMIT 1", (asset_id,)).fetchone()
        return dict(row) if row else None

    def observations(self, asset_id, since, until):
        with self.connection() as db:
            rows = db.execute(
                "SELECT lon,lat,time,speed,source FROM positions WHERE asset_id=? AND time>=? AND time<=? ORDER BY time LIMIT 100001",
                (asset_id, utc_timestamp(since), utc_timestamp(until)),
            ).fetchall()
        return [dict(row) for row in rows]
