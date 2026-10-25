"""Re-apply the current scoring rules to a round's stored runs (EVAL_PLAN §4).

    python -m evals rescore r1-dev --note "P10.no_reopen_implied is a style note"

Nothing is re-run and no result is edited by hand. For each stored run, using the persona's
current YAML: every stored persona check takes the YAML's hard/soft setting; a transcript
check the YAML has but the run lacks is computed from the stored transcript (SQL, gateway and
judge checks need the live run and are never added). Then failed_hard and the outcome are
recomputed the way the runner does (invalid if the fidelity judge failed). Runs that errored
are left alone. Each changed run records what changed under "rescored"; round.json follows.
"""

import json

from . import checks, runner
from .config import RESULTS


def _vars(rec):
    out = dict(rec.get("mobiles") or {})
    if rec.get("t0_db"):
        out["T0"] = rec["t0_db"]
    out.update({k: v for k, v in (rec.get("fixtures") or {}).items() if isinstance(v, dict)})
    return out


def rescore_run(rec):
    """The changes made to `rec` (in place), or [] if the current rules give the same result."""
    if rec.get("outcome") not in ("pass", "fail", "invalid") or not rec.get("checks"):
        return []
    spec = {c["id"]: c for c in runner.load_persona(rec["persona"]).get("checks", [])}
    changes = []
    for c in rec["checks"]:
        s = spec.get(c["id"])
        if s and c["hard"] != s.get("hard", True):
            changes.append("%s: %s -> %s" % (c["id"], "hard" if c["hard"] else "soft",
                                             "hard" if s.get("hard", True) else "soft"))
            c["hard"] = s.get("hard", True)
    have = {c["id"] for c in rec["checks"]}
    new = [s for s in spec.values() if s["kind"] == "transcript" and s["id"] not in have]
    for c in checks.persona_checks(new, rec, _vars(rec)):
        rec["checks"].append(c)
        changes.append("%s added (%s)" % (c["id"], "pass" if c["pass"] else "fail"))
    hard_fail = [c["id"] for c in rec["checks"] if c["hard"] and not c["pass"]]
    outcome = "invalid" if (rec.get("fidelity") or {}).get("verdict") != "pass" else (
        "fail" if hard_fail else "pass")
    if outcome != rec["outcome"]:
        changes.append("outcome: %s -> %s" % (rec["outcome"], outcome))
    rec["outcome"], rec["failed_hard"] = outcome, hard_fail
    return changes


def rescore(round_name, note):
    rpath = RESULTS / round_name / "round.json"
    rnd = json.loads(rpath.read_text(encoding="utf-8"))
    by_counter = {x["run_counter"]: x for x in rnd["runs"]}
    when = runner.now_iso()
    for f in sorted((RESULTS / round_name / "runs").glob("p*-*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        changes = rescore_run(rec)
        if not changes:
            continue
        rec.setdefault("rescored", []).append({"at": when, "commit": runner._git("rev-parse", "--short", "HEAD"),
                                               "note": note, "changes": changes})
        f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        row = by_counter.get(rec["run_counter"])
        if row:
            row["outcome"], row["failed_hard"] = rec["outcome"], rec["failed_hard"]
        print("%s: %s" % (f.name, "; ".join(changes)))
    before = dict(rnd["summary"])
    runner.summarise(rnd)
    rnd.setdefault("rescored", []).append({"at": when, "note": note, "summary_before": before})
    rpath.write_text(json.dumps(rnd, ensure_ascii=False, indent=1), encoding="utf-8")
    print("round %s: %d/%d passed (was %d/%d)" % (round_name, rnd["summary"]["passed"], rnd["summary"]["valid_runs"],
                                                 before["passed"], before["valid_runs"]))
