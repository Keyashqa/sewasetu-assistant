# -*- coding: utf-8 -*-
"""
The block officer MCP server: /mcp/officer, scope `officer`.

Identity rule: a tool that records anything reads the signed-in principal in its async
body and passes the officer's username into services explicitly.
"""

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import services
from mcp_server.auth import current_principal          # noqa: F401  (decision tools, step 14)
from mcp_server.common import transport_security

INSTRUCTIONS = """\
Sewa Setu is the Government of Purvanchal's portal for the Old Age Pension: Rs 250 a month \
for residents aged 60 or above. These tools help a block officer work the application queue: \
see what is waiting, open a case, look at the age proof, and record a decision. The portal is \
the system of record; every decision appears in its audit trail.

How the office works today:
- There is a single departmental officer account. Every decision is recorded under the \
signed-in officer's name, marked as made through the assistant.
- If nobody decides within 15 days, the law approves an application automatically (deemed \
approval, by a nightly job). Overdue cases are the urgent ones.
- Decisions are final. An approved or rejected application cannot be reopened or changed; a \
rejected applicant has to apply again. Decide one application at a time, only when the \
officer clearly asks for that decision on that application.

Honesty:
- Never say or imply that a document was looked at, read or verified unless view_age_proof \
was called for that application in this conversation and returned the image. If there is no \
document, say so.
- Never say the citizen was notified unless the decision tool returned sms_sent: true. If it \
is false, say plainly that the citizen has NOT been told.
- Report eligibility warnings exactly as the tools give them; never invent a reason for or \
against an application.
- Dates are Indian: DD/MM/YYYY. Never offer a month-first reading of a date.
- State only facts these tools return. Never speculate about rules, policy or outcomes no \
tool told you."""

officer = FastMCP(
    "Sewa Setu — Old Age Pension (block officer)",
    instructions=INSTRUCTIONS,
    stateless_http=True,
    transport_security=transport_security(),
)


def _run(fn, *args, **kwargs):
    return anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


@officer.tool(
    description=(
        "What is waiting in the queue: pending counts per block, how many are past the 15-day "
        "statutory deadline, and which ones will be deemed approved in the next two days. Call "
        "this first when the officer asks what is waiting or what is urgent. No input."),
    annotations=ToolAnnotations(title="Queue summary", readOnlyHint=True))
async def get_queue_summary() -> dict:
    q = await _run(services.queue_summary)
    d = q["deemed_within_48h"]
    return {
        "pending_total": q["pending_total"], "by_block": q["by_block"],
        "overdue_15d": q["overdue_15d"],
        "deemed_within_48h": {
            "count": d["count"],
            "showing": [{"application_no": x["application_no"], "id": x["id"],
                         "block": x["block"], "deemed_on": x["deemed_on_ist"]}
                        for x in d["first_20"]]},
        "oldest_pending": q["oldest_pending_ist"],
        "note": "Anything not decided within 15 days is approved automatically by law at the "
                "next nightly run (%s). Overdue cases are deemed approved at that run."
                % q["next_nightly_run_ist"],
    }


@officer.tool(
    description=(
        "Lists applications oldest first, 20 per page. Call with no arguments for the pending "
        "queue. status: PENDING, APPROVED, DEEMED_APPROVED, REJECTED or WITHDRAWN (case does "
        "not matter). block: one of the six block names. overdue_only: true for pending ones "
        "past 15 days. search: an application number, a 10-digit mobile number, or part of a "
        "name (searches every status unless status is given). page starts at 1. "
        'Example: {"block":"Sonari","overdue_only":true}'),
    annotations=ToolAnnotations(title="List applications", readOnlyHint=True))
async def list_applications(status: str | None = None, block: str | None = None,
                            overdue_only: bool = False, search: str | None = None,
                            page: int | str = 1) -> dict:
    r = await _run(services.list_applications, status=status, block=block,
                   overdue_only=overdue_only, search=search, page=page)
    if r["status"] == "bad_status":
        return {"error": "status must be one of %s. Call again with one of them, or with no "
                         "status for the pending queue." % ", ".join(r["valid"])}
    if r["status"] == "bad_block":
        return {"error": "block must be one of %s. Call again with one of them."
                         % ", ".join(r["valid"])}
    out = {"filter": r["filter"], "total": r["total"], "page": r["page"], "pages": r["pages"],
           "showing": len(r["rows"]),
           "rows": [{"id": x["id"], "application_no": x["application_no"],
                     "name": x["applicant_name"], "mobile": x["mobile"], "block": x["block"],
                     "status": x["status"], "submitted": x["submitted_at_ist"],
                     "days_pending": x["days_pending"]} for x in r["rows"]]}
    if not r["rows"] and r["total"]:
        out["note"] = "Page %d is past the end; there are %d pages." % (r["page"], r["pages"])
    elif not r["total"]:
        out["note"] = "No applications match."
    elif r["pages"] > r["page"]:
        out["note"] = "More on page %d." % (r["page"] + 1)
    return out


@officer.tool(
    description=(
        "The full record of one application, its history, the recorded facts about its age "
        "proof, and any eligibility problems the officer should see before deciding. Identify "
        "it by application_id (the id the other tools return) or application_no (e.g. "
        'SSP26540132) — exactly one. Example: {"application_no":"SSP26540132"}'),
    annotations=ToolAnnotations(title="Open a case", readOnlyHint=True))
async def get_application(application_id: int | None = None,
                          application_no: str | None = None) -> dict:
    if (application_id is None) == (not application_no):
        return {"error": "Give exactly one of application_id or application_no."}
    r = await _run(services.get_application, application_id=application_id,
                   application_no=application_no)
    if r["status"] == "not_found":
        return {"error": "No application with that id or number. Check it with "
                         "list_applications(search=...)."}
    a = r["application"]
    if not a["doc_attached"]:
        document = {"attached": False, "note": "No age-proof document is attached."}
    elif r["document"]["recorded"]:
        d = r["document"]
        document = {"attached": True, "recorded": True, "original_name": d["original_name"],
                    "sha256": d["sha256"], "byte_size": d["byte_size"],
                    "content_type": d["content_type"], "uploaded": d["uploaded_at_ist"],
                    "source": d["source"],
                    "note": "Recorded when the file arrived. Call view_age_proof to see it."}
    else:
        document = {"attached": True, "recorded": False, "reason": r["document"]["reason"],
                    "note": "Call view_age_proof to see it."}
    return {
        "id": a["id"], "application_no": a["application_no"], "name": a["applicant_name"],
        "mobile": a["mobile"], "date_of_birth": a["date_of_birth"], "age_today": a["age_today"],
        "gender": a["gender"], "marital_status": a["marital_status"],
        "husband_name": a["husband_name"], "village": a["village"], "block": a["block"],
        "bank_account": a["bank_account"], "ifsc": a["ifsc"], "status": a["app_status"],
        "submitted": a["submitted_at_ist"], "decided": a["decided_at_ist"],
        "decided_by": a["decided_by"], "days_pending": a["days_pending"],
        "days_to_decision": a["days_to_decision"], "deemed_on": a["deemed_on_ist"],
        "document": document,
        "warnings": r["warnings"] or ["No eligibility problems found."],
        "history": r["history"],
    }
