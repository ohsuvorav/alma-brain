"""Retro digest, ledger and the unattended run, on the synthetic transcript. `claude` is mocked."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from teambrain import config as cfgmod
from teambrain import retro

FIXTURE = Path(__file__).parent / "fixture-brain"
TRANSCRIPTS = Path(__file__).parent / "fixture-transcripts"


class RetroTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self.tmp.name) / "brain"
        shutil.copytree(FIXTURE, self.brain)
        self.env = mock.patch.dict(os.environ, {"BRAIN_STATE_DIR": str(Path(self.tmp.name) / "state"), "TZ": "UTC"})
        self.env.start()
        time.tzset()
        os.environ.pop("BRAIN_ROOT", None)
        self.cfg = cfgmod.Config(self.brain, {"retro": {
            "enabled": True,
            "transcripts": str(TRANSCRIPTS / "demo-project" / "*.jsonl"),
        }})

    def tearDown(self):
        self.env.stop()
        time.tzset()
        self.tmp.cleanup()

    def test_digest_is_cut_at_the_day_and_labels_typed_text(self):
        text, n = retro.build_digest(self.cfg, "2026-01-05")
        self.assertEqual(n, 1)
        self.assertIn("**[01-05 09:02] USER:** 63% of what?", text)
        self.assertIn("_assistant before:_", text)
        self.assertIn("INTERRUPT", text)
        self.assertNotIn("next day", text)

    def test_mark_then_only_new_days_remain(self):
        self.assertEqual(retro.mark(self.cfg, "2026-01-05"), 1)
        self.assertEqual(retro.build_digest(self.cfg, "2026-01-05")[1], 0)
        text, n = retro.build_digest(self.cfg, "2026-01-06")
        self.assertEqual(n, 1)
        self.assertIn("next day", text)
        self.assertNotIn("63% of what", text)

    def test_run_marks_only_when_daily_file_written(self):
        def fake_claude(cmd, **kw):
            self.assertIn("--restricted", cmd)
            tools = cmd[cmd.index("--tools") + 1].split(",")
            self.assertIn("Edit", tools)
            self.assertNotIn("Bash", tools)
            self.assertEqual(cmd[cmd.index("--disallowedTools") + 1], "Bash")
            self.assertNotIn("--allowedTools", cmd)
            self.assertEqual(Path(kw["cwd"]).resolve(), (self.brain / "wiki/claude-retro").resolve())
            self.assertIn("DATE: 2026-01-05", " ".join(cmd))
            return SimpleNamespace(returncode=0)

        out = retro.run(self.cfg, "2026-01-05", runner=fake_claude)
        self.assertTrue(out["status"].startswith("failed"))  # nothing written → nothing marked
        self.assertEqual(retro.build_digest(self.cfg, "2026-01-05")[1], 1)

        def writing_claude(cmd, **kw):
            (self.brain / "wiki/claude-retro/daily/2026-01-05.md").write_text("# Retro\n")
            return SimpleNamespace(returncode=0)

        out = retro.run(self.cfg, "2026-01-05", runner=writing_claude)
        self.assertEqual(out["status"], "written")
        self.assertEqual(retro.build_digest(self.cfg, "2026-01-05")[1], 0)

    def test_preexisting_or_symlink_daily_does_not_mark(self):
        daily = self.brain / "wiki/claude-retro/daily/2026-01-05.md"
        daily.parent.mkdir(parents=True)
        daily.write_text("OLD\n")

        def noop(cmd, **kw):
            return SimpleNamespace(returncode=0)

        out = retro.run(self.cfg, "2026-01-05", runner=noop)
        self.assertTrue(out["status"].startswith("failed"))
        self.assertEqual(daily.read_text(), "OLD\n")
        self.assertEqual(retro.build_digest(self.cfg, "2026-01-05")[1], 1)

        daily.unlink()
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("OUTSIDE\n")
        daily.symlink_to(outside)
        called = []

        def unexpected(cmd, **kw):
            called.append(1)
            return SimpleNamespace(returncode=0)

        out = retro.run(self.cfg, "2026-01-05", runner=unexpected)
        self.assertEqual(called, [])
        self.assertIn("symlink", out["status"])
        self.assertEqual(outside.read_text(), "OUTSIDE\n")
        self.assertEqual(retro.build_digest(self.cfg, "2026-01-05")[1], 1)

    def test_disabled_or_broad_transcripts_are_not_read(self):
        home = Path(self.tmp.name) / "home"
        for name in ("proj-a", "proj-b"):
            d = home / ".claude/projects" / name
            d.mkdir(parents=True)
            (d / "s.jsonl").write_text(
                '{"type":"user","timestamp":"2026-01-05T09:00:00Z","origin":{"kind":"human"},'
                '"message":{"role":"user","content":"MARKER_%s typed a long note"}}\n' % name
            )
        disabled = cfgmod.Config(self.brain)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            text, n = retro.build_digest(disabled, "2026-01-05")
            called = []
            out = retro.run(disabled, "2026-01-05", runner=lambda *a, **k: called.append(1))
        self.assertEqual(n, 0)
        self.assertNotIn("MARKER_", text)
        self.assertEqual(called, [])
        self.assertEqual(out["status"], "transcripts disabled")

        broad = cfgmod.Config(self.brain, {"retro": {
            "enabled": True, "transcripts": "~/.claude/projects/*/*.jsonl",
        }})
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            text, n = retro.build_digest(broad, "2026-01-05")
            called = []
            out = retro.run(broad, "2026-01-05", runner=lambda *a, **k: called.append(1))
        self.assertEqual(n, 0)
        self.assertNotIn("MARKER_", text)
        self.assertEqual(called, [])
        self.assertIn("refused", out["status"])

        narrow = cfgmod.Config(self.brain, {"retro": {
            "enabled": True,
            "transcripts": str(home / ".claude/projects/proj-a/*.jsonl"),
        }})
        text, n = retro.build_digest(narrow, "2026-01-05")
        self.assertEqual(n, 1)
        self.assertIn("MARKER_proj-a", text)
        self.assertNotIn("MARKER_proj-b", text)


if __name__ == "__main__":
    unittest.main()
