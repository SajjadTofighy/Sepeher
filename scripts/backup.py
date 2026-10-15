#!/usr/bin/env python3
"""Consistent backup of Sepehr field data: both SQLite stores and stored media.

Usage:
  python scripts/backup.py --out /secure/backups [--field-db PATH] [--track-db PATH] [--media-dir PATH]

SQLite files are copied with sqlite3.Connection.backup, which is consistent while the
service is running; each copy passes PRAGMA integrity_check. Media objects are copied
unchanged. manifest.json lists every file with size and sha256 for scripts/restore.py.
The Keycloak PostgreSQL database is backed up separately with pg_dump (see the runbook).
Standard library only.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "data"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def default_paths():
    field = Path(os.environ.get("SEPEHR_FIELD_DB", DATA / "field.sqlite3"))
    track = Path(os.environ.get("SEPEHR_TRACK_DB", DATA / "tracks.sqlite3"))
    media = Path(os.environ.get("SEPEHR_MEDIA_DIR", field.parent / "media"))
    return field, track, media


def copy_sqlite(source, target):
    if not source.exists():
        raise FileNotFoundError(f"database not found: {source}")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        # A backup is one self-contained file: no WAL sidecars; the service re-enables WAL on open.
        dst.execute("PRAGMA journal_mode=DELETE")
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"integrity check failed for backup of {source.name}")
    # Close explicitly so the copy is complete on disk before hashing.
    src.close()
    dst.close()


def backup(field_db, track_db, media_dir, out_dir, now=None):
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    target = Path(out_dir) / f"sepehr-backup-{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    copy_sqlite(Path(field_db), target / "field.sqlite3")
    copy_sqlite(Path(track_db), target / "tracks.sqlite3")
    objects = Path(media_dir) / "objects"
    if objects.exists():
        shutil.copytree(objects, target / "media" / "objects")
    files = []
    for path in sorted(p for p in target.rglob("*") if p.is_file()):
        files.append(dict(path=path.relative_to(target).as_posix(), size=path.stat().st_size, sha256=sha256(path)))
    manifest = dict(format=1, application="sepehr", created_at=(now or datetime.now(timezone.utc)).isoformat(),
                    files=files, keycloak="PostgreSQL باید جداگانه با pg_dump پشتیبان‌گیری شود")
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main(argv=None):
    field, track, media = default_paths()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--field-db", default=str(field))
    parser.add_argument("--track-db", default=str(track))
    parser.add_argument("--media-dir", default=str(media))
    args = parser.parse_args(argv)
    target = backup(args.field_db, args.track_db, args.media_dir, args.out)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
