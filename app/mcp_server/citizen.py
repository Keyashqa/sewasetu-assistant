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

INSTRUCTIONS = """\
Sewa Setu is the Government of Purvanchal's portal for the Old Age Pension: Rs 250 a month \
for residents aged 60 or above. These tools let you check eligibility, prepare and file an \
application, and follow it up, under the same rules as the portal's web form and counter.

Who you are talking to:
- The person talking may be the applicant, or a family member, helper or CSC operator \
applying on the applicant's behalf with the applicant's consent. This is normal and allowed; \
it is how most applications are made.
- The signed-in mobile number can be anyone's. It becomes the contact number for this \
application: status checks, SMS updates and the portal login go to it. The applicant's own \
details (name, date of birth, village, bank account) are what go on the application.
- A helper may confirm the declaration on the applicant's behalf when they say the applicant \
consents. Do not refuse because the mobile, or the person typing, is not the applicant.
- The only rule about mobile numbers: one active application per mobile number. A second \
applicant needs a different mobile number (their own or any family member's), verified as \
below, or the block office.

Applying for more than one person (helpers, CSC operators):
- By default everything is filed on the signed-in number. For one applicant nothing extra is \
needed: leave applicant_mobile out.
- Use get_number_verification_link only when the person wants to file for someone else on \
another mobile number, or the signed-in number already has an active application. The person \
opens the link, enters that mobile number and types the OTP sent to that phone on the page.
- Never ask for, accept or repeat an OTP in the chat. If someone types one here, tell them it \
is not needed in the chat and to enter it on the page.
- When the person replies after you gave the link (with anything), call \
get_number_verification_link again and check verified_numbers before asking them to verify \
again. Once the number is there, pass it as applicant_mobile to check_eligibility, \
save_application_details, get_document_upload_link and submit_application for that \
applicant, every time. Keep each applicant's details separate.
- withdraw_application only withdraws the signed-in number's own application.

The age proof:
- The person uploads it themselves: give them the link from get_document_upload_link. When \
they reply after that (with anything), call it again and check document_attached before \
asking them to upload again.
- Never verify, judge or comment on the document, and never ask about its authenticity or \
contents. Checking it is the block officer's job.

Honesty:
- Never invent or guess applicant details: file only what the applicant or their helper \
tells you.
- Never create, generate or alter a document yourself; the person uploads their own \
document through the link.
- Dates are Indian: DD/MM/YYYY. Never offer a month-first reading of a date.
- State only scheme facts these tools return. Never speculate about future application \
windows, rule changes or anything no tool told you."""

citizen = FastMCP(
    "Sewa Setu — Old Age Pension (citizen)",
    instructions=INSTRUCTIONS,
    stateless_http=True,
    transport_security=transport_security(),
)


def _run(fn, *args, **kwargs):
    return anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


APPLICANT_MOBILE_DOC = (
    "applicant_mobile (optional): leave it out to use the signed-in number. Otherwise a "
    "10-digit number verified with get_number_verification_link in this sign-in.")


async def _applicant(p, applicant_mobile):
    """(mobile, None) when the signed-in number may act for applicant_mobile, else
    (None, error result). Only the signed-in number or one it verified by OTP."""
    r = await _run(services.applicant_for, p.mobile, applicant_mobile)
    if r["status"] == "ok":
        return r["mobile"], None
    if r["status"] == "bad_number":
        return None, {"error": "applicant_mobile must be a 10-digit mobile number. Leave it "
                               "out to use the signed-in number."}
    return None, {"error": "The number %s has not been verified in this sign-in, so nothing "
                           "can be done for it yet. Call get_number_verification_link and "
                           "send the person the link: they enter that number there and type "
                           "the OTP from that phone on the page (never in this chat). When "
                           "they reply, check verified_numbers with that tool and try again." % r["mobile"]}


def _for(mobile, p):
    """Names the applicant mobile in a result when it is not the signed-in number."""
    return {} if mobile == p.mobile else {"applicant_mobile": mobile}


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
        "Checks whether the applicant can apply: age 60 or above from the applicant's date of "
        "birth, the window still open, and whether this mobile number already has an active "
        "application. The person asking may be the applicant or someone helping them; use the "
        "applicant's date of birth. Call before collecting details. Input: date_of_birth as "
        "DD/MM/YYYY (Indian order, day first), for example 10/04/1957. Other formats are "
        "accepted and corrected. " + APPLICANT_MOBILE_DOC),
    annotations=ToolAnnotations(title="Check eligibility", readOnlyHint=True))
