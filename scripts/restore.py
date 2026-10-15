#!/usr/bin/env python3
"""Restore a Sepehr backup after verifying its sha256 manifest.

Usage (service stopped):
  python scripts/restore.py BACKUP_DIR [--field-db PATH] [--track-db PATH] [--media-dir PATH] [--force]

Every listed file must match its size and sha256 and no unlisted file may be present;
otherwise nothing is restored. Existing data is replaced only with --force. Each
database is written to a temporary file and moved into place atomically.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import default_paths, sha256  # noqa: E402


class ManifestError(ValueError):
    pass


def verify(backup_dir):
    backup_dir = Path(backup_dir)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("application") != "sepehr" or manifest.get("format") != 1:
        raise ManifestError("manifest format is not a Sepehr backup")
    listed = {row["path"]: row for row in manifest["files"]}
    present = {p.relative_to(backup_dir).as_posix() for p in backup_dir.rglob("*") if p.is_file()} - {"manifest.json"}
    if present != set(listed):
        raise ManifestError(f"unlisted or missing files: {sorted(present ^ set(listed))[:5]}")
    for path, row in listed.items():
        file = backup_dir / path
        if file.stat().st_size != row["size"] or sha256(file) != row["sha256"]:
            raise ManifestError(f"checksum mismatch: {path}")
    for name in ("field.sqlite3", "tracks.sqlite3"):
        if name not in listed:
            raise ManifestError(f"missing database: {name}")
        with sqlite3.connect(f"file:{backup_dir / name}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ManifestError(f"integrity check failed: {name}")
    return manifest


def place(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".restore-tmp")
    shutil.copyfile(source, temporary)
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    os.replace(temporary, target)


def restore(backup_dir, field_db, track_db, media_dir, force=False):
    backup_dir, field_db, track_db, media_dir = map(Path, (backup_dir, field_db, track_db, media_dir))
    manifest = verify(backup_dir)
    if not force and (field_db.exists() or track_db.exists() or (media_dir / "objects").exists()):
        raise FileExistsError("target data exists; stop the service and pass --force to replace it")
    place(backup_dir / "field.sqlite3", field_db)
    place(backup_dir / "tracks.sqlite3", track_db)
    objects = media_dir / "objects"
    if objects.exists():
        shutil.rmtree(objects)
    if (backup_dir / "media" / "objects").exists():
        shutil.copytree(backup_dir / "media" / "objects", objects)
    return manifest


def main(argv=None):
    field, track, media = default_paths()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("backup_dir")
    parser.add_argument("--field-db", default=str(field))
    parser.add_argument("--track-db", default=str(track))
    parser.add_argument("--media-dir", default=str(media))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = restore(args.backup_dir, args.field_db, args.track_db, args.media_dir, args.force)
    except (ManifestError, FileExistsError) as error:
        print(f"restore refused: {error}", file=sys.stderr)
        return 1
    print(f"restored {len(manifest['files'])} files from {manifest['created_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
