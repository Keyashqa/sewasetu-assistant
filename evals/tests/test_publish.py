import unittest

from evals import publish


class PublishSafety(unittest.TestCase):
    def test_mobiles_masked(self):
        out = publish._mask_mobiles({"t": "SMS sent to 9801000600; account 30219876543"})
        self.assertEqual(out["t"], "SMS sent to 98XXXX0600; account 30219876543")

    def test_scan_refuses(self):
        for bad in ("Your Sewa Setu OTP is 482913.", "contact 9801000600",
                    "http://localhost:8000/upload/9NJRNvlzGg", "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJjaXRpemVu.c2ln"):
            with self.assertRaises(publish.Unsafe, msg=bad):
                publish.scan(bad)

    def test_safe_dump_masks_then_passes(self):
        text = publish.safe_dump({"a": "call 9801000600 or open /upload/9NJRNvlzGgtg"})
        self.assertIn("98XXXX0600", text)
        self.assertIn("/upload/9NJR…", text)

    def test_compact_drops_bulk(self):
        r = publish._compact_result({"reply": "x", "villages_by_block": {"a": ["b"] * 500}, "status": "ok"})
        self.assertEqual(r, {"reply": "x", "status": "ok"})


class Happened(unittest.TestCase):
    def run_with(self, persona, checks, calls=()):
        return {"persona": persona, "checks": [{"id": k, "actual": v} for k, v in checks.items()],
                "turns": [{"client": {"tool_calls": [{"name": n, "result": r} for n, r in calls]}}]}

    def test_phrase_follows_recorded_status(self):
        self.assertEqual(publish.happened(self.run_with("p01", {"P01.row": "PENDING|x"})), "Filed — Pending")
        self.assertEqual(publish.happened(self.run_with("p01", {"P01.row": "DEEMED_APPROVED|x"})), "Filed — Deemed approved")
        self.assertEqual(publish.happened(self.run_with("p01", {"P01.row": "", "P01.count": "0"})), "Not filed")

    def test_tool_result_condition(self):
        blocked = [("approve_application", {"status": "blocked", "approved": False})]
        self.assertEqual(publish.happened(self.run_with("p14", {"P14.still_pending": "PENDING"}, blocked)),
                         "Approval refused by portal")
        self.assertEqual(publish.happened(self.run_with("p14", {"P14.still_pending": "PENDING"})), "Not approved — Pending")

    def test_no_rule_matches(self):
        self.assertEqual(publish.happened(self.run_with("p12", {})), "Not recorded")


if __name__ == "__main__":
    unittest.main()
