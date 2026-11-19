"""Hybrid scoring and prompt-hook filters. Pure functions: no model or index needed."""
import unittest

from teambrain import hooks
from teambrain.search import _key, rank


def row(file, dist, text="t", source_type="log", session=""):
    return {"file": file, "heading": "", "text": text, "_distance": dist,
            "source_type": source_type, "session": session}


class RankTest(unittest.TestCase):
    def test_default_behaviour_is_min_score_and_per_file_cap(self):
        rows = [row("a.md", 0.1, "1"), row("a.md", 0.2, "2"), row("a.md", 0.3, "3"), row("b.md", 0.7)]
        out = rank(rows, 0.35, 2, 5)
        self.assertEqual([r["text"] for _, r in out], ["1", "2"])  # b.md below min_score, a.md capped at 2

    def test_relative_window_drops_long_tail(self):
        rows = [row("a.md", 0.10), row("b.md", 0.20), row("c.md", 0.40)]
        out = rank(rows, 0.35, 2, 5, relative_window=0.12)
        self.assertEqual([r["file"] for _, r in out], ["a.md", "b.md"])

    def test_keyword_boost_reorders_exact_match(self):
        exact = row("ticket.md", 0.30, "ABC-123 fixed")
        rows = [row("a.md", 0.25), exact]
        out = rank(rows, 0.35, 2, 1, keyword_keys={_key(exact)}, keyword_boost=0.08)
        self.assertEqual(out[0][1]["file"], "ticket.md")

    def test_type_weights_demote_a_source_type(self):
        rows = [row("raw.md", 0.20, source_type="log"), row("wiki.md", 0.22, source_type="article")]
        out = rank(rows, 0.35, 2, 1, type_weights={"log": -0.04})
        self.assertEqual(out[0][1]["file"], "wiki.md")

    def test_excludes_current_session(self):
        rows = [row("chat/s1", 0.05, session="s1"), row("a.md", 0.2)]
        out = rank(rows, 0.35, 2, 5, exclude_session="s1")
        self.assertEqual([r["file"] for _, r in out], ["a.md"])


class UnitTest(unittest.TestCase):
    def test_normalizes_and_keeps_direction(self):
        from teambrain.search import unit
        v = unit([3.0, 4.0])
        self.assertAlmostEqual(v[0], 0.6)
        self.assertAlmostEqual(v[1], 0.8)
        self.assertEqual(unit([0.0, 0.0]), [0.0, 0.0])


class SkipPromptTest(unittest.TestCase):
    def test_defaults_only_skip_tiny_prompts(self):
        r = {}
        self.assertTrue(hooks.skip_prompt("ok", r))
        self.assertFalse(hooks.skip_prompt("/review the latest outage", r))

    def test_slash_commands_and_min_words(self):
        r = {"skip_slash_commands": True, "min_words": 3}
        self.assertTrue(hooks.skip_prompt("/review the latest outage", r))
        self.assertTrue(hooks.skip_prompt("continue please", r))
        self.assertFalse(hooks.skip_prompt("why did recovery take four hours", r))


if __name__ == "__main__":
    unittest.main()
