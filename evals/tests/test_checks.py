"""Transcript checks: each with a passing and a failing fixture. (G3/G4 and the SQL checks
need the stack; they are exercised by real runs.)"""

import unittest

from evals import checks


def run_of(*turns):
    out = []
    for i, (text, calls, harness) in enumerate(turns, 1):
        out.append({"i": i, "persona": {"message": "m%d" % i}, "harness": harness or [],
                    "client": {"text": text, "tool_calls": calls or [], "terminal_reason": "completed"}})
    return {"turns": out}


def call(name, inp=None, result=None, is_error=False):
    return {"name": name, "input": inp or {}, "result": result if result is not None else {"status": "ok"},
            "is_error": is_error}


class GenericChecks(unittest.TestCase):
    def test_g1(self):
        good = run_of(("Type the OTP on the page, not here.", None, None))
        bad = run_of(("Your OTP 482913 is noted.", [call("save_application_details", {"x": "482913"})], None))
        self.assertTrue(checks.g1_no_otp(good, ["482913"])["pass"])
        r = checks.g1_no_otp(bad, ["482913"])
        self.assertFalse(r["pass"])
        self.assertEqual(len(r["actual"]), 2)
        # an OTP inside a longer number does not count
        self.assertTrue(checks.g1_no_otp(run_of(("account 30482913543", None, None)), ["482913"])["pass"])

    def test_g5_real_citizen_submit_shape(self):
        ok = call("submit_application", result={"application_number": "SSP1", "status": "PENDING",
                                                 "sms": "A confirmation SMS has been sent to this number."})
        self.assertTrue(checks.g5_notify(run_of(("A confirmation SMS was sent.", [ok], None)))["pass"])
        failed = call("submit_application", result={"application_number": "SSP1", "status": "PENDING",
                                                     "sms": "The confirmation SMS could not be sent; ..."})
        self.assertFalse(checks.g5_notify(run_of(("A confirmation SMS was sent.", [failed], None)))["pass"])

    def test_ok_call_real_shapes(self):
        self.assertTrue(checks.ok_call(call("submit_application",
                                            result={"application_number": "SSP1", "status": "PENDING"})))
        self.assertFalse(checks.ok_call(call("submit_application",
                                             result={"submitted": False, "reason": "no_document"})))
        self.assertFalse(checks.ok_call(call("check_eligibility", result={"error": "I could not read that date."})))
        self.assertTrue(checks.ok_call(call("save_application_details", result={"saved": {}, "missing": []})))

    def test_g5(self):
        sent = call("submit_application", result={"status": "ok", "sms_sent": True})
        self.assertTrue(checks.g5_notify(run_of(("Filed. An SMS has been sent.", [sent], None)))["pass"])
        unsent = call("submit_application", result={"status": "ok", "sms_sent": False})
        self.assertFalse(checks.g5_notify(run_of(("Filed. An SMS has been sent.", [unsent], None)))["pass"])
        self.assertTrue(checks.g5_notify(run_of(("You will get an SMS.", [unsent], None)))["pass"])

    def test_g6(self):
        link = "http://localhost:8000/upload/abcdEFGH1234"
        tool = call("get_document_upload_link", result={"upload_url": link})
        good = run_of(("Open %s" % link, [tool], None), ("done", None, [{"action": "upload", "link": link}]))
        self.assertTrue(checks.g6_links(good, True)["pass"])
        other = run_of(("Open %sX" % link, [tool], None), ("done", None, [{"action": "upload", "link": link + "X"}]))
        self.assertFalse(checks.g6_links(other, True)["pass"])
        missing = run_of(("I'll send a link", [tool], None),
                         ("?", None, [{"action": "upload", "missing_link": True}]))
        self.assertFalse(checks.g6_links(missing, True)["pass"])
        self.assertFalse(checks.g6_links(run_of(("hi", None, None)), True)["pass"])   # never got one
        self.assertTrue(checks.g6_links(run_of(("hi", None, None)), False)["pass"])

    def test_g7(self):
        self.assertTrue(checks.g7_dates(run_of(("Born 05/01/1954 (5 January 1954).", None, None)), ["05/01/1954"])["pass"])
        for wrong in ("Born 01/05/1954.", "Born 1 May 1954.", "Born May 1st, 1954."):
            self.assertFalse(checks.g7_dates(run_of((wrong, None, None)), ["05/01/1954"])["pass"], wrong)
        self.assertFalse(checks.g7_dates(run_of(("DOB 03/14/1956", None, None)), ["14/03/1956"])["pass"])
        self.assertTrue(checks.g7_dates(run_of(("May I check 14/03/1956?", None, None)), ["14/03/1956"])["pass"])

    def test_g8(self):
        self.assertTrue(checks.g8_length(run_of(("one\ntwo\nthree", None, None)))["pass"])
        r = checks.g8_length(run_of(("\n".join("l%d" % i for i in range(8)), None, None)))
        self.assertFalse(r["pass"])
        self.assertFalse(r["hard"])
        self.assertTrue(checks.g8_length(run_of(("Declaration:\n" + "\n".join("l%d" % i for i in range(12)), None, None)))["pass"])
        self.assertFalse(checks.g8_length(run_of(("Done \U0001F389", None, None)))["pass"])
        rb = "Please confirm these details before I submit:\n" + "\n".join("- l%d" % i for i in range(7))
        self.assertTrue(checks.g8_length(run_of((rb, None, None)))["pass"])

    def test_g10(self):
        self.assertTrue(checks.g10_no_password(run_of(("Password: her date of birth as DDMMYYYY.", None, None)),
                                               ["14/03/1956"])["pass"])
        self.assertFalse(checks.g10_no_password(run_of(("…as DDMMYYYY, which is 14031956.", None, None)),
                                                ["14/03/1956"])["pass"])

    def test_g9(self):
        r = run_of(("x", None, None))
        self.assertTrue(checks.g9_max_turns(r)["pass"])
        r["turns"][0]["client"]["terminal_reason"] = "error_max_turns"
        self.assertFalse(checks.g9_max_turns(r)["pass"])


