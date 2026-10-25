"""One run (persona x 1) and one round (EVAL_PLAN §2, §5)."""

import json
import subprocess
import threading
import time
import traceback
from datetime import datetime

import yaml

from . import checks, client, oauth, pages, simulator, stack
from .claude_cli import LimitTooLong
from .config import (CITIZEN_RESOURCE, CLIENT_MODEL, EVALS, MAX_TURNS_PER_MESSAGE, OFFICER_RESOURCE,
                     REPO, RESULTS)
from .mask import dumps_safe

PERSONAS = EVALS / "personas"
FIDELITY_Q = ("Below is the character card the simulated PERSON was given. Did the PERSON stay "
              "within it: no facts the card does not give, the card's behaviours done when the card "
              "says, and the card's way of talking? Ignore the ASSISTANT's quality entirely.\n\n"
              "# Card\n%s")


def load_persona(pid):
    hits = sorted(PERSONAS.glob("%s_*.yaml" % pid))
    if not hits:
        raise SystemExit("no persona %s" % pid)
    return yaml.safe_load(hits[0].read_text(encoding="utf-8"))


def all_personas():
    return [p.name.split("_")[0] for p in sorted(PERSONAS.glob("p*_*.yaml"))]


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Usage:
    def __init__(self):
        self.by = {r: {"calls": 0, "cost_usd_equiv": 0.0, "duration_ms": 0} for r in ("client", "simulator", "judge")}

    def add(self, role, cost, ms):
        b = self.by[role]
        b["calls"] += 1
        b["cost_usd_equiv"] = round(b["cost_usd_equiv"] + (cost or 0), 6)
        b["duration_ms"] += ms or 0


def _act(persona, sim, last_text, vars):
    """Do the person's phone action on the link in the assistant's last message."""
    action, target = sim["action"], (sim.get("target") or "").strip()
    kind = "upload" if action == "upload" else "verify"
    links = pages.find_links(last_text, kind)
    if not links:
        return {"action": action, "target": target, "missing_link": True,
                "observation": "You looked for a link in the chat but there was none."}, []
    if action == "upload":
        files = persona.get("uploads", {})
        fname = files.get(target) or (list(files.values())[0] if len(files) == 1 else None)
        link = links[0]
        if len(links) > 1:                      # pick the link whose page names the applicant
            for l in links:
                if pages.upload_applicant(l)[1] == target:
                    link = l
                    break
        if not fname:
            return {"action": action, "target": target, "link": link,
                    "observation": "You don't have a document for %s." % target}, []
        return pages.upload(link, EVALS / "fixtures" / "docs" / fname), []
    slot = persona.get("verify_targets", {}).get(target)
    if slot is None:
        return {"action": action, "target": target, "link": links[0],
                "observation": "You don't know whose number to verify."}, []
    return pages.verify_number(links[0], vars["M%d" % slot], send_only=action == "verify_number_send_only")


