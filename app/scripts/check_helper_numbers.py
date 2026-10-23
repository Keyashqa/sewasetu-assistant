"""Checks for a helper filing for several applicants in one sign-in: the
/verify-number/<token> page, applicant_mobile on the citizen tools, and the rules around
them. Run inside the app container:

    docker compose exec -T app python /app/scripts/check_helper_numbers.py

LOCAL USE ONLY: it files real applications, so it refuses unless PUBLIC_BASE_URL is
localhost. It uses reserved test mobiles 90000999xx and deletes everything it created on
them (applications, audit rows, portal accounts, drafts, uploads, verifications) before
and after, even when a check fails. It reads OTPs from the simulated SMS gateway, as a
tester at the counter would, only to drive the portal page. Exits 1 if any check fails.
"""
import asyncio
import json
import os
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import app as portal                      # MUST be first (see services.py import note)
import services
from mcp_server import citizen as citizen_mod
from mcp_server.auth import Principal, set_principal, reset_principal

HELPER, HELPER2 = "9000099911", "9000099912"
A1, A2, A3 = "9000099921", "9000099922", "9000099923"
MOBILES = (HELPER, HELPER2, A1, A2, A3)
SESSION_ENDS = int(time.time()) + 3600
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")
PERSON = {"date_of_birth": "10/04/1950", "gender": "Female", "marital_status": "Widowed",
          "village": "Kathoni", "bank_account": "123456789012"}

results = []
outputs = []                              # every tool result, for the no-OTP check
codes = []                                # every OTP the gateway delivered


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % detail) if detail and not ok else ""))


def cleanup():
    with services.db(commit=True) as cur:
        cur.execute("SELECT id FROM applications WHERE mobile IN %s", (MOBILES,))
        ids = tuple(r[0] for r in cur.fetchall()) or (-1,)
        cur.execute("DELETE FROM audit_log WHERE application_id IN %s", (ids,))
        cur.execute("DELETE FROM helper_filings WHERE application_id IN %s OR helper IN %s",
                    (ids, MOBILES))
        cur.execute("DELETE FROM applications WHERE id IN %s", (ids,))
        cur.execute("DELETE FROM portal_users WHERE mobile IN %s", (MOBILES,))
        cur.execute("SELECT doc_path FROM document_uploads WHERE mobile IN %s", (MOBILES,))
        for (path,) in cur.fetchall():
            full = os.path.join(portal.UPLOAD_DIR, os.path.basename(path))
            if os.path.isfile(full):
                os.remove(full)
        cur.execute("DELETE FROM document_uploads WHERE mobile IN %s", (MOBILES,))
        cur.execute("DELETE FROM agent_drafts WHERE owner IN %s OR mobile IN %s",
                    (MOBILES, MOBILES))
        cur.execute("DELETE FROM verified_numbers WHERE helper IN %s", (MOBILES,))
        cur.execute("DELETE FROM number_verifications WHERE helper IN %s", (MOBILES,))
        cur.execute("DELETE FROM otps WHERE mobile IN %s", (MOBILES,))


def principal(mobile):
    return Principal(role="citizen", subject="citizen:" + mobile, mobile=mobile, officer=None,
                     kind="access", session_ends=SESSION_ENDS)


async def call(who, tool, **kw):
    tok = set_principal(principal(who))
    try:
        out = await getattr(citizen_mod, tool)(**kw)
    finally:
        reset_principal(tok)
    outputs.append(out)
    return out


def last_sms(mobile, after_id=0, wait=8.0):
    """The newest delivered message to mobile with id > after_id (polls: 1-4 s latency)."""
    end = time.time() + wait
    while time.time() < end:
        r = portal.requests.get(portal.SMS_GATEWAY_URL + "/api/messages",
                                params={"to": mobile}, timeout=5)
        msgs = [m for m in r.json()["messages"] if m["id"] > after_id]
        if msgs and msgs[-1]["delivered"]:
            return msgs[-1]
        time.sleep(0.5)
    return None


def max_sms_id(mobile):
    r = portal.requests.get(portal.SMS_GATEWAY_URL + "/api/messages", params={"to": mobile},
                            timeout=5)
    return max([m["id"] for m in r.json()["messages"]] or [0])


