"""Publish a round to app/eval_data/ for /eval-dashboard (EVAL_PLAN §6).

    python -m evals publish r1-dev --as dev-persona-by-persona \
        --label "Persona-by-persona development runs (Haiku simulator)"
    python -m evals publish r2-final --label "Full round on <commit>" --headline

Takes the latest run of each persona in the source round, compacts it, masks mobile numbers
(98XXXX0701), and refuses to write anything that still holds a secret: a token, an OTP, an
unmasked link token, an unmasked mobile, or the admin password. Also publishes the persona
cards and rounds.yaml. The first round published becomes the headline; --headline moves it.
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

from . import mask, runner
from .config import EVALS, REPO, RESULTS, admin_password

OUT = REPO / "app" / "eval_data"
MOBILE_RE = re.compile(r"(?<!\d)([6-9]\d)\d{4}(\d{4})(?!\d)")
# results that only bloat the page: lists of villages, blocks and documents
DROP_KEYS = {"villages_by_block", "blocks", "documents_accepted", "formats", "next_step"}
MAX_RESULT = 2000


class Unsafe(Exception):
    pass


def _mask_mobiles(obj):
    if isinstance(obj, str):
        return MOBILE_RE.sub(lambda m: m.group(1) + "XXXX" + m.group(2), obj)
    if isinstance(obj, list):
        return [_mask_mobiles(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _mask_mobiles(v) for k, v in obj.items()}
    return obj


def _compact_result(r):
    if not isinstance(r, dict):
        return r if len(str(r)) <= MAX_RESULT else str(r)[:MAX_RESULT] + " …(truncated)"
    out = {k: v for k, v in r.items() if k not in DROP_KEYS}
    if len(json.dumps(out, ensure_ascii=False)) > MAX_RESULT:
        keep = {k: out[k] for k in ("reply", "status", "error", "application_number", "approved",
                                    "rejected", "submitted") if k in out}
        keep["_truncated"] = True
        return keep
    return out


def _commit_at(iso):
    """The commit HEAD was on when a run started (runs before runs carried their commit)."""
    out = subprocess.run(["git", "log", "-1", "--format=%h", "--before=%s" % iso], cwd=REPO,
                         capture_output=True, text=True).stdout.strip()
    return out or None


def _talks(p):
    if p.get("talks"):
        return p["talks"]
    m = re.search(r"How you talk:\s*(.+?)(?:\n\s*\n|$)", p.get("card", ""), re.S)
    return " ".join(m.group(1).split()) if m else ""


def persona_cards():
    cards = []
    for pid in runner.all_personas():
        p = runner.load_persona(pid)
        cards.append({k: (" ".join(str(p.get(k, "")).split())) for k in
                      ("id", "name", "title", "line", "summary", "why", "expected_end_state", "role",
                       "outcome", "reason")}
                     | {"number": p["number"], "talks": _talks(p), "tags": p.get("tags", [])})
    return cards


def _field(value, n):
    """Field n (1-based) of a recorded SQL value's first row, as a word: PENDING -> Pending."""
    parts = str(value).split("\n")[0].split("|")
    return parts[n - 1].replace("_", " ").capitalize() if 0 < n <= len(parts) else ""


def happened(r):
    """What the run left in the portal, in a few words, from its recorded check values (and, for
    a call: key, its stored tool results). The persona card's `happened` rules pick the phrase;
    the first rule whose conditions all match the recorded data wins."""
    actual = {c["id"]: "" if c.get("actual") is None else str(c["actual"]) for c in r.get("checks", [])}
    results = {}
    for t in r.get("turns", []):
        for c in (t.get("client") or {}).get("tool_calls", []):
            results.setdefault(c["name"], []).append(json.dumps(c.get("result"), ensure_ascii=False))
    def value(key):
        return "\n".join(results.get(key[5:], [])) if key.startswith("call:") else actual.get(key)
    for rule in runner.load_persona(r["persona"]).get("happened", []):
        if all(value(k) is not None and re.search(rx, value(k)) for k, rx in rule.get("if", {}).items()):
            return re.sub(r"\{([A-Za-z0-9_.]+)\.(\d+)\}", lambda m: _field(actual.get(m.group(1), ""), int(m.group(2))),
                          rule["say"])
    return "Not recorded"