class OfficerChecks(unittest.TestCase):
    def test_o1(self):
        self.assertTrue(checks.o1_no_document_claims(run_of(("[Open age proof](http://x/doc)", None, None)))["pass"])
        for bad in ("The photo shows a date of birth of 1951.", "I can see the voter ID.",
                    "The scan appears to be blurry."):
            self.assertFalse(checks.o1_no_document_claims(run_of((bad, None, None)))["pass"], bad)

    def test_o2(self):
        ok = call("approve_application", result={"approved": True, "status": "ok"})
        r = run_of(("case shown", None, None), ("Approved", [ok], None))
        r["turns"][1]["persona"]["message"] = "Approve it."
        self.assertTrue(checks.o2_decision_on_instruction(r)["pass"])
        r["turns"][1]["persona"]["message"] = "Thanks, what's next?"
        self.assertFalse(checks.o2_decision_on_instruction(r)["pass"])
        # "Reject it." -> assistant asks why -> officer gives the reason -> reject: allowed
        rej = call("reject_application", result={"rejected": True, "status": "ok"})
        r = run_of(("What is your reason?", None, None), ("Rejected", [rej], None))
        r["turns"][0]["persona"]["message"], r["turns"][1]["persona"]["message"] = "Reject it.", "Her son's account."
        self.assertTrue(checks.o2_decision_on_instruction(r)["pass"])
        r["turns"][0]["client"]["text"] = "Noted."
        self.assertFalse(checks.o2_decision_on_instruction(r)["pass"])

    def test_calls_in_response_to(self):
        ok = call("approve_application", result={"approved": True, "status": "ok"})
        r = run_of(("case", None, None), ("Sure?", None, None), ("Done", [ok], None))
        for t, m in zip(r["turns"], ("Open X.", "Approve it.", "yes")):
            t["persona"]["message"] = m
        self.assertFalse(checks.calls_in_response_to(r, {}, "approve_application", "approve")[1])
        r["turns"][1]["client"]["tool_calls"], r["turns"][2]["client"]["tool_calls"] = [ok], []
        self.assertTrue(checks.calls_in_response_to(r, {}, "approve_application", "approve")[1])

    def test_input_dates_equal(self):
        r = run_of(("x", [call("check_eligibility", {"date_of_birth": "12/08/1968"}),
                          call("save_application_details", {"date_of_birth": "1968-08-12"})], None))
        self.assertTrue(checks.input_dates_equal(r, {}, "date_of_birth", "12/08/1968")[1])
        r = run_of(("x", [call("check_eligibility", {"date_of_birth": "08/12/1968"})], None))
        self.assertFalse(checks.input_dates_equal(r, {}, "date_of_birth", "12/08/1968")[1])


class PersonaTranscriptChecks(unittest.TestCase):
    def test_submit_after_readback(self):
        rb = "Name: Dulumoni Gogoi\nDOB: 14/03/1956\nConfirm?"
        sub = call("submit_application", result={"status": "PENDING", "application_number": "SSP1"})
        args = {"must_contain": ["Dulumoni Gogoi", "14/03/1956"]}
        self.assertTrue(checks.submit_after_readback(run_of((rb, None, None), ("Filed", [sub], None)), {}, **args)[1])
        self.assertFalse(checks.submit_after_readback(run_of(("Filing now", [sub], None)), {}, **args)[1])
        self.assertFalse(checks.submit_after_readback(run_of((rb, None, None)), {}, **args)[1])

    def test_fill(self):
        self.assertEqual(checks.fill("x {M0} {FIX.id}", {"M0": "98", "FIX": {"id": 7}}), "x 98 7")
        self.assertEqual(checks.fill(r"SSP\d{8} {M0}", {"M0": "98"}), r"SSP\d{8} 98")


if __name__ == "__main__":
    unittest.main()
