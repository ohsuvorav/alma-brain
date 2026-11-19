"""Lint rules on a throwaway synthetic brain."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from teambrain import config as cfgmod
from teambrain import lint


def write(root, rel, text, age_days=0):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    return p


class LintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        write(self.root, "teambrain.yaml", "name: lint-fixture\n")
        self.cfg = cfgmod.Config(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def rules(self):
        return {(f["rule"], f["file"]) for f in lint.check(self.cfg)}

    def test_clean_brain_has_no_findings(self):
        write(self.root, "wiki/a.md", "# Alpha\n\nSee [beta](b.md).\n")
        write(self.root, "wiki/b.md", "# Beta\n\nBody.\n")
        self.assertEqual(lint.check(self.cfg), [])

    def test_self_stale_only_on_status_lines(self):
        write(self.root, "wiki/old.md", "# Old plan (superseded by new-plan.md)\n\nBody.\n")
        write(self.root, "wiki/quote.md", "# Notes\n\nSomeone said the cache was stale yesterday.\n")
        self.assertEqual(self.rules(), {("DOC-SELF-STALE", "wiki/old.md")})

    def test_idle_temp_folder(self):
        write(self.root, "raw/temp/old-topic/README.md", "# Old topic\n", age_days=30)
        write(self.root, "raw/temp/fresh-topic/README.md", "# Fresh topic\n")
        self.assertIn(("TEMP-IDLE", "raw/temp/old-topic/README.md"), self.rules())
        self.assertNotIn(("TEMP-IDLE", "raw/temp/fresh-topic/README.md"), self.rules())

    def test_duplicates_and_broken_links(self):
        write(self.root, "wiki/x.md", "# Same\n\nOne.\n")
        write(self.root, "wiki/y.md", "# Same\n\nTwo. [gone](missing.md)\n")
        write(self.root, "raw/import.md", "# Import\n\n[orig](not-here.md)\n")  # raw/* skips link checks
        found = self.rules()
        self.assertIn(("DUP-FILE", "wiki/x.md"), found)
        self.assertIn(("BROKEN-DOC-LINK", "wiki/y.md"), found)
        self.assertNotIn(("BROKEN-DOC-LINK", "raw/import.md"), found)


if __name__ == "__main__":
    unittest.main()
