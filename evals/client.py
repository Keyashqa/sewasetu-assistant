"""The client under test: stock Claude Code (`claude -p`, Haiku) with one Sewa Setu MCP
server and nothing else (EVAL_PLAN §3.1). One invocation per persona message; the
conversation is carried by --session-id / --resume.
"""

import json
import os
import shutil
import subprocess
import tempfile
import uuid

from . import claude_cli
from .config import CLIENT_MODEL, MAX_TURNS_PER_MESSAGE

TOOLS = {
    "citizen": {"check_eligibility", "get_document_upload_link", "get_my_application",
                "get_number_verification_link", "get_scheme_info", "save_application_details",
                "submit_application", "withdraw_application"},
    "officer": {"approve_application", "get_age_proof_link", "get_application",
                "get_queue_summary", "list_applications", "reject_application"},
}


class IsolationBreach(Exception):
    pass


class Client:
    def __init__(self, role, url, grant, pauses, ctx):
        self.role, self.url, self.grant = role, url, grant
        self.server = "sewasetu-" + role
        self.tmp = tempfile.mkdtemp(prefix="sseval-")
        self.session = str(uuid.uuid4())
        self.started = False
        self.cost_so_far = 0.0
        self.pauses, self.ctx = pauses, ctx

    def _write_cfg(self):
        with open(os.path.join(self.tmp, "mcp.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {self.server: {
                "type": "http", "url": self.url,
                "headers": {"Authorization": "Bearer " + self.grant.fresh()}}}}, f)

    def _check_init(self, ev):
        want = {"mcp__%s__%s" % (self.server, t) for t in TOOLS[self.role]}
        problems = []
        if set(ev.get("tools") or []) != want:
            problems.append("tools %s" % sorted(set(ev.get("tools") or []) ^ want))
        servers = ev.get("mcp_servers") or []
        if [(s.get("name"), s.get("status")) for s in servers] != [(self.server, "connected")]:
            problems.append("mcp_servers %s" % servers)
        if ev.get("slash_commands") or ev.get("skills"):
            problems.append("slash_commands/skills present")
        if any(p.get("path") != "builtin" for p in ev.get("plugins") or []):
            problems.append("non-builtin plugin %s" % ev.get("plugins"))
        if problems:
            raise IsolationBreach("; ".join(problems))

    def turn(self, message, turn_no):
        """Send one persona message. Returns the turn record (visible text, tool calls with
        results, usage)."""
        self._write_cfg()
        cmd = ["claude", "-p", "--model", CLIENT_MODEL, "--max-turns", str(MAX_TURNS_PER_MESSAGE),
               "--mcp-config", os.path.join(self.tmp, "mcp.json"), "--strict-mcp-config",
               "--tools", "", "--allowedTools", "mcp__" + self.server,
               "--permission-mode", "dontAsk", "--permission-prompts", "none",
               "--setting-sources", "", "--disable-slash-commands", "--no-chrome",
               "--output-format", "stream-json", "--verbose"]
        cmd += ["--resume", self.session] if self.started else ["--session-id", self.session]
        events, rc, stderr = claude_cli.run(cmd, message, self.tmp, self.pauses,
                                            dict(self.ctx, role="client", turn=turn_no),
                                            session_id=self.session)
        self.started = True
        texts, calls, by_id, result, ok_init = [], [], {}, None, False
        for ev in events:
            t = ev.get("type")
            if t == "system" and ev.get("subtype") == "init":
                self._check_init(ev)
                ok_init = True
            elif t == "assistant":
                for c in ev["message"].get("content", []):
                    if c.get("type") == "text" and c.get("text", "").strip():
                        texts.append(c["text"].strip())
                    elif c.get("type") == "tool_use":
                        if not c["name"].startswith("mcp__sewasetu-"):
                            raise IsolationBreach("tool_use %s" % c["name"])
                        call = {"name": c["name"].split("__")[-1], "input": c.get("input", {}),
                                "result": None, "is_error": None, "after_text": len(texts)}
                        by_id[c["id"]] = call
                        calls.append(call)
            elif t == "user":
                content = ev.get("message", {}).get("content", [])
                for c in content if isinstance(content, list) else []:
                    if c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                        call = by_id[c["tool_use_id"]]
                        call["is_error"] = bool(c.get("is_error"))
                        call["result"] = _tool_result(c.get("content"))
            elif t == "result":
                result = ev
        if not ok_init and rc == 0:
            raise IsolationBreach("no init event")
        cost_total = (result or {}).get("total_cost_usd") or 0.0
        cost = max(0.0, cost_total - self.cost_so_far)
        self.cost_so_far = max(self.cost_so_far, cost_total)
        usage = (result or {}).get("usage") or {}
        return {
            "text": "\n\n".join(texts),
            "tool_calls": calls,
            "num_turns": (result or {}).get("num_turns"),
            "terminal_reason": (result or {}).get("terminal_reason") or (result or {}).get("subtype"),
            "is_error": (result or {}).get("is_error", rc != 0),
            "error": None if result and not result.get("is_error") else (stderr or "")[-300:] or
            (result or {}).get("result"),
            "cost_usd_equiv": round(cost, 6),
            "duration_ms": (result or {}).get("duration_ms"),
            "usage": {k: usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                                "cache_read_input_tokens", "output_tokens")},
        }

    def close(self):
        subprocess.run(["claude", "purge", self.tmp, "-y"], capture_output=True, text=True)
        shutil.rmtree(self.tmp, ignore_errors=True)


def _tool_result(content):
    """A tool result as the model got it: the parsed JSON object if it is one, else text."""
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return content
    return content
