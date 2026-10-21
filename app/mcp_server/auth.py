# -*- coding: utf-8 -*-
"""
Authentication for the two MCP servers.

The portal is the OAuth authorization server; these servers are protected resources
(RFC 9728). A request carries a portal-issued RS256 JWT. It is verified against the
portal's JWKS, its `iss` must be the portal, its `aud` must be exactly this server's
canonical URL, and its role and scope must be this server's role. The result is a
Principal, stored in a ContextVar for the duration of the request.

Every 401 carries the full challenge (error, error_description, scope,
resource_metadata) so a client knows where to sign in and for which scope.
"""

import json
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

import jwt
from jwt import PyJWKClient
from starlette.responses import JSONResponse, Response

import app as portal              # noqa: F401  must precede `import oauth` (circular import)
import oauth

ISSUER = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
# The JWKS is fetched over the internal network: inside this container the public
# address may not route back to the portal (locally, localhost is this container).
JWKS_URL = os.environ.get("JWKS_URL", "http://app:8000/.well-known/jwks.json")

CITIZEN_URL = ISSUER + "/mcp/citizen"
OFFICER_URL = ISSUER + "/mcp/officer"
CANONICAL = {"citizen": CITIZEN_URL, "officer": OFFICER_URL}
RESOURCE_NAMES = {"citizen": "Sewa Setu — Old Age Pension (citizen)",
                  "officer": "Sewa Setu — Old Age Pension (block officer)"}

JWKS = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=600)


@dataclass
class Principal:
    role: str                    # "citizen" | "officer"
    subject: str                 # "citizen:9876543210" | "officer:admin"
    mobile: Optional[str]        # citizen only, parsed from sub — never from tool input
    officer: Optional[str]
    kind: str                    # "access" | "program"
    session_ends: Optional[int]


class AuthError(Exception):
    status = 401

    def __init__(self, description):
        super().__init__(description)
        self.description = description


class Unauthorized(AuthError):
    status = 401


class Forbidden(AuthError):
    status = 403


def authenticate(header, expected_role, canonical_url):
    if not header or not header.startswith("Bearer "):
        raise Unauthorized("Sign in to use the Sewa Setu %s service." % expected_role)
    token = header[7:].strip()
    try:
        key = JWKS.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=ISSUER,
                            options={"verify_aud": False,
                                     "require": ["iss", "sub", "aud", "exp", "iat"]})
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Your sign-in has ended. Please sign in again.")
    except jwt.PyJWKClientConnectionError:
        raise Unauthorized("The sign-in service could not be reached. Please try again.")
    except jwt.PyJWTError:
        raise Unauthorized("This sign-in is not valid here. Please sign in again.")

    # The portal accepts any `resource` verbatim, so the audience check is ours, exact
    # apart from a trailing slash.
    aud = claims["aud"]
    if isinstance(aud, list):
        aud = aud[0] if len(aud) == 1 else ""
    if str(aud).rstrip("/") != canonical_url:
        other = {v: k for k, v in CANONICAL.items()}.get(str(aud).rstrip("/"))
        if other:
            raise Forbidden("This token was issued for the %s service. Reconnect with the "
                            "%s MCP server." % (other, expected_role))
        raise Forbidden("This token was issued for a different service. Reconnect with "
                        "the %s MCP server." % expected_role)
    if claims.get("role") != expected_role or claims.get("scope") != expected_role:
        raise Forbidden("This token is for the %s service. Reconnect with the %s MCP "
                        "server." % (claims.get("role"), expected_role))
    if claims.get("kind") == "program":
        if expected_role != "officer":
            raise Forbidden("Program tokens are for the officer service only.")
        if not oauth.verify_program_jti(claims.get("jti", "")):
            raise Unauthorized("This program token has been revoked. Please sign in again "
                               "or ask an administrator for a new token.")
    if claims.get("session_ends") and claims["session_ends"] <= time.time():
        raise Unauthorized("Your sign-in has ended. Please sign in again.")

    sub = claims["sub"]
    return Principal(role=expected_role, subject=sub,
                     mobile=sub.split(":", 1)[1] if sub.startswith("citizen:") else None,
                     officer=sub.split(":", 1)[1] if sub.startswith("officer:") else None,
                     kind=claims.get("kind", "access"),
                     session_ends=claims.get("session_ends"))


# ---------------------------------------------------------------------------
# The identity of the current request
# ---------------------------------------------------------------------------

_PRINCIPAL: ContextVar[Optional[Principal]] = ContextVar("sewasetu_principal", default=None)


def set_principal(p):
    return _PRINCIPAL.set(p)


def reset_principal(token):
    _PRINCIPAL.reset(token)


def current_principal():
    """Read in the async tool body, on the request's own task — never in a worker
    thread. Pass the identity explicitly into services."""
    p = _PRINCIPAL.get()
    if p is None:
        raise RuntimeError("no authenticated principal for this request")
    return p


# ---------------------------------------------------------------------------
# Challenge and metadata documents
# ---------------------------------------------------------------------------

def prm_url(role):
    return ISSUER + "/.well-known/oauth-protected-resource/mcp/" + role


def _quote(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def challenge_response(err, role):
    if err.status == 403:
        error = "insufficient_scope"
    else:
        error = "invalid_token"
    header = "Bearer error=%s, error_description=%s, scope=%s, resource_metadata=%s" % (
        _quote(error), _quote(err.description), _quote(role), _quote(prm_url(role)))
    return JSONResponse({"error": error, "error_description": err.description},
                        status_code=err.status, headers={"WWW-Authenticate": header})


def protected_resource_metadata(role):
    return {
        "resource": CANONICAL[role],
        "authorization_servers": [ISSUER],
        "jwks_uri": ISSUER + "/.well-known/jwks.json",
        "scopes_supported": [role],
        "bearer_methods_supported": ["header"],
        "resource_name": RESOURCE_NAMES[role],
        "resource_documentation": ISSUER + "/about",
    }


def prm_response(role):
    return Response(json.dumps(protected_resource_metadata(role), ensure_ascii=False),
                    media_type="application/json",
                    headers={"Access-Control-Allow-Origin": "*"})
