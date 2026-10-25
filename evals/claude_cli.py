"""Running `claude -p`, with Claude Pro usage limits in mind (EVAL_PLAN §3.4).

Every stream-json / json run carries a `rate_limit_event`:
  {"rate_limit_info": {"status": "allowed"|"rejected", "resetsAt": <epoch>,
   "rateLimitType": "five_hour", "unifiedWindows": {"five_hour": {"utilization": 0.15,
   "resetsAt": ..., "status": ...}, "seven_day": {...}}}}
That is the primary signal. The error text ("You've hit your ... limit", "usage limit
reached", "resets 3pm") is composed at run time, so it is only a fallback.
"""

import re
import time

LIMIT_TEXT = re.compile(r"hit your [\w' ]*limit|usage limit|rate.?limit|resets? (at )?\d", re.I)
# pause before a call when a window is this full, so a run is not cut mid-turn
PAUSE_AT_UTILIZATION = 0.97
NO_RESET_PROBE_S = 15 * 60
RESET_MARGIN_S = 60


def rate_limit_info(events):
    """The last rate_limit_info seen in a run's events, or None."""
    info = None
    for ev in events:
        if ev.get("type") == "rate_limit_event":
            info = ev.get("rate_limit_info") or info
    return info


def limit_hit(events, stdout_text="", stderr_text="", returncode=0):
    """None, or {"reset_at": epoch|None, "kind": str, "message": str} when the call was
    refused for a usage limit. Any other failure returns None (an ordinary error)."""
    info = rate_limit_info(events)
    result = next((ev for ev in reversed(events) if ev.get("type") == "result"), None)
    failed = returncode != 0 or (result is not None and result.get("is_error"))
    message = ((result or {}).get("result") or stderr_text or stdout_text or "")[:300]
    if info and info.get("status") == "rejected":
        return {"reset_at": _reset(info), "kind": info.get("rateLimitType") or "unknown",
                "message": message}
    if failed and ((result or {}).get("api_error_status") == 429 or LIMIT_TEXT.search(message)):
        return {"reset_at": _reset(info) if info else None, "kind": "text", "message": message}
    return None


def near_limit(info, threshold=PAUSE_AT_UTILIZATION):
    """(window, reset_at) of a window at or above `threshold`, else None."""
    for name, w in ((info or {}).get("unifiedWindows") or {}).items():
        if (w.get("utilization") or 0) >= threshold:
            return name, w.get("resetsAt")
    return None


def _reset(info):
    windows = info.get("unifiedWindows") or {}
    rejected = [w.get("resetsAt") for w in windows.values() if w.get("status") == "rejected" and w.get("resetsAt")]
    return max(rejected) if rejected else info.get("resetsAt")


def wait_seconds(reset_at, now=None):
    """How long to sleep before retrying: until the reset plus a margin, or one probe
    interval when the reset time is unknown."""
    now = time.time() if now is None else now
    if not reset_at:
        return NO_RESET_PROBE_S
    return max(0, reset_at - now) + RESET_MARGIN_S
