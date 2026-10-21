# -*- coding: utf-8 -*-
"""
ASGI entrypoint for both MCP servers: uvicorn mcp_server.main:app

Each server is served on its exact canonical path (/mcp/citizen, /mcp/officer) by its
own MCPEndpoint, which authenticates and then hands the raw ASGI scope to that
server's session manager. No redirects, no trailing slashes, no path matching inside
the MCP layer. The protected-resource metadata documents (RFC 9728) are served here
too, since they describe these servers.
"""

import app as portal                      # noqa: F401  MUST be first: oauth imports app
import services                           # noqa: F401,E402

from contextlib import AsyncExitStack, asynccontextmanager    # noqa: E402

from starlette.applications import Starlette                  # noqa: E402
from starlette.responses import JSONResponse                  # noqa: E402
from starlette.routing import Route                           # noqa: E402

from mcp_server.auth import (CANONICAL, CITIZEN_URL, OFFICER_URL, AuthError,  # noqa: E402
                             authenticate, challenge_response, prm_response,
                             reset_principal, set_principal)
from mcp_server.citizen import citizen                        # noqa: E402
from mcp_server.officer import officer                        # noqa: E402

# mcp 1.x builds a server's session manager inside streamable_http_app(). The app it
# returns is not used (its router would expect to be mounted); only the manager is.
citizen.streamable_http_app()
officer.streamable_http_app()


def _get_header(scope, name):
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1")
    return None


class MCPEndpoint:
    """One ASGI app per MCP server: authenticate, then hand the raw scope straight to the
    session manager. No internal path matching, so the mount prefix is irrelevant.
    An instance (not a function) so Starlette treats it as an ASGI app, not a view."""

    def __init__(self, server, role, canonical_url):
        self.server, self.role, self.canonical = server, role, canonical_url

    async def __call__(self, scope, receive, send):
        header = _get_header(scope, b"authorization")
        try:
            principal = authenticate(header, self.role, self.canonical)
        except AuthError as e:
            await challenge_response(e, self.role)(scope, receive, send)
            return
        token = set_principal(principal)
        try:
            await self.server.session_manager.handle_request(scope, receive, send)
        finally:
            reset_principal(token)


@asynccontextmanager
async def lifespan(app):
    # Each session manager may be run exactly once per process; both live as long as
    # the app does.
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(citizen.session_manager.run())
        await stack.enter_async_context(officer.session_manager.run())
        yield


async def prm_citizen(request):
    return prm_response("citizen")


async def prm_officer(request):
    return prm_response("officer")


async def prm_by_query(request):
    wanted = (request.query_params.get("resource") or "").rstrip("/")
    for role, url in CANONICAL.items():
        if wanted == url:
            return prm_response(role)
    return JSONResponse({"error": "not_found",
                         "error_description": "resource must be one of: "
                                              + ", ".join(CANONICAL.values())},
                        status_code=404, headers={"Access-Control-Allow-Origin": "*"})


routes = [
    Route("/mcp/citizen", MCPEndpoint(citizen, "citizen", CITIZEN_URL),
          methods=["POST", "GET", "DELETE"]),
    Route("/mcp/officer", MCPEndpoint(officer, "officer", OFFICER_URL),
          methods=["POST", "GET", "DELETE"]),
    Route("/.well-known/oauth-protected-resource/mcp/citizen", prm_citizen, methods=["GET"]),
    Route("/.well-known/oauth-protected-resource/mcp/officer", prm_officer, methods=["GET"]),
    Route("/.well-known/oauth-protected-resource", prm_by_query, methods=["GET"]),
    Route("/mcp/citizen/.well-known/oauth-protected-resource", prm_citizen, methods=["GET"]),
    Route("/mcp/officer/.well-known/oauth-protected-resource", prm_officer, methods=["GET"]),
]
app = Starlette(routes=routes, lifespan=lifespan)
# Never answer /mcp/citizen/ with a 307 to /mcp/citizen (or the reverse): the
# canonical path is served, anything else is a plain 404.
app.router.redirect_slashes = False
