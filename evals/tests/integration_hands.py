"""Step 3 check (needs the local stack): links from real tool results, used by pages.py,
show up in the tools as document_attached and verified_numbers, with no OTP in any
stored output.

    python -m evals.tests.integration_hands
"""

import json
import sys

from evals import config, mcp_rpc, oauth, pages, stack

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s  %s" % ("PASS" if ok else "FAIL", name, detail))


def main():
    n, ms = stack.reserve_mobiles(99, [0, 1])
    m0, m1 = ms[0], ms[1]
    cid = oauth.register_client()
    g, otps = oauth.sign_in(cid, config.CITIZEN_RESOURCE, "citizen", m0)
    c = mcp_rpc.MCP(config.CITIZEN_RESOURCE, g.access)
    stored = []                                     # everything the harness would write

    # verify-number: the link from the tool, the number typed on the page
    v = c.call("get_number_verification_link")
    stored.append(v)
    links = pages.find_links(v["reply"], "verify")
    check("verify link is in the reply text", links == [v["verify_url"]], links)
    step, new = pages.verify_number(links[0], m1)
    otps += new
    stored.append(step)
    check("page says verified", "Number verified" in step["observation"], step["observation"])
    v2 = c.call("get_number_verification_link")
    stored.append(v2)
    check("verified_numbers contains M1", m1 in v2["verified_numbers"], v2["verified_numbers"])

    # upload: details first, so the page shows the applicant's name
    s = c.call("save_application_details", full_name="Kamala Das", date_of_birth="01/01/1960",
               village="Teliagaon", bank_account="33445566778", applicant_mobile=m1)
    stored.append(s)
    u = c.call("get_document_upload_link", applicant_mobile=m1)
    stored.append(u)
    links = pages.find_links(u["reply"], "upload")
    check("upload link is in the reply text", links == [u["upload_url"]], links)
    code, name, _ = pages.upload_applicant(links[0])
    check("upload page names the applicant", (code, name) == (200, "Kamala Das"), (code, name))
    step = pages.upload(links[0], config.EVALS / "fixtures" / "docs" / "p06.png")
    stored.append(step)
    check("page says uploaded", step["observation"].endswith("Uploaded. Go back to your chat and say done."),
          step["observation"])
    u2 = c.call("get_document_upload_link", applicant_mobile=m1)
    stored.append(u2)
    check("document_attached true", u2["document_attached"] is True, u2["document_attached"])

    # a link off the local stack is never followed
    try:
        pages.upload("https://136-116-6-93.sslip.io/upload/abc", config.EVALS / "fixtures" / "docs" / "p06.png")
        check("off-stack link refused", False)
    except ValueError:
        check("off-stack link refused", True)

    blob = json.dumps(stored)
    check("no OTP in stored output", otps and not any(o in blob for o in otps), "%d OTPs handled" % len(otps))
    check("nothing filed", stack.scalar("SELECT count(*) FROM applications WHERE mobile IN ('%s','%s')"
                                        % (m0, m1)) == "0")
    print("%d/%d passed" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
