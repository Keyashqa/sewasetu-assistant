"""/admin/mcp-metrics session rules (app/mcp_metrics_calc.py) on synthetic mcp_calls rows."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))
import mcp_metrics_calc as calc  # noqa: E402

T0 = datetime(2026, 11, 14, 10, 0, 0)
NOW = T0 + timedelta(hours=3)


def rows(*calls, session="s1", kind="access", start=T0, step=60):
    """calls: (tool, args, outcome, completion) or (tool, args, outcome, completion, at)."""
    out = []
    for i, c in enumerate(calls):
        tool, args, outcome, completion = c[:4]
        at = c[4] if len(c) > 4 else start + timedelta(seconds=i * step)
        out.append({"session_key": session, "token_kind": kind, "tool": tool,
                    "args_key": args, "outcome": outcome, "completion": completion, "at": at})
    return out


class ProcessTests(unittest.TestCase):
    def test_apply_counts_calls_up_to_submit(self):
        r = rows(("get_scheme_info", "a", "ok", None),
                 ("check_eligibility", "b", "ok", None),
                 ("save_application_details", "c", "ok", None),
                 ("get_document_upload_link", "d", "ok", None),
                 ("submit_application", "e", "ok", "apply"))
        s = calc.analyze(r, NOW)
        self.assertEqual(s["processes"]["apply"], {"n": 1, "median": 5, "p90": 5, "mean": 5.0})
        self.assertEqual(s["completed_sessions"], 1)
        self.assertEqual(s["abandoned_sessions"], 0)

    def test_two_decisions_split_into_two_processes(self):
        r = rows(("get_queue_summary", "a", "ok", None),
                 ("list_applications", "b", "ok", None),
                 ("get_application", "c", "ok", None),
                 ("approve_application", "d", "ok", "decision"),
                 ("get_application", "e", "ok", None),
                 ("reject_application", "f", "ok", "decision"))
        s = calc.analyze(r, NOW)
        self.assertEqual(s["processes"]["decision"]["n"], 2)
        self.assertEqual(s["processes"]["decision"]["median"], 3)    # [2, 4]
        self.assertEqual(s["processes"]["decision"]["p90"], 4)
        self.assertEqual(s["processes"]["decision"]["mean"], 3.0)

    def test_status_only_counts_without_apply(self):
        alone = rows(("get_scheme_info", "a", "ok", None),
                     ("get_my_application", "b", "ok", "status"),
                     ("get_my_application", "b", "ok", "status"))
        s = calc.analyze(alone, NOW)
        self.assertEqual(s["processes"]["status"]["n"], 1)
        self.assertEqual(s["processes"]["status"]["median"], 2)
        with_apply = rows(("get_my_application", "a", "ok", "status"),
                          ("save_application_details", "b", "ok", None),
                          ("submit_application", "c", "ok", "apply"), session="s2")
        s = calc.analyze(with_apply, NOW)
        self.assertEqual(s["processes"]["status"]["n"], 0)
        self.assertEqual(s["processes"]["apply"]["median"], 3)


class WasteTests(unittest.TestCase):
    def test_repeat_same_args_is_waste(self):
        r = rows(("check_eligibility", "x", "ok", None),
                 ("check_eligibility", "x", "ok", None),
                 ("check_eligibility", "y", "ok", None))
        s = calc.analyze(r, NOW)
        self.assertEqual((s["repeats"], s["wasted"], s["polls"]), (1, 1, 0))
        self.assertEqual(s["per_tool"]["check_eligibility"]["repeats"], 1)

    def test_successful_write_resets_repeats(self):
        r = rows(("get_application", "x", "ok", None),
                 ("save_application_details", "w", "ok", None),
                 ("get_application", "x", "ok", None))
        self.assertEqual(calc.analyze(r, NOW)["repeats"], 0)

    def test_failed_write_does_not_reset(self):
        r = rows(("submit_application", "x", "refused", None),
                 ("submit_application", "x", "refused", None))
        s = calc.analyze(r, NOW)
        self.assertEqual(s["repeats"], 1)

    def test_polls_are_not_waste(self):
        r = rows(("get_document_upload_link", "x", "ok", None),
                 ("get_document_upload_link", "x", "ok", None),
                 ("get_number_verification_link", "y", "ok", None),
                 ("get_number_verification_link", "y", "ok", None))
        s = calc.analyze(r, NOW)
        self.assertEqual((s["polls"], s["repeats"], s["wasted"]), (2, 0, 0))

    def test_merged_link_tool_polls_are_not_waste(self):
        r = rows(("get_link", "age", "ok", None), ("get_link", "age", "ok", None),
                 ("get_link", "ver", "ok", None), ("get_link", "ver", "ok", None))
        s = calc.analyze(r, NOW)
        self.assertEqual((s["polls"], s["repeats"], s["wasted"]), (2, 0, 0))

    def test_error_counted_once_even_if_repeated(self):
        r = rows(("check_eligibility", "x", "error", None),
                 ("check_eligibility", "x", "error", None))
        s = calc.analyze(r, NOW)
        self.assertEqual((s["errors"], s["repeats"], s["wasted"]), (2, 1, 2))
        self.assertEqual(s["wasted_pct"], 100.0)

    def test_refusal_is_not_waste(self):
        r = rows(("check_eligibility", "x", "refused", None))
        self.assertEqual(calc.analyze(r, NOW)["wasted"], 0)

    def test_repeats_are_per_session(self):
        r = rows(("check_eligibility", "x", "ok", None), session="a") + \
            rows(("check_eligibility", "x", "ok", None), session="b")
        self.assertEqual(calc.analyze(r, NOW)["repeats"], 0)


class SessionTests(unittest.TestCase):
    def test_abandoned_after_idle_gap(self):
        r = rows(("check_eligibility", "a", "ok", None),
                 ("save_application_details", "b", "ok", None))
        s = calc.analyze(r, NOW)
        self.assertEqual((s["abandoned_sessions"], s["abandoned_applications"]), (1, 1))

    def test_recent_session_is_in_progress(self):
        r = rows(("check_eligibility", "a", "ok", None), start=NOW - timedelta(minutes=5))
        s = calc.analyze(r, NOW)
        self.assertEqual((s["abandoned_sessions"], s["in_progress_sessions"]), (0, 1))

    def test_abandoned_without_save_is_not_an_abandoned_application(self):
        r = rows(("get_scheme_info", "a", "ok", None))
        s = calc.analyze(r, NOW)
        self.assertEqual((s["abandoned_sessions"], s["abandoned_applications"]), (1, 0))

    def test_program_token_splits_on_idle_gap(self):
        r = rows(("get_queue_summary", "a", "ok", None, T0),
                 ("get_queue_summary", "a", "ok", None, T0 + timedelta(minutes=45)),
                 kind="program")
        s = calc.analyze(r, NOW)
        self.assertEqual(s["sessions"], 2)
        self.assertEqual(s["repeats"], 0)

    def test_access_token_does_not_split_on_idle_gap(self):
        r = rows(("get_document_upload_link", "a", "ok", None, T0),
                 ("save_application_details", "b", "ok", None, T0 + timedelta(minutes=45)),
                 ("submit_application", "c", "ok", "apply", T0 + timedelta(minutes=46)))
        s = calc.analyze(r, NOW)
        self.assertEqual(s["sessions"], 1)
        self.assertEqual(s["processes"]["apply"]["median"], 3)

    def test_empty(self):
        s = calc.analyze([], NOW)
        self.assertEqual((s["calls"], s["wasted_pct"], s["sessions"]), (0, None, 0))


class SummaryTests(unittest.TestCase):
    def test_median_and_p90(self):
        self.assertEqual(calc.summarize([5, 1, 3]), {"n": 3, "median": 3, "p90": 5, "mean": 3.0})
        self.assertEqual(calc.summarize(list(range(1, 11)))["p90"], 9)
        self.assertEqual(calc.summarize([1, 2])["median"], 1.5)


class TokenTests(unittest.TestCase):
    def test_estimate(self):
        self.assertEqual(calc.est_tokens(350), 100)
        self.assertEqual(calc.est_tokens(0), 0)
        self.assertEqual(calc.est_tokens(Decimal("700.0")), 200)      # SQL avg() is a Decimal


if __name__ == "__main__":
    unittest.main()
