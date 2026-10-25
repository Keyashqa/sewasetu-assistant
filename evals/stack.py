"""The local docker compose stack the evals run against (EVAL_PLAN §2)."""

import json
import os
import subprocess
import threading
import time

import requests

from .config import BASE_URL, REPO, RESULTS, assert_local

SERVICES = ["db", "app", "mcp", "proxy", "smsgw"]     # the scheduler stays off
EVAL_PREFIX = "98"                                     # mobiles 98 PP RRRR SS (§2a)
_counter_lock = threading.Lock()


def compose(*args, env=None, check=True, capture=True, input=None):
    """env values of None remove the variable, so compose falls back to .env."""
    e = dict(os.environ)
    for k, v in (env or {}).items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    p = subprocess.run(["docker", "compose", *args], cwd=REPO, env=e, input=input,
                       capture_output=capture, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError("docker compose %s failed:\n%s" % (" ".join(args), (p.stderr or "")[-2000:]))
    return p


def psql(sql):
    """Rows as lists of strings (psql -At, '|' separated), decoded as UTF-8."""
    p = compose("exec", "-T", "db", "psql", "-U", "sewasetu", "-d", "sewasetu", "-v", "ON_ERROR_STOP=1",
                "-At", "-F", "|", "-c", sql)
    return [line.split("|") for line in p.stdout.splitlines() if line != ""]


def scalar(sql):
    rows = psql(sql)
    return rows[0][0] if rows else None


def fixture(*args):
    """Run app/scripts/eval_fixtures.py in the app container; returns its JSON."""
    p = compose("exec", "-T", "app", "python", "/app/scripts/eval_fixtures.py", *args, check=False)
    lines = [l for l in p.stdout.splitlines() if l.strip()]
    out = json.loads(lines[-1]) if lines else {"status": "error", "stderr": p.stderr[-1000:]}
    if out.get("status") != "ok":
        raise RuntimeError("fixture %s failed: %s %s" % (args[0], out, p.stderr[-500:]))
    return out


def wait_healthy(timeout=300):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            home = requests.get(BASE_URL + "/", timeout=5).status_code
            mcp = [requests.post(BASE_URL + "/mcp/" + s, json={}, timeout=5) for s in ("citizen", "officer")]
            ok_mcp = all(r.status_code == 401 and "resource_metadata" in r.headers.get("WWW-Authenticate", "")
                         for r in mcp)
            gw = requests.get(BASE_URL + "/__gateway/api/messages", timeout=5).status_code
            if home == 200 and ok_mcp and gw == 200 and scalar(
                    "SELECT count(*) FROM applications WHERE status='PENDING' AND id<=100000") == "700":
                return
            last = (home, [r.status_code for r in mcp], gw)
        except Exception as e:                       # starting up: connection refused, db not ready
            last = repr(e)[:200]
        time.sleep(3)
    raise TimeoutError("stack not healthy after %ss: %s" % (timeout, last))


def baseline():
    """Seed status counts (id <= 100000): G3 compares against this."""
    return {s: int(c) for s, c in psql(
        "SELECT status, count(*) FROM applications WHERE id<=100000 GROUP BY 1 ORDER BY 1")}


MOBILE_TABLES = ("applications", "portal_users", "otps", "agent_drafts", "helper_filings",
                 "document_uploads")


def used_mobiles(mobiles):
    """Which of `mobiles` already appear anywhere. The seed's 100k mobiles cover every
    2-4 digit prefix, so runs reserve exact numbers and check them instead (§2a)."""
    if not mobiles:
        return set()
    lst = ",".join("'%s'" % m for m in mobiles if m.isdigit())
    sql = " UNION ".join("SELECT mobile FROM %s WHERE mobile IN (%s)" % (t, lst) for t in MOBILE_TABLES)
    sql += " UNION SELECT helper FROM helper_filings WHERE helper IN (%s)" % lst
    return {r[0] for r in psql(sql)}


def reset():
    """down -v, up without the scheduler, wait, sanity checks. Returns the baseline."""
    assert_local()
    compose("down", "-v")
    compose("up", "-d", "--build", *SERVICES)
    try:
        wait_healthy(600)
    except TimeoutError:
        # app workers that booted before Postgres finished loading the seed can hang; one
        # restart of app + mcp clears it (seen once, 25/10/2026)
        compose("restart", "app", "mcp")
        wait_healthy(300)
    return baseline()


def set_deadline(value):
    """Recreate app + mcp with SCHEME_DEADLINE (None = back to the .env value, or app.ini if
    .env has none). --no-deps keeps the SMS gateway's in-memory inbox."""
    compose("up", "-d", "--force-recreate", "--no-deps", "app", "mcp",
            env={"SCHEME_DEADLINE": value})
    end = time.time() + 120
    while time.time() < end:
        try:
            if requests.post(BASE_URL + "/mcp/citizen", json={}, timeout=5).status_code == 401 and \
                    requests.get(BASE_URL + "/", timeout=5).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError("app/mcp not back after deadline change")


def next_run_counter():
    """Global, monotonic run counter (RRRR in the mobiles), kept across rounds."""
    with _counter_lock:
        RESULTS.mkdir(parents=True, exist_ok=True)
        path = RESULTS / ".counter"
        n = int(path.read_text().strip() or 0) + 1 if path.exists() else 1
        path.write_text(str(n))
        return n


def mobile(persona_no, run_counter, slot):
    return "%s%02d%04d%02d" % (EVAL_PREFIX, persona_no, run_counter % 10000, slot)


def reserve_mobiles(persona_no, slots):
    """(run_counter, {slot: mobile}) for a run, skipping any counter whose numbers exist."""
    while True:
        n = next_run_counter()
        ms = {s: mobile(persona_no, n, s) for s in slots}
        if not used_mobiles(list(ms.values())):
            return n, ms
