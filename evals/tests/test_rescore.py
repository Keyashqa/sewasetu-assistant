import unittest

from evals import rescore


def _run(text, checks, fidelity="pass", outcome="fail"):
    return {"persona": "p10", "outcome": outcome, "fidelity": {"verdict": fidelity}, "mobiles": {"M0": "9810005300"},
            "turns": [{"i": 1, "persona": {}, "harness": [], "client": {"text": text, "tool_calls": []}}],
            "checks": checks}


def _check(cid, ok, hard=True):
    return {"id": cid, "kind": "transcript", "hard": hard, "desc": cid, "expected": "true", "actual": "x", "pass": ok}


class Rescore(unittest.TestCase):
    def test_soft_rule_flips_outcome_and_adds_check(self):
        rec = _run("Closed on 01/10/2026.", [_check("P10.says_date", True), _check("P10.no_reopen_implied", False)])
        changes = rescore.rescore_run(rec)
        self.assertEqual(rec["outcome"], "pass")
        self.assertEqual(rec["failed_hard"], [])
        self.assertIn("P10.no_reopen_implied: hard -> soft", changes)
        self.assertIn("P10.no_upload added (pass)", changes)

    def test_other_hard_failure_still_fails(self):
        rec = _run("Closed.", [_check("P10.says_date", False), _check("P10.no_reopen_implied", False)])
        rescore.rescore_run(rec)
        self.assertEqual((rec["outcome"], rec["failed_hard"]), ("fail", ["P10.says_date"]))

    def test_invalid_stays_invalid_and_errors_untouched(self):
        rec = _run("Closed on 01/10/2026.", [_check("P10.no_reopen_implied", False)], fidelity="fail", outcome="invalid")
        rescore.rescore_run(rec)
        self.assertEqual(rec["outcome"], "invalid")
        err = {"persona": "p10", "outcome": "error", "checks": []}
        self.assertEqual(rescore.rescore_run(err), [])


if __name__ == "__main__":
    unittest.main()