def otp_from(msg):
    import re
    m = re.search(r"OTP is (\d{6})", msg["text"] or "")
    if m:
        codes.append(m.group(1))
    return m.group(1) if m else None


def token_of(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def page(client, token, **form):
    if form:
        r = client.post("/verify-number/%s" % token, data=form)
    else:
        r = client.get("/verify-number/%s" % token)
    return r.status_code, r.get_data(as_text=True)


def upload(client, url):
    import io
    r = client.post("/upload/%s" % token_of(url),
                    data={"document": (io.BytesIO(PNG), "age-proof.png")},
                    content_type="multipart/form-data")
    return r.status_code


def verify(client, token, mobile, html_out=None):
    """Drive the page for one number with the real OTP. Returns the final HTML."""
    before = max_sms_id(mobile)
    _, html = page(client, token, action="send", mobile=mobile)
    msg = last_sms(mobile, before)
    code = otp_from(msg) if msg else None
    if html_out is not None:
        html_out.append(html)
    return page(client, token, action="check", otp=code or "000000")[1], code


async def descriptions():
    tools = {t.name: t for t in await citizen_mod.citizen.list_tools()}
    check("citizen server lists 8 tools", len(tools) == 8, sorted(tools))
    d = tools.get("get_number_verification_link")
    check("get_number_verification_link exists", d is not None)
    check("verification tool: never asks for, sees or relays the OTP",
          d is not None and "never ask for, see or relay the OTP" in d.description)
    check("verification tool: on any reply, check verified_numbers before asking again",
          d is not None and "check verified_numbers before asking them to verify again"
          in d.description)
    check("verification tool: only for another number / signed-in number already active",
          d is not None and "only when the person wants to file for someone else" in d.description
          and "already has an active application" in d.description)
    for name in ("check_eligibility", "save_application_details", "get_document_upload_link",
                 "submit_application"):
        props = tools[name].inputSchema.get("properties", {})
        check("%s takes optional applicant_mobile" % name,
              "applicant_mobile" in props
              and "applicant_mobile" not in tools[name].inputSchema.get("required", []))
    for name in ("get_my_application", "withdraw_application", "get_scheme_info"):
        check("%s has no applicant_mobile" % name,
              "applicant_mobile" not in tools[name].inputSchema.get("properties", {}))
    ins = citizen_mod.INSTRUCTIONS
    check("instructions: never ask for, accept or repeat an OTP",
          "Never ask for, accept or repeat an OTP in the chat" in ins)
    check("instructions: default is the signed-in number", "leave applicant_mobile out" in ins)


async def single_applicant(client):
    """The existing flow, unchanged: no applicant_mobile anywhere."""
    e = await call(HELPER, "check_eligibility", date_of_birth="10/04/1950")
    check("single: eligible on the signed-in number", e["eligible"] and "applicant_mobile" not in e, e)
    s = await call(HELPER, "save_application_details", full_name="Test Helper Own", **PERSON)
    check("single: details saved, no applicant_mobile in output",
          s["missing"] == [services.DOC_MISSING] and "applicant_mobile" not in s, s)
    u = await call(HELPER, "get_document_upload_link")
    check("single: upload page accepts the document", upload(client, u["upload_url"]) == 200)
    r = await call(HELPER, "submit_application", confirm_declaration=True)
    check("single: filed", r.get("status") == "PENDING", r)
    with services.db() as cur:
        cur.execute("SELECT a.mobile, l.actor FROM applications a JOIN audit_log l "
                    "ON l.application_id = a.id AND l.action = 'SUBMIT' "
                    "WHERE a.application_no = %s", (r.get("application_number"),))
        row = cur.fetchone()
        cur.execute("SELECT count(*) FROM helper_filings WHERE helper = %s", (HELPER,))
        hf = cur.fetchone()[0]
    check("single: on the signed-in mobile, actor applicant:<mobile>, not a helper filing",
          row == (HELPER, "applicant:" + HELPER) and hf == 0, (row, hf))
    return r.get("application_number")


async def unverified():
    for tool, kw in (("check_eligibility", {"date_of_birth": "10/04/1950"}),
                     ("save_application_details", dict(full_name="Test Nobody", **PERSON)),
                     ("get_document_upload_link", {}),
                     ("submit_application", {"confirm_declaration": True})):
        out = await call(HELPER, tool, applicant_mobile=A1, **kw)
        check("unverified %s refused, names get_number_verification_link" % tool,
              "error" in out and "get_number_verification_link" in out["error"], out)
    out = await call(HELPER, "save_application_details", full_name="X", applicant_mobile="12345")
    check("malformed applicant_mobile refused", "10-digit" in out.get("error", ""), out)
    with services.db() as cur:
        cur.execute("SELECT count(*) FROM agent_drafts WHERE mobile = %s", (A1,))
        n = cur.fetchone()[0]
    check("unverified: nothing written", n == 0, n)


async def verification_page(client):
    link = await call(HELPER, "get_number_verification_link")
    again = await call(HELPER, "get_number_verification_link")
    check("link: same link while unused", link["verify_url"] == again["verify_url"])
    check("link: reply says type the OTP on the page, not here",
          "type the OTP on that page (not here)" in link["reply"])
    check("link: nothing verified yet", link["verified_numbers"] == [])
    token = token_of(link["verify_url"])

    status, html = page(client, token)
    check("page 200, phone viewport, asks for the number",
          status == 200 and 'name="viewport"' in html and "Send OTP" in html, status)
    _, html = page(client, token, action="send", mobile=HELPER)
    check("own number: not needed", "already signed in with" in html)
    _, html = page(client, token, action="send", mobile="12345")
    check("bad number: plain message", "10-digit mobile number" in html)

    before = max_sms_id(A1)
    _, html = page(client, token, action="send", mobile="+91 90000 99921")
    msg = last_sms(A1, before)
    code = otp_from(msg) if msg else None
    check("OTP sent by SMS to the applicant's mobile (+91 and spaces accepted)", bool(code), msg)
    check("page shows only the last 4 digits and never the code",
          "ending <b>9921</b>" in html and (code or "x") not in html)
    _, html = page(client, token, action="send", mobile=A1)
    check("resend cooldown", "wait a minute" in html)
    wrong = "000000" if code != "000000" else "111111"
    _, html = page(client, token, action="check", otp=wrong)
    check("wrong OTP: message, 4 tries left", "not right" in html and "4 tries left" in html)
    _, html = page(client, token, action="check", otp=code or "")
    check("success message", "Number verified. Go back to your chat and say done." in html, html[-500:])
    check("success: return-to-chat button, close only (no going back), close-tab hint",
          "Done &ndash; return to chat" in html and "window.close()" in html and "history.back()" not in html
          and "You can close this tab and return to your chat, then say done." in html)
    _, html = page(client, token, action="check", otp=code or "")
    check("link is single-use", "This link has been used" in html)

    after = await call(HELPER, "get_number_verification_link")
    check("verified number listed for the helper", after["verified_numbers"] == [A1], after)
    check("a new link after the used one", after["verify_url"] != link["verify_url"])
    with services.db() as cur:
        cur.execute("SELECT expires_at FROM verified_numbers WHERE helper = %s AND mobile = %s",
                    (HELPER, A1))
        exp = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM number_verifications WHERE code_hash LIKE %s",
                    (code or "x",))
        plain = cur.fetchone()[0]
    check("verification lasts until the helper's sign-in ends",
          abs((exp - services.datetime.fromtimestamp(SESSION_ENDS, services.timezone.utc)
                       .replace(tzinfo=None)).total_seconds()) < 1, exp)
    check("OTP not stored in plain text", plain == 0)

    other = await call(HELPER2, "save_application_details", full_name="X", applicant_mobile=A1)
    check("another helper cannot use that verification", "not been verified" in
          other.get("error", ""), other)

    # A2 through the next link
    html, code2 = verify(client, token_of(after["verify_url"]), A2)
    check("second number verified", "Number verified" in html and bool(code2))

    # attempt limit and OTP expiry on A3
    t3 = token_of((await call(HELPER, "get_number_verification_link"))["verify_url"])
    before = max_sms_id(A3)
    page(client, t3, action="send", mobile=A3)
    code3 = otp_from(last_sms(A3, before) or {"text": ""})
    with services.db(commit=True) as cur:
        cur.execute("UPDATE number_verifications SET code_sent_at = code_sent_at - "
                    "interval '301 seconds' WHERE token = %s", (t3,))
    _, html = page(client, t3, action="check", otp=code3 or "")
    check("OTP older than 5 minutes refused", "has expired" in html and "valid for 5 minutes" in html)
    before = max_sms_id(A3)
    page(client, t3, action="send", mobile=A3)
    code3 = otp_from(last_sms(A3, before) or {"text": ""})
    bad = "000000" if code3 != "000000" else "111111"
    for _ in range(5):
        _, html = page(client, t3, action="check", otp=bad)
    check("5 wrong OTPs lock the link", "Too many wrong OTPs" in html)
    _, html = page(client, t3, action="check", otp=code3 or "")
    check("locked link refuses even the right OTP", "Too many wrong OTPs" in html)
    check("A3 not verified", A3 not in (await call(HELPER, "get_number_verification_link"))
          ["verified_numbers"])
    status, _ = page(client, "not-a-real-token")
    check("unknown link: 404", status == 404)


