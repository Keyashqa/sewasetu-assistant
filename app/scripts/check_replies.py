"""Checks the `reply` field: every citizen and officer tool result carries one, no reply is
longer than 6 lines, and the main templates read as intended. Run inside the app container:

    docker compose exec -T app python /app/scripts/check_replies.py

LOCAL USE ONLY: it files and decides applications, so it refuses unless PUBLIC_BASE_URL is
localhost. Reserved test mobiles 90000999 61-63; everything created on them is deleted
before and after. Prints the verify-link, upload, read-back and submitted replies.
Exits 1 if any check fails.
"""
import asyncio
import io
import os
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import app as portal                      # MUST be first (see services.py import note)
import services
from mcp_server import citizen as citizen_mod, officer as officer_mod
from mcp_server.auth import Principal, set_principal, reset_principal

HELPER, OTHER, SPARE = "9000099961", "9000099962", "9000099963"
MOBILES = (HELPER, OTHER, SPARE)
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")

results, seen, samples = [], {}, {}


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


async def call(server, principal, tool, label=None, **kw):
    tok = set_principal(principal)
    try:
        out = await getattr(server, tool)(**kw)
    finally:
        reset_principal(tok)
    seen.setdefault(tool, []).append((label or tool, out))
    return out


def citizen(m):
    return Principal(role="citizen", subject="citizen:" + m, mobile=m, officer=None,
                     kind="access", session_ends=int(time.time()) + 3600)


OFFICER = Principal(role="officer", subject="officer:admin", mobile=None, officer="admin",
                    kind="access", session_ends=None)


async def scenario():
    c = lambda tool, label=None, **kw: call(citizen_mod, citizen(HELPER), tool, label, **kw)
    o = lambda tool, label=None, **kw: call(officer_mod, OFFICER, tool, label, **kw)

    await c("get_scheme_info")
    await c("check_eligibility", "eligibility: bad date", date_of_birth="31/31/1950")
    await c("check_eligibility", "eligibility: under 60", date_of_birth="01/01/1990")
    await c("check_eligibility", "eligibility: eligible", date_of_birth="10/04/1966")
    await c("get_my_application", "status: nothing yet")
    await c("save_application_details", "save: nothing given")
    await c("save_application_details", "save: unverified number", full_name="X",
            applicant_mobile=OTHER)
    await c("save_application_details", "save: bad IFSC", full_name="Seyalan Gogoi",
            ifsc="UTBI0PUR2819")
    await c("save_application_details", "save: missing", date_of_birth="10/04/1966",
            village="Kathoni", ifsc="")
    await c("submit_application", "submit: no declaration", confirm_declaration=False)
    await c("submit_application", "submit: incomplete", confirm_declaration=True)
    await c("save_application_details", "save: only document missing",
            bank_account="80157128856", ifsc="SBIN0003077")
    up = await c("get_document_upload_link", "upload: link")
    samples["upload"] = up["reply"]
    tok = up["upload_url"].rsplit("/", 1)[-1]
    services.attach_draft_document(tok, "age-proof.png", io.BytesIO(PNG))
    rb = await c("get_document_upload_link", "upload: attached -> read-back")
    samples["read-back"] = rb["reply"]
    sub = await c("submit_application", "submit: ok", confirm_declaration=True)
    samples["submitted"] = sub["reply"]
    await c("submit_application", "submit: duplicate", confirm_declaration=True)
    await c("check_eligibility", "eligibility: active application", date_of_birth="10/04/1966")
    v = await c("get_number_verification_link", "verify: link")
    samples["verify link"] = v["reply"]
    # the helper verifies OTHER on the page (the OTP stays on the portal)
    services.verify_send_code(v["verify_url"].rsplit("/", 1)[-1], OTHER)
    with services.db(commit=True) as cur:          # test shortcut: set a known code
        cur.execute("UPDATE number_verifications SET code_hash = %s WHERE token = %s",
                    (services._code_hash(v["verify_url"].rsplit("/", 1)[-1], "123456"),
                     v["verify_url"].rsplit("/", 1)[-1]))
    services.verify_check_code(v["verify_url"].rsplit("/", 1)[-1], "123456")
    await c("get_number_verification_link", "verify: after verification")
    await c("save_application_details", "save for other: read-back pending doc",
            applicant_mobile=OTHER, full_name="Sewalan Gogoi", date_of_birth="01/01/1958",
            gender="Female", marital_status="Widowed", husband_name="Late Ramen Gogoi",
            village="Kathoni", bank_account="123456789012")
    up2 = await c("get_document_upload_link", applicant_mobile=OTHER)
    services.attach_draft_document(up2["upload_url"].rsplit("/", 1)[-1], "a.png", io.BytesIO(PNG + b"2"))
    await c("save_application_details", "save for other: complete -> read-back",
            applicant_mobile=OTHER, gender="Female")
    other = await c("submit_application", "submit for other", confirm_declaration=True,
                    applicant_mobile=OTHER)
    await c("get_my_application", "status: own + filed for others")
    await c("withdraw_application", "withdraw: not confirmed",
            application_no=sub["application_number"], confirm=False)
    await c("withdraw_application", "withdraw: someone else's",
            application_no=other["application_number"], confirm=True)

    await o("get_queue_summary")
    await o("list_applications", "list: pending")
    await o("list_applications", "list: bad status", status="nonsense")
    await o("list_applications", "list: no match", search="no such name zz")
    with services.db() as cur:
        cur.execute("SELECT id FROM applications WHERE application_no = %s",
                    (other["application_number"],))
        oid = cur.fetchone()[0]
    with services.db() as cur:
        cur.execute("SELECT id FROM applications WHERE application_no = %s",
                    (sub["application_number"],))
        sid = cur.fetchone()[0]
    await o("get_application", "case: with document", application_id=sid)
    await o("get_application", "case: not found", application_no="SSP00000000")
    await o("get_application", "case: no document", application_id=1)
    await o("get_age_proof_link", "link: with document", application_id=sid)
    await o("get_age_proof_link", "link: no document", application_id=1)
    await o("reject_application", "reject: no reason", application_id=oid,
            application_no=other["application_number"])
    await o("reject_application", "reject: no quote", application_id=oid,
            application_no=other["application_number"], reason="age proof document illegible")
    await o("approve_application", "approve: mismatch", application_id=oid,
            application_no=sub["application_number"])
    ap = await o("approve_application", "approve: ok", application_id=sid,
                 application_no=sub["application_number"])
    await o("approve_application", "approve: not pending", application_id=sid,
            application_no=sub["application_number"])
    rj = await o("reject_application", "reject: ok", application_id=oid,
                 application_no=other["application_number"],
                 reason="bank account not in applicant's name",
                 officer_reason_quote="The account isn't in her name.")
    samples["officer approved"] = ap["reply"]
    samples["officer rejected"] = rj["reply"]
    await c("withdraw_application", "withdraw: not pending",
            application_no=sub["application_number"], confirm=True)


