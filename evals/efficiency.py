"""Efficiency and token figures for eval runs and rounds (/admin/mcp-metrics section 4).

Counted from the transcript with the same rules the servers use for production traffic
(app/mcp_metrics_calc.py): completed tasks, calls per task, errors, repeats and polls.
Tokens are the client's (`claude -p`, the assistant under test), summed over its API calls;
simulator and judge tokens are harness cost and are left out.

    python -m evals efficiency <round> [<round> ...]     # print, and write app/eval_data/mcp/
"""

import json
import statistics
import sys
from datetime import datetime, timedelta

from .config import REPO, RESULTS

sys.path.insert(0, str(REPO / "app"))
import mcp_metrics_calc as calc  # noqa: E402

OUT = REPO / "app" / "eval_data" / "mcp" / "efficiency.json"
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
              "output_tokens")


def _rows(rec):
    """mcp_calls-shaped rows from a run's transcript (one session per run)."""
    rows, t = [], datetime(2000, 1, 1)
    for turn in rec.get("turns", []):
        for c in (turn.get("client") or {}).get("tool_calls", []):
            t += timedelta(seconds=1)
            res = c.get("result")
            if c.get("is_error"):
                outcome, completion = "error", None
            else:
                outcome, _, completion = calc.classify(c["name"], res if isinstance(res, dict) else None)
            rows.append({"session_key": "run", "token_kind": "access", "tool": c["name"],
                         "args_key": json.dumps(c.get("input") or {}, sort_keys=True),
                         "outcome": outcome, "completion": completion, "at": t})
    return rows


def run_efficiency(rec):
    rows = _rows(rec)
    a = calc.analyze(rows, datetime(2000, 1, 1))
    applies = [r for r in rows if r["completion"] == "apply"]
    seg, per_apply = 0, []
    for r in rows:                         # calls per apply (the same segmenting as analyze)
        seg += 1
        if r["completion"] in ("apply", "decision"):
            if r["completion"] == "apply":
                per_apply.append(seg)
            seg = 0
    turns = [t.get("client") or {} for t in rec.get("turns", []) if t.get("client")]
    tok = {k: sum((c.get("usage") or {}).get(k) or 0 for c in turns) for k in USAGE_KEYS}
    tok["total"] = sum(tok.values())
    tok["context"] = tok["total"] - tok["output_tokens"]
    first = turns[0].get("first_call_context") if turns else None
    if first is None and turns:            # runs recorded before first_call_context existed
        u = turns[0].get("usage") or {}
        first = None if turns[0].get("num_turns", 1) != 1 else sum(u.get(k) or 0 for k in USAGE_KEYS[:3])
    return {
        "tool_calls": a["calls"], "errors": a["errors"], "repeats": a["repeats"],
        "polls": a["polls"], "wasted": a["wasted"], "applies": len(applies),
        "calls_per_apply": per_apply,
        "decisions": a["processes"]["decision"]["n"],
        "persona_messages": len(turns),
        "client_api_turns": sum(c.get("num_turns") or 0 for c in turns),
        "tokens": tok, "first_call_context": first,
        "tokens_per_apply": round(tok["total"] / len(applies)) if applies else None,
    }


