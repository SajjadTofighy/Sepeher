#!/usr/bin/env python3
"""Check an exported Keycloak realm against the approved Sepehr security baseline.

Usage:
  python scripts/check_keycloak_realm.py [realm.json] [--advisories advisories.json]
      [--keycloak-version 26.7.4] [--max-access-token-seconds 300]
      [--max-sso-session-seconds 50400] [--json]

The advisory list is manual input maintained by the operator, e.g.
  [{"id": "CVE-2026-0001", "fixed_in": "26.7.5", "summary": "..."}]
Exit status 1 when any check fails. Standard library only.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REALM = ROOT / "deploy" / "keycloak" / "realm-sepehr.json"
SECRET_KEYS = {"secret", "credentials", "password", "privateKey", "certificate"}


def version_tuple(value):
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def compose_version():
    match = re.search(r"keycloak/keycloak:([0-9][0-9.]*)", (ROOT / "compose.yaml").read_text(encoding="utf-8"))
    return match.group(1) if match else None


def find_secrets(value, path="realm"):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SECRET_KEYS and item not in (None, "", [], {}):
                yield f"{path}.{key}"
            yield from find_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from find_secrets(item, f"{path}[{index}]")


def check(realm, *, max_access_token=300, max_sso_session=50400, version=None, advisories=()):
    results = []

    def result(ok, name, detail="", level="fail"):
        results.append(dict(status="pass" if ok else level, check=name, detail=detail))

    result(realm.get("registrationAllowed") is False, "registration_disabled", "ثبت‌نام کاربر باید خاموش باشد")
    result(realm.get("sslRequired") in ("external", "all"), "ssl_required", str(realm.get("sslRequired")))
    result(realm.get("bruteForceProtected") is True, "brute_force_detection", "Brute Force Detection باید روشن باشد")
    result(realm.get("eventsEnabled") is True and bool(realm.get("eventsExpiration")), "login_events",
           "Events با مدت نگهداری روشن باشد")
    result(realm.get("adminEventsEnabled") is True, "admin_events", "Admin Events برای SOC روشن باشد")
    result(realm.get("revokeRefreshToken") is True and realm.get("refreshTokenMaxReuse", 0) == 0,
           "refresh_token_rotation", "Revoke Refresh Token بدون استفاده مجدد")
    access = realm.get("accessTokenLifespan")
    result(isinstance(access, int) and 0 < access <= max_access_token, "access_token_lifespan",
           f"{access} ≤ {max_access_token}")
    session = realm.get("ssoSessionMaxLifespan")
    result(isinstance(session, int) and 0 < session <= max_sso_session, "sso_session_lifespan",
           f"{session} ≤ {max_sso_session}")
    length = re.search(r"length\((\d+)\)", realm.get("passwordPolicy", ""))
    result(bool(length) and int(length.group(1)) >= 12, "password_policy", realm.get("passwordPolicy", ""))
    secrets_found = list(find_secrets(realm))
    result(not secrets_found, "no_embedded_secrets", ", ".join(secrets_found[:5]))
    flows = json.dumps(realm.get("authenticationFlows", []))
    result("auth-otp-form" in flows and realm.get("browserFlow") not in (None, "browser"), "otp_browser_flow",
           "جریان ورود سفارشی با OTP شرطی", level="warn")
    for client in realm.get("clients", []):
        name = client.get("clientId", "?")
        result(not client.get("directAccessGrantsEnabled"), f"{name}:direct_access_grants", "باید خاموش باشد")
        result(not client.get("implicitFlowEnabled"), f"{name}:implicit_flow", "باید خاموش باشد")
        if client.get("publicClient") and client.get("standardFlowEnabled", True):
            method = (client.get("attributes") or {}).get("pkce.code.challenge.method")
            result(method == "S256", f"{name}:pkce_s256", str(method))
        for field in ("redirectUris", "webOrigins"):
            values = client.get(field) or []
            wild = [v for v in values if "*" in v]
            result(not wild, f"{name}:{field}_no_wildcard", ", ".join(wild))
            plain = [v for v in values if v.startswith("http://") and not re.match(r"http://(127\.0\.0\.1|localhost)[:/]", v)]
            result(not plain, f"{name}:{field}_tls", ", ".join(plain), level="warn")
        lifespan = (client.get("attributes") or {}).get("client.session.max.lifespan")
        if lifespan:
            result(int(lifespan) <= max_sso_session, f"{name}:client_session_lifespan", f"{lifespan} ≤ {max_sso_session}")
    if version:
        for advisory in advisories:
            fixed = advisory.get("fixed_in", "")
            result(version_tuple(version) >= version_tuple(fixed), f"advisory:{advisory.get('id', '?')}",
                   f"Keycloak {version}؛ وصله در {fixed}")
    else:
        result(False, "keycloak_version", "نسخه کیکلاک تعیین نشد", level="warn")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("realm", nargs="?", default=str(DEFAULT_REALM))
    parser.add_argument("--advisories", help="JSON list of {id, fixed_in, summary} maintained manually")
    parser.add_argument("--keycloak-version", default=None)
    parser.add_argument("--max-access-token-seconds", type=int, default=300)
    parser.add_argument("--max-sso-session-seconds", type=int, default=50400)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    realm = json.loads(Path(args.realm).read_text(encoding="utf-8"))
    advisories = json.loads(Path(args.advisories).read_text(encoding="utf-8")) if args.advisories else []
    results = check(realm, max_access_token=args.max_access_token_seconds, max_sso_session=args.max_sso_session_seconds,
                    version=args.keycloak_version or compose_version(), advisories=advisories)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for row in results:
            print(f"{row['status'].upper():5} {row['check']} {row['detail']}")
    return 1 if any(row["status"] == "fail" for row in results) else 0


if __name__ == "__main__":
    sys.exit(main())
