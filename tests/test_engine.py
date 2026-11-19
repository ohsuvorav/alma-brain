"""Engine tests against the synthetic fixture brain. Index/search tests need fastembed's model."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import hooks

FIXTURE = Path(__file__).parent / "fixture-brain"


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ("BRAIN_ROOT", "SECOND_BRAIN_DIR", "BRAIN_STATE_DIR"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()

    def test_finds_root_by_walking_up(self):
        self.assertEqual(cfgmod.find_root(FIXTURE / "wiki" / "eng"), FIXTURE.resolve())

    def test_env_overrides_walk(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["BRAIN_ROOT"] = d
            self.assertEqual(cfgmod.find_root(FIXTURE), Path(d).resolve())

    def test_outside_brain_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(cfgmod.load(d))

    def test_yaml_merges_over_defaults(self):
        cfg = cfgmod.load(FIXTURE)
        self.assertEqual(cfg["mcp"]["search_tool"], "search_fixture")
        self.assertEqual(cfg["retrieval"]["limit"], 5)  # default kept
        self.assertEqual(cfg.state_dir, FIXTURE.resolve() / ".brain")

    def test_source_types_first_match_wins(self):
        cfg = cfgmod.load(FIXTURE)
        self.assertEqual(cfg.source_type("wiki/eng/principles.md"), "article")
        self.assertEqual(cfg.source_type(".private/facts.md"), "fact")
        self.assertEqual(cfg.source_type("raw/timeline.md"), "log")


class StopHookTest(unittest.TestCase):
    def test_reads_last_assistant_text_from_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "t.jsonl"
            lines = [
                {"type": "user", "message": {"role": "user", "content": "hi"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "first"}]}},
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "x"}]}},
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "final answer"}]}},
            ]
            t.write_text("\n".join(json.dumps(x) for x in lines))
            self.assertEqual(hooks.last_response({"transcript_path": str(t)}), "final answer")

    def test_writes_response_trace_to_state_dir(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"BRAIN_STATE_DIR": d}):
            hooks.on_stop({"cwd": str(FIXTURE), "session_id": "s1", "last_assistant_message": "done"})
            entry = json.loads((Path(d) / "trace-log.jsonl").read_text().splitlines()[0])
            self.assertEqual((entry["type"], entry["response"]), ("response", "done"))

    def test_outside_brain_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            hooks.on_stop({"cwd": d, "session_id": "s1", "last_assistant_message": "x"})
            self.assertEqual(list(Path(d).iterdir()), [])


def _model_available():
    try:
        import fastembed  # noqa: F401
        import lancedb  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_model_available(), "fastembed/lancedb not installed")
class IndexSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = tempfile.TemporaryDirectory()
        cls.env = mock.patch.dict(os.environ, {"BRAIN_STATE_DIR": cls.state.name})
        cls.env.start()
        os.environ.pop("BRAIN_ROOT", None)
        os.environ.pop("SECOND_BRAIN_DIR", None)
        from teambrain.index import build_index
        cls.cfg = cfgmod.load(FIXTURE)
        cls.rows = build_index(cls.cfg, verbose=False)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.state.cleanup()

    def test_index_writes_only_to_state_dir(self):
        self.assertGreaterEqual(self.rows, 2)
        self.assertTrue((Path(self.state.name) / ".lancedb").exists())
        self.assertFalse((FIXTURE / ".brain").exists())

    def test_search_finds_relevant_chunk(self):
        from teambrain import search as core
        results = core.search(self.cfg, "why did the database outage take so long to recover", 5, 2, 0.35)
        self.assertEqual(results[0][1]["file"], "raw/timeline.md")

    def test_prompt_hook_injects_and_traces(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            hooks.on_prompt({"cwd": str(FIXTURE), "session_id": "s2",
                             "prompt": "why did the database outage take so long to recover"})
        ctx = json.loads(buf.getvalue())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("raw/timeline.md", ctx)
        self.assertNotIn(".private/", ctx)
        trace = (Path(self.state.name) / "trace-log.jsonl").read_text()
        self.assertIn('"session_id": "s2"', trace)

    def test_query_adapter_reports_fresh_index(self):
        from teambrain.query import query
        result = query(self.cfg, "every incident gets a written postmortem within five working days")
        self.assertEqual(result["status"], "ok")
        self.assertIn("wiki/eng/principles.md", result["text"])


if __name__ == "__main__":
    unittest.main()