async def file_for(client, mobile, name):
    e = await call(HELPER, "check_eligibility", date_of_birth="10/04/1950", applicant_mobile=mobile)
    s = await call(HELPER, "save_application_details", full_name=name, applicant_mobile=mobile,
                   **PERSON)
    u = await call(HELPER, "get_document_upload_link", applicant_mobile=mobile)
    up = upload(client, u["upload_url"])
    u2 = await call(HELPER, "get_document_upload_link", applicant_mobile=mobile)
    before = max_sms_id(mobile)
    r = await call(HELPER, "submit_application", confirm_declaration=True, applicant_mobile=mobile)
    return e, s, u2, up, r, before


async def helper_files(client, own_no):
    results_by = {}
    for mobile, name in ((A1, "Test Applicant One"), (A2, "Test Applicant Two")):
        e, s, u2, up, r, before = await file_for(client, mobile, name)
        check("%s: eligibility checked on the applicant's number" % mobile,
              e["eligible"] and e.get("applicant_mobile") == mobile, e)
        check("%s: draft saved for that applicant" % mobile,
              s.get("applicant_mobile") == mobile and s["saved"]["full_name"] == name, s)
        check("%s: document uploaded through its own link" % mobile,
              up == 200 and u2["document_attached"], u2)
        check("%s: filed" % mobile, r.get("status") == "PENDING"
              and r.get("filed_on_mobile") == mobile, r)
        results_by[mobile] = r.get("application_number")
        sms = last_sms(mobile, before)
        check("%s: confirmation SMS to the applicant's number" % mobile,
              sms is not None and r.get("application_number", "?") in (sms["text"] or ""))
    with services.db() as cur:
        cur.execute("SELECT a.mobile, a.applicant_name, a.status, l.actor FROM applications a "
                    "JOIN audit_log l ON l.application_id = a.id AND l.action = 'SUBMIT' "
                    "WHERE a.application_no IN %s ORDER BY a.mobile",
                    (tuple(results_by.values()),))
        rows = cur.fetchall()
        cur.execute("SELECT mobile FROM helper_filings WHERE helper = %s ORDER BY mobile",
                    (HELPER,))
        hf = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM agent_drafts WHERE owner = %s", (HELPER,))
        drafts = cur.fetchone()[0]
    check("both on their own mobiles, PENDING, actor names helper and applicant",
          rows == [(A1, "Test Applicant One", "PENDING", "helper:%s for %s" % (HELPER, A1)),
                   (A2, "Test Applicant Two", "PENDING", "helper:%s for %s" % (HELPER, A2))],
          rows)
    check("audit actor fits 50 chars", all(len(r[3]) <= 50 for r in rows))
    check("helper filings recorded", hf == [A1, A2], hf)
    check("drafts cleared after filing", drafts == 0, drafts)

    # one active application per mobile, still
    e, s, u2, up, r, _ = await file_for(client, A1, "Test Applicant One Again")
    check("one active per mobile: eligibility says so",
          not e["eligible"] and e["existing_application"]["application_no"] == results_by[A1], e)
    check("one active per mobile: submit refused as duplicate",
          r.get("submitted") is False and r.get("reason") == "duplicate"
          and "withdraw_application" not in r["message"], r)
    with services.db() as cur:
        cur.execute("SELECT count(*) FROM applications WHERE mobile = %s AND status IN %s",
                    (A1, portal.ACTIVE_STATUSES))
        n = cur.fetchone()[0]
    check("one active per mobile: still exactly one", n == 1, n)
    await call(HELPER, "get_my_application")          # (draft kept for A1; listed below)

    # concurrent submits for a verified number with a fresh draft: one row
    services.withdraw(A2, application_no=results_by[A2])     # A2 withdraws their own
    services.save_draft(HELPER, dict(full_name="Test Applicant Two Again", **PERSON), applicant=A2)
    upload(client, services.issue_upload_token(HELPER, A2)["url"])
    rs = await asyncio.gather(*[call(HELPER, "submit_application", confirm_declaration=True,
                                     applicant_mobile=A2) for _ in range(3)])
    with services.db() as cur:
        cur.execute("SELECT count(*) FROM applications WHERE mobile = %s AND status IN %s",
                    (A2, portal.ACTIVE_STATUSES))
        n = cur.fetchone()[0]
    check("3 concurrent submits for one verified number: 1 active row", n == 1,
          (n, [x.get("reason") or x.get("status") for x in rs]))

    # status: own + filed for others
    m = await call(HELPER, "get_my_application")
    others = {o["mobile"]: o for o in m.get("filed_for_others", [])}
    check("get_my_application: own application", m.get("application_number") == own_no, m)
    check("get_my_application: filed for others with number, name, status",
          set(others) == {A1, A2} and others[A1]["name"] == "Test Applicant One"
          and others[A1]["status"] == "PENDING" and others[A1]["application_number"]
          == results_by[A1], m.get("filed_for_others"))
    check("get_my_application: draft for another applicant listed",
          any(d["applicant_mobile"] == A1 for d in m.get("drafts_for_others", [])), m)
    m2 = await call(HELPER2, "get_my_application")
    check("another helper sees none of them", "filed_for_others" not in m2, m2)

    # withdraw: only the signed-in number's own
    w = await call(HELPER, "withdraw_application", application_no=results_by[A1], confirm=True)
    with services.db() as cur:
        cur.execute("SELECT status FROM applications WHERE application_no = %s",
                    (results_by[A1],))
        st = cur.fetchone()[0]
    check("helper cannot withdraw a helper-filed application",
          w.get("withdrawn") is False and st == "PENDING", (w, st))
    w = await call(HELPER, "withdraw_application", application_no=own_no, confirm=True)
    check("helper can withdraw their own", w.get("withdrawn") is True, w)