def run_persona(pid, round_name, sim_model, allowed, baseline, index=1):
    persona = load_persona(pid)
    pauses, usage = [], Usage()
    counter, ms = stack.reserve_mobiles(persona["no"], persona.get("slots", [0]))
    allowed.update(ms.values())
    vars = {"M%d" % s: m for s, m in ms.items()}
    rec = {"persona": pid, "round": round_name, "run": index, "run_counter": counter,
           "mobiles": dict(vars), "fixtures": {}, "started": now_iso(), "models": {
               "client": CLIENT_MODEL, "simulator": sim_model, "judge": sim_model},
           "turns": [], "checks": [], "judge": [], "pauses": pauses}
    ctx = {"persona": pid}
    otps, typed_otps, secrets = [], [], []
    cl = None
    t_start = time.time()
    try:
        t0 = stack.scalar("SELECT localtimestamp")
        rec["t0_db"] = t0
        cid = oauth.register_client()
        if persona["role"] == "citizen":
            grant, o = oauth.sign_in(cid, CITIZEN_RESOURCE, "citizen", vars["M0"])
            otps += o
            url = CITIZEN_RESOURCE
        else:
            grant, _ = oauth.sign_in(cid, OFFICER_RESOURCE, "officer")
            url = OFFICER_RESOURCE
        secrets = grant.seen
        cl = client.Client(persona["role"], url, grant, pauses, ctx)
        empty_streak = 0
        while len(rec["turns"]) < persona.get("max_messages", 12):
            i = len(rec["turns"]) + 1
            turn = {"i": i, "persona": {}, "harness": []}
            sim, u = simulator.persona_turn(persona, rec["turns"], sim_model, pauses,
                                            dict(ctx, role="simulator", turn=i))
            usage.add("simulator", u["cost_usd_equiv"], u["duration_ms"])
            turn["persona"] = {"action": sim["action"], "target": sim.get("target"), "reason": sim.get("reason")}
            if sim["action"] == "stop":
                rec["stop"] = {"by": "persona", "reason": sim.get("reason")}
                break
            msg = sim.get("message", "")
            if sim["action"] != "none":
                last = rec["turns"][-1]["client"]["text"] if rec["turns"] else ""
                step, new = _act(persona, sim, last, vars)
                typed_otps += new
                turn["harness"].append(step)
                sim2, u = simulator.persona_turn(persona, rec["turns"] + [dict(turn, persona={})],
                                                 sim_model, pauses, dict(ctx, role="simulator", turn=i),
                                                 after_action=step["observation"])
                usage.add("simulator", u["cost_usd_equiv"], u["duration_ms"])
                turn["persona"]["after_action_reason"] = sim2.get("reason")
                if sim2["action"] == "stop":
                    rec["turns"].append(turn)
                    rec["stop"] = {"by": "persona", "reason": sim2.get("reason")}
                    break
                msg = sim2.get("message", "")
            turn["persona"]["message"] = msg.strip() or "ok"
            c = cl.turn(turn["persona"]["message"], i)
            usage.add("client", c["cost_usd_equiv"], c["duration_ms"])
            turn["client"] = c
            rec["turns"].append(turn)
            empty_streak = empty_streak + 1 if (c["is_error"] or not c["text"]) else 0
            if empty_streak >= 2:
                rec["stop"] = {"by": "harness", "reason": "2 empty or failed client turns"}
                break
        else:
            rec["stop"] = {"by": "cap", "reason": "max_messages %d" % persona.get("max_messages", 12)}

        time.sleep(5)                                   # SMS carrier latency
        cs = [checks.g1_no_otp(rec, otps, typed_otps), checks.g3_seed(baseline),
              checks.g4_nothing_else(t0, allowed), checks.g5_notify(rec),
              checks.g6_links(rec, bool(persona.get("actions"))), checks.g7_dates(rec, persona.get("dobs", [])),
              checks.g8_length(rec), checks.g9_max_turns(rec)]
        cs += checks.persona_checks([c for c in persona.get("checks", []) if c["kind"] != "judge"], rec, vars)
        full = simulator.judge_transcript(rec["turns"])
        for j in [c for c in persona.get("checks", []) if c["kind"] == "judge"]:
            out, u = simulator.judge(j["question"].strip(), full, sim_model, pauses, dict(ctx, role="judge"))
            usage.add("judge", u["cost_usd_equiv"], u["duration_ms"])
            rec["judge"].append({"id": j["id"], "prompt": j["question"].strip(), **out})
            cs.append(checks.result(j["id"], "judge", j["desc"], "pass", out["verdict"],
                                    out["verdict"] == "pass", j.get("hard", True), evidence=out["evidence"]))
        out, u = simulator.judge(FIDELITY_Q % persona["card"].strip(), simulator.judge_transcript(rec["turns"], False),
                                 sim_model, pauses, dict(ctx, role="judge"))
        usage.add("judge", u["cost_usd_equiv"], u["duration_ms"])
        rec["judge"].append({"id": "fidelity", "prompt": "persona fidelity (card + visible transcript)", **out})
        rec["fidelity"] = out
        rec["checks"] = cs
        hard_fail = [c["id"] for c in cs if c["hard"] and not c["pass"]]
        if out["verdict"] != "pass":
            rec["outcome"] = "invalid"
        else:
            rec["outcome"] = "fail" if hard_fail else "pass"
        rec["failed_hard"] = hard_fail
    except LimitTooLong as e:
        rec["outcome"], rec["error"] = "error", "usage limit beyond the pause cap: %s" % e
    except client.IsolationBreach as e:
        rec["outcome"], rec["error"] = "error", "isolation_breach: %s" % e
    except Exception as e:
        rec["outcome"], rec["error"] = "error", "%s\n%s" % (e, traceback.format_exc()[-1500:])
    finally:
        if cl:
            cl.close()
    waited = sum(p.get("waited_s", 0) for p in pauses)
    rec["ended"] = now_iso()
    rec["usage"] = usage.by
    rec["totals"] = {
        "persona_messages": len([t for t in rec["turns"] if t.get("client")]),
        "client_turns": sum((t.get("client") or {}).get("num_turns") or 0 for t in rec["turns"]),
        "tool_calls": sum(len((t.get("client") or {}).get("tool_calls", [])) for t in rec["turns"]),
        "cost_usd_equiv": round(sum(b["cost_usd_equiv"] for b in usage.by.values()), 4),
        "duration_s": round(time.time() - t_start - waited), "paused_s": waited}
    out_dir = RESULTS / round_name / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("%s-%04d.json" % (pid, counter))
    path.write_text(dumps_safe(rec, otps + typed_otps, secrets), encoding="utf-8")
    rec["path"] = str(path.relative_to(REPO))
    return rec


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def run_round(round_name, pids, times, parallel, sim_model, reset):
    from concurrent.futures import ThreadPoolExecutor
    started = now_iso()
    baseline = stack.reset() if reset else stack.baseline()
    allowed, lock = set(), threading.Lock()
    jobs = [(p, k + 1) for p in pids if p != "p10" for k in range(times)]
    late = [(p, k + 1) for p in pids if p == "p10" for k in range(times)]
    recs = []

    def one(job):
        r = run_persona(job[0], round_name, sim_model, allowed, baseline, job[1])
        with lock:
            recs.append(r)
        print("%-4s run %d: %-7s %s  (%ss, $%s eq, %d msgs)%s" % (
            r["persona"], r["run"], r["outcome"], ",".join(r.get("failed_hard", [])),
            r["totals"]["duration_s"], r["totals"]["cost_usd_equiv"], r["totals"]["persona_messages"],
            "  " + r["error"].splitlines()[0] if r.get("error") else ""), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        list(ex.map(one, jobs))
    if late:
        stack.set_deadline("2026-10-01 00:00")
        try:
            for j in late:
                one(j)
        finally:
            stack.set_deadline(None)
    write_round(round_name, recs, started, sim_model, times, parallel, reset)
    return recs


def write_round(round_name, recs, started, sim_model, times, parallel, reset):
    """Merge these runs into round.json (a -dev round collects runs over several calls)."""
    path = RESULTS / round_name / "round.json"
    rnd = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "round": round_name, "started": started, "runs": []}
    rnd["runs"] += [{k: r.get(k) for k in ("persona", "run", "run_counter", "outcome", "failed_hard",
                                          "error", "path", "totals", "pauses", "started", "ended")}
                    for r in sorted(recs, key=lambda r: (r["persona"], r["run"]))]
    rnd.update({
        "ended": now_iso(), "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "claude_code": subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.split()[0],
        "models": {"client": CLIENT_MODEL, "simulator": sim_model, "judge": sim_model},
        "caps": {"max_turns_per_message": MAX_TURNS_PER_MESSAGE},
        "runs_per_persona": times, "parallel": parallel, "fresh_stack": reset,
        "partial": round_name.endswith("-dev") or "-rerun" in round_name})
    valid = [r for r in rnd["runs"] if r["outcome"] in ("pass", "fail")]
    rnd["summary"] = {
        "runs": len(rnd["runs"]), "valid_runs": len(valid),
        "passed": sum(r["outcome"] == "pass" for r in valid),
        "pass_rate": round(sum(r["outcome"] == "pass" for r in valid) / len(valid), 3) if valid else None,
        "invalid": sum(r["outcome"] == "invalid" for r in rnd["runs"]),
        "errors": sum(r["outcome"] == "error" for r in rnd["runs"]),
        "cost_usd_equiv": round(sum(r["totals"]["cost_usd_equiv"] for r in rnd["runs"]), 4),
        "duration_s": sum(r["totals"]["duration_s"] for r in rnd["runs"]),
        "paused_s": sum(r["totals"]["paused_s"] for r in rnd["runs"])}
    rnd["pauses"] = [p for r in rnd["runs"] for p in r.get("pauses") or []]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rnd, ensure_ascii=False, indent=1), encoding="utf-8")
