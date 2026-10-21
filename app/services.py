# -*- coding: utf-8 -*-
"""
Sewa Setu service layer.

The one place business mutations happen. The Flask routes and both MCP servers call
these functions, and these functions call the portal's own rule functions
(validate_application, active_application, create_application, write_audit), so no
channel can admit an application another channel would refuse.

No Flask request/session/flash is touched here, so this module is callable from the
MCP process with no app context. Every function that touches one person's data takes
that person's identity (mobile / officer) as its first positional argument; nothing
here reads who is signed in.

Import order matters: `import app` must run before anything imports `oauth`, and this
module imports `app` at the top, so `import services` is always safe.

Timestamps: every stored timestamp is UTC-naive (datetime.now() in a UTC container),
while the portal's clock and the scheme deadline are IST-naive. Convert only for
display, with to_ist() / fmt_ist().
"""

import app as portal                      # MUST be first; see the import note above

import re
import threading
from contextlib import contextmanager
from datetime import datetime, date, timedelta

from psycopg2 import pool

# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

_POOL = None
_POOL_LOCK = threading.Lock()


def _pool():
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                c = portal.config
                _POOL = pool.ThreadedConnectionPool(
                    1, 10,
                    host=c.get("database", "host"),
                    port=c.get("database", "port"),
                    dbname=c.get("database", "name"),
                    user=c.get("database", "user"),
                    password=c.get("database", "password"),
                )
    return _POOL


@contextmanager
def db(commit=False):
    """A cursor on a pooled connection. Commits only when asked; otherwise rolls back,
    so a connection is never returned idle-in-transaction. Always returned to the pool."""
    conn = _pool().getconn()
    try:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
            else:
                conn.rollback()
        finally:
            cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool().putconn(conn)


