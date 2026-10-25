import unittest

from evals import claude_cli as cc

ALLOWED = {"type": "rate_limit_event", "rate_limit_info": {
    "status": "allowed", "resetsAt": 1792921800, "rateLimitType": "five_hour",
    "unifiedWindows": {"five_hour": {"utilization": 0.15, "resetsAt": 1792921800, "status": "allowed"},
                       "seven_day": {"utilization": 0.02, "resetsAt": 1793494800, "status": "allowed"}}}}
OK_RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "fine"}


def rejected(window="five_hour", reset=1792921800):
    return {"type": "rate_limit_event", "rate_limit_info": {
        "status": "rejected", "resetsAt": reset, "rateLimitType": window,
        "unifiedWindows": {window: {"utilization": 1.0, "resetsAt": reset, "status": "rejected"}}}}


class LimitTest(unittest.TestCase):
    def test_allowed_run_is_not_a_limit(self):
        self.assertIsNone(cc.limit_hit([ALLOWED, OK_RESULT]))

    def test_rejected_event(self):
        err = {"type": "result", "is_error": True, "result": "You've hit your limit · resets 3pm"}
        hit = cc.limit_hit([rejected(), err], returncode=1)
        self.assertEqual(hit["reset_at"], 1792921800)
        self.assertEqual(hit["kind"], "five_hour")

    def test_weekly_reset_wins(self):
        hit = cc.limit_hit([rejected("seven_day", 1793494800)], returncode=1)
        self.assertEqual(hit["reset_at"], 1793494800)

    def test_text_only_fallback(self):
        for text in ("Claude AI usage limit reached|1792921800", "You've hit your limit · resets 3pm (Asia/Calcutta)"):
            hit = cc.limit_hit([{"type": "result", "is_error": True, "result": text}], returncode=1)
            self.assertIsNotNone(hit, text)
            self.assertIsNone(hit["reset_at"])

    def test_text_needs_a_failure(self):
        # an assistant reply that mentions a limit is not a refused call
        ok = {"type": "result", "is_error": False, "result": "The usage limit for uploads is 5 MB"}
        self.assertIsNone(cc.limit_hit([ok]))

    def test_other_errors_are_not_limits(self):
        err = {"type": "result", "is_error": True, "result": "MCP server failed to connect"}
        self.assertIsNone(cc.limit_hit([err], returncode=1))

    def test_near_limit(self):
        self.assertIsNone(cc.near_limit(ALLOWED["rate_limit_info"]))
        info = rejected()["rate_limit_info"]
        self.assertEqual(cc.near_limit(info), ("five_hour", 1792921800))

    def test_wait_seconds(self):
        self.assertEqual(cc.wait_seconds(1000, now=400), 600 + cc.RESET_MARGIN_S)
        self.assertEqual(cc.wait_seconds(None), cc.NO_RESET_PROBE_S)
        self.assertEqual(cc.wait_seconds(100, now=400), cc.RESET_MARGIN_S)


if __name__ == "__main__":
    unittest.main()
