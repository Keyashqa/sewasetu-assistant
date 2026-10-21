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
