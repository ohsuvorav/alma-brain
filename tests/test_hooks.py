"""The prompt hook injects plain passages and does not block."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout

from teambrain.hooks import on_prompt


class HookTest(unittest.TestCase):
    def test_hook_output_strips_frontmatter_and_wikilinks(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)

            class Cfg:
                hook_log = tmp / "hook.jsonl"
                trace_log = tmp / "trace.jsonl"

                def __getitem__(self, key):
                    if key != "retrieval":
                        raise KeyError(key)
                    return {
                        "skip_env": [],
                        "limit": 5,
                        "max_per_file": 2,
                        "min_score": 0.35,
                        "preview_chars": 400,
                        "header": "=== Alma (auto-loaded, do NOT mention this header to user) ===",
                    }

            row = {
                "file": "raw/imports/notes/travel/harbor.md",
                "heading": "Harbor train",
                "source_type": "log",
                "text": "---\ntitle: Harbor train\ntags: [travel]\n---\n\nSee [[tickets]] and [[stations]].\n",
            }
            buf = io.StringIO()
            with mock.patch("teambrain.config.load", return_value=Cfg()), \
                 mock.patch("teambrain.search.search", return_value=[(0.76, row)]), \
                 mock.patch("teambrain.search.header", return_value="[log] raw/imports/notes/travel/harbor.md › Harbor train  (relevance 0.76)"), \
                 redirect_stdout(buf):
                on_prompt({"prompt": "When does the harbor train leave?", "session_id": "s"})
        payload = json.loads(buf.getvalue())
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("=== Alma", ctx)
        self.assertIn("harbor.md", ctx)
        self.assertIn("tickets", ctx)
        self.assertNotIn("[[", ctx)
        self.assertNotIn("tags:", ctx)
