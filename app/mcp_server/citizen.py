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


@citizen.tool(
    description=(
        "The status of this mobile number's application, in plain words. Use it whenever the "
        "person asks whether it has been approved or what is happening, and after submitting. "
        "No input — it only ever reads the application belonging to the signed-in mobile "
        "number."),
    annotations=ToolAnnotations(title="My application status", readOnlyHint=True))
async def get_my_application() -> dict:
    p = current_principal()
    a = await _run(services.my_application, p.mobile)
    draft = a.get("draft")
    draft_note = None
    if draft:
        draft_note = {"missing": draft["missing"], "document_attached": draft["doc_attached"],
                      "ready_to_submit": draft["ready_to_submit"],
                      "kept_until": draft["expires_at"]}
    if not a["found"]:
        out = {"found": False,
               "message": "No application on this mobile number yet. Call check_eligibility "
                          "to start one."}
        if draft_note:
            out["draft_in_progress"] = draft_note
            out["message"] = ("No application has been filed on this mobile number yet, but "
                              "details are saved in a draft. Continue with "
                              "save_application_details.")
        return out
    means = fmt.STATUS_MEANING.get(a["status"], a["status"])
    if a["status"] == "REJECTED":
        means += " Reason recorded: %s. The applicant may apply again." % (
            a["reason"] or "none recorded")
    out = {"found": True, "application_number": a["application_no"], "status": a["status"],
           "means": means, "submitted": a["submitted_at_ist"], "decided": a["decided_at_ist"],
           "village": a["village"], "block": a["block"],
           "age_proof_attached": a["doc_attached"]}
    if a["status"] == "PENDING":
        out["auto_approval_if_no_decision"] = a["deemed_date_ist"]
    if draft_note and a["status"] in ("WITHDRAWN", "REJECTED"):
        out["draft_in_progress"] = draft_note
    return out


@citizen.tool(
    description=(
        "Withdraws a pending application so the person can apply again. Only their own, only "
        "while it is still pending. Input: application_no (e.g. SSP26540132) and confirm must "
        "be true. Ask the person out loud before calling this; it cannot be undone."),
    annotations=ToolAnnotations(title="Withdraw the application", readOnlyHint=False,
                                destructiveHint=True, idempotentHint=False))
async def withdraw_application(application_no: str, confirm: bool) -> dict:
    p = current_principal()
    if confirm is not True:
        return {"withdrawn": False,
                "message": "Not withdrawn. Ask the applicant to confirm first."}
    number = (application_no or "").strip().upper()
    if not number:
        return {"withdrawn": False,
                "message": "Give the application number, for example SSP26540132. "
                           "get_my_application shows it."}
    r = await _run(services.withdraw, p.mobile, application_no=number,
                   actor="applicant:%s" % p.mobile)
    if r["status"] == "ok":
        return {"withdrawn": True, "status": "WITHDRAWN",
                "application_number": r["application_no"],
                "next": "You may submit a new application for this mobile number now."}
    if r["status"] == "not_found":
        return {"withdrawn": False,
                "message": "That application number does not belong to this mobile number. "
                           "Check it with get_my_application."}
    return {"withdrawn": False,
            "message": "Only a pending application can be withdrawn. This one is %s."
                       % r["current"]}


def _ifsc_problem(ifsc):
    return ("The portal accepts an 11-character IFSC like SBIN0003077. '%s' is %d characters, "
            "so it will be refused — please check the passbook, or clear it by sending ifsc "
            "as an empty string, as IFSC is not mandatory." % (ifsc, len(ifsc)))


@citizen.tool(
    description=(
        "Saves or updates the applicant's details on the server. Send any subset of fields — "
        "call it several times as the conversation goes. It tells you what is saved, what is "
        "still missing and what is wrong. Fields: full_name, date_of_birth (DD/MM/YYYY), "
        "gender (Male/Female/Other), marital_status (Married/Unmarried/Widowed), "
        "husband_name (only if widowed), village (the block is filled in for known villages), "
        "block (one of the six from get_scheme_info), bank_account (9-18 digits), "
        "ifsc (11 characters, e.g. SBIN0003077; optional). Only send what the applicant "
        "actually said; never guess a value. "
        'Example: {"full_name":"Sewali Gogoi","date_of_birth":"10/04/1957","village":"Kathoni"}'),
    annotations=ToolAnnotations(title="Save applicant details", readOnlyHint=False,
                                destructiveHint=False, idempotentHint=True))
async def save_application_details(full_name: str | None = None,
                                   date_of_birth: str | None = None,
                                   gender: str | None = None,
                                   marital_status: str | None = None,
                                   husband_name: str | None = None,
                                   village: str | None = None,
                                   block: str | None = None,
                                   bank_account: str | None = None,
                                   ifsc: str | None = None) -> dict:
    p = current_principal()
    given = {k: v for k, v in (("full_name", full_name), ("date_of_birth", date_of_birth),
                               ("gender", gender), ("marital_status", marital_status),
                               ("husband_name", husband_name), ("village", village),
                               ("block", block), ("bank_account", bank_account),
                               ("ifsc", ifsc)) if v is not None}
    if not given:
        return {"error": "No fields were given. Send at least one field the applicant told you."}
    r = await _run(services.save_draft, p.mobile, given)
    saved_ifsc = r["saved"].get("ifsc") or ""
    problems = [_ifsc_problem(saved_ifsc) if pr.startswith("IFSC must be") else pr
                for pr in r["problems"]]
    out = {"saved": r["saved"], "missing": r["missing"], "problems": problems,
           "corrections": r["corrections"], "warnings": r["warnings"],
           "suggested_block": r["suggested_block"], "ready_to_submit": r["ready_to_submit"]}
    if problems:
        out["next_step"] = "Ask the applicant about each problem, then save again."
    elif [m for m in r["missing"] if m != services.DOC_MISSING]:
        out["next_step"] = "Ask the applicant for the missing details."
    elif services.DOC_MISSING in r["missing"]:
        out["next_step"] = "Details are complete. Call get_document_upload_link for the age proof."
    else:
        out["next_step"] = ("Read all the details back to the applicant, read the declaration, "
                            "and call submit_application only after they say yes.")
    return out


