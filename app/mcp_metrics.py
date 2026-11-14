# -*- coding: utf-8 -*-
"""
/admin/mcp-metrics: how efficiently assistants use the two MCP servers, and how much
the servers cost a client in tokens. Departmental login only; read-only queries over
mcp_calls and mcp_footprint (written by the mcp container, mcp_server/metrics.py).
"""

import json
import logging
import os

from flask import Blueprint, redirect, render_template, request, session

import app as portal
from mcp_metrics_calc import PROCESS_TYPES, analyze, est_tokens

mcp_metrics = Blueprint("mcp_metrics", __name__)
log = logging.getLogger("sewasetu.mcp_metrics")

WINDOWS = {"24h": ("1 day", "last 24 hours"), "7d": ("7 days", "last 7 days"),
           "30d": ("30 days", "last 30 days")}
SERVERS = {"all": "both servers", "citizen": "citizen", "officer": "officer"}
ROW_CAP = 50000
EVAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_data", "mcp",
                         "efficiency.json")


def _eval_rounds():
    """Section 4: eval rounds written by `python -m evals efficiency` (no database)."""
    try:
        with open(EVAL_FILE, encoding="utf-8") as f:
            return json.load(f).get("rounds") or []
    except Exception:
        return []


def _rows(cur, interval, server):
    where, args = "at >= now() - %s::interval", [interval]
    if server != "all":
        where += " AND server = %s"
        args.append(server)
    cur.execute("SELECT server, tool, count(*), "
                "count(*) FILTER (WHERE outcome = 'ok'), "
                "count(*) FILTER (WHERE outcome = 'refused'), "
                "count(*) FILTER (WHERE outcome = 'error'), "
                "percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms), "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), "
                "avg(resp_chars) "
                "FROM mcp_calls WHERE " + where + " GROUP BY server, tool "
                "ORDER BY count(*) DESC, server, tool", args)
    tools = [{"server": s, "tool": t, "calls": n, "ok": ok, "refused": rf, "errors": er,
              "p50": int(p50 or 0), "p95": int(p95 or 0), "resp_tokens": est_tokens(float(avg or 0))}
             for s, t, n, ok, rf, er, p50, p95, avg in cur.fetchall()]
    cur.execute("SELECT session_key, token_kind, tool, args_key, outcome, completion, at "
                "FROM mcp_calls WHERE " + where + " ORDER BY session_key, at, id LIMIT %s",
                args + [ROW_CAP + 1])
    keys = ("session_key", "token_kind", "tool", "args_key", "outcome", "completion", "at")
    rows = [dict(zip(keys, r)) for r in cur.fetchall()]
    capped = len(rows) > ROW_CAP
    return tools, rows[:ROW_CAP], capped


def _footprint(cur):
    cur.execute("SELECT server, computed_at AT TIME ZONE 'Asia/Kolkata', instructions_chars, tools "
                "FROM mcp_footprint ORDER BY server")
    out = []
    for server, at, instr, tools in cur.fetchall():
        tl = sorted(({"name": t["name"], "tokens": est_tokens(t["chars"])} for t in tools),
                    key=lambda t: -t["tokens"])
        defs = sum(t["tokens"] for t in tl)
        out.append({"server": server, "computed_at": at.strftime("%d/%m/%Y %H:%M IST"),
                    "tool_count": len(tl), "instructions": est_tokens(instr),
                    "definitions": defs, "total": defs + est_tokens(instr), "tools": tl})
    return out


@mcp_metrics.route("/admin/mcp-metrics")
def page():
    if not session.get("admin"):
        return redirect("/admin?next=/admin/mcp-metrics")
    window = request.args.get("window", "7d")
    window = window if window in WINDOWS else "7d"
    server = request.args.get("server", "all")
    server = server if server in SERVERS else "all"

    ctx = {"window": window, "server": server, "windows": WINDOWS, "servers": SERVERS,
           "process_types": PROCESS_TYPES, "available": True, "eval_rounds": _eval_rounds()}
    conn = None
    try:
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SET statement_timeout = 3000")
        cur.execute("SELECT now()")
        now = cur.fetchone()[0]
        tools, rows, capped = _rows(cur, WINDOWS[window][0], server)
        ctx.update(tools=tools, capped=capped, stats=analyze(rows, now),
                   footprint=_footprint(cur))
        cur.close()
        per = ctx["stats"]["per_tool"]
        for t in ctx["tools"]:
            p = per.get(t["tool"], {})
            t["repeats"], t["polls"] = p.get("repeats", 0), p.get("polls", 0)
    except Exception as e:                  # a clean page, never a 500 or a traceback
        log.warning("mcp metrics page: %s", type(e).__name__)
        ctx["available"] = False
    finally:
        if conn is not None:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
    return render_template("admin_mcp_metrics.html", **ctx)
