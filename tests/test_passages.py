"""Frontmatter stays out of the index. Wikilinks become plain text when shown."""
import tempfile
import unittest
from pathlib import Path

from teambrain import config as cfgmod
from teambrain.index import chunk_file, collect_files
from teambrain.passages import display_text, strip_frontmatter


RAW = """---
title: Harbor train
tags: [travel]
---

# Harbor train

See [[tickets]] and [[stations|the stations]].
"""


class PassageTest(unittest.TestCase):
    def test_frontmatter_is_stripped_and_wikilinks_stay_in_the_chunk(self):
        self.assertNotIn("tags:", strip_frontmatter(RAW))
        self.assertIn("[[tickets]]", strip_frontmatter(RAW))
        shown = display_text(RAW)
        self.assertNotIn("title:", shown)
        self.assertNotIn("[[", shown)
        self.assertIn("tickets", shown)
        self.assertIn("the stations", shown)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "teambrain.yaml").write_text("name: passages\n")
            note = root / "raw" / "harbor.md"
            note.parent.mkdir()
            note.write_text(RAW)
            (root / "wiki").mkdir()
            cfg = cfgmod.Config(root)
            chunks = chunk_file(cfg, note)
        self.assertTrue(chunks)
        self.assertNotIn("tags:", chunks[0]["text"])
        self.assertIn("[[tickets]]", chunks[0]["text"])

    def test_private_notes_are_not_indexed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "teambrain.yaml").write_text("name: passages\n")
            (root / "wiki").mkdir()
            (root / "raw" / ".private").mkdir(parents=True)
            (root / "raw" / ".private" / "secret.md").write_text("a private fact\n")
            (root / "raw" / "tea.md").write_text("Evening tea.\n")
            names = [p.name for p, _ in collect_files(cfgmod.Config(root))]
        self.assertEqual(names, ["tea.md"])