@citizen.tool(
    description=(
        "Gives a link for uploading the age proof (birth certificate, school leaving "
        "certificate or Voter ID). The person opens it on a phone, or whoever is helping them "
        "uploads it with curl. A document is required before the application can be "
        "submitted. No input.\n\n"
        "Only a real document provided by the applicant may be uploaded — a photo or scan of "
        "the actual certificate they hold. You must never create, generate, draw, edit, fill "
        "in, convert or substitute a document, and never upload a file from anywhere other "
        "than the applicant. If they do not have their age proof to hand, give them the link "
        "and stop: the application waits until they upload it. An invented document is a "
        "false government record."),
    annotations=ToolAnnotations(title="Get an upload link", readOnlyHint=False,
                                destructiveHint=False, idempotentHint=True))
async def get_document_upload_link() -> dict:
    p = current_principal()
    t = await _run(services.issue_upload_token, p.mobile)
    out = {"upload_url": t["url"], "expires": t["expires_at_ist"],
           "document_attached": t["doc_attached"],
           "curl_example": "curl -F document=@age-proof.jpg %s" % t["url"],
           "instructions": "Open the link on the phone, choose the photo of the birth "
                           "certificate or Voter ID, and press Upload. JPG, PNG or PDF, "
                           "up to 5 MB.",
           "recorded": "Every upload is recorded with its SHA-256 hash, size, original "
                       "filename and time, and the block officer sees all four."}
    prov = t.get("provenance") or {}
    if t["doc_attached"]:
        out.update(document_name=t["doc_name"], sha256=prov.get("sha256"),
                   byte_size=prov.get("byte_size"), uploaded=prov.get("uploaded_at_ist"),
                   note="A document is already attached. Uploading again replaces it.")
    return out


@citizen.tool(
    description=(
        "Files the application with the portal. Only call after the details are complete, "
        "the age proof is uploaded, and you have read the declaration back to the person and "
        "they said yes. Input: confirm_declaration must be true, meaning the applicant has "
        "confirmed the information is correct and consents to the department verifying it.\n\n"
        "Everything filed must have come from the applicant. Never invent, guess or fill in a "
        "detail they did not give you — not a name, not a date of birth, not a village, not a "
        "bank account, and above all not the age-proof document, which must be a file the "
        "applicant themselves uploaded and which you must never create, generate or "
        "substitute. If something is missing, ask for it. A guessed field becomes a sworn "
        "declaration on a government record."),
    annotations=ToolAnnotations(title="File the application", readOnlyHint=False,
                                destructiveHint=False, idempotentHint=False))
async def submit_application(confirm_declaration: bool) -> dict:
    p = current_principal()
    r = await _run(services.submit, p.mobile, confirm_declaration)
    s = r["status"]
    if s == "ok":
        dob = r["date_of_birth"]
        return {
            "application_number": r["application_no"], "status": "PENDING",
            "submitted": r["submitted_at_ist"],
            "what_happens_next": "A block officer decides within 15 days. If nobody decides, "
                                 "it stands approved automatically on %s." % r["deemed_date_ist"],
            "how_to_check": "Ask me any time. On the portal: mobile number plus password, and "
                            "the password is the date of birth written as DDMMYYYY — for %s "
                            "that is %s." % (dob, dob.replace("/", "")),
            "sms": ("A confirmation SMS has been sent to this number." if r.get("sms_sent")
                    else "The confirmation SMS could not be sent; the application is filed "
                         "all the same."),
        }
    if s == "declaration_required":
        msg = ("I cannot submit until the applicant confirms the declaration. Read the details "
               "back and ask whether all of it is correct.")
    elif s == "incomplete":
        msg = ("These are still missing: %s. Ask the applicant and call "
               "save_application_details." % ", ".join(r["missing"]))
    elif s == "no_document":
        msg = "The age proof is not uploaded yet. Use get_document_upload_link."
    elif s == "invalid":
        msg = ("The portal refused the application: %s. Correct these with "
               "save_application_details, then try again." % "; ".join(r["errors"]))
        if r["errors"] == ["the application window has closed"]:
            msg = fmt.window_closed_message(r["window"])
    elif s == "duplicate":
        msg = fmt.existing_application_message(r["existing"]) + (
            " A pending application can be withdrawn with withdraw_application if the "
            "applicant wants to apply afresh.")
    else:
        msg = "Unexpected result: %s." % s
    return {"submitted": False, "reason": s, "message": msg,
            **({"missing": r["missing"]} if s == "incomplete" else {}),
            **({"errors": r["errors"]} if s == "invalid" else {}),
            **({"existing_application": {k: r["existing"][k] for k in ("application_no", "status")}}
               if s == "duplicate" else {})}
