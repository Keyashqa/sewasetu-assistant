# -*- coding: utf-8 -*-
"""The block officer MCP server: /mcp/officer, scope `officer`. Tools arrive in steps 12-14."""

from mcp.server.fastmcp import FastMCP

from mcp_server.common import transport_security

officer = FastMCP(
    "Sewa Setu — Old Age Pension (block officer)",
    instructions=(
        "Helps a block officer work the Old Age Pension queue on the Sewa Setu portal: "
        "see what is waiting, open a case, read the age proof, and record an approve or "
        "reject decision in the officer's name. One application at a time."),
    stateless_http=True,
    transport_security=transport_security(),
)
