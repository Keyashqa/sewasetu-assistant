"""Console summary of the latest run of each persona in a round:
python -m evals.summarize <round> p12 p02 ...   (transcript, non-passing checks, fidelity)"""

import json
import sys

from .config import RESULTS


def latest(round_name, pid):
    runs = sorted((RESULTS / round_name / "runs").glob("%s-*.json" % pid))
    return json.loads(runs[-1].read_text(encoding="utf-8")) if runs else None


def main(round_name, pids, full=True):
    for pid in pids:
        r = latest(round_name, pid)
        if not r:
            print("%s: no run" % pid)
            continue
        print("\n######## %s #%04d  %s  stop=%s  %s" % (pid, r["run_counter"], r["outcome"], r.get("stop"), r["totals"]))
        if r.get("error"):
            print("ERROR", r["error"][:1500])
        print("fidelity:", (r.get("fidelity") or {}).get("verdict"), "|", (r.get("fidelity") or {}).get("evidence", "")[:300])
        if full:
            for t in r["turns"]:
                for h in t.get("harness", []):
                    print("  [PHONE]", h["observation"][:150])
                print("  P%d: %s" % (t["i"], t["persona"].get("message")))
                c = t.get("client") or {}
                if c.get("tool_calls"):
                    print("     tools:", ", ".join("%s%s" % (k["name"], json.dumps(k["input"], ensure_ascii=False)[:120])
                                                  for k in c["tool_calls"]))
                print("  A%d: %s" % (t["i"], (c.get("text") or "").replace("\n", " / ")[:600]))
        for c in r["checks"]:
            if not c["pass"]:
                print("  %s %s %s | expected: %s | actual: %s%s" % (
                    "FAIL" if c["hard"] else "soft", c["id"], c["desc"][:60], str(c["expected"])[:100],
                    str(c["actual"])[:160], (" | " + c["evidence"][:200]) if c.get("evidence") else ""))
        for j in r.get("judge", []):
            if j["id"] != "fidelity":
                print("  judge %s: %s | %s" % (j["id"], j["verdict"], j["evidence"][:200]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
