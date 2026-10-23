"""Checks that the officer assistant never sees documents: get_age_proof_link returns a
link and recorded provenance only, get_application carries the same link, the texts
say the assistant cannot see documents, and the portal's document route opens inline
and sends a signed-out officer back to the document after login. Run inside the app
container:

    docker compose exec -T app python /app/scripts/check_officer_documents.py

Read-only: it finds an application with a document if there is one (the local demo
queue has eight) and otherwise skips those checks, saying so. Exits 1 if any check fails.
"""
import asyncio
import sys

sys.path.insert(0, "/app")
import app as portal                      # MUST be first (see services.py import note)
import services
from mcp_server import officer as officer_mod

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % detail) if detail and not ok else ""))


def walk(x):
    """Every key and string value in a nested tool result."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from walk(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from walk(v)
    else:
        yield x


def with_and_without_document():
    with services.db() as cur:
        cur.execute("SELECT id, application_no FROM applications WHERE doc_path <> '' "
                    "ORDER BY id DESC LIMIT 1")
        doc = cur.fetchone()
        cur.execute("SELECT id, application_no FROM applications WHERE doc_path = '' "
                    "ORDER BY id LIMIT 1")
        nodoc = cur.fetchone()
    return doc, nodoc


async def tool_checks(doc, nodoc):
    tools = {t.name: t for t in await officer_mod.officer.list_tools()}
    check("officer server lists 6 tools", len(tools) == 6, sorted(tools))
    check("view_age_proof is gone, get_age_proof_link is there",
          "view_age_proof" not in tools and "get_age_proof_link" in tools)
    desc = tools["get_age_proof_link"].description
    check("link description: cannot see, never describe/guess/comment",
          "you cannot see the document and must never describe, guess or comment on its "
          "contents" in desc)
    check("link tool is read-only", tools["get_age_proof_link"].annotations.readOnlyHint is True)
    ins = officer_mod.INSTRUCTIONS
    check("instructions: never sees documents", "You never see documents." in ins)
    check("instructions: give the link when opening a case or when asked",
          "When you open a case, or when the officer asks for the document, give them the "
          "link." in ins)
    check("instructions: no remind-to-open or restate-and-confirm rules",
          "remind them" not in ins and "ask once" not in ins and "restate" not in ins)
    check("instructions: officer_reason_quote unchanged", "officer_reason_quote" in ins
          and "officer_reason_quote" in tools["reject_application"].description)
    texts = " ".join([ins] + [t.description for t in tools.values()])
    check("no text says the assistant reviews documents",
          not any(w in texts for w in ("view_age_proof", "Reviewing is your job",
                                       "with the evidence", "so you can actually read it")))

    r = await officer_mod.get_age_proof_link(application_id=nodoc[0])
    check("no document: says so, no link", r.get("attached") is False and "link" not in r
          and r.get("note") == "No document attached.", r)
    r = await officer_mod.get_age_proof_link(application_no="SSP00000000")
    check("unknown number: error", "error" in r)
    r = await officer_mod.get_age_proof_link()
    check("neither id nor number: error", "error" in r)

    if not doc:
        print("SKIP  checks that need an application with a document (none in this database)")
        return
    url = "%s/admin/application/%d/document" % (services.PUBLIC_BASE_URL, doc[0])
    for kw in ({"application_id": doc[0]}, {"application_no": doc[1]}):
        r = await officer_mod.get_age_proof_link(**kw)
        check("link by %s" % list(kw)[0], r.get("link") == url, r)
    prov = r.get("provenance")
    check("provenance: filename, type, size, sha256, upload time, source",
          isinstance(prov, dict) and set(prov) == {"original_filename", "type", "byte_size",
                                                   "sha256", "uploaded", "source"}, prov)
    check("no image or file content in the result",
          not any(isinstance(v, (bytes, bytearray)) for v in walk(r))
          and not {"data", "image", "content"} & set(walk(r)))
    g = await officer_mod.get_application(application_id=doc[0])
    check("get_application: same link + provenance + warnings",
          g["document"].get("link") == url and "provenance" in g["document"]
          and isinstance(g.get("warnings"), list), g.get("document"))


def route_checks(client, doc):
    path = "/admin/application/%d/document" % (doc[0] if doc else 1)
    r = client.get(path)
    check("signed out: redirect to login with next",
          r.status_code == 302 and any("next=" + v in r.headers["Location"]
                                       for v in (path, path.replace("/", "%2F"))),
          r.headers.get("Location"))
    r = client.post("/admin?next=" + path, data={"username": portal.ADMIN_USERNAME,
                                                  "password": portal.ADMIN_PASSWORD})
    check("after login: back to the document", r.status_code == 302
          and r.headers["Location"].endswith(path), r.headers.get("Location"))
    r = client.post("/admin?next=//evil.example/admin/x",
                    data={"username": portal.ADMIN_USERNAME, "password": portal.ADMIN_PASSWORD})
    check("next to another host is ignored", r.headers["Location"].endswith("/admin/dashboard"),
          r.headers.get("Location"))
    if not doc:
        print("SKIP  inline-serving checks (no application with a document)")
        return
    r = client.get(path)
    cd = r.headers.get("Content-Disposition", "")
    check("document opens inline", r.status_code == 200 and cd.startswith("inline"), cd)
    check("image or PDF content type", r.headers.get("Content-Type", "").split(";")[0] in
          ("image/jpeg", "image/png", "application/pdf"), r.headers.get("Content-Type"))
    check("nosniff + no-store", r.headers.get("X-Content-Type-Options") == "nosniff"
          and "no-store" in r.headers.get("Cache-Control", ""))


if __name__ == "__main__":
    doc, nodoc = with_and_without_document()
    print("check_officer_documents: with document %s, without %s" % (doc, nodoc))
    asyncio.run(tool_checks(doc, nodoc))
    # Flask 2.2's test_client() reads werkzeug.__version__, which Werkzeug 3 removed
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    route_checks(Client(portal.app, Response, use_cookies=True), doc)
    print("%d/%d passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)
