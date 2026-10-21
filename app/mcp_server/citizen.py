# -*- coding: utf-8 -*-
"""The citizen MCP server: /mcp/citizen, scope `citizen`. Tools arrive in steps 8-10."""

from mcp.server.fastmcp import FastMCP

from mcp_server.common import transport_security

citizen = FastMCP(
    "Sewa Setu — Old Age Pension (citizen)",
    instructions=(
        "Helps a resident of Purvanchal apply for the Old Age Pension (Rs 250 a month, "
        "age 60 and above) on the Sewa Setu portal and follow up the application. "
        "The signed-in mobile number is the applicant's; every action is for that number."),
    stateless_http=True,
    transport_security=transport_security(),
)