class ServiceError(Exception):
    """A caller mistake (bad argument), as opposed to an expected business outcome,
    which is returned as a dict with a `status`."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCKS = portal.BLOCKS

# The 19 villages present in the data, and the block each belongs to (no village
# straddles a block). Nothing in the portal knows this mapping; it is used to suggest
# the block and to catch an invented village before it reaches the officer.
VILLAGES = {
    "Bhekulajan": "Sonari", "Kakotibari": "Sonari", "Lakhipur": "Sonari",
    "Namdang": "Sonari",
    "Dighaljan": "Rajapara", "Rajapara Gaon": "Rajapara", "Teliagaon": "Rajapara",
    "Borgaon Centre": "Borgaon", "Milanpur": "Borgaon", "Udaypur": "Borgaon",
    "Bordoloni": "Dhemaji Pathar", "Kathoni": "Dhemaji Pathar",
    "Nalbari Gaon": "Dhemaji Pathar",
    "Hatipara": "Namti", "Namti Chariali": "Namti", "Panidihing": "Namti",
    "Chengelimara": "Khelua", "Khelua Gaon": "Khelua", "Sialmari": "Khelua",
}

# The four reasons every seeded rejection carries, plus an escape hatch that needs a note.
REJECTION_REASONS = [
    "bank account not in applicant's name",
    "duplicate of an earlier beneficiary record",
    "age proof document illegible",
    "age proof does not match stated date of birth",
    "other",
]

DRAFT_TTL = timedelta(days=7)
UPLOAD_TOKEN_TTL = timedelta(hours=24)

IST_OFFSET = timedelta(hours=5, minutes=30)
DEEMED_RUN_HOUR_UTC = 2                    # deploy/crontab: 0 2 * * *

GENDERS = ["Male", "Female", "Other"]
MARITAL_STATUSES = ["Married", "Unmarried", "Widowed"]

# draft/tool field name -> validate_application() field name
FIELD_MAP = {
    "full_name": "applicant_name",
    "date_of_birth": "dob",
    "gender": "gender",
    "marital_status": "marital_status",
    "husband_name": "husband_name",
    "village": "village",
    "block": "block",
    "bank_account": "bank_account",
    "ifsc": "ifsc",
}

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def to_ist(dt):
    """A stored (UTC-naive) timestamp as naive IST."""
    if dt is None:
        return None
    return dt + IST_OFFSET


def _fmt(dt_ist):
    return dt_ist.strftime("%d/%m/%Y %H:%M") + " IST"


def fmt_ist(dt):
    """A stored (UTC-naive) timestamp for display, e.g. '21/10/2026 10:05 IST'."""
    if dt is None:
        return "—"
    return _fmt(to_ist(dt))


def deemed_date(submitted_at):
    """When the nightly job will deem this application approved, as naive IST.

    The job runs at 02:00 UTC and sweeps rows with submitted_at < now - 15 days, so a
    row is swept by the first 02:00 UTC run strictly after submitted_at + 15 days:
    between 15 and 16 days after submission, and always at 07:30 IST.
    """
    if submitted_at is None:
        return None
    due = submitted_at + timedelta(days=portal.SLA_DAYS)
    run = due.replace(hour=DEEMED_RUN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if run <= due:
        run += timedelta(days=1)
    return to_ist(run)


def _fmt_duration(hours):
    days, rem = divmod(int(hours), 24)
    parts = []
    if days:
        parts.append("%d day%s" % (days, "" if days == 1 else "s"))
    parts.append("%d hour%s" % (rem, "" if rem == 1 else "s"))
    return " ".join(parts)


def window_status():
    """Whether the scheme window is open, from config (never hardcoded)."""
    hours = portal.deadline_remaining()
    return {
        "open": hours is not None,
        "deadline_ist": _fmt(portal.SCHEME_DEADLINE),
        "hours_left": hours,
        "time_left": _fmt_duration(hours) if hours is not None else None,
    }


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------

_DOB_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


def parse_dob_any(raw):
    """A date of birth in any accepted spelling, or None if it cannot be read.
    %d/%m/%Y also accepts single-digit day and month (D/M/YYYY)."""
    s = (raw or "").strip()
    for f in _DOB_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def _key(s):
    return re.sub(r"[\s\-_.]+", "", (s or "")).lower()


_VILLAGE_KEYS = {_key(v): v for v in VILLAGES}
_BLOCK_KEYS = {_key(b): b for b in BLOCKS}


def match_village(raw):
    return _VILLAGE_KEYS.get(_key(raw))


def match_block(raw):
    return _BLOCK_KEYS.get(_key(raw))


def _pick(raw, allowed):
    for a in allowed:
        if (raw or "").strip().lower() == a.lower():
            return a
    return None


def normalise(fields):
    """Canonical spellings for whatever subset of draft fields is given.

    Returns (clean_fields, notes). Only fields present in the input appear in the
    output. A value that cannot be normalised is passed through unchanged, so the
    portal's own validator reports it; nothing is guessed.
    """
    if not isinstance(fields, dict):
        raise ServiceError("bad_field", "fields must be an object")
    clean, notes = {}, []
    for k, v in fields.items():
        if k not in FIELD_MAP:
            continue
        clean[k] = "" if v is None else str(v).strip()

    if "full_name" in clean:
        clean["full_name"] = re.sub(r"\s+", " ", clean["full_name"])
    if "husband_name" in clean:
        clean["husband_name"] = re.sub(r"\s+", " ", clean["husband_name"])

    if clean.get("date_of_birth"):
        d = parse_dob_any(clean["date_of_birth"])
        if d is not None:
            canon = d.strftime("%d/%m/%Y")
            if canon != clean["date_of_birth"]:
                notes.append("date of birth read as %s" % canon)
            clean["date_of_birth"] = canon

    if clean.get("ifsc"):
        canon = re.sub(r"[\s\-]", "", clean["ifsc"]).upper()
        if canon != clean["ifsc"]:
            notes.append("IFSC written as %s" % canon)
        clean["ifsc"] = canon

    if clean.get("bank_account"):
        canon = re.sub(r"[\s\-./]", "", clean["bank_account"])
        if canon != clean["bank_account"]:
            notes.append("bank account written as %s" % canon)
        clean["bank_account"] = canon

    if clean.get("village"):
        v = match_village(clean["village"])
        if v and v != clean["village"]:
            notes.append("village spelled %s" % v)
        if v:
            clean["village"] = v

    if clean.get("block"):
        b = match_block(clean["block"])
        if b and b != clean["block"]:
            notes.append("block spelled %s" % b)
        if b:
            clean["block"] = b

    for k, allowed in (("gender", GENDERS), ("marital_status", MARITAL_STATUSES)):
        if clean.get(k):
            p = _pick(clean[k], allowed)
            if p:
                clean[k] = p

    return clean, notes


def age_from_dob(raw):
    """Age today (IST) from a DD/MM/YYYY date of birth, or None if it cannot be read."""
    dob = portal.parse_dob(raw)
    if dob is None:
        return None
    return portal.age_on(dob, portal.now_ist().date())


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------


def _send_sms_checked(mobile, text):
    """Send an SMS and report whether the gateway accepted it. portal.send_sms swallows
    failures, which is fine for a web page but not for a tool that tells an officer
    the citizen was notified."""
    try:
        r = portal.requests.post(portal.SMS_GATEWAY_URL + "/api/send",
                                 json={"to": mobile, "text": text}, timeout=5)
        return r.status_code == 200 and (r.json() or {}).get("status") == "queued"
    except Exception as e:
        portal.app.logger.error("sms gateway error: %s" % e)
        return False


# ---------------------------------------------------------------------------
# Submission: the single write path for both channels
# ---------------------------------------------------------------------------

SUBMIT_SMS = ("Sewa Setu: application %s received. Track at the status portal "
              "with mobile no. and password (DOB as DDMMYYYY).")


def clear_draft(mobile):
    with db(commit=True) as cur:
        cur.execute("DELETE FROM agent_drafts WHERE mobile = %s", (mobile,))
    return {"status": "ok"}


def _submit_locked(cur, mobile, cleaned):
    """Lock the mobile, re-check the one-active-application rule, insert. Caller commits.

    The advisory lock is transaction-scoped and held until commit, so two concurrent
    submissions for one mobile serialise and the second sees the first's row.
    """
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (mobile,))
    existing = portal.active_application(cur, mobile)
    if existing:
        return {"status": "duplicate",
                "existing": {"id": existing[0], "application_no": existing[1],
                             "status": existing[2]}}
    new_id, app_no = portal.create_application(cur, mobile, cleaned)   # + SUBMIT audit row
    if cleaned.get("doc_path"):
        cur.execute("UPDATE document_uploads SET application_id = %s "
                    "WHERE doc_path = %s AND application_id IS NULL",
                    (new_id, cleaned["doc_path"]))
    return {"status": "ok", "id": new_id, "application_no": app_no}


def _after_submit(mobile, res):
    """After the commit: tell the applicant, and drop the agent draft."""
    if res["status"] == "ok":
        res["sms_sent"] = _send_sms_checked(mobile, SUBMIT_SMS % res["application_no"])
        clear_draft(mobile)
    return res


def submit_web(mobile, form_data, doc_path):
    """The web form's submission. form_data uses the form's own field names."""
    errors, cleaned = portal.validate_application(form_data or {}, doc_path)
    if errors:
        return {"status": "invalid", "errors": errors}
    with db(commit=True) as cur:
        res = _submit_locked(cur, mobile, cleaned)
    return _after_submit(mobile, res)


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------


def withdraw(mobile, application_no=None, app_id=None, actor=None):
    """Withdraw the applicant's own PENDING application, identified by number or id,
    always looked up within this mobile's applications."""
    if not application_no and not app_id:
        raise ServiceError("bad_field", "give application_no or app_id")
    with db(commit=True) as cur:
        if app_id:
            cur.execute("SELECT id, application_no, status FROM applications "
                        "WHERE id = %s AND mobile = %s FOR UPDATE", (app_id, mobile))
        else:
            cur.execute("SELECT id, application_no, status FROM applications "
                        "WHERE application_no = %s AND mobile = %s FOR UPDATE",
                        (application_no.strip().upper(), mobile))
        row = cur.fetchone()
        if not row:
            return {"status": "not_found"}
        if row[2] != "PENDING":
            return {"status": "not_pending", "application_no": row[1], "current": row[2]}
        cur.execute("UPDATE applications SET status = 'WITHDRAWN', decided_at = %s, "
                    "decided_by = 'APPLICANT' WHERE id = %s AND status = 'PENDING'",
                    (datetime.now(), row[0]))
        portal.write_audit(cur, row[0], "WITHDRAW", actor or "applicant:%s" % mobile)
    return {"status": "ok", "id": row[0], "application_no": row[1]}


