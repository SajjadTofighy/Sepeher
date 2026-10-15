#!/usr/bin/env python3
"""Inventory of pinned dependencies from the current lock files, for security review.

Usage: python scripts/dependency_inventory.py [--all] [--json]
Default lists direct runtime and build dependencies; --all adds every transitive npm package.
Standard library only; nothing is downloaded.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def python_packages():
    rows = []
    for line in (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, _, version = line.partition("==")
            rows.append(dict(ecosystem="pypi", name=name, version=version or "UNPINNED", scope="backend", direct=True,
                             source="backend/requirements.txt"))
    return rows


def npm_packages(include_transitive=False):
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    root = lock["packages"][""]
    runtime, build = set(root.get("dependencies", {})), set(root.get("devDependencies", {}))
    rows = []
    for path, meta in sorted(lock["packages"].items()):
        if not path:
            continue
        name = path.split("node_modules/")[-1]
        direct = path == "node_modules/" + name and (name in runtime or name in build)
        if direct or include_transitive:
            rows.append(dict(ecosystem="npm", name=name, version=meta.get("version", ""),
                             scope="runtime" if name in runtime else "build" if name in build else "transitive",
                             direct=direct, source="frontend/package-lock.json"))
    return rows


def inventory(include_transitive=False):
    return python_packages() + npm_packages(include_transitive)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = inventory(args.all)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0 if all(row["version"] != "UNPINNED" for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
