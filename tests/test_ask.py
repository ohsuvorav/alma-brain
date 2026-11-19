"""brain ask: debug view of the context a prompt hook would inject."""
import tempfile
import unittest
from pathlib import Path

from teambrain import config as cfgmod
from teambrain.ask import answer


def _brain(root, with_index):
    root = Path(root)
    (root / "teambrain.yaml").write_text("name: ask-fixture\n")
    (root / "wiki").mkdir()
    (root / "raw").mkdir()
    cfg = cfgmod.Config(root)
    if with_index:
        cfg.db_path.mkdir(parents=True)
    return cfg


HIT = {
    "file": "raw/imports/notes/tea.md",
    "heading": "Tea",
    "text": "Evening tea is ivan-chai.",
    "source_type": "log",
}


def _hits(cfg, question):
    del cfg, question
    return [(0.82, HIT)], False


class AskTest(unittest.TestCase):
    def test_empty_wiki_prints_raw_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _brain(d, with_index=True)
            text, code = answer(cfg, "what tea in the evening", retrieve_fn=_hits)
            self.assertEqual(code, 0)
            self.assertIn("raw/imports/notes/tea.md", text)
            self.assertIn("Context Alma would inject:", text)
            self.assertIn("Evening tea is ivan-chai.", text)
            self.assertFalse(list(Path(d).joinpath("wiki").iterdir()))

    def test_passages_drop_frontmatter_and_wikilinks(self):
        hit = dict(HIT, text="---\ntitle: Tea\n---\n\nSee [[evening tea|ivan-chai]].\n")

        def hits(cfg, question):
            del cfg, question
            return [(0.7, hit)], False

        with tempfile.TemporaryDirectory() as d:
            cfg = _brain(d, with_index=True)
            text, code = answer(cfg, "what tea", retrieve_fn=hits)
        self.assertEqual(code, 0)
        self.assertIn("Context Alma would inject:", text)
        self.assertIn("ivan-chai", text)
        self.assertNotIn("[[", text)
        self.assertNotIn("title:", text)

    def test_missing_index_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _brain(d, with_index=False)
            text, code = answer(cfg, "what tea", retrieve_fn=_hits)
        self.assertEqual(code, 0)
        self.assertIn("fix: brain index", text)
