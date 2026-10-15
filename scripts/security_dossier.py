#!/usr/bin/env python3
"""Build the evidence package for the AFTA (افتا) security-assessment inquiry.

Usage:
  python scripts/security_dossier.py --out DIR --base-url https://sepehr.internal --token AUDITOR_TOKEN [--run-tests]
  python scripts/security_dossier.py --out DIR --dossier-json saved-dossier.json   # air-gapped copy

The runtime dossier comes from GET /api/v1/audit/security-dossier (auditor role), so building
the package never writes to production data. The package adds the Keycloak realm baseline,
the dependency inventory, optional backend test results, a printable inquiry letter draft and
evidence summary, and a sha256 manifest of every file. Standard library only.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
from app.security.afta_letter import _table, render_letter, render_summary  # noqa: E402
from backup import sha256  # noqa: E402
import check_keycloak_realm  # noqa: E402
import dependency_inventory  # noqa: E402


def fetch_dossier(base_url, token):
    request = Request(base_url.rstrip("/") + "/api/v1/audit/security-dossier",
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def run_tests():
    result = subprocess.run([sys.executable, "-m", "pytest", "backend/tests", "-q"], cwd=ROOT,
                            capture_output=True, text=True)
    return dict(exit_code=result.returncode, summary=(result.stdout.strip().splitlines() or [""])[-1],
                output=result.stdout[-20000:])


def build(dossier, out_dir, *, tests=None, now=None):
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    target = Path(out_dir) / f"sepehr-afta-dossier-{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    realm = json.loads(check_keycloak_realm.DEFAULT_REALM.read_text(encoding="utf-8"))
    realm_results = check_keycloak_realm.check(realm, version=check_keycloak_realm.compose_version())
    dependencies = dependency_inventory.inventory()

    def write(name, text):
        (target / name).write_text(text, encoding="utf-8")

    write("dossier.json", json.dumps(dossier, ensure_ascii=False, indent=2))
    write("realm-check.json", json.dumps(realm_results, ensure_ascii=False, indent=2))
    write("dependencies.json", json.dumps(dependencies, ensure_ascii=False, indent=2))
    extra = [("بررسی پایه امنیتی realm کیکلاک", _table(("وضعیت", "بررسی", "جزئیات"),
                                                      [(r["status"], r["check"], r["detail"]) for r in realm_results])),
             ("فهرست وابستگی‌ها", _table(("اکوسیستم", "بسته", "نسخه", "دامنه"),
                                         [(d["ecosystem"], d["name"], d["version"], d["scope"]) for d in dependencies]))]
    if tests is not None:
        write("tests.txt", tests["output"])
        extra.append(("نتیجه آزمون‌های خودکار", _table(("کد خروج", "خلاصه"), [(tests["exit_code"], tests["summary"])])))
    write("summary.html", render_summary(dossier, extra))
    evidence = [dict(path=p.name, sha256=sha256(p)) for p in sorted(target.iterdir()) if p.is_file()]
    write("inquiry-letter.html", render_letter(dossier, evidence))
    files = [dict(path=p.name, size=p.stat().st_size, sha256=sha256(p)) for p in sorted(target.iterdir()) if p.is_file()]
    manifest = dict(format=1, application="sepehr-afta-dossier", created_at=(now or datetime.now(timezone.utc)).isoformat(),
                    classification_label=dossier["classification_label"], files=files,
                    realm_failures=[r["check"] for r in realm_results if r["status"] == "fail"])
    write("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--token")
    parser.add_argument("--dossier-json")
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args(argv)
    if args.dossier_json:
        dossier = json.loads(Path(args.dossier_json).read_text(encoding="utf-8"))
    elif args.base_url and args.token:
        dossier = fetch_dossier(args.base_url, args.token)
    else:
        parser.error("--base-url with --token, or --dossier-json, is required")
    target = build(dossier, args.out, tests=run_tests() if args.run_tests else None)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