def no_otp_anywhere():
    text = json.dumps(outputs, ensure_ascii=False)
    leaked = [c for c in codes if c in text]
    check("no OTP appears in any tool output (%d OTPs, %d outputs)" % (len(codes), len(outputs)),
          codes and not leaked, leaked)


if __name__ == "__main__":
    host = urlparse(os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")).hostname
    if host not in ("localhost", "127.0.0.1"):
        print("Refusing: PUBLIC_BASE_URL is not localhost; this check files applications.")
        sys.exit(2)
    print("check_helper_numbers: helper %s, applicants %s %s %s" % (HELPER, A1, A2, A3))
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    client = Client(portal.app, Response)
    cleanup()
    try:
        async def main():
            await descriptions()
            own = await single_applicant(client)
            await unverified()
            await verification_page(client)
            await helper_files(client, own)
        asyncio.run(main())
        no_otp_anywhere()
    finally:
        cleanup()
    with services.db() as cur:
        cur.execute("SELECT (SELECT count(*) FROM applications WHERE mobile IN %s) + "
                    "(SELECT count(*) FROM agent_drafts WHERE owner IN %s OR mobile IN %s) + "
                    "(SELECT count(*) FROM verified_numbers WHERE helper IN %s)",
                    (MOBILES, MOBILES, MOBILES, MOBILES))
        left = cur.fetchone()[0]
    check("cleanup: nothing left on the test mobiles", left == 0, left)
    print("%d/%d passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)
