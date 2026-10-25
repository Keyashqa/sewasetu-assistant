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


if __name__ == "__main__":
    unittest.main()
