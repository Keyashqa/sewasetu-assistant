"""The committed data files load: personas and rounds.yaml (the dashboard reads both)."""

import unittest

import yaml

from evals import runner
from evals.config import EVALS


class FilesLoad(unittest.TestCase):
    def test_rounds_yaml(self):
        d = yaml.safe_load((EVALS / "rounds.yaml").read_text(encoding="utf-8"))
        for r in d["rounds"]:
            for f in r["findings"]:
                self.assertIn("found", f, f.get("id"))
                self.assertIsInstance(f.get("changed", []), list, f.get("id"))

    def test_personas(self):
        for pid in runner.all_personas():
            p = runner.load_persona(pid)
            self.assertEqual(p["id"], pid)
            self.assertIsInstance(p["number"], int, pid)
            for c in p.get("checks", []):
                self.assertIn(c["kind"], ("sql", "gateway", "transcript", "judge", "probe"), c["id"])
                # a YAML double-quoted "\b" is a backspace, not a regex word boundary
                for ch in ("\x07", "\x08", "\x0c"):
                    self.assertNotIn(ch, repr(c).encode().decode("unicode_escape"), c["id"])


if __name__ == "__main__":
    unittest.main()
