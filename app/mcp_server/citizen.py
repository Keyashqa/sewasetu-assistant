# -*- coding: utf-8 -*-
"""
The citizen MCP server: /mcp/citizen, scope `citizen`.

Identity rule: every tool reads the signed-in principal in its async body and passes
the mobile into services explicitly. No tool takes a mobile number as input.
"""

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import services
from mcp_server import fmt
from mcp_server.auth import current_principal
from mcp_server.common import transport_security

citizen = FastMCP(
    "Sewa Setu — Old Age Pension (citizen)",
    instructions=(
        "Helps a resident of Purvanchal apply for the Old Age Pension (Rs 250 a month, "
        "age 60 and above) on the Sewa Setu portal and follow up the application. "
        "The signed-in mobile number is the applicant's; every action is for that number. "
        "Use only facts these tools return; never invent scheme rules or applicant details."),
    stateless_http=True,
    transport_security=transport_security(),
)


def _run(fn, *args, **kwargs):
    return anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


@citizen.tool(
    description=(
        "Facts about the Purvanchal Old Age Pension: the amount, who qualifies, which "
        "documents are needed, how long a decision takes, and whether the application "
        "window is open right now. Call this first when the person asks what the scheme is, "
        "who can get it, or what papers are needed. No input."),
    annotations=ToolAnnotations(title="Scheme information", readOnlyHint=True))
async def get_scheme_info() -> dict:
    s = await _run(services.scheme_info)
    return {
        "amount": "Rs %d per month" % s["amount_inr"],
        "min_age": s["min_age"],
        "residency": s["residency"],
        "documents_accepted": s["documents_accepted"],
        "formats": s["formats"],
        "decision_days": s["sla_days"],
        "deemed_approval": s["deemed_approval"],
        "window": fmt.window_text(s["window"]),
        "blocks": s["blocks"],
        "villages_by_block": s["villages_by_block"],
    }


@citizen.tool(
    description=(
        "Checks whether this person can apply: age 60 or above from their date of birth, "
        "the window still open, and whether this mobile number already has a live "
        "application. Call before collecting details. Input: date_of_birth as DD/MM/YYYY, "
        "for example 10/04/1957. Other formats are accepted and corrected."),
    annotations=ToolAnnotations(title="Check eligibility", readOnlyHint=True))
async def check_eligibility(date_of_birth: str) -> dict:
    p = current_principal()
    e = await _run(services.eligibility, p.mobile, date_of_birth)
    if e["status"] == "bad_date":
        return {"eligible": False,
                "error": "I could not read that date. Give it as DD/MM/YYYY, for example "
                         "10/04/1957."}
    if e["status"] == "future_date":
        return {"eligible": False,
                "error": "That date is in the future. Please check the year."}
    out = {"date_of_birth": e["date_of_birth"], "age": e["age"], "age_ok": e["age_ok"],
           "turns_60_on": e["turns_60_on"], "window_open": e["window"]["open"],
           "existing_application": e["existing"], "eligible": e["eligible"]}
    messages = []
    if "under_age" in e["reasons"]:
        messages.append("Age is %d. The pension is for people %d and above. They become "
                        "eligible on %s." % (e["age"], services.portal.MIN_AGE,
                                             e["turns_60_on"]))
    if "window_closed" in e["reasons"]:
        messages.append(fmt.window_closed_message(e["window"]))
    if "active_application" in e["reasons"]:
        messages.append(fmt.existing_application_message(e["existing"]))
    if e["eligible"]:
        out["next_step"] = ("Collect the details and call save_application_details. The age "
                            "proof is uploaded later with get_document_upload_link.")
    else:
        out["message"] = " ".join(messages)
        out["next_step"] = "Nothing can be filed now. Explain this to the person."
    return out
