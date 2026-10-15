"""RS256-only OIDC validation and request identity. No credentials are stored here."""

import asyncio
from contextvars import ContextVar
from functools import lru_cache
import json
import logging
import os
import threading
import time
from urllib.request import urlopen

import jwt
from fastapi import HTTPException
from starlette.responses import JSONResponse

from ..models import Principal

logger = logging.getLogger(__name__)
current_principal: ContextVar[Principal | None] = ContextVar("sepehr_principal", default=None)
current_scope: ContextVar[dict | None] = ContextVar("sepehr_request_scope", default=None)


def fail(code, status=401):
    messages = {
        "guard_not_linked": "هویت شما به نگهبان پیوند نخورده است؛ مدیر سامانه باید پیوند را ثبت کند",
        "device_required": "شناسه دستگاه ثبت‌شده لازم است",
        "device_revoked": "دستگاه باطل شده است؛ با مدیر سامانه تماس بگیرید",
        "device_owner_mismatch": "دستگاه متعلق به این کاربر نیست",
        "scope_denied": "داده خارج از محوطه، پیمانکار یا مالکیت مجاز شماست",
        "two_person_required": "درخواست‌دهنده نمی‌تواند درخواست خود را تأیید کند",
        "pin_rate_limited": "تلاش‌های ناموفق بیش از حد است؛ پنج دقیقه بعد دوباره تلاش کنید",
        "pin_not_configured": "رمز تأیید حضور توسط مدیر تنظیم نشده است",
        "invalid_enrollment_code": "کد ثبت دستگاه نامعتبر، استفاده‌شده یا منقضی است",
        "oidc_not_configured": "سرویس هویت در سرور تنظیم نشده است",
        "keycloak_token_required": "ثبت دستگاه به نشست معتبر کیکلاک نیاز دارد",
    }
    raise HTTPException(status, {"code": code, "message": messages.get(code, "احراز هویت یا مجوز دسترسی معتبر نیست")},
                        headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


def auth_mode():
    mode = os.environ.get("SEPEHR_AUTH_MODE", "keycloak")
    if mode not in ("keycloak", "demo"):
        raise RuntimeError("SEPEHR_AUTH_MODE must be keycloak or explicitly demo")
    return mode


def fetch_jwks(url):
    with urlopen(url, timeout=5) as response:
        return json.load(response)


class TokenVerifier:
    def __init__(self, issuer, audience="sepehr-api", clients=("sepehr-web", "sepehr-field"),
                 jwks_url=None, fetch=fetch_jwks, clock=time.monotonic):
        self.issuer = issuer
        self.audience = audience
        self.clients = clients
        self.url = jwks_url or issuer + "/protocol/openid-connect/certs"
        self.fetch = fetch
        self.clock = clock
        self.keys = {}
        self.last_attempt = float("-inf")
        self.last_success = float("-inf")
        self.lock = threading.Lock()

    def key(self, kid):
        with self.lock:
            stamp = self.clock()
            expired = stamp - self.last_success >= 300
            if (kid not in self.keys or expired) and stamp - self.last_attempt >= 10:
                self.last_attempt = stamp
                try:
                    result = {}
                    for item in self.fetch(self.url)["keys"]:
                        if (item.get("kty") == "RSA" and item.get("use", "sig") == "sig"
                                and item.get("alg", "RS256") == "RS256" and isinstance(item.get("kid"), str)):
                            result[item["kid"]] = jwt.PyJWK.from_dict(item, algorithm="RS256").key
                    if not result:
                        raise ValueError("JWKS contains no RS256 signing keys")
                    self.keys = result
                    self.last_success = stamp
                except Exception:
                    logger.warning("OIDC JWKS unavailable; retaining cached signing keys")
            key = self.keys.get(kid)
            if key is None:
                fail("unknown_signing_key")
            return key

    def verify(self, token):
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                fail("invalid_token_algorithm")
            claims = jwt.decode(token, self.key(header["kid"]), algorithms=["RS256"],
                                issuer=self.issuer, audience=self.audience, leeway=5,
                                options={"require": ["exp", "iss", "aud", "sub", "azp", "typ"]})
            if claims["typ"] != "Bearer" or claims["azp"] not in self.clients:
                fail("invalid_token_claims")
            sub, username = claims["sub"], claims.get("preferred_username", claims["sub"])
            groups = claims.get("groups", [])
            roles = claims.get("realm_access", {}).get("roles", [])
            if (not isinstance(sub, str) or not sub or not isinstance(username, str)
                    or not isinstance(groups, list) or not all(isinstance(x, str) for x in groups)
                    or not isinstance(roles, list) or not all(isinstance(x, str) for x in roles)):
                fail("invalid_token_claims")
            zones = tuple(sorted({g.split("/")[2] for g in groups if g.startswith("/zones/") and len(g.split("/")) == 3 and g.split("/")[2]}))
            contractors = {g.split("/")[2] for g in groups if g.startswith("/contractors/") and len(g.split("/")) == 3 and g.split("/")[2]}
            if len(contractors) > 1:
                fail("ambiguous_contractor")
            return Principal(sub=sub, username=username, roles=tuple(roles), zone_ids=zones,
                             contractor_id=next(iter(contractors), None))
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError):
            fail("invalid_token")


