# -*- coding: utf-8 -*-
"""
/eval-dashboard: the assistant's eval results (EVAL_PLAN.md §6). Read-only.

Serves the JSON that `python -m evals publish` writes to app/eval_data/: the published
rounds, the invented citizens and officers, every finding with its fix, and per persona the
checks and the masked transcript. GET only, no database access, no scripts, no external
requests; everything it shows was masked and scanned for secrets when it was published.
"""

import json
import os
import re

from flask import Blueprint, abort, render_template

eval_dashboard = Blueprint("eval_dashboard", __name__)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_data")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
_cache = {}


def _load(rel):
    """JSON from eval_data, cached by mtime. None if absent."""
    path = os.path.join(DATA, rel)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _cache[path] = (mtime, data)
    return data


def _round(rid):
    if not ID_RE.match(rid or ""):
        abort(404)
    r = _load("rounds/%s.json" % rid)
    if r is None:
        abort(404)
    return r


@eval_dashboard.get("/eval-dashboard")
def index():
    idx = _load("index.json") or {"rounds": []}
    head = _round(idx["headline"]) if idx.get("headline") else None
    personas = _load("personas.json") or []
    results = {p["persona"]: p for p in (head or {}).get("personas", [])}
    return render_template("eval_dashboard.html", idx=idx, head=head, personas=personas,
                           results=results, findings=_load("findings.json") or {"rounds": []})


@eval_dashboard.get("/eval-dashboard/<rid>")
def round_view(rid):
    r = _round(rid)
    personas = {p["id"]: p for p in (_load("personas.json") or [])}
    return render_template("eval_round.html", r=r, personas=personas)


@eval_dashboard.get("/eval-dashboard/<rid>/<pid>")
def persona_view(rid, pid):
    r = _round(rid)
    if not re.match(r"^p\d\d$", pid or ""):
        abort(404)
    run = _load("rounds/%s/%s.json" % (rid, pid))
    if run is None:
        abort(404)
    persona = next((p for p in (_load("personas.json") or []) if p["id"] == pid), {"id": pid})
    return render_template("eval_persona.html", r=r, run=run, p=persona)


@eval_dashboard.app_template_filter("pjson")
def _pjson(value):
    """Readable JSON for the transcript (non-ASCII kept; Jinja escapes it for HTML)."""
    return json.dumps(value, ensure_ascii=False, indent=1)


@eval_dashboard.after_request
def _headers(resp):
    resp.headers["X-Robots-Tag"] = "noindex"
    resp.headers["Content-Security-Policy"] = ("default-src 'none'; style-src 'unsafe-inline'; "
                                               "img-src 'none'; base-uri 'none'; form-action 'none'")
    return resp
