"""claude_cli.run against a fake `claude`: a refused call pauses, is recorded, and is
retried; the resumed session file is restored first, so the turn is not sent twice."""

import json
import os
import sys
import tempfile
import time
import unittest

from evals import claude_cli as cc

FAKE = r'''
import json, sys, time, os
state, session = sys.argv[1], sys.argv[2]
n = int(open(state).read()) if os.path.exists(state) else 0
open(state, "w").write(str(n + 1))
msg = sys.stdin.read()
with open(session, "a") as f:            # the CLI records the user turn before the API call
    f.write(json.dumps({"user": msg}) + "\n")
if n == 0:
    print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected",
        "resetsAt": int(time.time()) + 1, "rateLimitType": "five_hour",
        "unifiedWindows": {"five_hour": {"utilization": 1.0, "resetsAt": int(time.time()) + 1, "status": "rejected"}}}}))
    print(json.dumps({"type": "result", "is_error": True, "result": "You've hit your limit"}))
    sys.exit(1)
print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {}}}))
print(json.dumps({"type": "result", "is_error": False, "result": "hello"}))
'''


class RetryTest(unittest.TestCase):
    def test_pause_and_retry_without_duplicate(self):
        d = tempfile.mkdtemp()
        fake, state, session = (os.path.join(d, x) for x in ("fake.py", "state", "s.jsonl"))
        open(fake, "w").write(FAKE)
        open(session, "w").write(json.dumps({"user": "earlier turn"}) + "\n")
        orig_sf, orig_margin = cc.session_file, cc.RESET_MARGIN_S
        cc.session_file = lambda sid: session
        cc.RESET_MARGIN_S = 0
        try:
            pauses = []
            t = time.time()
            events, rc, _ = cc.run([sys.executable, fake, state, session], "turn 2", d, pauses,
                                   {"role": "client", "turn": 2}, session_id="sid")
        finally:
            cc.session_file, cc.RESET_MARGIN_S = orig_sf, orig_margin
        self.assertEqual(rc, 0)
        self.assertEqual(events[-1]["result"], "hello")
        with open(state) as f:
            self.assertEqual(f.read(), "2")                             # called twice
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0]["reason"], "limit:five_hour")
        self.assertEqual(pauses[0]["turn"], 2)
        with open(session) as f:
            lines = [json.loads(l)["user"] for l in f]
        self.assertEqual(lines, ["earlier turn", "turn 2"])            # not sent twice
        self.assertLess(time.time() - t, 30)


if __name__ == "__main__":
    unittest.main()