@lru_cache(maxsize=8)
def configured_verifier(issuer, audience, clients, jwks_url):
    return TokenVerifier(issuer, audience, clients, jwks_url or None)


def get_verifier():
    issuer = os.environ.get("SEPEHR_OIDC_ISSUER", "").rstrip("/")
    if not issuer:
        fail("oidc_not_configured", 503)
    clients = tuple(x.strip() for x in os.environ.get("SEPEHR_OIDC_CLIENTS", "sepehr-web,sepehr-field").split(",") if x.strip())
    return configured_verifier(issuer, os.environ.get("SEPEHR_OIDC_AUDIENCE", "sepehr-api"),
                               clients, os.environ.get("SEPEHR_OIDC_JWKS_URL", ""))


def authenticate(authorization):
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            fail("invalid_authorization")
        return get_verifier().verify(token)
    if auth_mode() == "demo":
        return Principal(sub="demo-operator", username="اپراتور نمایشی",
                         roles=("admin", "auditor", "security_manager", "security_officer", "shift_supervisor"),
                         mode="demo")
    fail("authentication_required")


def response_metadata(path):
    from .. import store
    from urllib.parse import quote, urlsplit
    with store.locked_state():
        label = store.state["settings"]["classification_label"]
    # RFC 8187 encoding keeps Persian metadata valid in HTTP headers.
    headers = {"X-Classification": "UTF-8''" + quote(label), "X-Server-Time": store.now(),
               "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
               "Strict-Transport-Security": "max-age=31536000", "X-Frame-Options": "DENY",
               "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Resource-Policy": "same-origin",
               # Field capture, location and NFC only for this origin; everything else off.
               "Permissions-Policy": "camera=(self), microphone=(self), geolocation=(self), nfc=(self), "
                                     "payment=(), usb=(), serial=(), bluetooth=(), display-capture=()"}
    if path.startswith('/api/v1/'):
        headers['Cache-Control'] = 'no-store'
    if path != "/docs":
        parsed = urlsplit(os.environ.get("SEPEHR_OIDC_ISSUER", ""))
        origins = [f"{parsed.scheme}://{parsed.netloc}"] if parsed.netloc else []
        origins.extend(x.strip() for x in os.environ.get("SEPEHR_GIS_ORIGINS", "").split(",") if x.strip())
        headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; connect-src 'self'" + (" " + " ".join(origins) if origins else "")
    if auth_mode() == "demo":
        headers["X-Sepehr-Demo"] = "1"
    return headers


class IdentityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from . import authz
        path = scope["path"]
        headers = {key.lower(): value for key, value in scope["headers"]}
        public = path in ("/api/v1/health", "/api/v1/auth/config") or (
            path == '/api/v1/tour/offline/emergency' and scope['method'] == 'POST')
        authorization = headers.get(b"authorization", b"").decode("latin1")
        principal = None
        started = False
        try:
            from . import hardening
            if path.startswith("/api/") and scope["method"] in ("POST", "PUT", "PATCH", "DELETE") and not hardening.raw_body(path):
                receive = await hardening.bounded_receive(scope, receive, await asyncio.to_thread(hardening.body_limit))
            if not public and (authz.protected(path) or authorization or auth_mode() == "demo"):
                principal = await asyncio.to_thread(authenticate, authorization)
                authz.authorize_path(principal, path, scope["method"])
            await asyncio.to_thread(hardening.check_rate, scope, principal, scope["method"], path)
            scope.setdefault("state", {})["principal"] = principal
            context = current_principal.set(principal)
            request_context = current_scope.set(scope)
            async def decorated_send(message):
                nonlocal started
                if message["type"] == "http.response.start":
                    started = True
                    existing = {key.lower() for key, _ in message.get('headers', [])}
                    extra = [(key.lower().encode("ascii"), value.encode("ascii"))
                             for key, value in response_metadata(path).items()
                             if key.lower().encode('ascii') not in existing]
                    message = dict(message, headers=list(message.get("headers", [])) + extra)
                await send(message)
            try:
                await self.app(scope, receive, decorated_send)
            finally:
                current_principal.reset(context)
                current_scope.reset(request_context)
        except HTTPException as error:
            response = JSONResponse({"detail": error.detail}, status_code=error.status_code,
                                    headers={**(error.headers or {}), **response_metadata(path)})
            await response(scope, receive, send)
        except Exception:
            if started:
                raise
            logger.exception("API request failed")
            response = JSONResponse({"detail": {"code": "internal_error", "message": "خطای داخلی سرویس"}},
                                    status_code=500, headers=response_metadata(path))
            await response(scope, receive, send)
