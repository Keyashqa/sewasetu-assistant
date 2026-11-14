# -*- coding: utf-8 -*-
"""
Tool-call metrics for both MCP servers (/admin/mcp-metrics).

MeteredFastMCP overrides FastMCP.call_tool, the single handler every tools/call goes
through. FastMCP registers `self.call_tool` with the low-level server in _setup_handlers,
so the override sees every call without touching the tool functions or their schemas:
tools/list is unchanged.

Rules:
- Never break or slow a tool. Recording runs inside try/except and only appends a tuple
  to a bounded in-memory buffer. A background task (started in main.lifespan) writes the
  buffer every FLUSH_S seconds in a worker thread; if the write fails the rows are dropped.
- No personal data. No argument values and no free text are stored. The subject, the
  sign-in and the arguments are stored as truncated HMACs under a key derived from
  SECRET_KEY; tool names and reason codes only from whitelists.
- MCP_METRICS=off turns recording off.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from collections import deque

import anyio
import jwt
from mcp.server.fastmcp import FastMCP
from psycopg2.extras import Json, execute_values

import services
from mcp_metrics_calc import REASONS, classify as _classify  # noqa: F401  (REASONS: check script)
from mcp_server import auth

log = logging.getLogger("sewasetu.mcp_metrics")

ENABLED = os.environ.get("MCP_METRICS", "on").strip().lower() not in ("off", "0", "false", "no")
FLUSH_S = 10
BUFFER_MAX = 2000
RETENTION_DAYS = 30
CLEANUP_EVERY_S = 24 * 3600

_KEY = hmac.new(os.environ.get("SECRET_KEY", "").encode(), b"mcp-metrics-v1",
                hashlib.sha256).digest()

_BUFFER = deque(maxlen=BUFFER_MAX)
_DROPPED = 0

def _h(value):
    return hmac.new(_KEY, value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _program_jti(server):
    """The program token's jti, read from the request (already verified by MCPEndpoint).
    None when it cannot be read."""
    try:
        req = server.get_context().request_context.request
        header = req.headers.get("authorization", "")
        if header.startswith("Bearer "):
            return jwt.decode(header[7:].strip(), options={"verify_signature": False}).get("jti")
    except Exception:
        pass
    return None


def _payload(result):
    """(dict or None, chars of text the client receives) from what FastMCP returns."""
    content, data = result, None
    if isinstance(result, tuple) and len(result) == 2:
        content, data = result
    chars = 0
    texts = []
    for c in content if isinstance(content, (list, tuple)) else []:
        t = getattr(c, "text", None)
        if isinstance(t, str):
            chars += len(t)
            texts.append(t)
    if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], dict):
        data = data["result"]
    if not isinstance(data, dict) and len(texts) == 1:
        try:
            data = json.loads(texts[0])
        except Exception:
            data = None
    return (data if isinstance(data, dict) else None), chars


def record(server, tool, arguments, result, error, duration_ms):
    """Append one row to the buffer. Never raises."""
    global _DROPPED
    if not ENABLED:
        return
    try:
        p = auth._PRINCIPAL.get()
        if p is None:
            return
        if p.kind == "program":
            kind = "program"
            session_key = _h("p|%s" % (_program_jti(server) or p.subject))
        else:
            kind = "access"
            session_key = _h("a|%s|%s" % (p.subject, p.session_ends or ""))
        if error is not None:
            outcome, reason, completion, chars = "error", "exception", None, len(str(error))
        else:
            data, chars = _payload(result)
            outcome, reason, completion = _classify(tool, data)
        try:
            args = json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            args = repr(sorted((arguments or {}).items()))
        if len(_BUFFER) == _BUFFER.maxlen:
            _DROPPED += 1
        _BUFFER.append((server.metrics_server, tool, session_key, _h("u|%s" % p.subject), kind,
                        _h("x|%s|%s" % (tool, args)), outcome, reason, completion,
                        int(duration_ms), int(chars)))
    except Exception:
        _DROPPED += 1


class MeteredFastMCP(FastMCP):
    """FastMCP whose tools/call handler records one metrics row per call."""

    def __init__(self, *args, metrics_server, **kwargs):
        self.metrics_server = metrics_server
        super().__init__(*args, **kwargs)

    async def call_tool(self, name, arguments):
        t0 = time.monotonic()
        try:
            result = await super().call_tool(name, arguments)
        except BaseException as e:
            try:
                tool = name if self._tool_manager.get_tool(name) else "unknown"
                record(self, tool, arguments, None, e, (time.monotonic() - t0) * 1000)
            except Exception:
                pass
            raise
        try:
            tool = name if self._tool_manager.get_tool(name) else "unknown"
            record(self, tool, arguments, result, None, (time.monotonic() - t0) * 1000)
        except Exception:
            pass
        return result


# ---------------------------------------------------------------------------
# Writing: background flusher, retention, footprint
# ---------------------------------------------------------------------------

def _write(rows, cleanup):
    with services.db(commit=True) as cur:
        if rows:
            execute_values(cur, "INSERT INTO mcp_calls (server, tool, session_key, principal_key, "
                                "token_kind, args_key, outcome, reason, completion, duration_ms, "
                                "resp_chars) VALUES %s", rows)
        if cleanup:
            cur.execute("DELETE FROM mcp_calls WHERE at < now() - make_interval(days => %s)",
                        (RETENTION_DAYS,))


def _flush_once(cleanup=False):
    global _DROPPED
    rows = []
    while _BUFFER:
        rows.append(_BUFFER.popleft())
    if not rows and not cleanup:
        return
    try:
        _write(rows, cleanup)
    except Exception as e:
        _DROPPED += len(rows)
        log.warning("mcp metrics: %d rows dropped (%s)", len(rows), type(e).__name__)


async def flusher(servers=()):
    """Runs for the life of the app (main.lifespan). Stores the servers' footprint once,
    then writes the buffer every FLUSH_S seconds and deletes rows past retention once a
    day."""
    if not ENABLED:
        return
    last_cleanup = 0.0
    try:
        await write_footprint(servers)
        while True:
            await asyncio.sleep(FLUSH_S)
            cleanup = time.monotonic() - last_cleanup > CLEANUP_EVERY_S
            if cleanup:
                last_cleanup = time.monotonic()
            try:
                await anyio.to_thread.run_sync(_flush_once, cleanup)
            except Exception:
                pass
    except asyncio.CancelledError:
        try:
            await anyio.to_thread.run_sync(_flush_once)
        except BaseException:
            pass
        raise


def _definition_chars(tool):
    """Characters of a tool definition as a client sends it to the model."""
    return len(json.dumps({"name": tool.name, "description": tool.description or "",
                           "input_schema": tool.inputSchema},
                          ensure_ascii=False, separators=(",", ":")))


async def write_footprint(servers):
    """Store each server's tool-definition and instruction sizes. Never raises."""
    try:
        rows = []
        for srv in servers:
            tools = await srv.list_tools()
            rows.append((srv.metrics_server, len(srv.instructions or ""),
                         [{"name": t.name, "chars": _definition_chars(t)} for t in tools]))

        def _store():
            with services.db(commit=True) as cur:
                for server, instr, tools in rows:
                    cur.execute("INSERT INTO mcp_footprint (server, computed_at, instructions_chars, "
                                "tools) VALUES (%s, now(), %s, %s) ON CONFLICT (server) DO UPDATE "
                                "SET computed_at = EXCLUDED.computed_at, instructions_chars = "
                                "EXCLUDED.instructions_chars, tools = EXCLUDED.tools",
                                (server, instr, Json(tools)))
        await anyio.to_thread.run_sync(_store)
    except Exception as e:
        log.warning("mcp metrics: footprint not written (%s)", type(e).__name__)
