#!/usr/bin/env python3
"""TEST-ONLY OpenID provider that mimics the Keycloak endpoints Sepehr uses. Never deploy.

Usage: python scripts/stub_oidc.py [--port 9400]
Issuer: http://127.0.0.1:<port>/realms/sepehr

Binds to 127.0.0.1 only. Enforces Authorization Code + PKCE S256, exact client and
loopback redirect URI, single-use codes, state passthrough and nonce in the ID token;
signs RS256 access tokens with an ephemeral key published at the JWKS endpoint, so the
backend verifies them exactly as it verifies Keycloak tokens. Users are fixed test personas.
Requires PyJWT and cryptography from backend/requirements.txt.
"""
import argparse
import base64
import hashlib
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENTS = {"sepehr-web", "sepehr-field"}
REDIRECT = re.compile(r"^http://127\.0\.0\.1:\d{2,5}/auth/callback$")
USERS = {
    "supervisor": dict(roles=["shift_supervisor"], groups=["/zones/Z1", "/contractors/SCHEMATIC"]),
    "auditor": dict(roles=["auditor"], groups=["/zones/Z1", "/contractors/SCHEMATIC"]),
    "admin": dict(roles=["admin", "security_manager"], groups=["/zones/Z1", "/contractors/SCHEMATIC"]),
    "guard": dict(roles=["guard"], groups=["/zones/Z1", "/contractors/SCHEMATIC"]),
}


class Provider:
    def __init__(self, issuer, access_seconds=300):
        self.issuer = issuer
        self.access_seconds = access_seconds
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = secrets.token_hex(8)
        self.flows, self.codes, self.refresh = {}, {}, {}

    def jwks(self):
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid=self.kid, alg="RS256", use="sig")
        return {"keys": [jwk]}

    def tokens(self, user, client, nonce=None):
        now = int(time.time())
        profile = USERS[user]
        access = jwt.encode(dict(iss=self.issuer, sub="stub-" + user, preferred_username=user, aud="sepehr-api",
                                 azp=client, typ="Bearer", iat=now, nbf=now, exp=now + self.access_seconds,
                                 realm_access={"roles": profile["roles"]}, groups=profile["groups"]),
                            self.key, algorithm="RS256", headers={"kid": self.kid})
        identity = jwt.encode(dict(iss=self.issuer, sub="stub-" + user, aud=client, azp=client, typ="ID", iat=now,
                                   exp=now + self.access_seconds, nonce=nonce),
                              self.key, algorithm="RS256", headers={"kid": self.kid})
        refresh = secrets.token_urlsafe(32)
        self.refresh[refresh] = (user, client)
        return dict(access_token=access, id_token=identity, refresh_token=refresh, token_type="Bearer",
                    expires_in=self.access_seconds)


def handler_for(provider, base):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body=b"", content_type="application/json", headers=()):
            self.send_response(status)
            origin = self.headers.get("Origin", "")
            if re.match(r"^http://127\.0\.0\.1:\d{2,5}$", origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def json(self, value, status=200):
            self.send(status, json.dumps(value).encode())

        def do_OPTIONS(self):
            self.send(204)

        def do_GET(self):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == base + "/.well-known/openid-configuration":
                return self.json(dict(issuer=provider.issuer,
                                      authorization_endpoint=provider.issuer + "/protocol/openid-connect/auth",
                                      token_endpoint=provider.issuer + "/protocol/openid-connect/token",
                                      end_session_endpoint=provider.issuer + "/protocol/openid-connect/logout",
                                      jwks_uri=provider.issuer + "/protocol/openid-connect/certs"))
            if url.path == base + "/protocol/openid-connect/certs":
                return self.json(provider.jwks())
            if url.path == base + "/protocol/openid-connect/auth":
                if (query.get("response_type") != "code" or query.get("client_id") not in CLIENTS
                        or not REDIRECT.match(query.get("redirect_uri", "")) or query.get("code_challenge_method") != "S256"
                        or not query.get("code_challenge") or not query.get("state")):
                    return self.send(400, b"invalid authorization request", "text/plain")
                flow = secrets.token_urlsafe(16)
                provider.flows[flow] = query
                links = "".join(f'<li><a id="user-{u}" href="{base}/approve?flow={flow}&user={u}">{escape(u)}</a></li>' for u in USERS)
                return self.send(200, f'<!doctype html><title>Stub IdP</title><h1>TEST-ONLY IdP</h1><ul>{links}</ul>'.encode(),
                                 "text/html; charset=utf-8")
            if url.path == base + "/approve":
                flow = provider.flows.pop(query.get("flow", ""), None)
                if not flow or query.get("user") not in USERS:
                    return self.send(400, b"unknown flow", "text/plain")
                code = secrets.token_urlsafe(24)
                provider.codes[code] = dict(flow, user=query["user"])
                target = flow["redirect_uri"] + "?" + urlencode(dict(code=code, state=flow["state"]))
                return self.send(302, headers=[("Location", target)])
            if url.path == base + "/protocol/openid-connect/logout":
                target = query.get("post_logout_redirect_uri", "")
                return self.send(302, headers=[("Location", target)]) if target.startswith("http://127.0.0.1:") \
                    else self.send(200, b"logged out", "text/plain")
            return self.send(404, b"not found", "text/plain")

        def do_POST(self):
            if urlparse(self.path).path != base + "/protocol/openid-connect/token":
                return self.send(404, b"not found", "text/plain")
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()).items()}
            if form.get("grant_type") == "authorization_code":
                flow = provider.codes.pop(form.get("code", ""), None)
                verifier = form.get("code_verifier", "")
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                if (not flow or flow["client_id"] != form.get("client_id") or flow["redirect_uri"] != form.get("redirect_uri")
                        or challenge != flow["code_challenge"]):
                    return self.json(dict(error="invalid_grant"), 400)
                return self.json(provider.tokens(flow["user"], flow["client_id"], flow.get("nonce")))
            if form.get("grant_type") == "refresh_token":
                owner = provider.refresh.pop(form.get("refresh_token", ""), None)
                if not owner or owner[1] != form.get("client_id"):
                    return self.json(dict(error="invalid_grant"), 400)
                return self.json(provider.tokens(*owner))
            return self.json(dict(error="unsupported_grant_type"), 400)
    return Handler


def serve(port, access_seconds=300):
    issuer = f"http://127.0.0.1:{port}/realms/sepehr"
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(Provider(issuer, access_seconds), "/realms/sepehr"))
    return server, issuer


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=9400)
    parser.add_argument("--access-seconds", type=int, default=300)
    args = parser.parse_args()
    server, issuer = serve(args.port, args.access_seconds)
    print(f"TEST-ONLY OIDC issuer {issuer}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
