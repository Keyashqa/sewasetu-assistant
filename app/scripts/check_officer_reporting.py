"""Checks that the officer assistant reports rather than investigates: the instructions and
decision-tool texts, that warnings are the portal's rules only, and that audit notes hold only the
officer's words. Run inside the app container:

    docker compose exec -T app python /app/scripts/check_officer_reporting.py

LOCAL USE ONLY: it files and decides real applications, so it refuses unless
PUBLIC_BASE_URL is localhost. It uses reserved test mobiles 90000999 51-54 and deletes
everything it created on them before and after, even when a check fails. Exits 1 if any
check fails.
"""
import asyncio
import io
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import app as portal                      # MUST be first (see services.py import note)
import services
from mcp_server import officer as officer_mod
from mcp_server.auth import Principal, set_principal, reset_principal

A, B, C, D = "9000099951", "9000099952", "9000099953", "9000099954"
MOBILES = (A, B, C, D)
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")
PERSON = {"date_of_birth": "10/04/1950", "gender": "Female", "marital_status": "Widowed",
          "village": "Kathoni", "bank_account": "123456789012"}
APPROVE_NOTE = "Checked her Voter ID at the counter myself."
REJECT_QUOTE = "Reject it, the bank account isn't in her name."

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % detail) if detail and not ok else ""))


def cleanup():
    with services.db(commit=True) as cur:
        cur.execute("SELECT id FROM applications WHERE mobile IN %s", (MOBILES,))
        ids = tuple(r[0] for r in cur.fetchall()) or (-1,)
        cur.execute("DELETE FROM audit_log WHERE application_id IN %s", (ids,))
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


def file(mobile, name, doc):
    """An application through the citizen path: draft, upload link, submit."""
    services.save_draft(mobile, dict(full_name=name, **PERSON))
    token = services.issue_upload_token(mobile)["token"]
    services.attach_draft_document(token, "age-proof.png", io.BytesIO(doc))
    r = services.submit(mobile, True)
    assert r["status"] == "ok", r
    return r["id"], r["application_no"]


def audit_note(app_id, action):
    with services.db() as cur:
        cur.execute("SELECT note FROM audit_log WHERE application_id = %s AND action = %s",
                    (app_id, action))
        return [r[0] for r in cur.fetchall()]


async def text_checks():
    ins = officer_mod.INSTRUCTIONS
    tools = {t.name: t for t in await officer_mod.officer.list_tools()}
    check("instructions: do what the officer asks; relay warnings one line each, no commentary",
          "Do what the officer asks." in ins and "one short line each" in ins
          and "without commentary" in ins)
    check("instructions: warnings are the portal's rule-based ones",
          "the portal's rule-based warnings" in ins and "sha256" not in ins)
    check("instructions: no cross-referencing, patterns, fraud, conflicts, second-guessing",
          all(x in ins for x in ("Never cross-reference other applications", "relatives",
                                 "speculate about fraud or conflicts of interest",
                                 "second-guess the officer's decision")))
    check("instructions: call the tool on the officer's word, no repeated confirmation",
          "call the tool. Do not ask for confirmation again." in ins)
    check("instructions: reminder and restate rules removed",
          "remind them" not in ins and "ask once" not in ins and "restate" not in ins)
    check("instructions: give the document link when opening a case or asked",
          "When you open a case, or when the officer asks for the document, give them the "
          "link." in ins)
    check("instructions: hard blocks stated (under 60, no age proof)",
          "refuses approval when the applicant is under 60 today or no age proof is attached"
          in ins)
    check("instructions: audit notes are the officer's words only",
          "Never add your own note, summary, observation or analysis to any decision." in ins)
    ap, rj = tools["approve_application"].description, tools["reject_application"].description
    check("approve description: no repeated confirmation",
          "do not ask the officer to confirm again" in ap and "ask once" not in ap)
    check("approve description: note only the officer's words, verbatim",
          "only words the officer asked to have recorded, copied verbatim; never your own "
          "words" in ap)
    check("reject description: ask for the reason, never choose one, no own note",
          "ask them for it" in rj and "never choose one yourself" in rj
          and "never add your own note or observation" in rj and "suggest" not in rj)