def _runs(round_name):
    out = []
    for f in sorted((RESULTS / round_name / "runs").glob("p*-*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        r["efficiency"] = r.get("efficiency") or run_efficiency(r)
        out.append(r)
    return out


def _mean(v):
    return round(statistics.mean(v), 1) if v else None


def round_summary(round_name):
    runs = _runs(round_name)
    valid = [r for r in runs if r["outcome"] in ("pass", "fail")]
    eff = [r["efficiency"] for r in valid]
    per_apply = [n for e in eff for n in e["calls_per_apply"]]
    apply_runs = [e for e in eff if e["applies"]]
    calls = sum(e["tool_calls"] for e in eff)
    wasted = sum(e["wasted"] for e in eff)
    cal_path = RESULTS / round_name / "calibration.json"
    cal = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else None
    by_persona = {}
    for r in valid:
        p = by_persona.setdefault(r["persona"], {"runs": 0, "passed": 0})
        p["runs"] += 1
        p["passed"] += r["outcome"] == "pass"
    return {
        "round": round_name,
        "commits": sorted({r.get("commit") for r in runs if r.get("commit")}),
        "runs": len(runs), "valid": len(valid),
        "passed": sum(r["outcome"] == "pass" for r in valid),
        "pass_rate": round(sum(r["outcome"] == "pass" for r in valid) / len(valid), 3) if valid else None,
        "applies": len(per_apply),
        "calls_per_apply": calc.summarize(per_apply),
        "tool_calls_per_run": _mean([e["tool_calls"] for e in eff]),
        "wasted": wasted, "errors": sum(e["errors"] for e in eff),
        "repeats": sum(e["repeats"] for e in eff), "polls": sum(e["polls"] for e in eff),
        "wasted_pct": round(100.0 * wasted / calls, 1) if calls else None,
        "tokens_per_run": _mean([e["tokens"]["total"] for e in eff]),
        "output_tokens_per_run": _mean([e["tokens"]["output_tokens"] for e in eff]),
        "tokens_per_apply": (round(sum(e["tokens"]["total"] for e in apply_runs) /
                                   sum(e["applies"] for e in apply_runs)) if apply_runs else None),
        "persona_messages_per_run": _mean([e["persona_messages"] for e in eff]),
        "client_api_turns_per_run": _mean([e["client_api_turns"] for e in eff]),
        "footprint": cal,
        "by_persona": by_persona,
        "failed": sorted("%s-%04d" % (r["persona"], r["run_counter"]) for r in valid if r["outcome"] == "fail"),
        "not_valid": sorted("%s-%04d: %s" % (r["persona"], r["run_counter"], r["outcome"])
                            for r in runs if r not in valid),
    }


ROWS = [("Pass rate", lambda s: "%d/%d" % (s["passed"], s["valid"])),
        ("Calls per completed apply (median / mean)",
         lambda s: "%s / %s" % (s["calls_per_apply"]["median"], s["calls_per_apply"]["mean"])),
        ("Tool calls per run", lambda s: s["tool_calls_per_run"]),
        ("Wasted calls (errors + repeats)", lambda s: "%s (%s%%)" % (s["wasted"], s["wasted_pct"])),
        ("Client tokens per run", lambda s: s["tokens_per_run"]),
        ("Client tokens per completed apply", lambda s: s["tokens_per_apply"]),
        ("Client API turns per run", lambda s: s["client_api_turns_per_run"]),
        ("Citizen footprint, real tokens", lambda s: (s["footprint"] or {}).get("citizen", {}).get("real")),
        ("Citizen footprint, estimate", lambda s: (s["footprint"] or {}).get("citizen", {}).get("estimate"))]


def write(round_names):
    """round_names: "<round>" or "<round>=<label shown on the page>"."""
    summaries = []
    for arg in round_names:
        rid, _, label = arg.partition("=")
        summaries.append(dict(round_summary(rid), label=label or rid))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated": datetime.now().astimezone().isoformat(timespec="seconds"),
                               "rounds": summaries}, ensure_ascii=False, indent=1), encoding="utf-8")
    w = max(len(n) for n, _ in ROWS)
    print("%-*s  %s" % (w, "", "  ".join("%-18s" % s["round"] for s in summaries)))
    for name, fn in ROWS:
        print("%-*s  %s" % (w, name, "  ".join("%-18s" % fn(s) for s in summaries)))
    for s in summaries:
        if s["failed"] or s["not_valid"]:
            print("%s: failed %s; not valid %s" % (s["round"], s["failed"], s["not_valid"]))
    print("wrote", OUT.relative_to(REPO))
    return summaries
