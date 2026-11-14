"""Run-level efficiency and tokens from a transcript (evals/efficiency.py)."""

import unittest

from evals import efficiency


def turn(calls, usage, num_turns=1, first=None):
    return {"client": {"tool_calls": calls, "usage": usage, "num_turns": num_turns,
                       "first_call_context": first}}


def call(name, inp=None, result=None, is_error=False):
    return {"name": name, "input": inp or {}, "result": result if result is not None else {"reply": "x"},
            "is_error": is_error}


U = {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000,
     "output_tokens": 50}


class RunEfficiencyTests(unittest.TestCase):
    def test_apply_counts_waste_and_tokens(self):
        rec = {"turns": [
            turn([call("get_scheme_info"), call("check_eligibility", {"date_of_birth": "x"},
                                                {"eligible": False, "error": "bad date"})], U, 3, 8000),
            turn([call("check_eligibility", {"date_of_birth": "y"}, {"eligible": True}),
                  call("save_application_details", {"full_name": "A"}, {"reply": "saved"}),
                  call("get_document_upload_link", {}, {"document_attached": False}),
                  call("get_document_upload_link", {}, {"document_attached": True}),
                  call("submit_application", {"confirm_declaration": True},
                       {"application_number": "SSP1", "submitted": "14/11/2026"})], U, 4)]}
        e = efficiency.run_efficiency(rec)
        self.assertEqual(e["applies"], 1)
        self.assertEqual(e["calls_per_apply"], [7])
        self.assertEqual((e["errors"], e["repeats"], e["polls"], e["wasted"]), (1, 0, 1, 1))
        self.assertEqual(e["tokens"]["total"], 2 * 1160)
        self.assertEqual(e["tokens_per_apply"], 2320)
        self.assertEqual(e["client_api_turns"], 7)
        self.assertEqual(e["first_call_context"], 8000)

    def test_is_error_and_refused_submit(self):
        rec = {"turns": [turn([call("submit_application", {}, "boom", is_error=True),
                               call("submit_application", {}, {"submitted": False, "reason": "incomplete"})], U)]}
        e = efficiency.run_efficiency(rec)
        self.assertEqual((e["applies"], e["errors"], e["tokens_per_apply"]), (0, 1, None))


if __name__ == "__main__":
    unittest.main()
