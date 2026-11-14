"""MCP tool-call metrics (/admin/mcp-metrics): recording, failure isolation, privacy.

    docker compose exec -T mcp python /app/scripts/check_mcp_metrics.py          # full, local only
    docker compose exec -T mcp python /app/scripts/check_mcp_metrics.py --scan   # privacy scan only

Full mode (LOCAL ONLY, refuses unless PUBLIC_BASE_URL is localhost) calls read-only tools
through the metered servers (nothing is filed or changed), then checks:
- each call is recorded with the right tool, outcome, reason and completion;
- a tool's result is identical when recording fails, when the database write fails, and
  when metrics are off; a failed write drops rows without raising;
- the privacy scan below.
Its own rows are deleted afterwards.

--scan is read-only and safe on production: every value in every mcp_calls row must match
a strict format (whitelisted names and codes, 16-hex keys, integers), so no name, mobile,
date, account, IFSC, OTP or other text can be stored. Exits 1 if any check fails.
"""
import asyncio
import os
import re
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import app as portal                      # noqa: F401  MUST be first (see services.py)
import services                           # noqa: E402
from mcp_server import metrics            # noqa: E402
from mcp_metrics_calc import RETIRED_TOOLS  # noqa: E402
from mcp_server.auth import Principal, reset_principal, set_principal   # noqa: E402
from mcp_server.citizen import citizen    # noqa: E402
from mcp_server.officer import officer    # noqa: E402

MOBILE = "9000099971"
OTHER = "9000099972"
DOB_OK, DOB_YOUNG, DOB_BAD = "01/01/1950", "01/01/1990", "31/02/1950"

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % detail) if detail and not ok else ""))


async def tool_names():
    return {s.metrics_server: {t.name for t in await s.list_tools()} for s in (citizen, officer)}


def privacy_scan(names):
    allowed_tools = names["citizen"] | names["officer"] | {"unknown"} | RETIRED_TOOLS
    hex16 = re.compile(r"^[0-9a-f]{16}$")
    reasons = metrics.REASONS | {"other"}
    with services.db() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'mcp_calls' ORDER BY ordinal_position")
        cols = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT server, tool, session_key, principal_key, token_kind, args_key, "
                    "outcome, reason, completion, duration_ms, resp_chars FROM mcp_calls")
        rows = cur.fetchall()
    expected = ["id", "at", "server", "tool", "session_key", "principal_key", "token_kind",
                "args_key", "outcome", "reason", "completion", "duration_ms", "resp_chars"]
    check("mcp_calls has exactly the expected columns (no free-text column)", cols == expected,
          ", ".join(cols))
    bad = []
    for r in rows:
        server, tool, sk, pk, kind, ak, outcome, reason, completion, dur, chars = r
        ok = (server in ("citizen", "officer") and tool in allowed_tools
              and all(hex16.match(k or "") for k in (sk, pk, ak))
              and kind in ("access", "program") and outcome in ("ok", "refused", "error")
              and (reason is None or reason in reasons)
              and completion in (None, "apply", "decision", "status")
              and isinstance(dur, int) and isinstance(chars, int))
        if not ok:
            bad.append(r)
    check("every stored value matches its strict format (%d rows scanned)" % len(rows), not bad,
          "first offending row: %r" % (bad[:1],))
    return rows


def principal(session_ends):
    return Principal(role="citizen", subject="citizen:" + MOBILE, mobile=MOBILE, officer=None,
                     kind="access", session_ends=session_ends)


OFFICER = Principal(role="officer", subject="officer:admin", mobile=None, officer="admin",
                    kind="access", session_ends=None)


async def call(server, p, name, args):
    tok = set_principal(p)
    try:
        return await server.call_tool(name, args)
    finally:
        reset_principal(tok)


def text_of(result):
    content = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(c, "text", "") for c in content)


def our_rows(session_key):
    with services.db() as cur:
        cur.execute("SELECT tool, outcome, reason, completion, args_key, resp_chars FROM mcp_calls "
                    "WHERE session_key = %s ORDER BY id", (session_key,))
        return cur.fetchall()