# ---------------------------------------------------------------------------
# Officer decisions
# ---------------------------------------------------------------------------

IFSC_RE = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")

APPLICATION_COLUMNS = ("id", "application_no", "applicant_name", "mobile", "dob", "gender",
                       "marital_status", "husband_name", "village", "block", "bank_account",
                       "ifsc", "doc_path", "status", "submitted_at", "decided_at",
                       "decided_by")


def _row_dict(row):
    return dict(zip(APPLICATION_COLUMNS, row))


def _warnings(row):
    """[(hard, text)] for an application row dict. Hard problems are the ones the
    portal's own validator refuses today: age under the minimum, no document."""
    out = []
    dob = row.get("dob")
    if dob is None:
        out.append((True, "No date of birth is recorded."))
    else:
        age = portal.age_on(dob, portal.now_ist().date())
        if age < portal.MIN_AGE:
            out.append((True, "Age today is %d — below the %d-year minimum."
                        % (age, portal.MIN_AGE)))
    if not (row.get("doc_path") or "").strip():
        out.append((True, "No age-proof document is attached."))
    ifsc = (row.get("ifsc") or "").strip()
    if ifsc and not IFSC_RE.fullmatch(ifsc):
        out.append((False, "IFSC '%s' is not the 11-character form the portal requires "
                           "(e.g. SBIN0003077)." % ifsc))
    village, block = (row.get("village") or "").strip(), (row.get("block") or "").strip()
    known = VILLAGES.get(village)
    if village and not known:
        out.append((False, "Village '%s' is not one of the 19 known villages." % village))
    elif known and block and known != block:
        out.append((False, "Village %s is in %s block, but the application says %s."
                    % (village, known, block)))
    if row.get("decided_at") and row.get("submitted_at") \
            and row["decided_at"] < row["submitted_at"]:
        out.append((False, "The record shows a decision before the submission date."))
    return out