async def check_eligibility(date_of_birth: str, applicant_mobile: str | None = None) -> dict:
    p = current_principal()
    mobile, err = await _applicant(p, applicant_mobile)
    if err:
        return dict(err, eligible=False)
    e = await _run(services.eligibility, mobile, date_of_birth)
    if e["status"] == "bad_date":
        return {"eligible": False,
                "error": "I could not read that date. Give it as DD/MM/YYYY, for example "
                         "10/04/1957."}
    if e["status"] == "future_date":
        return {"eligible": False,
                "error": "That date is in the future. Please check the year."}
    out = {"date_of_birth": e["date_of_birth"], "age": e["age"], "age_ok": e["age_ok"],
           "turns_60_on": e["turns_60_on"], "window_open": e["window"]["open"],
           "existing_application": e["existing"], "eligible": e["eligible"], **_for(mobile, p)}
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
    elif e["reasons"] == ["active_application"]:
        out["message"] = " ".join(messages)
        out["next_step"] = ("Nothing new can be filed on this number. If this is a different "
                            "applicant, file on another mobile number: "
                            "get_number_verification_link, then applicant_mobile.")
    else:
        out["message"] = " ".join(messages)
        out["next_step"] = "Nothing can be filed now. Explain this to the person."
    return out


@citizen.tool(
    description=(
        "The status of this mobile number's application, in plain words, plus the "
        "applications this signed-in number filed for other people on their verified numbers "
        "(filed_for_others: number, name, status). Use it whenever the person asks whether "
        "an application has been approved or what is happening, and after submitting. No "
        "input."),
    annotations=ToolAnnotations(title="My application status", readOnlyHint=True))
async def get_my_application() -> dict:
    p = current_principal()
    a = await _run(services.my_application, p.mobile)
    out = _own_application(a)
    if a["filed_for_others"]:
        out["filed_for_others"] = [
            {"mobile": o["mobile"], "application_number": o["application_no"],
             "name": o["name"], "status": o["status"],
             "means": fmt.STATUS_MEANING.get(o["status"], o["status"])}
            for o in a["filed_for_others"]]
    if a["drafts_for_others"]:
        out["drafts_for_others"] = [
            {"applicant_mobile": o["mobile"], "name": o["name"] or "not given yet"}
            for o in a["drafts_for_others"]]
    return out


def _own_application(a):
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
        "Withdraws a pending application so it can be filed again. Only the signed-in mobile "
        "number's own application, only while it is still pending; not one filed for someone "
        "else on their number. Input: application_no (e.g. SSP26540132) and confirm must be "
        "true. Ask the person out loud before calling this; it cannot be undone."),
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
                "message": "That application number does not belong to this mobile number, "
                           "so it cannot be withdrawn here. An application filed on someone "
                           "else's number can be withdrawn by them from the status portal "
                           "(their mobile number and date-of-birth password) or at the block "
                           "office. Check numbers with get_my_application."}
    return {"withdrawn": False,
            "message": "Only a pending application can be withdrawn. This one is %s."
                       % r["current"]}


def _ifsc_problem(ifsc):
    return ("The portal accepts an 11-character IFSC like SBIN0003077. '%s' is %d characters, "
            "so it will be refused — please check the passbook, or clear it by sending ifsc "
            "as an empty string, as IFSC is not mandatory." % (ifsc, len(ifsc)))


