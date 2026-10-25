import json
import unittest

from evals import mask

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJjaXRpemVuOjk4MDEifQ.c2lnbmF0dXJlLXBhcnQ"


class MaskTest(unittest.TestCase):
    def test_p06_otp_everywhere(self):
        otp = "482913"
        run = {"turns": [
            {"harness": [{"observation": 'That phone got an SMS: "Your Sewa Setu OTP is 482913."'}],
             "persona": {"message": "code is 482913"},
             "client": {"text": "Please type 482913 on the page, not here.",
                        "tool_calls": [{"input": {"note": "otp 482913"}}]}}]}
        text = mask.dumps_safe(run, otps=[otp])
        self.assertNotIn(otp, text)
        self.assertEqual(text.count("[OTP]"), 4)
        self.assertIn('"code is [OTP]"', text)

    def test_otp_inside_longer_number_is_kept(self):
        self.assertEqual(mask.mask_text("account 30482913543", otps=["482913"]), "account 30482913543")

    def test_jwt_and_secret(self):
        s = mask.mask_text("Bearer %s refresh abcSECRETxyz" % JWT, secrets=["abcSECRETxyz"])
        self.assertEqual(s, "Bearer [JWT] refresh [SECRET]")

    def test_links_keep_four_chars(self):
        s = mask.mask_text("open http://localhost:8000/upload/9NJRNvlzGgtgQmRa8f and "
                           "http://localhost:8000/verify-number/PJHgc1gDNfVu")
        self.assertEqual(s, "open http://localhost:8000/upload/9NJR… and http://localhost:8000/verify-number/PJHg…")

    def test_scan_refuses_leaks(self):
        for bad in (JWT, "OTP is 482913", "/upload/9NJRNvlzGg"):
            with self.assertRaises(mask.SecretLeak):
                mask.scan(json.dumps(bad), otps=["482913"])

    def test_scan_passes_masked(self):
        mask.scan(mask.dumps_safe({"a": "OTP is 482913 at /upload/9NJRNvlzGg"}, otps=["482913"]), otps=["482913"])


if __name__ == "__main__":
    unittest.main()