def eligibility_warnings(row):
    return [text for _, text in _warnings(row)]


APPROVE_SMS = ("Sewa Setu: your pension application %s has been approved. Rs 250 per "
               "month will be credited to your bank account by DBT.")
REJECT_SMS = ("Sewa Setu: your pension application %s has been rejected. Reason: %s. "
              "You may apply again at the Sewa Setu portal or at your block office.")


def decide(application_id, decision, reason, note, officer, channel,
           expect_application_no=None):
    """Approve or reject one PENDING application, in one transaction.

    channel "mcp" may not approve a case with a hard eligibility problem; channel
    "web" (the officer at the keyboard) keeps today's authority. Reject is never
    blocked. The citizen is told by SMS after the commit, and sms_sent reports whether
    the gateway actually accepted it.
    """
    if decision not in ("APPROVED", "REJECTED"):
        raise ServiceError("bad_field", "decision must be APPROVED or REJECTED")
    if channel not in ("web", "mcp"):
        raise ServiceError("bad_field", "channel must be web or mcp")
    reason = (reason or "").strip()
    note = (note or "").strip()
    with db(commit=True) as cur:
        cur.execute("SELECT %s FROM applications WHERE id = %%s FOR UPDATE"
                    % ", ".join(APPLICATION_COLUMNS), (application_id,))
        r = cur.fetchone()
        if not r:
            return {"status": "not_found"}
        row = _row_dict(r)
        if expect_application_no is not None and \
                str(expect_application_no).strip().upper() != row["application_no"]:
            return {"status": "no_match", "application_no": row["application_no"]}
        if row["status"] != "PENDING":
            return {"status": "not_pending", "application_no": row["application_no"],
                    "current": row["status"]}
        if decision == "REJECTED" and not reason:
            return {"status": "reason_required", "application_no": row["application_no"],
                    "reasons": REJECTION_REASONS}
        warns = _warnings(row)
        if decision == "APPROVED" and channel == "mcp" and any(h for h, _ in warns):
            return {"status": "blocked", "application_no": row["application_no"],
                    "warnings": [t for h, t in warns if h]}
        now = datetime.now()
        cur.execute("UPDATE applications SET status = %s, decided_at = %s, decided_by = %s "
                    "WHERE id = %s AND status = 'PENDING' RETURNING application_no",
                    (decision, now, officer, application_id))
        if not cur.fetchone():          # cannot happen under FOR UPDATE; kept as the guard
            return {"status": "not_pending", "application_no": row["application_no"]}
        if channel == "mcp":
            actor = ("officer:%s via assistant" % officer)[:50]
        else:
            actor = "admin:%s" % officer
        note_text = " — ".join(p for p in (reason, note) if p)[:500]
        portal.write_audit(cur, application_id, decision, actor, note_text)
    if decision == "APPROVED":
        text = APPROVE_SMS % row["application_no"]
    else:
        text = REJECT_SMS % (row["application_no"], reason)
    sms_sent = _send_sms_checked(row["mobile"], text)
    return {"status": "ok", "decision": decision, "id": application_id,
            "application_no": row["application_no"], "mobile": row["mobile"],
            "decided_by": officer, "decided_at_ist": fmt_ist(now), "actor": actor,
            "note": note_text, "warnings": [t for _, t in warns], "sms_sent": sms_sent}