async def full(names):
    session_ends = int(time.time()) + 3600
    p = principal(session_ends)
    key = metrics._h("a|citizen:%s|%s" % (MOBILE, session_ends))
    officer_key = metrics._h("a|officer:admin|")
    metrics._BUFFER.clear()

    plan = [
        (citizen, p, "check_scheme_and_eligibility", {}, ("ok", None, None)),
        (citizen, p, "check_scheme_and_eligibility", {"date_of_birth": DOB_BAD}, ("error", "input", None)),
        (citizen, p, "check_scheme_and_eligibility", {"date_of_birth": DOB_YOUNG}, ("refused", "not_eligible", None)),
        (citizen, p, "check_scheme_and_eligibility", {"date_of_birth": DOB_OK}, ("ok", None, None)),
        (citizen, p, "check_scheme_and_eligibility", {"date_of_birth": DOB_OK}, ("ok", None, None)),
        (citizen, p, "check_scheme_and_eligibility", {"date_of_birth": DOB_OK, "applicant_mobile": OTHER},
         ("error", "input", None)),
        (citizen, p, "get_my_application", {}, ("ok", None, None)),
    ]
    texts = []
    for server, pr, name, args, _ in plan:
        texts.append(text_of(await call(server, pr, name, args)))
    try:
        await call(citizen, p, "no_such_tool", {})
    except Exception:
        pass
    await call(officer, OFFICER, "get_queue_summary", {})
    metrics._flush_once()

    rows = our_rows(key)
    want = [(name, *exp) for _, _, name, _, exp in plan] + [("unknown", "error", "exception", None)]
    got = [r[:4] for r in rows]
    check("each citizen call recorded with tool, outcome, reason, completion", got == want,
          "got %r" % got)
    if len(rows) == len(want):
        check("same tool + same inputs give the same args_key; different inputs differ",
              rows[3][4] == rows[4][4] and rows[3][4] != rows[2][4])
        check("resp_chars is the length of the text the client receives",
              all(rows[i][5] == len(texts[i]) for i in range(len(texts))),
              "%r vs %r" % ([r[5] for r in rows[:len(texts)]], [len(t) for t in texts]))
    check("officer call recorded under the officer server", any(
        r[0] == "get_queue_summary" and r[1] == "ok" for r in our_rows(officer_key)))

    # failure isolation: the tool's text must be identical in every case
    args = {"date_of_birth": DOB_OK}
    base = text_of(await call(citizen, p, "check_scheme_and_eligibility", args))
    real_record = metrics.record

    def broken_record(*a, **k):
        raise RuntimeError("injected")
    metrics.record = broken_record
    try:
        same = text_of(await call(citizen, p, "check_scheme_and_eligibility", args))
    finally:
        metrics.record = real_record
    check("a failure while recording does not change the tool's result", same == base)

    real_write = metrics._write

    def broken_write(rows, cleanup):
        raise RuntimeError("injected: database unavailable")
    metrics._write = broken_write
    dropped_before = metrics._DROPPED
    try:
        same = text_of(await call(citizen, p, "check_scheme_and_eligibility", args))
        metrics._flush_once()                   # must not raise
        flushed_ok = True
    except Exception:
        flushed_ok = False
    finally:
        metrics._write = real_write
    check("a failed database write does not change the result or raise; rows are dropped",
          same == base and flushed_ok and metrics._DROPPED > dropped_before)

    metrics.ENABLED = False
    n = len(metrics._BUFFER)
    try:
        same = text_of(await call(citizen, p, "check_scheme_and_eligibility", args))
    finally:
        metrics.ENABLED = True
    check("MCP_METRICS=off records nothing and the result is unchanged",
          same == base and len(metrics._BUFFER) == n)

    sample = await call(citizen, p, "check_scheme_and_eligibility", args)
    metrics._BUFFER.clear()
    tok = set_principal(p)
    try:
        t0 = time.perf_counter()
        for _ in range(1000):
            metrics.record(citizen, "check_scheme_and_eligibility", args, sample, None, 1)
        per_call_us = (time.perf_counter() - t0) / 1000 * 1e6
    finally:
        reset_principal(tok)
    check("recording costs well under 1 ms per call (%.0f µs)" % per_call_us,
          per_call_us < 1000 and len(metrics._BUFFER) == 1000)
    metrics._BUFFER.clear()
    metrics._flush_once()

    # nothing typed into a tool appears anywhere
    rows_all = privacy_scan(names)
    blob = " ".join(str(v) for r in rows_all for v in r)
    leaks = [s for s in (MOBILE, OTHER, DOB_OK, DOB_YOUNG, DOB_BAD, "01011950", "admin")
             if s in blob]
    check("no test input (mobiles, dates, officer name) appears in any stored value", not leaks,
          ", ".join(leaks))

    with services.db(commit=True) as cur:
        cur.execute("DELETE FROM mcp_calls WHERE session_key IN (%s, %s)", (key, officer_key))


def main():
    names = asyncio.run(tool_names())
    check("tool counts: citizen = 7 (merged, TOOL_MERGE.md), officer = 6",
          (len(names["citizen"]), len(names["officer"])) == (7, 6))
    if "--scan" in sys.argv:
        privacy_scan(names)
    else:
        host = urlparse(os.environ.get("PUBLIC_BASE_URL", "")).hostname
        if host not in ("localhost", "127.0.0.1"):
            sys.exit("check_mcp_metrics.py: full mode is local only (PUBLIC_BASE_URL is %r); "
                     "use --scan on a deployment" % host)
        asyncio.run(full(names))
    print("\n%d/%d passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
