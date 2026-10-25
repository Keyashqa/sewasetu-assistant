"""Browser-like sign-in to the portal's OAuth server, as a citizen or the officer.

One requests.Session per sign-in (the portal binds a request id to the browser cookie).
OTPs are read from the gateway and kept in memory only; callers get them back so the
checks can make sure no OTP reached the chat.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from . import gateway
from .config import BASE_URL, REDIRECT_URI, admin_password

ISSUER = BASE_URL


def register_client(name="Sewa Setu eval harness"):
    r = requests.post(BASE_URL + "/oauth/register", json={
        "client_name": name, "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none"}, timeout=10)
    r.raise_for_status()
    return r.json()["client_id"]


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt_claims(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


class Grant:
    """Access + refresh token for one signed-in person; refreshes itself."""

    def __init__(self, client_id, resource, tok):
        self.client_id, self.resource = client_id, resource
        self._set(tok)

    def _set(self, tok):
        self.access, self.refresh_token = tok["access_token"], tok["refresh_token"]
        self.claims = jwt_claims(self.access)
        self.session_ends = tok.get("session_ends")

    def seconds_left(self):
        return self.claims["exp"] - time.time()

    def refresh(self):
        r = requests.post(BASE_URL + "/oauth/token", data={
            "grant_type": "refresh_token", "refresh_token": self.refresh_token,
            "client_id": self.client_id, "resource": self.resource}, timeout=10)
        if r.status_code != 200:
            raise RuntimeError("refresh failed: %s" % r.text[:200])
        self._set(r.json())

    def fresh(self, min_left=300):
        if self.seconds_left() < min_left:
            self.refresh()
        return self.access


def sign_in(client_id, resource, scope, mobile=None):
    """Returns (Grant, otps); otps lists every OTP handled, kept in memory only."""
    s = requests.Session()
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(16)
    r = s.get(BASE_URL + "/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256", "state": state, "scope": scope, "resource": resource},
        allow_redirects=False, timeout=10)
    assert r.status_code == 302 and "/oauth/login" in r.headers["Location"], r.text[:300]
    login_url = urljoin(BASE_URL, r.headers["Location"])
    otps = []
    if scope == "citizen":
        after = gateway.last_id(mobile)
        r = s.post(login_url, data={"mobile": mobile}, allow_redirects=False, timeout=10)
        assert r.status_code == 200, r.status_code
        otp = gateway.wait_otp(mobile, after)
        otps.append(otp)
        r = s.post(login_url, data={"otp": otp}, allow_redirects=False, timeout=10)
    else:
        r = s.post(login_url, data={"username": "admin", "password": admin_password()},
                   allow_redirects=False, timeout=10)
    assert r.status_code == 302 and "/oauth/consent" in r.headers.get("Location", ""), "login failed"
    r = s.post(urljoin(BASE_URL, r.headers["Location"]), data={"decision": "allow"},
               allow_redirects=False, timeout=10)
    assert r.status_code == 302, r.status_code
    q = parse_qs(urlparse(r.headers["Location"]).query)
    assert q.get("state") == [state], "state mismatch"
    assert q.get("iss") == [ISSUER], "iss mismatch"
    r = requests.post(BASE_URL + "/oauth/token", data={
        "grant_type": "authorization_code", "code": q["code"][0], "code_verifier": verifier,
        "client_id": client_id, "redirect_uri": REDIRECT_URI, "resource": resource}, timeout=10)
    r.raise_for_status()
    g = Grant(client_id, resource, r.json())
    want_sub = ("citizen:" + mobile) if scope == "citizen" else "officer:admin"
    assert (g.claims["aud"], g.claims["scope"], g.claims["sub"]) == (resource, scope, want_sub), g.claims
    return g, otps
