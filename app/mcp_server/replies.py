# -*- coding: utf-8 -*-
"""The `reply` field every tool returns: a short markdown message the assistant shows
almost verbatim. Wording only; the facts come from the tool result. At most 4 short
lines plus a link, one action in bold, dates DD/MM/YYYY, times like 10:11 IST."""

from datetime import datetime

import services

STATUS = {"PENDING": "Pending", "APPROVED": "Approved", "DEEMED_APPROVED": "Approved (deemed)",
          "REJECTED": "Rejected", "WITHDRAWN": "Withdrawn"}
NEEDED = {"full_name": "full name", "date_of_birth": "date of birth", "village": "village",
          "block": "block", "bank_account": "bank account number",
          services.DOC_MISSING: "age proof"}
MAX_LIST = 4                       # list lines in one reply, plus one "and N more" line

STYLE = """\
How to reply:
- Every tool result has a `reply`: a short message ready to show. Use it as the basis of your \
answer, almost verbatim; add nothing unless the person asked a question.
- At most 4 short lines, plus a link on its own line. One action per message, in bold.
- Do not repeat details already shown, except in the declaration read-back.
- Do not explain rules unless the person asks or something is blocked.
- No advice beyond the task. No emojis.
- Dates DD/MM/YYYY; times like 10:11 IST."""


def lines(*parts):
    return "\n".join(p for p in parts if p)


def when(ist_text):
    """'23/10/2026 10:11 IST' -> '10:11 IST' today, else '24/10 09:59 IST'."""
    try:
        dt = datetime.strptime(ist_text, "%d/%m/%Y %H:%M IST")
    except (TypeError, ValueError):
        return ist_text
    if dt.date() == services.portal.now_ist().date():
        return dt.strftime("%H:%M IST")
    return dt.strftime("%d/%m %H:%M IST")


def day(ist_text):
    """'08/11/2026 07:30 IST' -> '08/11/2026'."""
    return (ist_text or "").split(" ")[0] or ist_text


def either(items):
    """['a', 'b', 'c'] -> 'a, b or c'."""
    return items[0] if len(items) == 1 else "%s or %s" % (", ".join(items[:-1]), items[-1])


def still_needed(missing):
    return "Still needed: %s." % ", ".join(NEEDED.get(m, m) for m in missing)


def status_line(no, name, status, deemed=None, reason=None):
    parts = [no, name or "name not recorded", STATUS.get(status, status)]
    if status == "PENDING" and deemed:
        parts.append("auto-approval %s" % day(deemed))
    if status == "REJECTED" and reason:
        parts.append("reason: %s" % reason)
    return " · ".join(parts)


def capped(items):
    """At most MAX_LIST lines, then one line saying how many more there are."""
    if len(items) <= MAX_LIST + 1:
        return items
    return items[:MAX_LIST] + ["…and %d more." % (len(items) - MAX_LIST)]


# ---------------------------------------------------------------------------
# Citizen
# ---------------------------------------------------------------------------

def read_back(fields, contact):
    """The declaration read-back: every detail that will be filed, then the declaration."""
    who = [fields.get("full_name"), fields.get("date_of_birth")]
    personal = ", ".join(x for x in (fields.get("gender"), fields.get("marital_status")) if x)
    if fields.get("husband_name"):
        personal += " (husband %s)" % fields["husband_name"]
    if personal:
        who.append(personal)
    who.append(", ".join(x for x in (fields.get("village"), fields.get("block")) if x))
    bank = ["Bank %s" % fields.get("bank_account")]
    if fields.get("ifsc"):
        bank.append("IFSC %s" % fields["ifsc"])
    bank += ["Age proof uploaded", "Contact %s" % contact]
    return lines("**Please confirm**", " · ".join(x for x in who if x), " · ".join(bank),
                 "These details are correct and the applicant agrees to apply. "
                 "Reply **yes** to submit.")


def upload_link(url, expires):
    return lines("**Upload the age proof** (birth certificate, school leaving certificate or "
                 "Voter ID)",
                 "[Open upload page](%s) — link expires %s." % (url, when(expires)),
                 "Say **done** when uploaded.")


def verify_link(url, expires, verified):
    if verified:
        return lines("**Verified:** %s" % ", ".join(verified),
                     "To verify another number: [Open verification page](%s) — link expires "
                     "%s." % (url, when(expires)))
    return lines("**Verify the applicant's number**",
                 "[Open verification page](%s) — enter the applicant's mobile number, then "
                 "type the OTP on that page (not here)." % url,
                 "Link expires %s. Say **done** when the page says \"Number verified\"."
                 % when(expires))


def submitted(no, deemed, mobile, sms_sent):
    return lines("**Submitted — %s (Pending)**" % no,
                 "Decision within 15 days; approved automatically on %s if none." % day(deemed),
                 "SMS sent to %s." % mobile if sms_sent
                 else "The confirmation SMS could not be sent; the application is filed.")


def existing(e):
    return "This number already has application %s (%s)." % (
        e["application_no"], STATUS.get(e["status"], e["status"]))


# ---------------------------------------------------------------------------
# Officer
# ---------------------------------------------------------------------------

def case_view(a, warnings, link):
    head = "**%s — %s** (%s%s)" % (
        a["application_no"], a["applicant_name"], STATUS.get(a["app_status"], a["app_status"]),
        ", %d days" % a["days_pending"] if a["days_pending"] is not None else "")
    who = " · ".join(x for x in (
        "DOB %s (%s)" % (a["date_of_birth"], a["age_today"]) if a["date_of_birth"] else
        "No date of birth recorded",
        "%s, %s" % (a["village"], a["block"])) if x)
    doc_line = "[Open age proof](%s)" % link if link else None
    warn = [w for w in warnings if not (link is None and w.startswith("No age-proof document"))]
    warn_lines = ["Warning: %s" % w for w in warn[:3]]
    if link is None:
        warn_lines.append("No age proof attached.")
    return lines(head, who, *warn_lines, doc_line)


def decided(verb, no, name, mobile, sms_sent, reason=None):
    head = "**%s — %s%s**." % (verb, no, " (%s)" % name if name and not reason else "")
    if reason:
        head += " Reason: %s." % reason
    if sms_sent:
        head += " SMS sent to %s." % mobile if not reason else " SMS sent."
        return head
    return lines(head, "The citizen has NOT been notified.")
