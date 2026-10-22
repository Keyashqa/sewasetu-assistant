"""Checks for the citizen age-proof flow: the /upload/<token> page and the citizen
server's document texts. Run inside the app container (it needs the read-write uploads
volume):

    docker compose exec -T app python /app/scripts/check_document_flow.py

Uses one reserved test mobile (9000099901) and removes everything it creates — the
draft, the uploaded files and their document_uploads rows — even when a check fails.
No application is ever submitted. Exits 1 if any check fails.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")
import app as portal                      # MUST be first (see services.py import note)
import services
from mcp_server import citizen as citizen_mod
from mcp_server.auth import Principal, set_principal, reset_principal

MOBILE = "9000099901"
NAME = "Test Upload Page"
RULE = ("Never create, generate or alter a document yourself; the person uploads their own "
        "document through the link.")
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % detail) if detail and not ok else ""))


def post(client, token, filename, data, fmt=""):
    import io
    form = {} if filename is None else {"document": (io.BytesIO(data), filename)}
    return client.post("/upload/%s%s" % (token, fmt), data=form,
                       content_type="multipart/form-data")


def cleanup():
    with services.db(commit=True) as cur:
        cur.execute("SELECT doc_path FROM document_uploads WHERE mobile = %s", (MOBILE,))
        for (path,) in cur.fetchall():
            full = os.path.join(portal.UPLOAD_DIR, os.path.basename(path))
            if os.path.isfile(full):
                os.remove(full)
        cur.execute("DELETE FROM document_uploads WHERE mobile = %s", (MOBILE,))
        cur.execute("DELETE FROM agent_drafts WHERE mobile = %s", (MOBILE,))


def page_checks(client):
    services.save_draft(MOBILE, {"full_name": NAME})
    token = services.issue_upload_token(MOBILE)["token"]

    r = client.get("/upload/%s" % token)
    html = r.get_data(as_text=True)
    check("page 200", r.status_code == 200, r.status_code)
    check("page shows applicant name", NAME in html)
    check("page shows masked mobile", "******" + MOBILE[-4:] in html and MOBILE not in html)
    check("file picker accepts image/* and PDF", 'accept="image/*,application/pdf"' in html)
    check("phone viewport", 'name="viewport"' in html)
    check("size/format hint", "up to 5 MB" in html and "JPG or PNG" in html)

    html = post(client, token, "notes.txt", b"hello").get_data(as_text=True)
    check("wrong type: plain message", "This kind of file cannot be used" in html, html[-400:])
    html = post(client, token, None, b"").get_data(as_text=True)
    check("no file: plain message", "No file was received" in html)
    html = post(client, token, "big.png", b"\0" * (5 * 1024 * 1024 + 1)).get_data(as_text=True)
    check("too large: plain message", "This file is too big" in html)
    check("nothing attached after errors", not services.issue_upload_token(MOBILE)["doc_attached"])

    html = post(client, token, "age-proof.png", PNG).get_data(as_text=True)
    check("success message", "Uploaded. Go back to your chat and say done." in html)
    check("document_attached after upload", services.issue_upload_token(MOBILE)["doc_attached"])

    r = post(client, token, "age-proof.png", PNG, fmt="?format=json")
    check("fallback: multipart upload with ?format=json", r.status_code == 200
          and r.get_json().get("status") == "ok", r.get_data(as_text=True)[:200])

    r = client.get("/upload/not-a-real-token")
    check("unknown link: 404 + plain message", r.status_code == 404
          and "This link has expired" in r.get_data(as_text=True))


async def tool_checks():
    tools = {t.name: t for t in await citizen_mod.citizen.list_tools()}
    check("citizen server lists 7 tools", len(tools) == 7, sorted(tools))
    up = tools["get_document_upload_link"].description
    sub = tools["submit_application"].description
    ins = citizen_mod.INSTRUCTIONS
    check("upload description: one-line document rule", RULE in up)
    check("upload description: local-file fallback only on request",
          "Only if the person explicitly gives a local file path" in up)
    check("upload description: no curl", "curl" not in up.lower())
    check("upload description: does not judge the document", "Do not ask about, verify or comment" in up)
    check("submit description: document rule", RULE in sub)
    check("submit description: keeps 'never invent or guess applicant details'",
          "Never invent or guess applicant details" in sub)
    check("instructions: document rule", RULE in ins)
    check("instructions: never verify/judge/comment", "Never verify, judge or comment on the document" in ins)
    check("instructions: keeps 'never invent or guess applicant details'",
          "Never invent or guess applicant details" in ins)
    for name, text in (("upload", up), ("submit", sub), ("instructions", ins)):
        check("%s: long anti-fabrication text removed" % name,
              "false government record" not in text and "sworn declaration" not in text
              and "substitute" not in text)

    tok = set_principal(Principal(role="citizen", subject="citizen:" + MOBILE, mobile=MOBILE,
                                  officer=None, kind="access", session_ends=None))
    try:
        out = await citizen_mod.get_document_upload_link()
        check("tool output: no curl_example", "curl_example" not in out, out)
        check("tool output: link + instructions before upload",
              out["upload_url"] in out.get("instructions", "") and not out["document_attached"])
        check("tool output: no hash/size/filename", not {"sha256", "byte_size", "document_name",
                                                       "recorded"} & set(out))
    finally:
        reset_principal(tok)


if __name__ == "__main__":
    print("check_document_flow: test mobile %s" % MOBILE)
    cleanup()
    try:
        asyncio.run(tool_checks())
        cleanup()
        page_checks(portal.app.test_client())
    finally:
        cleanup()
    with services.db() as cur:
        cur.execute("SELECT (SELECT count(*) FROM agent_drafts WHERE mobile = %s) + "
                    "(SELECT count(*) FROM document_uploads WHERE mobile = %s)", (MOBILE, MOBILE))
        left = cur.fetchone()[0]
    check("cleanup: nothing left for the test mobile", left == 0, left)
    print("%d/%d passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)
