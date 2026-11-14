"""Real token footprint of each MCP server, against the chars/3.5 estimate.

One `claude -p` turn ("Reply with the single word OK.", --max-turns 1, same isolation flags
as the client under test) three ways: no MCP server, citizen only, officer only. The first
API call's context (input + cache creation + cache read tokens) holds the system prompt,
every tool definition and the server instructions; with minus without is what the server
costs an assistant before any call. LOCAL ONLY (signs in on the local stack).

    python -m evals calibrate <round>     # writes evals/results/<round>/calibration.json
"""

import json
import os
import shutil
import subprocess
import tempfile

from . import oauth, stack
from .client import TOOLS
from .config import CITIZEN_RESOURCE, CLIENT_MODEL, OFFICER_RESOURCE, RESULTS, assert_local

import sys
sys.path.insert(0, str(RESULTS.parent.parent / "app"))
from mcp_metrics_calc import est_tokens  # noqa: E402

MESSAGE = "Reply with the single word OK."
KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _context(server=None, url=None, token=None):
    tmp = tempfile.mkdtemp(prefix="sscal-")
    try:
        servers = {server: {"type": "http", "url": url, "headers": {"Authorization": "Bearer " + token}}} \
            if server else {}
        with open(os.path.join(tmp, "mcp.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": servers}, f)
        cmd = ["claude", "-p", "--model", CLIENT_MODEL, "--max-turns", "1",
               "--mcp-config", os.path.join(tmp, "mcp.json"), "--strict-mcp-config", "--tools", "",
               "--permission-mode", "dontAsk", "--setting-sources", "", "--disable-slash-commands",
               "--no-chrome", "--no-session-persistence", "--output-format", "stream-json", "--verbose"]
        if server:
            cmd[cmd.index("--permission-mode"):cmd.index("--permission-mode")] = ["--allowedTools", "mcp__" + server]
        p = subprocess.run(cmd, input=MESSAGE, capture_output=True, text=True, encoding="utf-8", cwd=tmp,
                           timeout=300)
        events = [json.loads(l) for l in p.stdout.splitlines() if l.strip().startswith("{")]
        init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
        first = next((e["message"]["usage"] for e in events if e.get("type") == "assistant"), None)
        if first is None:
            raise RuntimeError("no assistant event (rc %s): %s" % (p.returncode, p.stderr[-300:]))
        tools = sorted(t for t in init.get("tools", []) if t.startswith("mcp__"))
        return sum(first.get(k) or 0 for k in KEYS), tools
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _estimates():
    out = {}
    for server, instr, tools in [r for r in stack.psql(
            "SELECT server, instructions_chars, tools::text FROM mcp_footprint ORDER BY server")]:
        tl = json.loads(tools)
        out[server] = {"tools": len(tl), "estimate": est_tokens(int(instr)) + sum(est_tokens(t["chars"]) for t in tl)}
    return out


def calibrate(round_name):
    assert_local()
    cid = oauth.register_client("Sewa Setu calibration")
    _, ms = stack.reserve_mobiles(99, [0])
    citizen, _ = oauth.sign_in(cid, CITIZEN_RESOURCE, "citizen", ms[0])
    officer, _ = oauth.sign_in(cid, OFFICER_RESOURCE, "officer")
    base, _ = _context()
    est = _estimates()
    out = {"model": CLIENT_MODEL, "message": MESSAGE, "baseline_context": base}
    for role, url, grant in (("citizen", CITIZEN_RESOURCE, citizen), ("officer", OFFICER_RESOURCE, officer)):
        ctx, tools = _context("sewasetu-" + role, url, grant.fresh())
        want = sorted("mcp__sewasetu-%s__%s" % (role, t) for t in TOOLS[role])
        if tools != want:
            raise RuntimeError("%s: client saw tools %s, expected %s" % (role, tools, want))
        real = ctx - base
        e = est.get(role, {}).get("estimate")
        out[role] = {"tools": len(tools), "context": ctx, "real": real, "estimate": e,
                     "estimate_error_pct": round(100.0 * (e - real) / real, 1) if e and real else None}
    path = RESULTS / round_name / "calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return out
