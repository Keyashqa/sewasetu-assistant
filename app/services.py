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

import os
import re
import hashlib
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, date, timedelta

from psycopg2 import pool
from psycopg2.extras import Json

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
                # one pool per process; DB_POOL_MAX is lowered on the small production VM
                _POOL = pool.ThreadedConnectionPool(
                    1, int(os.environ.get("DB_POOL_MAX", "10")),
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
# Citizen: scheme facts and eligibility
# ---------------------------------------------------------------------------

DOCUMENTS_ACCEPTED = ["Birth certificate", "School leaving certificate", "Voter ID"]
PENSION_AMOUNT_INR = 250


def scheme_info():
    """The scheme's facts, from config and the portal's constants (never hardcoded
    dates)."""
    return {
        "amount_inr": PENSION_AMOUNT_INR,
        "min_age": portal.MIN_AGE,
        "residency": "resident of Purvanchal",
        "documents_accepted": DOCUMENTS_ACCEPTED,
        "formats": "JPG, PNG or PDF up to 5 MB",
        "sla_days": portal.SLA_DAYS,
        "deemed_approval": "If no officer decides within %d days, the application stands "
                           "approved automatically." % portal.SLA_DAYS,
        "window": window_status(),
        "blocks": list(BLOCKS),
        "villages_by_block": {b: sorted(v for v, bb in VILLAGES.items() if bb == b)
                              for b in BLOCKS},
    }


def _sixtieth_birthday(dob):
    try:
        return dob.replace(year=dob.year + portal.MIN_AGE)
    except ValueError:                       # born 29 February
        return date(dob.year + portal.MIN_AGE, 3, 1)


def eligibility(mobile, dob_raw=None):
    """Can this mobile apply now, for someone born on dob_raw? Only the portal's own
    rules: age on today's IST date, the scheme window, one active application per
    mobile. No invented criteria."""
    out = {"status": "ok", "age": None, "age_ok": None, "turns_60_on": None}
    reasons = []
    if dob_raw is not None:
        dob = parse_dob_any(dob_raw)
        if dob is None:
            return {"status": "bad_date"}
        today = portal.now_ist().date()
        if dob > today:
            return {"status": "future_date"}
        age = portal.age_on(dob, today)
        out.update(age=age, age_ok=age >= portal.MIN_AGE,
                   date_of_birth=dob.strftime("%d/%m/%Y"))
        if age < portal.MIN_AGE:
            out["turns_60_on"] = _sixtieth_birthday(dob).strftime("%d/%m/%Y")
            reasons.append("under_age")
    win = window_status()
    out["window"] = win
    if not win["open"]:
        reasons.append("window_closed")
    with db() as cur:
        existing = portal.active_application(cur, mobile)
    out["existing"] = ({"application_no": existing[1], "status": existing[2]}
                       if existing else None)
    if existing:
        reasons.append("active_application")
    out["reasons"] = reasons
    out["eligible"] = not reasons and out["age_ok"] is not False
    return out


# ---------------------------------------------------------------------------
# Drafts (the agent channel's equivalent of the web form's session)
# ---------------------------------------------------------------------------

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
REQUIRED_FIELDS = ("full_name", "date_of_birth", "village", "block", "bank_account")
DOC_MISSING = "age proof document"
UPLOAD_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_EXTENSIONS = ("pdf", "jpg", "jpeg", "png")
DRAFT_COLUMNS = ("mobile", "data", "doc_path", "doc_name", "upload_token", "token_expires",
                 "created_at", "updated_at", "expires_at")


def _portal_fields(fields):
    """Draft field names -> the names validate_application() reads."""
    return {FIELD_MAP[k]: v for k, v in fields.items() if k in FIELD_MAP}


def _villages_text(block=None):
    if block in BLOCKS:
        names = sorted(v for v, b in VILLAGES.items() if b == block)
        return "Villages in %s are %s and %s." % (block, ", ".join(names[:-1]), names[-1])
    return "Known villages: " + "; ".join(
        "%s: %s" % (b, ", ".join(sorted(v for v, bb in VILLAGES.items() if bb == b)))
        for b in BLOCKS) + "."


def _load_draft(cur, mobile, lock=False):
    cur.execute("SELECT %s FROM agent_drafts WHERE mobile = %%s AND expires_at > %%s%s"
                % (", ".join(DRAFT_COLUMNS), " FOR UPDATE" if lock else ""),
                (mobile, datetime.now()))
    r = cur.fetchone()
    return dict(zip(DRAFT_COLUMNS, r)) if r else None


def _assess(fields, doc_path):
    """(missing, problems, ready) for a merged draft, using the portal's own validator.
    'X is required' errors become `missing`; everything else is a problem."""
    missing = [k for k in REQUIRED_FIELDS if not (fields.get(k) or "").strip()]
    if not doc_path:
        missing.append(DOC_MISSING)
    errors, _ = portal.validate_application(_portal_fields(fields), doc_path)
    problems = [e for e in errors
                if not e.endswith(" is required")
                and not (e.startswith("date of birth must be") and "date_of_birth" in missing)]
    return missing, problems, not missing and not problems


def get_draft(mobile):
    with db() as cur:
        d = _load_draft(cur, mobile)
    if not d:
        return None
    missing, problems, ready = _assess(d["data"], d["doc_path"])
    return {"fields": d["data"], "doc_attached": bool(d["doc_path"]),
            "doc_name": d["doc_name"], "missing": missing, "errors": problems,
            "ready_to_submit": ready, "expires_at": fmt_ist(d["expires_at"])}


def save_draft(mobile, fields):
    """Merge any subset of fields into the draft. Never refuses a half-filled draft.

    A value that cannot be read (a date that is not a date, a block that does not
    exist, a gender outside the form's choices) is not stored: it is reported in
    `problems` so the assistant asks again, and the earlier value is kept. A village
    outside the known 19 is stored once a valid block is known, with a warning.
    """
    clean, corrections = normalise(fields)
    problems = []

    if "date_of_birth" in clean and clean["date_of_birth"]:
        d = parse_dob_any(clean["date_of_birth"])
        if d is None:
            problems.append("I could not read the date of birth '%s'. Give it as DD/MM/YYYY, "
                            "for example 10/04/1957." % clean.pop("date_of_birth"))
        elif d > portal.now_ist().date():
            problems.append("The date of birth %s is in the future. Please check the year."
                            % clean.pop("date_of_birth"))
    for k, allowed in (("gender", GENDERS), ("marital_status", MARITAL_STATUSES)):
        if clean.get(k) and clean[k] not in allowed:
            problems.append("%s must be one of %s; '%s' was not saved."
                            % (k, ", ".join(allowed), clean.pop(k)))
    if clean.get("block") and clean["block"] not in BLOCKS:
        problems.append("I do not know the block '%s'. The blocks are %s."
                        % (clean.pop("block"), ", ".join(BLOCKS)))

    now = datetime.now()
    with db(commit=True) as cur:
        d = _load_draft(cur, mobile, lock=True)
        merged = dict(d["data"]) if d else {}
        warnings = []
        # The portal accepts any village, so the assistant does too: an unknown village
        # is stored as given once a valid block anchors it, and the officer is warned
        # (eligibility_warnings). Without a block there is nothing to check it against.
        if clean.get("village") and clean["village"] not in VILLAGES:
            block = clean.get("block") or merged.get("block")
            if block in BLOCKS:
                warnings.append("Village '%s' is not in the list of known villages. It has "
                                "been saved as given, in %s block; the block officer will "
                                "see this note." % (clean["village"], block))
            else:
                bad = clean.pop("village")
                problems.append("I do not know the village '%s' and no block is given. If "
                                "the village is right, send it again together with the "
                                "block. %s" % (bad, _villages_text()))
        merged.update(clean)

        suggested_block = VILLAGES.get(merged.get("village"))
        if suggested_block:
            if not merged.get("block"):
                merged["block"] = suggested_block
                corrections.append("block set to %s, the block %s is in"
                                   % (suggested_block, merged["village"]))
            elif merged["block"] != suggested_block:
                problems.append("%s is in %s block, not %s. Ask the applicant which is right."
                                % (merged["village"], suggested_block, merged["block"]))

        doc_path = d["doc_path"] if d else None
        if d:
            cur.execute("UPDATE agent_drafts SET data = %s, updated_at = %s, expires_at = %s "
                        "WHERE mobile = %s",
                        (Json(merged), now, now + DRAFT_TTL, mobile))
        else:
            cur.execute("INSERT INTO agent_drafts (mobile, data, created_at, updated_at, "
                        "expires_at) VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT (mobile) DO UPDATE SET data = EXCLUDED.data, "
                        "doc_path = NULL, doc_name = NULL, upload_token = NULL, "
                        "token_expires = NULL, created_at = EXCLUDED.created_at, "
                        "updated_at = EXCLUDED.updated_at, expires_at = EXCLUDED.expires_at",
                        (mobile, Json(merged), now, now,
                         now + DRAFT_TTL))

    missing, validator_problems, _ = _assess(merged, doc_path)
    problems += [p for p in validator_problems if p not in problems]
    return {"status": "ok", "saved": merged, "missing": missing, "problems": problems,
            "corrections": corrections, "warnings": warnings,
            "suggested_block": suggested_block,
            "ready_to_submit": not missing and not problems}


def _ensure_draft(cur, mobile):
    d = _load_draft(cur, mobile, lock=True)
    if d:
        return d
    now = datetime.now()
    cur.execute("INSERT INTO agent_drafts (mobile, data, created_at, updated_at, expires_at) "
                "VALUES (%s, '{}'::jsonb, %s, %s, %s) "
                "ON CONFLICT (mobile) DO UPDATE SET data = '{}'::jsonb, doc_path = NULL, "
                "doc_name = NULL, upload_token = NULL, token_expires = NULL, "
                "created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at, "
                "expires_at = EXCLUDED.expires_at", (mobile, now, now, now + DRAFT_TTL))
    return _load_draft(cur, mobile, lock=True)


def issue_upload_token(mobile):
    """A link for uploading this mobile's age proof. Reuses a live token, so asking
    twice gives the same link. The token is bound to the mobile and nothing else."""
    now = datetime.now()
    with db(commit=True) as cur:
        d = _ensure_draft(cur, mobile)
        if d["upload_token"] and d["token_expires"] and d["token_expires"] > now:
            token, expires = d["upload_token"], d["token_expires"]
        else:
            token, expires = secrets.token_urlsafe(24), now + UPLOAD_TOKEN_TTL
            cur.execute("UPDATE agent_drafts SET upload_token = %s, token_expires = %s, "
                        "updated_at = %s WHERE mobile = %s", (token, expires, now, mobile))
    out = {"url": "%s/upload/%s" % (PUBLIC_BASE_URL, token), "token": token,
           "expires_at_ist": fmt_ist(expires), "doc_attached": bool(d["doc_path"]),
           "doc_name": d["doc_name"]}
    if d["doc_path"]:
        out["provenance"] = document_provenance(doc_path=d["doc_path"])
    return out


def draft_for_upload_token(token):
    """The draft a live upload token belongs to, or None (unknown or expired)."""
    if not token:
        return None
    now = datetime.now()
    with db() as cur:
        cur.execute("SELECT mobile, doc_name, token_expires FROM agent_drafts "
                    "WHERE upload_token = %s AND token_expires > %s AND expires_at > %s",
                    (token, now, now))
        r = cur.fetchone()
    if not r:
        return None
    return {"mobile_masked": "******" + r[0][-4:], "doc_attached": bool(r[1]),
            "doc_name": r[1], "token_expires_ist": fmt_ist(r[2])}


def attach_draft_document(token, filename, stream, source="upload_token"):
    """Store an uploaded age proof against the draft its token belongs to.

    The only writer of a document on the agent path. Same rules as /upload (pdf, jpg,
    jpeg, png; at most 5 MB), read in chunks and abandoned past the limit. The file
    gets a fresh server-chosen name, so nothing the uploader sends becomes part of a
    path and no earlier file is overwritten. The bytes are hashed as they are read and
    the provenance row records exactly what arrived. `source` is 'upload_token' for the
    /upload/<token> route; only scripts/seed_demo_queue.py passes 'demo_seed'.
    """
    original = (filename or "").strip()
    if stream is None or not original:
        return {"status": "no_file",
                "message": "Choose a file to upload (JPG, PNG or PDF, up to 5 MB)."}
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in UPLOAD_EXTENSIONS:
        return {"status": "bad_type", "message": "Please upload a JPG, PNG or PDF file."}

    now = datetime.now()
    with db(commit=True) as cur:
        cur.execute("SELECT mobile FROM agent_drafts WHERE upload_token = %s "
                    "AND token_expires > %s AND expires_at > %s FOR UPDATE",
                    (token, now, now))
        r = cur.fetchone()
        if not r:
            return {"status": "expired",
                    "message": "This upload link has expired. Ask for a new one."}
        mobile = r[0]
        name = "draft_%s_%s_%s.%s" % (mobile, now.strftime("%Y%m%d%H%M%S"),
                                      secrets.token_hex(2), ext)
        path = os.path.join(portal.UPLOAD_DIR, name)
        os.makedirs(portal.UPLOAD_DIR, exist_ok=True)
        h, size = hashlib.sha256(), 0
        try:
            with open(path, "xb") as out:
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > UPLOAD_MAX_BYTES:
                        raise _TooLarge()
                    h.update(chunk)
                    out.write(chunk)
        except _TooLarge:
            os.remove(path)
            return {"status": "too_large",
                    "message": "File is larger than 5 MB. Please upload a smaller file."}
        if size == 0:
            os.remove(path)
            return {"status": "no_file", "message": "The file is empty."}
        content_type = (getattr(stream, "mimetype", None) or DOC_MIMETYPES.get(ext))[:60]
        digest = h.hexdigest()
        cur.execute("INSERT INTO document_uploads (mobile, doc_path, original_name, sha256, "
                    "byte_size, content_type, source, uploaded_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (mobile, path, original[:200], digest, size, content_type, source, now))
        cur.execute("UPDATE agent_drafts SET doc_path = %s, doc_name = %s, updated_at = %s "
                    "WHERE mobile = %s", (path, original[:120], now, mobile))
    return {"status": "ok", "doc_name": original, "sha256": digest, "byte_size": size,
            "uploaded_at_ist": fmt_ist(now)}


class _TooLarge(Exception):
    pass


def document_provenance(application_id=None, doc_path=None):
    """What was recorded when a document arrived through the agent channel."""
    if application_id is None and not doc_path:
        raise ServiceError("bad_field", "give application_id or doc_path")
    with db() as cur:
        if application_id is not None:
            cur.execute("SELECT original_name, sha256, byte_size, content_type, source, "
                        "uploaded_at FROM document_uploads WHERE application_id = %s "
                        "ORDER BY id DESC LIMIT 1", (application_id,))
        else:
            cur.execute("SELECT original_name, sha256, byte_size, content_type, source, "
                        "uploaded_at FROM document_uploads WHERE doc_path = %s "
                        "ORDER BY id DESC LIMIT 1", (doc_path,))
        r = cur.fetchone()
    if not r:
        return {"recorded": False,
                "reason": "uploaded through the web form or predates this release"}
    return {"recorded": True, "original_name": r[0], "sha256": r[1], "byte_size": r[2],
            "content_type": r[3], "source": r[4], "uploaded_at_ist": fmt_ist(r[5])}


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


def submit(mobile, confirm_declaration):
    """The agent path: file this mobile's draft. Same validator, same locked write as
    the web form; the SUBMIT audit row is written by portal.create_application."""
    if confirm_declaration is not True:
        return {"status": "declaration_required"}
    win = window_status()
    if not win["open"]:
        return {"status": "invalid", "errors": ["the application window has closed"],
                "window": win}
    with db() as cur:
        existing = portal.active_application(cur, mobile)
        d = _load_draft(cur, mobile)
    if existing:                     # checked again under the lock in _submit_locked
        return {"status": "duplicate",
                "existing": {"id": existing[0], "application_no": existing[1],
                             "status": existing[2]}}
    fields = d["data"] if d else {}
    doc_path = d["doc_path"] if d else None
    missing, _, _ = _assess(fields, doc_path)
    fields_missing = [m for m in missing if m != DOC_MISSING]
    if fields_missing:
        return {"status": "incomplete", "missing": missing}
    if not doc_path:
        return {"status": "no_document"}
    errors, cleaned = portal.validate_application(_portal_fields(fields), doc_path)
    if errors:
        return {"status": "invalid", "errors": errors}
    with db(commit=True) as cur:
        res = _submit_locked(cur, mobile, cleaned)
        if res["status"] == "ok":
            cur.execute("SELECT submitted_at FROM applications WHERE id = %s", (res["id"],))
            submitted_at = cur.fetchone()[0]
            res.update(submitted_at_ist=fmt_ist(submitted_at),
                       deemed_date_ist=_fmt(deemed_date(submitted_at)),
                       date_of_birth=cleaned["dob"].strftime("%d/%m/%Y"))
    return _after_submit(mobile, res)


def submit_web(mobile, form_data, doc_path):
    """The web form's submission. form_data uses the form's own field names."""
    errors, cleaned = portal.validate_application(form_data or {}, doc_path)
    if errors:
        return {"status": "invalid", "errors": errors}
    with db(commit=True) as cur:
        res = _submit_locked(cur, mobile, cleaned)
    return _after_submit(mobile, res)


# ---------------------------------------------------------------------------
# Citizen: their own application
# ---------------------------------------------------------------------------


def my_application(mobile):
    """The signed-in mobile's most recent application, and any draft in progress.
    Reads only rows for this mobile."""
    with db() as cur:
        cur.execute("SELECT %s FROM applications WHERE mobile = %%s "
                    "ORDER BY submitted_at DESC, id DESC LIMIT 1"
                    % ", ".join(APPLICATION_COLUMNS), (mobile,))
        r = cur.fetchone()
        reason = None
        if r:
            row = _row_dict(r)
            if row["status"] == "REJECTED":
                cur.execute("SELECT note FROM audit_log WHERE application_id = %s "
                            "AND action = 'REJECTED' ORDER BY at DESC LIMIT 1", (row["id"],))
                n = cur.fetchone()
                reason = (n[0] or "").strip() if n else None
    draft = get_draft(mobile)
    if not r:
        return {"found": False, "draft": draft}
    return {
        "found": True, "application_no": row["application_no"], "status": row["status"],
        "submitted_at_ist": fmt_ist(row["submitted_at"]),
        "decided_at_ist": fmt_ist(row["decided_at"]), "decided_by": row["decided_by"],
        "reason": reason or None,
        "deemed_date_ist": (_fmt(deemed_date(row["submitted_at"]))
                            if row["status"] == "PENDING" else None),
        "village": row["village"], "block": row["block"],
        "doc_attached": bool((row["doc_path"] or "").strip()),
        "draft": draft,
    }


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


STATUSES = ("PENDING", "APPROVED", "DEEMED_APPROVED", "REJECTED", "WITHDRAWN")
PAGE_SIZE = 20


def next_deemed_run():
    """The next run of the nightly deemed-approval job, naive UTC."""
    now = datetime.now()
    run = now.replace(hour=DEEMED_RUN_HOUR_UTC, minute=0, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def _deemed_on(submitted_at):
    """When the job will actually deem this row approved: its statutory date, or the next
    nightly run if that date has already passed."""
    nxt = to_ist(next_deemed_run())
    due = deemed_date(submitted_at)
    return max(due, nxt)


def _days_since(dt):
    return max(0, (datetime.now() - dt).days) if dt else None


def queue_summary():
    """What is waiting: per block, past the 15-day SLA, and due to be deemed approved
    within 48 hours. Overdue uses the same cutoff as the dashboard and the job."""
    cutoff = datetime.now() - timedelta(days=portal.SLA_DAYS)
    horizon = portal.now_ist() + timedelta(hours=48)
    with db() as cur:
        cur.execute("SELECT block, count(*) FROM applications WHERE status = 'PENDING' "
                    "GROUP BY block")
        counts = dict(cur.fetchall())
        cur.execute("SELECT count(*), min(submitted_at) FROM applications "
                    "WHERE status = 'PENDING'")
        total, oldest = cur.fetchone()
        cur.execute("SELECT count(*) FROM applications WHERE status = 'PENDING' "
                    "AND submitted_at < %s", (cutoff,))
        overdue = cur.fetchone()[0]
        # anything submitted more than 13 days ago can fall due within 48 hours
        cur.execute("SELECT id, application_no, block, submitted_at FROM applications "
                    "WHERE status = 'PENDING' AND submitted_at < %s "
                    "ORDER BY submitted_at ASC, id ASC",
                    (datetime.now() - timedelta(days=portal.SLA_DAYS - 2),))
        due = [(r, _deemed_on(r[3])) for r in cur.fetchall()]
    due = [(r, d) for r, d in due if d <= horizon]
    by_block = [{"block": b, "pending": counts.get(b, 0)} for b in BLOCKS]
    other = sum(n for b, n in counts.items() if b not in BLOCKS)
    if other:
        by_block.append({"block": "(other)", "pending": other})
    return {
        "pending_total": total, "by_block": by_block, "overdue_15d": overdue,
        "deemed_within_48h": {
            "count": len(due),
            "first_20": [{"id": r[0], "application_no": r[1], "block": r[2],
                          "deemed_on_ist": _fmt(d)} for r, d in due[:PAGE_SIZE]]},
        "oldest_pending_ist": fmt_ist(oldest) if oldest else None,
        "next_nightly_run_ist": _fmt(to_ist(next_deemed_run())),
    }


def list_applications(status=None, block=None, overdue_only=False, search=None, page=1):
    """Oldest first, 20 a page. With no status: PENDING, unless searching (then all)."""
    st = None
    if status not in (None, ""):
        st = str(status).strip().upper()
        if st not in STATUSES:
            return {"status": "bad_status", "valid": list(STATUSES)}
    blk = None
    if block not in (None, ""):
        blk = match_block(block)
        if not blk:
            return {"status": "bad_block", "valid": list(BLOCKS)}
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    s = (search or "").strip()
    if st is None and not s:
        st = "PENDING"

    where, args = [], []
    if st:
        where.append("status = %s"); args.append(st)
    if blk:
        where.append("block = %s"); args.append(blk)
    if overdue_only:
        where.append("status = 'PENDING' AND submitted_at < %s")
        args.append(datetime.now() - timedelta(days=portal.SLA_DAYS))
    if s:
        if re.fullmatch(r"(?i)SSP\d{8}", s):
            where.append("application_no = %s"); args.append(s.upper())
        elif re.fullmatch(r"\d{10}", s):
            where.append("mobile = %s"); args.append(s)
        else:
            where.append("applicant_name ILIKE %s")
            args.append("%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with db() as cur:
        cur.execute("SELECT count(*) FROM applications " + w, args)
        total = cur.fetchone()[0]
        cur.execute("SELECT id, application_no, applicant_name, mobile, block, status, "
                    "submitted_at FROM applications " + w +
                    " ORDER BY submitted_at ASC, id ASC LIMIT %s OFFSET %s",
                    args + [PAGE_SIZE, (page - 1) * PAGE_SIZE])
        rows = cur.fetchall()
    pages = max(1, -(-total // PAGE_SIZE))
    return {"status": "ok", "filter": {"status": st or "any", "block": blk,
                                       "overdue_only": bool(overdue_only), "search": s or None},
            "total": total, "page": page, "pages": pages,
            "rows": [{"id": r[0], "application_no": r[1], "applicant_name": r[2],
                      "mobile": r[3], "block": r[4], "status": r[5],
                      "submitted_at_ist": fmt_ist(r[6]),
                      "days_pending": _days_since(r[6]) if r[5] == "PENDING" else None}
                     for r in rows]}


def get_application(application_id=None, application_no=None):
    """One application in full: record, history, document provenance and computed
    eligibility warnings."""
    if (application_id is None) == (not application_no):
        raise ServiceError("bad_field", "give exactly one of application_id or application_no")
    with db() as cur:
        if application_id is not None:
            cur.execute("SELECT %s FROM applications WHERE id = %%s"
                        % ", ".join(APPLICATION_COLUMNS), (application_id,))
        else:
            cur.execute("SELECT %s FROM applications WHERE application_no = %%s"
                        % ", ".join(APPLICATION_COLUMNS), (application_no.strip().upper(),))
        r = cur.fetchone()
        if not r:
            return {"status": "not_found"}
        row = _row_dict(r)
        cur.execute("SELECT at, action, actor, note FROM audit_log WHERE application_id = %s "
                    "ORDER BY at ASC, id ASC", (row["id"],))
        audit = cur.fetchall()
    dob = row["dob"]
    pending = row["status"] == "PENDING"
    ttd = None
    if row["decided_at"] and row["submitted_at"]:
        ttd = max(0, (row["decided_at"] - row["submitted_at"]).days)
    return {
        "status": "ok",
        "application": {
            "id": row["id"], "application_no": row["application_no"],
            "applicant_name": row["applicant_name"], "mobile": row["mobile"],
            "date_of_birth": dob.strftime("%d/%m/%Y") if dob else None,
            "age_today": portal.age_on(dob, portal.now_ist().date()) if dob else None,
            "gender": row["gender"] or None, "marital_status": row["marital_status"] or None,
            "husband_name": row["husband_name"] or None, "village": row["village"],
            "block": row["block"], "bank_account": row["bank_account"],
            "ifsc": row["ifsc"] or None,
            "doc_attached": bool((row["doc_path"] or "").strip()),
            "app_status": row["status"], "submitted_at_ist": fmt_ist(row["submitted_at"]),
            "decided_at_ist": fmt_ist(row["decided_at"]), "decided_by": row["decided_by"],
            "days_pending": _days_since(row["submitted_at"]) if pending else None,
            "days_to_decision": ttd,
            "deemed_on_ist": _fmt(_deemed_on(row["submitted_at"])) if pending else None,
        },
        "document": (document_provenance(application_id=row["id"])
                     if (row["doc_path"] or "").strip() else None),
        "warnings": eligibility_warnings(row),
        "history": [{"at_ist": fmt_ist(a[0]), "action": a[1], "by": a[2], "note": a[3] or ""}
                    for a in audit],
    }


DOC_READ_CAP = 10 * 1024 * 1024
DOC_MIMETYPES = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "png": "image/png"}


def _safe_doc_path(doc_path):
    """The real path of a stored document, or None if it resolves outside UPLOAD_DIR."""
    if not (doc_path or "").strip():
        return None
    root = os.path.realpath(portal.UPLOAD_DIR)
    real = os.path.realpath(doc_path)
    if os.path.commonpath([root, real]) != root or real == root:
        return None
    return real


def application_document(application_id):
    """(bytes, mimetype, filename) of an application's age proof, or None when there is
    no document, the file is missing, it lies outside UPLOAD_DIR, or it exceeds 10 MB."""
    with db() as cur:
        cur.execute("SELECT doc_path FROM applications WHERE id = %s", (application_id,))
        row = cur.fetchone()
    real = _safe_doc_path(row[0] if row else None)
    if not real or not os.path.isfile(real):
        return None
    with open(real, "rb") as fh:
        data = fh.read(DOC_READ_CAP + 1)
    if len(data) > DOC_READ_CAP:
        return None
    name = os.path.basename(real)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return data, DOC_MIMETYPES.get(ext, "application/octet-stream"), name


def document_for_view(application_id):
    """Everything view_age_proof needs, with each failure told apart: no document, file
    missing on disk, path refused, too large. On success the bytes are hashed again so a
    file changed since upload is caught."""
    with db() as cur:
        cur.execute("SELECT application_no, doc_path, dob FROM applications WHERE id = %s",
                    (application_id,))
        r = cur.fetchone()
    if not r:
        return {"status": "not_found"}
    app_no, doc_path, dob = r
    base = {"application_no": app_no, "doc_path": doc_path,
            "date_of_birth": dob.strftime("%d/%m/%Y") if dob else None}
    if not (doc_path or "").strip():
        return dict(base, status="no_document")
    real = _safe_doc_path(doc_path)
    if not real:
        return dict(base, status="refused")
    if not os.path.isfile(real):
        return dict(base, status="missing_file")
    with open(real, "rb") as fh:
        data = fh.read(DOC_READ_CAP + 1)
    if len(data) > DOC_READ_CAP:
        return dict(base, status="too_large")
    name = os.path.basename(real)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    prov = document_provenance(application_id=application_id)
    if not prov["recorded"]:
        prov = document_provenance(doc_path=doc_path)
    return dict(base, status="ok", data=data, ext=ext,
                mimetype=DOC_MIMETYPES.get(ext, "application/octet-stream"),
                sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data),
                provenance=prov)


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
