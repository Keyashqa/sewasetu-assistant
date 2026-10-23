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
from mcp_server.auth import current_principal
from mcp_server.common import transport_security

INSTRUCTIONS = """\
Sewa Setu is the Government of Purvanchal's portal for the Old Age Pension: Rs 250 a month \
for residents aged 60 or above. These tools help a block officer work the application queue: \
see what is waiting, open a case, get the link to its age-proof document, and record a \
decision. The portal is the system of record; every decision appears in its audit trail.

How the office works today:
- There is a single departmental officer account. Every decision is recorded under the \
signed-in officer's name, marked as made through the assistant.
- If nobody decides within 15 days, the law approves an application automatically (deemed \
approval, by a nightly job). Overdue cases are the urgent ones.
- Decisions are final. An approved or rejected application cannot be reopened or changed; a \
rejected applicant has to apply again.

Age-proof documents:
- You never see documents. get_age_proof_link and get_application give a link that the \
officer opens in their own browser (portal login required). When you open a case, or when the \
officer asks for the document, give them the link. If no document is attached, say so.
- Never describe, guess or comment on what a document shows, and never say or imply that you \
have seen, read or checked one.

You assist; you do not investigate:
- Do what the officer asks. Relay the record and the warnings the tools return (such as age \
under 60, no document, an invalid IFSC, a village and block that do not match), one short \
line each, without commentary.
- Never cross-reference other applications, analyse patterns (bank accounts, phone numbers, \
timing, relatives), speculate about fraud or conflicts of interest, or second-guess the \
officer's decision.

Decisions:
- When the officer says to approve or reject a specific application, call the tool. Do not ask \
for confirmation again. Never decide on your own initiative or as a follow-on step; one \
application at a time.
- approve_application needs that application's application_id and application_no. The portal \
refuses approval when the applicant is under 60 today or no age proof is attached, as the \
counter does; if it refuses, tell the officer the reason it gives.
- reject_application needs the officer's reason and their own words. If they say "reject it" \
without a reason, ask for the reason (you may list the four canonical reasons). Map it to the \
matching canonical reason (for example "the account isn't in her name" is "bank account not \
in applicant's name"); use "other" only when none of the four fits.

Audit notes are the officer's words only:
- approve_application note: only words the officer asked to have recorded, copied verbatim. \
If they gave none, leave note out.
- reject_application officer_reason_quote: the officer's own words giving or confirming the \
reason, verbatim. note: only with reason "other", the officer's explanation, verbatim.
- Never add your own note, summary, observation or analysis to any decision.

Honesty:
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
        "proof with the link the officer opens to see it, and the eligibility warnings computed "
        "from the record. Identify it by application_id (the id the other tools return) or "
        "application_no (e.g. SSP26540132) — exactly one. "
        'Example: {"application_no":"SSP26540132"}'),
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
    else:
        document = {"attached": True, "link": services.document_url(a["id"]),
                    **_provenance(r["document"]), "note": LINK_NOTE}
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


LINK_NOTE = ("Give this link to the officer to open in their browser (portal login "
             "required). You cannot see the document.")
SOURCE_TEXT = {
    "upload_token": "the upload link issued to the application's mobile number",
    "demo_seed": "seed_demo_queue.py — DEMO DATA, not a real document",
}


def _provenance(p):
    """The recorded facts about how a document arrived, or why there are none."""
    if not p["recorded"]:
        return {"provenance": "not recorded (%s)" % p["reason"]}
    return {"provenance": {"original_filename": p["original_name"], "type": p["content_type"],
                           "byte_size": p["byte_size"], "sha256": p["sha256"],
                           "uploaded": p["uploaded_at_ist"],
                           "source": SOURCE_TEXT.get(p["source"], p["source"])}}


@officer.tool(
    description=(
        "Gives the link to an application's age-proof document, for the officer to open in "
        "their own browser (portal login required), with what was recorded when the file "
        "arrived: original filename, type, size, SHA-256, upload time and source. Give this "
        "link to the officer to open in their browser; you cannot see the document and must "
        "never describe, guess or comment on its contents. Identify the application by "
        'application_id or application_no — exactly one. Example: {"application_id":100021}'),
    annotations=ToolAnnotations(title="Age-proof link", readOnlyHint=True))
async def get_age_proof_link(application_id: int | None = None,
                             application_no: str | None = None) -> dict:
    if (application_id is None) == (not application_no):
        return {"error": "Give exactly one of application_id or application_no."}
    d = await _run(services.age_proof_record, application_id=application_id,
                   application_no=application_no)
    s = d["status"]
    if s == "not_found":
        return {"error": "No application with that id or number. Check it with "
                         "list_applications(search=...)."}
    out = {"application_id": d["application_id"], "application_no": d["application_no"]}
    if s == "no_document":
        return dict(out, attached=False, note="No document attached.")
    out.update(attached=True, link=d["url"])
    if s == "missing_file":
        return dict(out, problem="The record names a file that is missing on the server, so the "
                                 "link will not open. Tell the officer.")
    if s == "refused":
        return dict(out, problem="The recorded file path is outside the upload store, so the "
                                 "portal will not serve it. Tell the officer.")
    if s == "too_large":
        return dict(out, problem="The file is larger than 10 MB, so the portal will not serve "
                                 "it. Tell the officer.")
    p = d["provenance"]
    out.update(_provenance(p))
    if not p["recorded"]:
        out["file_on_server"] = {"type": d["mimetype"], "byte_size": d["byte_size"],
                                 "sha256": d["sha256"]}
    elif p["sha256"] != d["sha256"] or p["byte_size"] != d["byte_size"]:
        out["integrity_warning"] = ("The file on the server no longer matches what was recorded "
                                    "at upload (now %s bytes, SHA-256 %s)."
                                    % (format(d["byte_size"], ","), d["sha256"]))
    out["note"] = LINK_NOTE
    return out


def _decision_error(r, application_id, application_no):
    s = r["status"]
    if s == "not_found":
        return "No application with id %s. Nothing was changed — check with list_applications." \
               % application_id
    if s == "no_match":
        return ("application_id %s is %s, not %s. Nothing was changed — check with "
                "get_application." % (application_id, r["application_no"], application_no))
    if s == "not_pending":
        return ("Only a pending application can be decided; %s is %s. Nothing was changed."
                % (r["application_no"], r.get("current", "already decided")))
    if s == "reason_required":
        return ("A reason is required to reject, and it must be the officer's. Ask the officer "
                "which applies (you may list these): %s ('other' needs the "
                "explanation in note). Nothing was changed."
                % "; ".join('"%s"' % x for x in services.REJECTION_REASONS))
    if s == "blocked":
        msg = ("Not approved. %s The counter would refuse this application, so it cannot be "
               "approved through the assistant." % " ".join(r["warnings"]))
        return msg
    return "Unexpected result: %s. Nothing was changed." % s


def _decided(r, verb):
    out = {"status": verb, "application_no": r["application_no"],
           "decided_by": r["decided_by"], "decided_at": r["decided_at_ist"],
           "recorded_in_audit_as": r["actor"], "citizen_notified": r["sms_sent"]}
    if r["note"]:
        out["recorded_reason_or_note"] = r["note"]
    if r["sms_sent"]:
        out["message"] = "%s. An SMS has been sent to %s." % (verb.capitalize(), r["mobile"])
    else:
        out["message"] = ("%s, but the SMS could not be sent — the applicant has NOT been "
                          "notified." % verb.capitalize())
    soft = [w for w in r["warnings"]]
    if soft:
        out["warnings_on_record"] = soft
    return out


@officer.tool(
    description=(
        "Approves a pending application in the officer's name. This is final: an approved "
        "application cannot be reopened. Only call when the officer has explicitly said to "
        "approve this specific application — never on your own judgement, even if every check "
        "passed. Pass both application_id and application_no — they must "
        "refer to the same application; that is the confirmation step, so do not ask the "
        "officer to confirm again. note (optional): only words the officer asked "
        "to have recorded, copied verbatim; never your own words. If the officer gave "
        "none, leave it out. The portal refuses approval when the applicant is under 60 "
        "today or no age proof is attached, as the counter does; then tell the officer the "
        "reason it gives. "
        'Example: {"application_id":100021,"application_no":"SSP26540132"}'),
    annotations=ToolAnnotations(title="Approve (final)", readOnlyHint=False,
                                destructiveHint=True, idempotentHint=False))
async def approve_application(application_id: int, application_no: str,
                              note: str | None = None) -> dict:
    p = current_principal()
    r = await _run(services.decide, application_id=application_id, decision="APPROVED",
                   reason=note or "", note="", officer=p.officer, channel="mcp",
                   expect_application_no=application_no)
    if r["status"] != "ok":
        return {"approved": False, "status": r["status"],
                "message": _decision_error(r, application_id, application_no)}
    return _decided(r, "approved")


@officer.tool(
    description=(
        "Rejects a pending application with a reason recorded against the officer's name. This "
        "is final: the applicant would have to apply again. Only call when the officer has "
        "asked to reject this application AND given their reason. If they said \"reject it\" "
        "without a reason, ask them for it (you may list the four reasons below); never choose "
        "one yourself. Do not ask for confirmation again once they have. reason: map the officer's stated reason to one of \"bank account not in "
        "applicant's name\", \"duplicate of an earlier beneficiary record\", \"age proof "
        "document illegible\", \"age proof does not match stated date of birth\"; use "
        "\"other\" only when none fits; then note is the officer's explanation, verbatim. "
        "Otherwise leave note out: never add your own note or observation. "
        "officer_reason_quote (required): the officer's own words giving or confirming the "
        "reason, copied verbatim — never your own observation or a paraphrase. It is recorded "
        "in the audit trail. Pass application_id and application_no; they must match. The "
        "reason is sent to the applicant by SMS. "
        'Example: {"application_id":100021,"application_no":"SSP26540132",'
        '"reason":"bank account not in applicant\'s name",'
        '"officer_reason_quote":"reject it, the account isn\'t in her name"}'),
    annotations=ToolAnnotations(title="Reject (final)", readOnlyHint=False,
                                destructiveHint=True, idempotentHint=False))
async def reject_application(application_id: int, application_no: str,
                             reason: str | None = None, officer_reason_quote: str | None = None,
                             note: str | None = None) -> dict:
    p = current_principal()
    given = (reason or "").strip().strip("'\"").lower()
    note = (note or "").strip()
    quote = " ".join((officer_reason_quote or "").split()).strip("'\"")
    canonical = {x.lower(): x for x in services.REJECTION_REASONS}
    if not given:
        return {"rejected": False, "status": "reason_required",
                "message": _decision_error({"status": "reason_required"}, application_id,
                                           application_no)}
    if not quote:
        return {"rejected": False, "status": "quote_required",
                "message": "officer_reason_quote is required: the officer's own words giving or "
                           "confirming the reason, verbatim. If the officer has not said why, ask "
                           "them. Nothing was changed."}
    if given not in canonical:
        return {"rejected": False, "status": "bad_reason",
                "message": "reason must be one of: %s. For anything else use \"other\" and put "
                           "the explanation in note. Nothing was changed."
                           % "; ".join('"%s"' % x for x in services.REJECTION_REASONS)}
    if canonical[given] == "other":
        if not note:
            return {"rejected": False, "status": "note_required",
                    "message": "Give the reason in note when reason is 'other'. Nothing was "
                               "changed."}
        reason_text, note_text = note, ""
    else:
        reason_text, note_text = canonical[given], note
    # audit note: <reason> — Officer: "<quote>"[ — <note>]
    note_text = " — ".join(x for x in ('Officer: "%s"' % quote, note_text) if x)
    r = await _run(services.decide, application_id=application_id, decision="REJECTED",
                   reason=reason_text, note=note_text, officer=p.officer, channel="mcp",
                   expect_application_no=application_no)
    if r["status"] != "ok":
        return {"rejected": False, "status": r["status"],
                "message": _decision_error(r, application_id, application_no)}
    out = _decided(r, "rejected")
    out["reason"] = reason_text
    return out
