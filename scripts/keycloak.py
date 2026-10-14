"""Explicit Keycloak provisioning through the Admin REST API; stdlib only."""

import argparse
from copy import deepcopy
from getpass import getpass
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
REALM = json.loads((ROOT / "deploy/keycloak/realm-sepehr.json").read_text())
ROLES = [role["name"] for role in REALM["roles"]["realm"] if role["name"] != "sepehr-mfa-required"]


def exact_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment or "*" in value):
        raise argparse.ArgumentTypeError("نشانی دقیق HTTP/HTTPS بدون wildcard لازم است")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise argparse.ArgumentTypeError("HTTP فقط برای loopback مجاز است؛ از HTTPS استفاده کنید")
    return value


def origin(value):
    exact_url(value)
    parsed = urlsplit(value)
    if parsed.path or parsed.query:
        raise argparse.ArgumentTypeError("origin باید فقط شامل scheme، host و port باشد")
    return value


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise argparse.ArgumentTypeError("شناسه باید حداکثر ۱۰۰ نویسه و شامل حروف لاتین، عدد، .، _ یا - باشد")
    return value


class Admin:
    def __init__(self, args):
        self.base = args.server.rstrip("/")
        self.token = None
        password = os.environ.get("KEYCLOAK_ADMIN_PASSWORD") or getpass("رمز مدیر Keycloak: ")
        form = urlencode({"client_id": "admin-cli", "grant_type": "password",
                          "username": args.admin, "password": password}).encode()
        result = self.request("POST", "/realms/master/protocol/openid-connect/token", form,
                              "application/x-www-form-urlencoded")
        self.token = result["access_token"]
        self.realm_path = "/admin/realms/" + quote(args.realm, safe="")

    def request(self, method, path, data=None, content_type="application/json"):
        headers = {"Content-Type": content_type}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode()
        req = Request(self.base + path, data=data, headers=headers, method=method)
        with urlopen(req, timeout=20) as response:
            body = response.read()
            return json.loads(body) if body else None

    def realm(self, method, path, data=None):
        return self.request(method, self.realm_path + path, data)


def client_payload(args):
    # Inherit the shared PKCE, audience and group mapper configuration.
    payload = deepcopy(next(c for c in REALM["clients"] if c["clientId"] == "sepehr-web"))
    payload.update(clientId=args.client_id, redirectUris=args.redirect_uri, webOrigins=args.origin)
    payload["attributes"]["post.logout.redirect.uris"] = "##".join(origin + "/" for origin in args.origin)
    return payload


