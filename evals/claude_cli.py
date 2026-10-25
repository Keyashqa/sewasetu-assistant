"""Running `claude -p`, with Claude Pro usage limits in mind (EVAL_PLAN §3.4).

Every stream-json / json run carries a `rate_limit_event`:
  {"rate_limit_info": {"status": "allowed"|"rejected", "resetsAt": <epoch>,
   "rateLimitType": "five_hour", "unifiedWindows": {"five_hour": {"utilization": 0.15,
   "resetsAt": ..., "status": ...}, "seven_day": {...}}}}
That is the primary signal. The error text ("You've hit your ... limit", "usage limit
reached", "resets 3pm") is composed at run time, so it is only a fallback.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

LIMIT_TEXT = re.compile(r"hit your [\w' ]*limit|usage limit|rate.?limit|resets? (at )?\d", re.I)
# pause before a call when a window is this full, so a run is not cut mid-turn
PAUSE_AT_UTILIZATION = 0.99
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


# ---------------------------------------------------------------------------
# running a call: one shared pause for all workers
# ---------------------------------------------------------------------------

MAX_PAUSE_S = 6 * 3600
_lock = threading.Lock()
_paused_until = 0.0
_last_info = None


class LimitTooLong(Exception):
    """A usage limit whose reset is further off than MAX_PAUSE_S (e.g. the weekly one)."""


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def _wait_shared(pauses, ctx, reason, reset_at, message):
    """Every worker waits for the same reset; the pause is recorded by whoever saw it."""
    global _paused_until
    wait = wait_seconds(reset_at)
    if wait > MAX_PAUSE_S:
        raise LimitTooLong("%s: resets %s" % (message[:120], _iso(reset_at) if reset_at else "?"))
    with _lock:
        _paused_until = max(_paused_until, time.time() + wait)
        until = _paused_until
    start = time.time()
    rec = dict(ctx, at=_iso(start), reason=reason, message=message[:300],
               reset_at=_iso(reset_at) if reset_at else None)
    print("[limits] pausing %.0f min (%s): %s" % ((until - start) / 60, reason, message[:120]), flush=True)
    while time.time() < until:
        time.sleep(min(30, until - time.time()))
    rec.update(resumed_at=_iso(time.time()), waited_s=round(time.time() - start))
    pauses.append(rec)


def _wait_if_paused():
    while True:
        with _lock:
            left = _paused_until - time.time()
        if left <= 0:
            return
        time.sleep(min(30, left))


def session_file(session_id):
    hits = glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*",
                                    session_id + ".jsonl"))
    return hits[0] if hits else None


def run(cmd, stdin, cwd, pauses, ctx, session_id=None, env=None):
    """Run one `claude -p` call to completion, pausing through usage limits.

    Returns (events, returncode, stderr). `pauses` collects pause records; `ctx` names
    the role/persona/turn for them. For a resumed client session, the session file is
    snapshotted first and restored before a retry, so a refused turn is never sent twice.
    """
    global _last_info
    while True:
        _wait_if_paused()
        near = near_limit(_last_info)
        if near:
            _wait_shared(pauses, ctx, "near_limit:%s" % near[0], near[1], "utilization >= %.0f%%"
                         % (PAUSE_AT_UTILIZATION * 100))
            with _lock:
                _last_info = None
        snap = None
        sf = session_file(session_id) if session_id else None
        if sf:
            snap = sf + ".bak"
            shutil.copyfile(sf, snap)
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=cwd, env=dict(os.environ, **(env or {})))
        events = []
        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        info = rate_limit_info(events)
        if info:
            with _lock:
                _last_info = info
        hit = limit_hit(events, p.stdout[-500:], p.stderr[-500:], p.returncode)
        if not hit:
            if snap:
                os.remove(snap)
            return events, p.returncode, p.stderr
        if snap:
            shutil.copyfile(snap, session_file(session_id) or sf)
            os.remove(snap)
        elif session_id and session_file(session_id):
            os.remove(session_file(session_id))     # a refused first turn: --session-id again
        _wait_shared(pauses, ctx, "limit:%s" % hit["kind"], hit["reset_at"], hit["message"])
        with _lock:
            _last_info = None           # that reading is from before the reset


def utilization(info):
    """{five_hour: {utilization, resets_at}, seven_day: {...}} from a rate_limit_info."""
    out = {}
    for name, w in ((info or {}).get("unifiedWindows") or {}).items():
        out[name] = {"utilization": w.get("utilization"),
                     "resets_at": _iso(w["resetsAt"]) if w.get("resetsAt") else None}
    return out


def probe_utilization(pauses, ctx):
    """Read the subscription's 5-hour and weekly utilization with one tiny Haiku call. Only
    stream-json output carries the rate_limit_event, so the probe uses it."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="ssprobe-")
    cmd = ["claude", "-p", "--model", "claude-haiku-5-5", "--max-turns", "1", "--tools", "",
           "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--no-chrome",
           "--no-session-persistence", "--output-format", "stream-json", "--verbose"]
    try:
        events, _, _ = run(cmd, "Reply with the word ok.", tmp, pauses, dict(ctx, role="probe"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return dict(utilization(rate_limit_info(events)), at=_iso(time.time()),
                probe_cost_usd_equiv=result.get("total_cost_usd"))
