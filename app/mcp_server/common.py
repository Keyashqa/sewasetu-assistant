# -*- coding: utf-8 -*-
"""Settings shared by both MCP servers."""

from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings

from mcp_server.auth import ISSUER


def transport_security():
    """DNS-rebinding protection that accepts the public host as well as loopback.
    The SDK's default allows only loopback hosts, which is right locally and would
    refuse every request once PUBLIC_BASE_URL is a real hostname."""
    u = urlparse(ISSUER)
    origin = "%s://%s" % (u.scheme, u.netloc)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted({u.netloc, "localhost:*", "127.0.0.1:*", "[::1]:*"}),
        allowed_origins=sorted({origin, "http://localhost:*", "http://127.0.0.1:*",
                                "http://[::1]:*"}),
    )