def sync_security(api):
    """Upgrade an existing realm without deleting users, memberships or secrets."""
    for role in REALM["roles"]["realm"]:
        path = "/roles/" + quote(role["name"], safe="")
        try:
            api.realm("GET", path)
        except HTTPError as error:
            if error.code != 404:
                raise
            api.realm("POST", "/roles", {"name": role["name"], "description": role.get("description", "")})
    mfa = api.realm("GET", "/roles/sepehr-mfa-required")
    for role in REALM["roles"]["realm"]:
        if role.get("composite"):
            api.realm("POST", "/roles/" + quote(role["name"], safe="") + "/composites", [mfa])
    for desired in REALM["clients"]:
        existing = api.realm("GET", "/clients?" + urlencode({"clientId": desired["clientId"]}))
        if existing:
            client = existing[0]
            updated = {**client, **desired}
            if desired.get("publicClient"):
                # Preserve deployment-specific exact URLs while enforcing policy.
                updated["redirectUris"] = [exact_url(url) for url in client["redirectUris"]]
                updated["webOrigins"] = [origin(url) for url in client["webOrigins"]]
                if not updated["redirectUris"] or not updated["webOrigins"]:
                    raise ValueError("کلاینت وب باید redirect و origin دقیق داشته باشد")
                updated["attributes"] = {**client.get("attributes", {}), **desired["attributes"]}
                updated["attributes"]["post.logout.redirect.uris"] = "##".join(url + "/" for url in updated["webOrigins"])
            api.realm("PUT", "/clients/" + client["id"], updated)
        else:
            api.realm("POST", "/clients", desired)
    aliases = {flow["alias"] for flow in api.realm("GET", "/authentication/flows")}
    if "sepehr-browser" not in aliases:
        definitions = {flow["alias"]: flow for flow in REALM["authenticationFlows"]}
        configs = {config["alias"]: config for config in REALM["authenticatorConfig"]}
        root = definitions["sepehr-browser"]
        api.realm("POST", "/authentication/flows", {key: value for key, value in root.items() if key != "authenticationExecutions"})
        def assemble(alias):
            path = "/authentication/flows/" + quote(alias, safe="") + "/executions"
            for execution in definitions[alias]["authenticationExecutions"]:
                if execution["authenticatorFlow"]:
                    child = execution["flowAlias"]
                    api.realm("POST", path + "/flow", {"alias": child, "type": "basic-flow", "provider": "basic-flow"})
                    node = next(e for e in api.realm("GET", path) if e["displayName"] == child)
                    api.realm("PUT", path, {**node, "requirement": execution["requirement"]})
                    assemble(child)
                else:
                    provider = execution["authenticator"]
                    api.realm("POST", path + "/execution", {"provider": provider})
                    node = next(e for e in api.realm("GET", path) if e.get("providerId") == provider)
                    api.realm("PUT", path, {**node, "requirement": execution["requirement"]})
                    if execution.get("authenticatorConfig"):
                        api.realm("POST", "/authentication/executions/" + node["id"] + "/config", configs[execution["authenticatorConfig"]])
        assemble("sepehr-browser")
    for flow in REALM["authenticationFlows"]:
        path = "/authentication/flows/" + quote(flow["alias"], safe="") + "/executions"
        nodes = api.realm("GET", path)
        for execution in flow["authenticationExecutions"]:
            matches = [node for node in nodes if (node.get("displayName") == execution.get("flowAlias") if execution["authenticatorFlow"] else node.get("providerId") == execution["authenticator"])]
            if len(matches) != 1 or matches[0]["requirement"] != execution["requirement"]:
                raise ValueError("ساختار جریان امنیتی با realm مصوب تطابق ندارد؛ در کنسول بررسی کنید")
            if execution.get("authenticatorConfig"):
                node = api.realm("GET", "/authentication/executions/" + matches[0]["id"])
                desired = next(c for c in REALM["authenticatorConfig"] if c["alias"] == execution["authenticatorConfig"])
                config_path = "/authentication/config/" + node["authenticatorConfig"]
                # Keycloak masks some boolean configuration values as secrets.
                # Set the approved values explicitly before checking readable values.
                api.realm("PUT", config_path, {**desired, "id": node["authenticatorConfig"]})
                config = api.realm("GET", config_path)
                if any(config["config"].get(key) not in (value, "**********")
                       for key, value in desired["config"].items()):
                    raise ValueError("شرط نقش جریان OTP با realm مصوب تطابق ندارد")
    parents = {group["name"] for group in api.realm("GET", "/groups")}
    for group in REALM["groups"]:
        if group["name"] not in parents:
            api.realm("POST", "/groups", group)
    management = api.realm("GET", "/clients?clientId=realm-management")[0]
    view_events = api.realm("GET", "/clients/" + management["id"] + "/roles/view-events")
    audit_client = api.realm("GET", "/clients?clientId=sepehr-audit")[0]
    service = api.realm("GET", "/clients/" + audit_client["id"] + "/service-account-user")
    mapping = "/users/" + service["id"] + "/role-mappings/clients/" + management["id"]
    assigned = api.realm("GET", mapping)
    extra = [role for role in assigned if role["name"] != "view-events"]
    if extra:
        api.realm("DELETE", mapping, extra)
    api.realm("POST", mapping, [view_events])
    api.realm("POST", "/clients/" + audit_client["id"] + "/scope-mappings/clients/" + management["id"], [view_events])
    # Activate the browser flow only after its roles/executions are complete.
    excluded = {"realm", "roles", "clients", "users", "groups", "authenticationFlows", "authenticatorConfig", "clientScopeMappings"}
    api.realm("PUT", "", {key: value for key, value in REALM.items() if key not in excluded})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8081", type=origin)
    parser.add_argument("--realm", default=REALM["realm"], type=identifier)
    parser.add_argument("--admin", default=os.environ.get("KEYCLOAK_ADMIN_USERNAME", "admin"))
    commands = parser.add_subparsers(dest="command", required=True)
    client = commands.add_parser("create-client", help="ساخت کلاینت public با PKCE S256")
    client.add_argument("--client-id", required=True, type=identifier)
    client.add_argument("--redirect-uri", action="append", required=True, type=exact_url)
    client.add_argument("--origin", action="append", required=True, type=origin)
    client.add_argument("--dry-run", action="store_true")
    user = commands.add_parser("create-user", help="ساخت کاربر با رمز موقت و نقش‌های مشخص")
    user.add_argument("--username", required=True, type=identifier)
    user.add_argument("--role", action="append", required=True, choices=ROLES)
    audit = commands.add_parser("configure-audit", help="تنظیم راز کلاینت فقط‌خواندنی ممیزی در فایل محیط")
    audit.add_argument("--env-file", type=Path, default=ROOT / ".env")
    security = commands.add_parser("sync-security", help="ارتقای سیاست امنیتی realm موجود بدون حذف کاربران")
    security.add_argument("--apply", action="store_true", help="اعمال صریح پس از backup و بررسی پیش‌نمایش")
    args = parser.parse_args()
    if args.command == "sync-security":
        if not args.apply:
            print("پیش‌نمایش: نقش MFA مرکب، PKCE و mapperها، رویدادها، سیاست رمز، جریان OTP و کلاینت فقط view-events همگام می‌شوند؛ کاربران و گروه‌ها حفظ می‌شوند. پیش از --apply از PostgreSQL backup بگیرید. redirect/origin موجود باید دقیق باشد؛ realm sepehr باید موجود باشد.")
            return
        sync_security(Admin(args))
        print("سیاست امنیتی realm همگام شد؛ ورود و OTP را پیش از انتشار بررسی کنید.")
        return
    if args.command == "configure-audit":
        api = Admin(args)
        clients = api.realm("GET", "/clients?clientId=sepehr-audit")
        if len(clients) != 1:
            raise ValueError("کلاینت sepehr-audit باید ابتدا از realm وارد شود")
        secret = api.realm("GET", "/clients/" + quote(clients[0]["id"], safe="") + "/client-secret")["value"]
        content = args.env_file.read_text() if args.env_file.exists() else ""
        content = re.sub(r"^SEPEHR_AUDIT_CLIENT_SECRET=.*\n?", "", content, flags=re.MULTILINE)
        fd = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(content.rstrip() + "\nSEPEHR_AUDIT_CLIENT_SECRET=" + secret + "\n")
        print("راز ممیزی بدون نمایش در فایل محیط ثبت شد؛ backend را بازسازی کنید.")
        return
    if args.command == "create-client":
        payload = client_payload(args)
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        api = Admin(args)
        api.realm("POST", "/clients", payload)
        print("کلاینت ساخته شد؛ توکن‌ها audience برابر sepehr-api خواهند داشت.")
        return

    # Resolve roles before creating anything; never replace an existing user.
    api = Admin(args)
    roles = [api.realm("GET", "/roles/" + quote(role, safe="")) for role in dict.fromkeys(args.role)]
    existing = api.realm("GET", "/users?" + urlencode({"username": args.username, "exact": "true"}))
    if existing:
        raise ValueError("کاربر موجود است؛ هیچ تغییری اعمال نشد")
    password = getpass("رمز موقت کاربر (حداقل ۱۲ نویسه، بزرگ/کوچک، عدد و نماد): ")
    if (len(password) < 12 or not re.search(r"[A-Z]", password)
            or not re.search(r"[a-z]", password) or not re.search(r"[0-9]", password)
            or not re.search(r"[^A-Za-z0-9]", password)):
        raise ValueError("رمز با سیاست realm سازگار نیست")
    if password != getpass("تکرار رمز موقت: "):
        raise ValueError("تکرار رمز یکسان نیست")
    actions = ["UPDATE_PASSWORD"]
    if any(role != "guard" for role in args.role):
        actions.append("CONFIGURE_TOTP")
    # Keep the account disabled until its role mapping is complete.
    api.realm("POST", "/users", {"username": args.username, "enabled": False,
                                  "requiredActions": actions,
                                  "credentials": [{"type": "password", "value": password, "temporary": True}]})
    users = api.realm("GET", "/users?" + urlencode({"username": args.username, "exact": "true"}))
    if len(users) != 1:
        raise ValueError("شناسایی کاربر ساخته‌شده ممکن نشد؛ وضعیت را در کنسول بررسی کنید")
    path = "/users/" + quote(users[0]["id"], safe="")
    api.realm("POST", path + "/role-mappings/realm", roles)
    api.realm("PUT", path, {"enabled": True})
    print("کاربر ساخته شد؛ تغییر رمز در اولین ورود اجباری است. شناسه sub: " + users[0]["id"])


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        # Do not print responses that may contain credentials or tokens.
        print(f"خطای Keycloak: HTTP {error.code}. وضعیت را در کنسول بررسی کنید؛ کاربر ناقص غیرفعال می‌ماند.", file=sys.stderr)
        sys.exit(1)
    except (URLError, TimeoutError, ValueError, OSError, EOFError) as error:
        print(f"خطا: {error}", file=sys.stderr)
        sys.exit(1)