@citizen.tool(
    description=(
        "Saves or updates the applicant's details on the server. The details are the "
        "applicant's own, given by the applicant or by the person helping them with their "
        "consent. Send any subset of fields — call it several times as the conversation goes. "
        "It tells you what is saved, what is still missing and what is wrong. Required: "
        "full_name, date_of_birth (DD/MM/YYYY, day first), village, block (filled in "
        "automatically for known villages), bank_account (9-18 digits). Optional: gender "
        "(Male/Female/Other), marital_status (Married/Unmarried/Widowed), husband_name (only "
        "if widowed), ifsc (11 characters, e.g. SBIN0003077). Send only details the applicant "
        "or their helper actually gave; never guess a value. " + APPLICANT_MOBILE_DOC + " "
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
                                   ifsc: str | None = None,
                                   applicant_mobile: str | None = None) -> dict:
    p = current_principal()
    mobile, err = await _applicant(p, applicant_mobile)
    if err:
        return err
    given = {k: v for k, v in (("full_name", full_name), ("date_of_birth", date_of_birth),
                               ("gender", gender), ("marital_status", marital_status),
                               ("husband_name", husband_name), ("village", village),
                               ("block", block), ("bank_account", bank_account),
                               ("ifsc", ifsc)) if v is not None}
    if not given:
        return {"error": "No fields were given. Send at least one field the applicant told you."}
    r = await _run(services.save_draft, p.mobile, given, applicant=mobile)
    saved_ifsc = r["saved"].get("ifsc") or ""
    problems = [_ifsc_problem(saved_ifsc) if pr.startswith("IFSC must be") else pr
                for pr in r["problems"]]
    out = {**_for(mobile, p), "saved": r["saved"], "missing": r["missing"],
           "problems": problems, "corrections": r["corrections"], "warnings": r["warnings"],
           "suggested_block": r["suggested_block"], "ready_to_submit": r["ready_to_submit"]}
    if problems:
        out["next_step"] = "Ask about each problem, then save again."
    elif [m for m in r["missing"] if m != services.DOC_MISSING]:
        out["next_step"] = "Ask for the missing details."
    elif services.DOC_MISSING in r["missing"]:
        out["next_step"] = "Details are complete. Call get_document_upload_link for the age proof."
    else:
        out["next_step"] = ("Read all the details and the declaration back to the person you "
                            "are talking with, and call submit_application only after they "
                            "confirm (for the applicant, or on the applicant's behalf with "
                            "their consent).")
    return out


@citizen.tool(
    description=(
        "Gives a link where the person uploads the applicant's age proof (birth certificate, "
        "school leaving certificate or Voter ID) from their phone. Send them the link and the "
        "instructions. When the person replies after that (with anything), call this tool "
        "again and check document_attached before asking them to upload again; a document "
        "is required before submit_application. "
        "Calling it again gives the same link. " + APPLICANT_MOBILE_DOC + "\n\n"
        "Never create, generate or alter a document yourself; the person uploads their own "
        "document through the link. Do not ask about, verify or comment on the document: the "
        "block officer checks it.\n\n"
        "Only if the person explicitly gives a local file path and asks you to upload it, you "
        "may upload that exact file to the link (multipart form field \"document\")."),
    annotations=ToolAnnotations(title="Get an upload link", readOnlyHint=False,
                                destructiveHint=False, idempotentHint=True))
async def get_document_upload_link(applicant_mobile: str | None = None) -> dict:
    p = current_principal()
    mobile, err = await _applicant(p, applicant_mobile)
    if err:
        return err
    t = await _run(services.issue_upload_token, p.mobile, mobile)
    out = {**_for(mobile, p), "upload_url": t["url"], "expires": t["expires_at_ist"],
           "document_attached": t["doc_attached"]}
    if t["doc_attached"]:
        out["next_step"] = ("The age proof is uploaded. Do not comment on it. Read the details "
                            "and the declaration back, then submit_application after they "
                            "confirm. Uploading again through the same link replaces it.")
    else:
        out["instructions"] = ("Open this link on your phone: %s . Tap \"Take a photo or "
                               "choose a file\", take a clear photo of the birth certificate, "
                               "school leaving certificate or Voter ID (or choose a PDF), then "
                               "tap Upload. When the page says Uploaded, come back here and "
                               "say done." % t["url"])
        out["next_step"] = ("Send the person the link and these instructions. When they "
                            "reply (with anything), call get_document_upload_link again and "
                            "check document_attached before asking them to upload again.")
    return out


@citizen.tool(
    description=(
        "Files the application with the portal. Only call after the details are complete, "
        "the age proof is uploaded, and you have read the details and the declaration back to "
        "the person you are talking with and they said yes. Input: confirm_declaration must "
        "be true, meaning the applicant — or the person helping them, with the applicant's "
        "consent — has confirmed the information is correct and consents to the department "
        "verifying it. Filing on the applicant's behalf from someone else's mobile is normal; "
        "the application is filed on applicant_mobile, which becomes its contact number. "
        + APPLICANT_MOBILE_DOC + "\n\n"
        "Never invent or guess applicant details; if something is missing, ask for it. Never "
        "create, generate or alter a document yourself; the person uploads their own document "
        "through the link."),
    annotations=ToolAnnotations(title="File the application", readOnlyHint=False,
                                destructiveHint=False, idempotentHint=False))
async def submit_application(confirm_declaration: bool,
                             applicant_mobile: str | None = None) -> dict:
    p = current_principal()
    mobile, err = await _applicant(p, applicant_mobile)
    if err:
        return dict(err, submitted=False)
    r = await _run(services.submit, p.mobile, confirm_declaration, applicant=mobile)
    s = r["status"]
    if s == "ok":
        dob = r["date_of_birth"]
        if mobile != p.mobile:
            return {
                "application_number": r["application_no"], "status": "PENDING",
                "filed_on_mobile": mobile, "submitted": r["submitted_at_ist"],
                "what_happens_next": "A block officer decides within 15 days. If nobody "
                                     "decides, it stands approved automatically on %s."
                                     % r["deemed_date_ist"],
                "how_to_check": "Ask me any time in this chat: get_my_application lists it. "
                                "On the portal: mobile number %s plus password, and the "
                                "password is the date of birth written as DDMMYYYY — for %s "
                                "that is %s." % (mobile, dob, dob.replace("/", "")),
                "sms": ("A confirmation SMS has been sent to %s." % mobile if r.get("sms_sent")
                        else "The confirmation SMS could not be sent; the application is "
                             "filed all the same."),
            }
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
        msg = ("Not submitted yet: the declaration needs confirming. Read the details back and "
               "ask whether all of it is correct — the applicant can confirm, or the person "
               "helping them can confirm on their behalf with their consent.")
    elif s == "incomplete":
        msg = ("These are still missing: %s. Ask the applicant and call "
               "save_application_details." % ", ".join(r["missing"]))
    elif s == "no_document":
        msg = ("The age proof is not uploaded yet. Give the person the link from "
               "get_document_upload_link. When they reply, check document_attached with that "
               "tool before asking them to upload again.")
    elif s == "invalid":
        msg = ("The portal refused the application: %s. Correct these with "
               "save_application_details, then try again." % "; ".join(r["errors"]))
        if r["errors"] == ["the application window has closed"]:
            msg = fmt.window_closed_message(r["window"])
    elif s == "duplicate" and mobile != p.mobile:
        msg = fmt.existing_application_message(r["existing"]) + (
            " Only that number's owner can withdraw it, from the status portal or at the "
            "block office.")
    elif s == "duplicate":
        msg = fmt.existing_application_message(r["existing"]) + (
            " A pending application can be withdrawn with withdraw_application if the "
            "applicant wants to apply afresh.")
    else:
        msg = "Unexpected result: %s." % s
    return {"submitted": False, "reason": s, "message": msg, **_for(mobile, p),
            **({"missing": r["missing"]} if s == "incomplete" else {}),
            **({"errors": r["errors"]} if s == "invalid" else {}),
            **({"existing_application": {k: r["existing"][k] for k in ("application_no", "status")}}
               if s == "duplicate" else {})}


@citizen.tool(
    description=(
        "Gives a link where the person verifies another mobile number by OTP, so an "
        "application can be filed on that number in this chat without signing in again. Use "
        "it only when the person wants to file for someone else on another mobile number, or "
        "the signed-in number already has an active application. For a single applicant on "
        "the signed-in number it is not needed.\n\n"
        "Send the person the link and the instructions, then wait. On the page they enter the "
        "applicant's mobile number and type the OTP sent to that phone. You never ask for, "
        "see or relay the OTP; if someone types an OTP in the chat, tell them to enter it on "
        "the page instead. When the person replies after that (with anything), call this tool "
        "again and check verified_numbers before asking them to verify again. Once the number "
        "is there, pass it as applicant_mobile to check_eligibility, "
        "save_application_details, get_document_upload_link and submit_application. No input."),
    annotations=ToolAnnotations(title="Verify another mobile number", readOnlyHint=False,
                                destructiveHint=False, idempotentHint=True))
async def get_number_verification_link() -> dict:
    p = current_principal()
    link = await _run(services.issue_verify_link, p.mobile, p.session_ends)
    verified = await _run(services.verified_numbers, p.mobile)
    return {
        "verify_url": link["url"], "expires": link["expires_at_ist"],
        "instructions": ("Open this link: %s . Enter the mobile number of the person you are "
                         "applying for and tap Send OTP. An OTP comes by SMS to that phone; "
                         "type it on the page, not here. When the page says Number verified, "
                         "come back here and say done." % link["url"]),
        "verified_numbers": [v["mobile"] for v in verified],
        "next_step": ("Send the person the link and instructions. When they reply (with "
                      "anything), call this tool again and check verified_numbers before asking "
                      "them to verify again. A number "
                      "in verified_numbers can be used as applicant_mobile until this sign-in "
                      "ends; it does not need verifying again."),
    }