def checks():
    all_tools = sorted(set(t.name for t in asyncio.run(citizen_mod.citizen.list_tools())) |
                       set(t.name for t in asyncio.run(officer_mod.officer.list_tools())))
    check("every tool exercised (%d tools)" % len(all_tools), set(all_tools) <= set(seen),
          sorted(set(all_tools) - set(seen)))
    missing = [label for outs in seen.values() for label, out in outs
               if not isinstance(out.get("reply"), str) or not out["reply"].strip()]
    check("every result has a reply (%d results)" % sum(len(v) for v in seen.values()),
          not missing, missing)
    long = [(label, out["reply"]) for outs in seen.values() for label, out in outs
            if isinstance(out.get("reply"), str) and len(out["reply"].splitlines()) > 6]
    check("no reply exceeds 6 lines", not long, long)
    emoji = [label for outs in seen.values() for label, out in outs
             if any(ord(ch) > 0x2600 and ch not in "—–·…" for ch in out.get("reply", ""))]
    check("no emojis", not emoji, emoji)
    for name, want in (("verify link", "**Verify the applicant's number**"),
                       ("upload", "**Upload the age proof**"),
                       ("read-back", "**Please confirm**"),
                       ("submitted", "**Submitted — ")):
        check("template: %s" % name, samples.get(name, "").startswith(want), samples.get(name))
    # "Reply **yes** to submit." or, when optional fields are missing (finding F2),
    # "Optional, not given: … or reply **yes** to submit."
    check("read-back: declaration and yes", "reply **yes** to submit." in samples["read-back"].lower()
          and "agrees to apply" in samples["read-back"]
          and "Age proof uploaded" in samples["read-back"])
    check("officer approved: SMS line", samples["officer approved"].startswith("**Approved — ")
          and "SMS sent to" in samples["officer approved"], samples["officer approved"])
    check("officer rejected: reason", samples["officer rejected"].startswith("**Rejected — ")
          and "Reason: bank account not in applicant's name." in samples["officer rejected"],
          samples["officer rejected"])
    print("\n--- sample replies ---")
    for k, v in samples.items():
        print("[%s]\n%s\n" % (k, v))
    print("--- every reply ---")
    for outs in seen.values():
        for label, out in outs:
            print("[%s] %s" % (label, out.get("reply", "").replace("\n", " / ")))


if __name__ == "__main__":
    host = urlparse(os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")).hostname
    if host not in ("localhost", "127.0.0.1"):
        print("Refusing: PUBLIC_BASE_URL is not localhost; this check files applications.")
        sys.exit(2)
    cleanup()
    try:
        asyncio.run(scenario())
        checks()
    finally:
        cleanup()
    print("%d/%d passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)
