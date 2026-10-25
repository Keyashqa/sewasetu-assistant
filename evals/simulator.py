"""The persona simulator and the judge: stateless `claude -p` calls with JSON-schema output
(EVAL_PLAN §3.2, §3.3). The simulator sees only what the person would see."""

import json
import os
import tempfile

from . import claude_cli
from .config import EVALS

RULES = EVALS / "simulator_rules.txt"

ACTIONS_HELP = {
    "upload": "you open the upload link from the assistant's last message and upload the "
              "document photo. target = the applicant's name the document belongs to.",
    "verify_number": "you open the verify-number link from the assistant's last message, type "
                     "the other person's mobile, and type the OTP that phone receives on the "
                     "page. target = whose number (their name).",
    "verify_number_send_only": "you open the verify-number link, type the other person's "
                               "mobile and tap Send OTP, and read the OTP on that phone, but do "
                               "not type it on the page. target = whose number.",
    "stop": "you end the conversation.",
}

JUDGE_SCHEMA = {"type": "object", "required": ["verdict", "evidence"],
                "properties": {"verdict": {"enum": ["pass", "fail", "unclear"]},
                               "evidence": {"type": "string"}}}


def _call(model, system_file, prompt, schema, pauses, ctx):
    tmp = tempfile.mkdtemp(prefix="sssim-")
    cmd = ["claude", "-p", "--model", model, "--max-turns", "3", "--tools", "",
           "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--no-chrome",
           "--no-session-persistence", "--output-format", "json",
           "--json-schema", json.dumps(schema)]
    if system_file:
        cmd += ["--system-prompt-file", str(system_file)]
    try:
        events, rc, stderr = claude_cli.run(cmd, prompt, tmp, pauses, ctx)
    finally:
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    out = result.get("structured_output")
    if not isinstance(out, dict):
        raise RuntimeError("no structured output (rc %s): %s %s" % (rc, str(result.get("result"))[:300],
                                                                    stderr[-300:]))
    return out, {"cost_usd_equiv": result.get("total_cost_usd") or 0.0,
                 "duration_ms": result.get("duration_ms"), "num_turns": result.get("num_turns")}


def visible_transcript(turns):
    lines = []
    for t in turns:
        for h in t.get("harness", []):
            lines.append("[ON YOUR PHONE] " + h["observation"])
        if t["persona"].get("message"):
            lines.append("YOU: " + t["persona"]["message"])
        if t.get("client"):
            lines.append("ASSISTANT: " + (t["client"]["text"] or "(no reply)"))
    return "\n\n".join(lines) or "(nothing yet: you are about to send your first message)"


def persona_turn(persona, turns, model, pauses, ctx, after_action=None):
    """The person's next move: {message, action, target, reason}. With `after_action`
    (the observation of the action just done), only a chat message is asked for."""
    actions = ["none"] + persona.get("actions", []) + ["stop"]
    if after_action:
        actions = ["none", "stop"]
    schema = {"type": "object", "required": ["message", "action", "reason"],
              "properties": {"message": {"type": "string"}, "action": {"enum": actions},
                             "target": {"type": "string"}, "reason": {"type": "string"}}}
    help_lines = "\n".join("- %s: %s" % (a, ACTIONS_HELP[a]) for a in actions if a in ACTIONS_HELP)
    prompt = ("# Your character card\n%s\n\n# Things you can do besides typing\n- none: just send "
              "your message.\n%s\n\n# The conversation so far\n%s\n\n" %
              (persona["card"].strip(), help_lines, visible_transcript(turns)))
    if after_action:
        prompt += ("# Now\nYou just did this on your phone: %s\nWrite the chat message you send "
                   "now (action none), or stop.\n" % after_action)
    else:
        prompt += "# Now\nWhat do you do next? Write your next chat message, or choose an action.\n"
    return _call(model, RULES, prompt, schema, pauses, ctx)


def judge(question, transcript, model, pauses, ctx):
    prompt = ("You are checking a transcript of a conversation between a person and a government "
              "pension assistant. Answer one yes/no question strictly from the transcript.\n"
              "verdict: pass if the answer is yes, fail if no, unclear if the transcript does not "
              "show it. evidence: quote the lines that decide it.\n\n# Question\n%s\n\n"
              "# Transcript\n%s\n" % (question, transcript))
    return _call(model, None, prompt, JUDGE_SCHEMA, pauses, ctx)


def judge_transcript(turns, with_tools=True):
    """Transcript for the judge: messages, harness actions and (optionally) tool calls."""
    lines = []
    for t in turns:
        for h in t.get("harness", []):
            lines.append("[person's phone] " + h["observation"])
        if t["persona"].get("message"):
            lines.append("PERSON: " + t["persona"]["message"])
        c = t.get("client")
        if c:
            if with_tools:
                for call in c["tool_calls"]:
                    lines.append("[assistant called %s %s]" % (call["name"], json.dumps(call["input"],
                                                                                    ensure_ascii=False)))
            lines.append("ASSISTANT: " + (c["text"] or "(no reply)"))
    return "\n\n".join(lines)