async def decision_checks():
    # A and B share the same age-proof file and the same bank account: no pattern warnings
    a = file(A, "Test Shared One", PNG)
    b = file(B, "Test Shared Two", PNG)
    c = file(C, "Test Clean Record", PNG + b"different file")
    for label, g in (("first", await officer_mod.get_application(application_id=a[0])),
                     ("second", await officer_mod.get_application(application_no=b[1]))):
        check("shared file and account (%s): no pattern warning, only the portal's rules"
              % label, g["warnings"] == ["No eligibility problems found."], g["warnings"])

    # approve with no warnings: one call, no confirmation argument; audit note = officer's words
    r = await officer_mod.approve_application(application_id=c[0], application_no=c[1],
                                              note=APPROVE_NOTE)
    check("approve (no warnings): one call", r.get("status") == "approved"
          and "warnings_on_record" not in r, r)
    check("approve: audit note equals the officer's text exactly",
          audit_note(c[0], "APPROVED") == [APPROVE_NOTE], audit_note(c[0], "APPROVED"))

    # approve without a note: nothing added
    r = await officer_mod.approve_application(application_id=b[0], application_no=b[1])
    check("approve without a note: one call, audit note empty",
          r.get("status") == "approved" and audit_note(b[0], "APPROVED") == [""],
          (r, audit_note(b[0], "APPROVED")))

    # reject: canonical reason + the officer's words verbatim, nothing else
    r = await officer_mod.reject_application(
        application_id=a[0], application_no=a[1], reason="bank account not in applicant's name",
        officer_reason_quote=REJECT_QUOTE)
    check("reject: recorded", r.get("status") == "rejected", r)
    check("reject: audit note is the reason and the officer's words, nothing else",
          audit_note(a[0], "REJECTED") == ['bank account not in applicant\'s name — Officer: "%s"'
                                          % REJECT_QUOTE], audit_note(a[0], "REJECTED"))

    # hard blocks: the portal's rules, same as the counter (fixture row edited locally)
    d = file(D, "Test Hard Block", PNG + b"another file")
    with services.db(commit=True) as cur:
        cur.execute("UPDATE applications SET ifsc = 'UTBI0PUR2819', block = 'Sonari' "
                    "WHERE id = %s", (d[0],))
    g = await officer_mod.get_application(application_id=d[0])
    check("rule-based warnings exactly: invalid IFSC, village/block",
          g["warnings"] == ["IFSC 'UTBI0PUR2819' is not the 11-character form the portal "
                            "requires (e.g. SBIN0003077).",
                            "Village Kathoni is in Dhemaji Pathar block, but the application "
                            "says Sonari."], g["warnings"])
    with services.db(commit=True) as cur:
        cur.execute("UPDATE applications SET doc_path = '' WHERE id = %s", (d[0],))
    r = await officer_mod.approve_application(application_id=d[0], application_no=d[1])
    check("no document: approval refused with the portal's reason",
          r.get("approved") is False and r.get("status") == "blocked"
          and "No age-proof document is attached." in r["message"]
          and "may reject" not in r["message"], r)
    today = portal.now_ist().date()
    young = today.replace(year=today.year - 59)
    with services.db(commit=True) as cur:
        cur.execute("UPDATE applications SET doc_path = %s, dob = %s WHERE id = %s",
                    ("/app/uploads/x.png", young, d[0]))
    r = await officer_mod.approve_application(application_id=d[0], application_no=d[1])
    check("under 60: approval refused with the portal's reason",
          r.get("approved") is False
          and "Age today is 59 \u2014 below the 60-year minimum." in r.get("message", ""), r)
    with services.db() as cur:
        cur.execute("SELECT status FROM applications WHERE id = %s", (d[0],))
        st = cur.fetchone()[0]
    check("blocked approvals changed nothing",
          st == "PENDING" and audit_note(d[0], "APPROVED") == [],
          (st, audit_note(d[0], "APPROVED")))


async def main():
    tok = set_principal(Principal(role="officer", subject="officer:admin", mobile=None,
                                  officer="admin", kind="access", session_ends=None))
    try:
        await text_checks()
        await decision_checks()
    finally:
        reset_principal(tok)


if __name__ == "__main__":
    host = urlparse(os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")).hostname
    if host not in ("localhost", "127.0.0.1"):
        print("Refusing: PUBLIC_BASE_URL is not localhost; this check decides applications.")
        sys.exit(2)
    print("check_officer_reporting: test mobiles %s %s %s %s" % MOBILES)
    cleanup()
    try:
        asyncio.run(main())
    finally:
        cleanup()
    with services.db() as cur:
        cur.execute("SELECT count(*) FROM applications WHERE mobile IN %s", (MOBILES,))
        left = cur.fetchone()[0]
    check("cleanup: nothing left on the test mobiles", left == 0, left)
    print("%d/%d passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)
