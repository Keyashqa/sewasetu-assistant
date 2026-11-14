# -*- coding: utf-8 -*-
"""
Session-level MCP metrics, computed from mcp_calls rows (no database access here, so the
rules are unit-tested on synthetic rows: evals/tests/test_mcp_metrics.py).

Definitions (also shown on /admin/mcp-metrics):
- Session: one sign-in. Access tokens: the sign-in's fixed end time identifies it (it is
  copied unchanged into every refreshed token). Program tokens: one token, split into a
  new session after IDLE_GAP of no calls.
- Process: the calls since the previous apply/decision completion in the session, up to
  and including this completion. A status check counts as a process only in a session
  with no apply or decision; its calls run up to the first successful status read.
- Repeat: the same tool with the same arguments earlier in the session, with no
  successful write in between. Repeats of POLL_TOOLS are polls (asked for by design),
  not waste.
- Wasted call: an error, or a repeat that is not a poll (counted once).
- Abandoned session: no completion, and no call for IDLE_GAP. Abandoned application: an
  abandoned session that saved application details.
"""

import math
import statistics
from datetime import timedelta

IDLE_GAP = timedelta(minutes=30)
CHARS_PER_TOKEN = 3.5          # estimate; see imp.md §5

# Successful calls of these change portal state: a repeat after one is not a waste.
WRITE_TOOLS = frozenset({"save_application_details", "submit_application",
                         "withdraw_application", "approve_application", "reject_application"})
# Called again by design (the instructions say to check again after the person replies).
POLL_TOOLS = frozenset({"get_link", "get_my_application",
                        # before the merge (TOOL_MERGE.md), for older runs
                        "get_document_upload_link", "get_number_verification_link"})
PROCESS_TYPES = ("apply", "decision", "status")
# Citizen tools retired by the merge (TOOL_MERGE.md); rows logged before it keep these names.
RETIRED_TOOLS = frozenset({"get_scheme_info", "check_eligibility", "get_document_upload_link",
                           "get_number_verification_link"})

# A result that is False on one of these keys is a refusal (the portal said no).
REFUSAL_FLAGS = ("submitted", "approved", "rejected", "withdrawn", "eligible")
# Codes the tools put in "status" / "reason". Anything else is stored as 'other'.
REASONS = frozenset({
    "not_found", "reason_required", "not_pending", "invalid", "no_file", "duplicate",
    "too_large", "quote_required", "note_required", "not_verified", "no_match",
    "no_document", "incomplete", "future_date", "expired", "declaration_required",
    "blocked", "bad_type", "bad_status", "bad_reason", "bad_number", "bad_date", "bad_block",
    "not_eligible", "input", "exception",
})


def classify(tool, data):
    """(outcome, reason, completion) from a tool's result dict (None: not readable).
    Used by the servers (mcp_server/metrics.py) and by the eval harness, so both count
    the same way."""
    if data is None:
        return "ok", None, None
    if "error" in data:
        return "error", "input", None
    refused = any(data.get(k) is False for k in REFUSAL_FLAGS)
    completion = None
    # success shapes: submit -> application_number (and "submitted" is the filing time);
    # approve / reject -> status "approved" / "rejected" (failures carry approved/rejected False)
    if tool == "submit_application" and not refused and data.get("application_number"):
        completion = "apply"
    elif tool == "approve_application" and not refused and data.get("status") == "approved":
        completion = "decision"
    elif tool == "reject_application" and not refused and data.get("status") == "rejected":
        completion = "decision"
    elif tool == "get_my_application" and (data.get("found") is True or data.get("filed_for_others")):
        completion = "status"
    if not refused:
        return "ok", None, completion
    code = data.get("reason") if tool == "submit_application" else data.get("status")
    if data.get("eligible") is False:
        code = "not_eligible"
    code = code if isinstance(code, str) and code in REASONS else "other"
    return "refused", code, None



def est_tokens(chars):
    return int(round(float(chars or 0) / CHARS_PER_TOKEN))


def _split_sessions(rows):
    """rows: dicts with session_key, token_kind, tool, args_key, outcome, completion, at,
    ordered by (session_key, at). Yields lists of rows, one per session."""
    cur, key, last = [], None, None
    for r in rows:
        new = r["session_key"] != key
        if not new and r["token_kind"] == "program" and r["at"] - last > IDLE_GAP:
            new = True
        if new and cur:
            yield cur
            cur = []
        cur.append(r)
        key, last = r["session_key"], r["at"]
    if cur:
        yield cur


def summarize(values):
    """n, median, 90th percentile (nearest rank) and mean of a list of call counts."""
    v = sorted(values)
    if not v:
        return {"n": 0, "median": None, "p90": None, "mean": None}
    median = statistics.median(v)
    return {"n": len(v), "median": int(median) if median == int(median) else median,
            "p90": v[max(0, math.ceil(0.9 * len(v)) - 1)],
            "mean": round(sum(v) / len(v), 1)}


def analyze(rows, now):
    """Session metrics for a window of rows. Returns plain numbers for the page."""
    process_calls = {t: [] for t in PROCESS_TYPES}
    per_tool = {}                     # tool -> {"repeats", "polls"}
    total = errors = wasted = repeats = polls = 0
    sessions = completed = abandoned = abandoned_apps = in_progress = 0

    for sess in _split_sessions(rows):
        sessions += 1
        seen, epoch = set(), 0
        seg_calls = 0
        has_main = any(r["completion"] in ("apply", "decision") for r in sess)
        status_counted = False
        any_completion = False
        saved = False
        for i, r in enumerate(sess, 1):
            total += 1
            tool = r["tool"]
            t = per_tool.setdefault(tool, {"repeats": 0, "polls": 0})
            key = (epoch, tool, r["args_key"])
            is_repeat = key in seen
            seen.add(key)
            is_error = r["outcome"] == "error"
            errors += is_error
            if is_repeat and tool in POLL_TOOLS:
                polls += 1
                t["polls"] += 1
            elif is_repeat:
                repeats += 1
                t["repeats"] += 1
            if is_error or (is_repeat and tool not in POLL_TOOLS):
                wasted += 1
            if tool in WRITE_TOOLS and r["outcome"] == "ok":
                epoch += 1
                if tool == "save_application_details":
                    saved = True

            seg_calls += 1
            c = r["completion"]
            if c:
                any_completion = True
            if c in ("apply", "decision"):
                process_calls[c].append(seg_calls)
                seg_calls = 0
            elif c == "status" and not has_main and not status_counted:
                process_calls["status"].append(i)
                status_counted = True

        if any_completion:
            completed += 1
        elif now - sess[-1]["at"] > IDLE_GAP:
            abandoned += 1
            abandoned_apps += saved
        else:
            in_progress += 1

    return {
        "calls": total, "errors": errors, "repeats": repeats, "polls": polls,
        "wasted": wasted,
        "wasted_pct": round(100.0 * wasted / total, 1) if total else None,
        "sessions": sessions, "completed_sessions": completed,
        "abandoned_sessions": abandoned, "abandoned_applications": abandoned_apps,
        "in_progress_sessions": in_progress,
        "processes": {t: summarize(v) for t, v in process_calls.items()},
        "per_tool": per_tool,
    }
