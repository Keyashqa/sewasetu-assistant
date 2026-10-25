"""python -m evals ...   (EVAL_PLAN §7)"""

import argparse
import json
import sys

from . import runner, stack
from .config import RESULTS, SIM_MODEL_DEV, SIM_MODEL_PUBLISHED


def main():
    ap = argparse.ArgumentParser(prog="python -m evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stack")
    s.add_argument("what", choices=["reset"])
    r = sub.add_parser("run")
    r.add_argument("--round", required=True)
    r.add_argument("--persona", help="comma-separated ids (default: all)")
    r.add_argument("--times", type=int, default=1)
    r.add_argument("--parallel", type=int, default=2)
    r.add_argument("--no-reset", action="store_true")
    r.add_argument("--sim-model")
    rp = sub.add_parser("report")
    rp.add_argument("round")
    pb = sub.add_parser("publish")
    pb.add_argument("round", help="source round under evals/results/")
    pb.add_argument("--as", dest="as_id", help="published id (default: the source round's)")
    pb.add_argument("--label")
    pb.add_argument("--headline", action="store_true", help="make this the dashboard's headline")
    a = ap.parse_args()

    if a.cmd == "stack":
        print("baseline", stack.reset())
        return 0
    if a.cmd == "run":
        pids = a.persona.split(",") if a.persona else runner.all_personas()
        dev = a.round.endswith("-dev")
        complete = not dev and "-rerun" not in a.round and not a.persona
        if complete and a.no_reset:
            raise SystemExit("--no-reset is refused for a complete round")
        sim = a.sim_model or (SIM_MODEL_DEV if dev else SIM_MODEL_PUBLISHED)
        runner.run_round(a.round, pids, a.times, a.parallel, sim, not a.no_reset)
        return 0
    if a.cmd == "publish":
        from . import publish
        publish.publish(a.round, a.as_id, a.label, a.headline)
        return 0
    if a.cmd == "report":
        rnd = json.loads((RESULTS / a.round / "round.json").read_text(encoding="utf-8"))
        print("%s  commit %s  sim %s  %s" % (rnd["round"], rnd["commit"], rnd["models"]["simulator"], rnd["summary"]))
        for x in rnd["runs"]:
            print("  %-4s #%04d %-7s %-40s %4ss $%s" % (x["persona"], x["run_counter"], x["outcome"],
                                                     ",".join(x.get("failed_hard") or []),
                                                     x["totals"]["duration_s"], x["totals"]["cost_usd_equiv"]))
        return 0


if __name__ == "__main__":
    sys.exit(main())