def compact_run(r):
    turns = []
    for t in r["turns"]:
        c = t.get("client") or {}
        turns.append({
            "i": t["i"],
            "persona": {k: t["persona"].get(k) for k in ("message", "action", "target")},
            "harness": [{k: h.get(k) for k in ("action", "observation", "missing_link")} for h in t.get("harness", [])],
            "client": {"text": c.get("text"), "terminal_reason": c.get("terminal_reason"),
                       "num_turns": c.get("num_turns"),
                       "tool_calls": [{"name": x["name"], "input": x["input"], "is_error": x.get("is_error"),
                                       "result": _compact_result(x.get("result"))}
                                      for x in c.get("tool_calls", [])]} if c else None,
        })
    return {
        "persona": r["persona"], "run_counter": r["run_counter"], "outcome": r["outcome"],
        "error": (r.get("error") or "").splitlines()[0] if r.get("error") else None,
        "commit": r.get("commit") or _commit_at(r["started"]), "started": r["started"],
        "models": r.get("models"), "stop": r.get("stop"), "failed_hard": r.get("failed_hard", []),
        "checks": [{k: c.get(k) for k in ("id", "kind", "hard", "desc", "expected", "actual", "pass", "evidence")}
                   for c in r.get("checks", [])],
        "judge": r.get("judge", []), "fidelity": r.get("fidelity"), "probes": r.get("probes", []),
        "totals": r.get("totals"), "usage": r.get("usage"), "pauses": r.get("pauses", []),
        "turns": turns, "happened": happened(r),
    }


def latest_runs(source):
    runs = {}
    for f in sorted((RESULTS / source / "runs").glob("p*-*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        prev = runs.get(r["persona"])
        if prev is None or r["run_counter"] > prev["run_counter"]:
            runs[r["persona"]] = r
    return [runs[p] for p in sorted(runs)]


def safe_dump(obj):
    """Masked JSON, refused if anything secret-looking remains."""
    text = json.dumps(_mask_mobiles(mask.mask(obj)), ensure_ascii=False, indent=1)
    scan(text)
    return text


def scan(text):
    checks = [("JWT", mask.JWT_RE), ("link token", re.compile(r"/(?:upload|verify-number)/[A-Za-z0-9_-]{5,}")),
              ("OTP", re.compile(r"OTP is \d{6}|code is \d{6}", re.I)), ("mobile", MOBILE_RE)]
    for name, rx in checks:
        m = rx.search(text)
        if m:
            raise Unsafe("%s in published data: %r" % (name, text[max(0, m.start() - 40):m.end() + 10]))
    pw = admin_password()
    if pw and pw in text:
        raise Unsafe("admin password in published data")


def publish(source, as_id=None, label=None, headline=False):
    rid = as_id or source
    runs = [compact_run(r) for r in latest_runs(source)]
    if not runs:
        raise SystemExit("no runs in %s" % source)
    src_round = RESULTS / source / "round.json"
    meta = json.loads(src_round.read_text(encoding="utf-8")) if src_round.exists() else {}
    valid = [r for r in runs if r["outcome"] in ("pass", "fail")]
    commits = sorted({r["commit"] for r in runs if r["commit"]})
    sims = sorted({(r.get("models") or {}).get("simulator") for r in runs if r.get("models")})
    summary = {
        "id": rid, "source": source, "label": label or rid,
        "published": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs": len(runs), "valid": len(valid), "passed": sum(r["outcome"] == "pass" for r in valid),
        "invalid": sum(r["outcome"] == "invalid" for r in runs),
        "errors": sum(r["outcome"] == "error" for r in runs),
        "runs_per_persona": 1, "commits": commits, "simulator": sims,
        "client": (runs[0].get("models") or {}).get("client"),
        "claude_code": meta.get("claude_code"),
        "first_run": min(r["started"] for r in runs), "last_run": max(r["started"] for r in runs),
        "cost_usd_equiv": round(sum((r.get("totals") or {}).get("cost_usd_equiv", 0) for r in runs), 4),
        "pauses": sum(len(r.get("pauses") or []) for r in runs),
        "personas": [{"persona": r["persona"], "outcome": r["outcome"], "run_counter": r["run_counter"],
                      "commit": r["commit"], "messages": (r.get("totals") or {}).get("persona_messages"),
                      "happened": r["happened"],
                      "failed": [c for c in r["checks"] if not c["pass"]]} for r in runs],
    }
    summary["pass_rate"] = round(summary["passed"] / summary["valid"], 3) if summary["valid"] else None

    texts = {"rounds/%s.json" % rid: safe_dump(summary)}
    for r in runs:
        texts["rounds/%s/%s.json" % (rid, r["persona"])] = safe_dump(r)
    texts["personas.json"] = safe_dump(persona_cards())
    texts["findings.json"] = safe_dump(yaml.safe_load((EVALS / "rounds.yaml").read_text(encoding="utf-8")))
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"rounds": []}
    index["rounds"] = [x for x in index["rounds"] if x["id"] != rid] + [
        {k: summary[k] for k in ("id", "label", "published", "runs", "valid", "passed", "pass_rate",
                                 "commits", "simulator", "client")}]
    if headline or not index.get("headline"):
        index["headline"] = rid
    texts["index.json"] = safe_dump(index)

    for rel, text in texts.items():           # everything scanned before anything is written
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    size = sum(len(t.encode()) for t in texts.values())
    print("published %s (%d runs, %d/%d passed) -> %s, %d files, %.0f KB" % (
        rid, len(runs), summary["passed"], summary["valid"], OUT.relative_to(REPO), len(texts), size / 1024))
    print("next: git add app/eval_data && git commit, then deploy (DEPLOY.md §2: rebuild app)")
    return summary
