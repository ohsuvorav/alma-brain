"""brain init: copy a folder, import a memory dump, and refuse to invent a brain."""
import argparse
import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from teambrain import init as initmod


class InitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "TEAMBRAIN_CURRENT": str(self.root / "current"),
            "ALMA_HOME": str(self.root / "should-not-exist"),
        }, clear=False)
        self.env.start()
        for key in ("BRAIN_ROOT", "SECOND_BRAIN_DIR", "BRAIN_STATE_DIR"):
            os.environ.pop(key, None)
        self.index = mock.patch("teambrain.index.build_index", return_value=1)
        self.build = self.index.start()
        self._sched_patch = mock.patch("teambrain.schedule.install", return_value=0)
        self.install_jobs = self._sched_patch.start()
        self._claude_patch = mock.patch("teambrain.init.claude_project_pattern", return_value=None)
        self._claude_patch.start()
        self._detected = mock.patch("teambrain.connect.claude_detected", return_value=False)
        self._detected.start()

    def tearDown(self):
        self.index.stop()
        self.env.stop()
        if self._sched_patch is not None:
            self._sched_patch.stop()
        self._claude_patch.stop()
        self._detected.stop()
        self.tmp.cleanup()

    def notes(self, name="Notes"):
        src = self.root / name
        (src / "meetings").mkdir(parents=True)
        (src / "meetings" / "monday.md").write_text("# Monday\n\nShip the notes importer.\n")
        (src / "tea.md").write_text("# Tea\n\nEvening tea is ivan-chai.\n")
        (src / "node_modules").mkdir()
        (src / "node_modules" / "skip.md").write_text("# Skip\n")
        (src / ".secret.md").write_text("# Hidden\n")
        return src

    def test_copies_folder_and_writes_yaml(self):
        src = self.notes()
        brain = self.root / "brain"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = initmod.main(["--yes", "--brain", str(brain), str(src)])
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("2 files", out)
        self.assertIn("meetings", out)
        copied = brain / "raw" / "imports" / "notes" / "meetings" / "monday.md"
        self.assertEqual(copied.read_text(), "# Monday\n\nShip the notes importer.\n")
        self.assertFalse((brain / "raw" / "imports" / "notes" / "node_modules").exists())
        self.assertFalse((brain / "raw" / "imports" / "notes" / ".secret.md").exists())
        self.assertIn("name: alma", (brain / "teambrain.yaml").read_text())
        self.assertTrue((brain / "wiki").is_dir())
        self.assertEqual((self.root / "current").read_text().strip(), str(brain.resolve()))
        self.build.assert_called_once()

    def test_memory_dump_lands_in_raw_imports_memory(self):
        dump = self.root / "memory.txt"
        dump.write_text("User likes tea in the evening.\n")
        brain = self.root / "brain"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = initmod.main(["--yes", "--brain", str(brain), str(dump)])
        self.assertEqual(code, 0)
        self.assertIn("1 file", buf.getvalue())
        saved = brain / "raw" / "imports" / "memory" / "memory.txt"
        self.assertEqual(saved.read_text(), dump.read_text())

    def test_obsidian_preview_names_the_vault(self):
        src = self.notes("Vault")
        (src / ".obsidian").mkdir()
        text = initmod.format_preview(initmod.inspect_source(src))
        self.assertIn("Obsidian vault", text)
        self.assertIn("meetings", text)

    def test_no_source_creates_nothing(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = initmod.main([], stdin=io.StringIO(""))
        self.assertEqual(code, 2)
        self.assertIn("brain init <path>", buf.getvalue())
        self.assertFalse((self.root / "should-not-exist").exists())
        self.build.assert_not_called()

    def test_empty_folder_does_not_create_a_brain(self):
        empty = self.root / "empty"
        empty.mkdir()
        brain = self.root / "brain"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = initmod.main(["--yes", "--brain", str(brain), str(empty)])
        self.assertEqual(code, 2)
        self.assertFalse((brain / "teambrain.yaml").exists())
        self.assertIn("No markdown", buf.getvalue())
        self.build.assert_not_called()

    def test_without_yes_does_not_copy(self):
        src = self.notes()
        brain = self.root / "brain"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = initmod.main([str(src), "--brain", str(brain)], stdin=io.StringIO(""))
        self.assertEqual(code, 2)
        self.assertIn("2 files", buf.getvalue())
        self.assertIn("--yes", buf.getvalue())
        self.assertFalse((brain / "teambrain.yaml").exists())
        self.build.assert_not_called()

    def test_in_place_records_the_folder(self):
        import yaml
        src = self.notes()
        brain = self.root / "brain"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = initmod.main(["--yes", "--in-place", "--brain", str(brain), str(src)])
        self.assertEqual(code, 0)
        self.assertIn("Indexing in place", buf.getvalue())
        self.assertFalse((brain / "raw" / "imports" / "notes").exists())
        data = yaml.safe_load((brain / "teambrain.yaml").read_text())
        self.assertEqual(data["index"]["extra_dirs"][0]["path"], str(src.resolve()))


class ScheduleInitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "TEAMBRAIN_CURRENT": str(self.root / "current"),
            "ALMA_HOME": str(self.root / "should-not-exist"),
        }, clear=False)
        self.env.start()
        for key in ("BRAIN_ROOT", "SECOND_BRAIN_DIR", "BRAIN_STATE_DIR"):
            os.environ.pop(key, None)
        self.index = mock.patch("teambrain.index.build_index", return_value=1)
        self.index.start()
        self.claude = mock.patch("teambrain.init.claude_project_pattern", return_value=None)
        self.claude.start()
        self.detected = mock.patch("teambrain.connect.claude_detected", return_value=False)
        self.detected.start()

    def tearDown(self):
        self.detected.stop()
        self.claude.stop()
        self.index.stop()
        self.env.stop()
        self.tmp.cleanup()

    def notes(self):
        src = self.root / "Notes"
        src.mkdir()
        (src / "tea.md").write_text("# Tea\n\nEvening tea is ivan-chai.\n")
        return src

    def jobs(self, brain):
        import yaml
        data = yaml.safe_load((brain / "teambrain.yaml").read_text())
        return data["schedule"]["jobs"]

    def test_defaults_are_written_and_yes_installs_them(self):
        brain = self.root / "brain"
        with mock.patch("teambrain.schedule.install", return_value=0) as install:
            code = initmod.main(["--yes", "--brain", str(brain), str(self.notes())])
        self.assertEqual(code, 0)
        names = [job["name"] for job in self.jobs(brain)]
        self.assertEqual(names, ["index", "lint", "snapshot"])
        self.assertEqual(self.jobs(brain)[0]["run"], "index --incremental")
        self.assertEqual(self.jobs(brain)[0]["at"], "03:15")
        text = (brain / "teambrain.yaml").read_text()
        self.assertIn("retro run", text)
        self.assertIn("Codex", text)
        install.assert_called_once()

    def test_claude_project_adds_retro_and_chat_capture(self):
        brain = self.root / "brain"
        pattern = "/tmp/claude-project/*.jsonl"
        with mock.patch("teambrain.schedule.install", return_value=0), \
             mock.patch("teambrain.init.claude_project_pattern", return_value=pattern):
            code = initmod.main(["--no-schedule", "--yes", "--brain", str(brain), str(self.notes())])
        self.assertEqual(code, 0)
        import yaml
        data = yaml.safe_load((brain / "teambrain.yaml").read_text())
        self.assertEqual([job["name"] for job in data["schedule"]["jobs"]],
                         ["index", "lint", "snapshot", "retro"])
        self.assertTrue(data["index"]["chats"]["enabled"])
        self.assertEqual(data["index"]["chats"]["glob"], pattern)
        self.assertTrue(data["retro"]["enabled"])
        self.assertEqual(data["retro"]["transcripts"], pattern)

    def test_no_schedule_skips_install(self):
        brain = self.root / "brain"
        buf = io.StringIO()
        with mock.patch("teambrain.schedule.install", return_value=0) as install, redirect_stdout(buf):
            code = initmod.main(["--yes", "--no-schedule", "--brain", str(brain), str(self.notes())])
        self.assertEqual(code, 0)
        install.assert_not_called()
        self.assertIn("--no-schedule", buf.getvalue())
        self.assertEqual(len(self.jobs(brain)), 3)

    def test_missing_scheduler_still_exits_zero(self):
        from teambrain.schedule import SchedulerMissing
        brain = self.root / "brain"
        buf = io.StringIO()
        with mock.patch("teambrain.schedule.install", side_effect=SchedulerMissing("crontab")), \
             redirect_stdout(buf):
            code = initmod.main(["--yes", "--brain", str(brain), str(self.notes())])
        self.assertEqual(code, 0)
        self.assertIn("brain schedule install", buf.getvalue())
        self.assertIn("Next: open Claude Code", buf.getvalue())

    def test_rerun_does_not_duplicate_jobs(self):
        brain = self.root / "brain"
        src = self.notes()
        crontab = {"": ""}

        def write(text):
            crontab[""] = text

        with mock.patch("teambrain.schedule._is_mac", return_value=False), \
             mock.patch("teambrain.schedule._cron_read", side_effect=lambda: crontab[""]), \
             mock.patch("teambrain.schedule._cron_write", side_effect=write):
            self.assertEqual(initmod.main(["--yes", "--brain", str(brain), str(src)]), 0)
            first = crontab[""]
            self.assertEqual(initmod.main(["--yes", "--brain", str(brain), str(src)]), 0)
        self.assertEqual(crontab[""], first)
        self.assertEqual(first.count("# >>>"), 1)
        self.assertEqual(first.count("index --incremental"), 1)
        self.assertEqual(len(self.jobs(brain)), 3)

    def test_enter_installs_and_n_skips(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        cfg = mock.Mock()
        args = argparse.Namespace(yes=False, no_schedule=False)
        buf = io.StringIO()
        with mock.patch("teambrain.schedule.install", return_value=0) as install, redirect_stdout(buf):
            initmod.maybe_install_schedule(cfg, args, Tty("\n"))
        self.assertIn(
            "Install nightly jobs (index, stale-doc check, ...) via launchd/cron? [Y/n]",
            buf.getvalue(),
        )
        install.assert_called_once_with(cfg)
        buf = io.StringIO()
        with mock.patch("teambrain.schedule.install", return_value=0) as install, redirect_stdout(buf):
            initmod.maybe_install_schedule(cfg, args, Tty("n\n"))
        install.assert_not_called()
        self.assertIn("Nightly jobs not installed.", buf.getvalue())

    def test_yes_connects_claude_code(self):
        brain = self.root / "brain"
        with mock.patch("teambrain.connect.claude_detected", return_value=True), \
             mock.patch("teambrain.connect.install", return_value=True) as install, \
             mock.patch("teambrain.schedule.install", return_value=0):
            code = initmod.main(["--yes", "--brain", str(brain), str(self.notes())])
        self.assertEqual(code, 0)
        install.assert_called_once()

    def test_no_connect_skips(self):
        brain = self.root / "brain"
        buf = io.StringIO()
        with mock.patch("teambrain.connect.install", return_value=True) as install, \
             mock.patch("teambrain.schedule.install", return_value=0), \
             redirect_stdout(buf):
            code = initmod.main(["--yes", "--no-connect", "--brain", str(brain), str(self.notes())])
        self.assertEqual(code, 0)
        install.assert_not_called()
        self.assertIn("--no-connect", buf.getvalue())
        self.assertNotIn(".cursor/mcp.json", buf.getvalue())

    def test_missing_claude_prints_one_line_and_exits_zero(self):
        brain = self.root / "brain"
        buf = io.StringIO()
        with mock.patch("teambrain.connect.install", return_value=True) as install, \
             mock.patch("teambrain.schedule.install", return_value=0), \
             redirect_stdout(buf):
            code = initmod.main(["--yes", "--brain", str(brain), str(self.notes())])
        self.assertEqual(code, 0)
        install.assert_not_called()
        out = buf.getvalue()
        self.assertIn("Claude Code was not found", out)
        self.assertIn(".cursor/mcp.json", out)
        self.assertIn("config.toml", out)
        self.assertEqual(out.count("\nClaude Code was not found"), 1)

    def test_enter_connects_and_n_skips(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        cfg = mock.Mock()
        cfg.root = self.root
        args = argparse.Namespace(yes=False, no_connect=False)
        buf = io.StringIO()
        with mock.patch("teambrain.connect.claude_detected", return_value=True), \
             mock.patch("teambrain.connect.install", return_value=True) as install, \
             redirect_stdout(buf):
            initmod.maybe_connect(cfg, args, Tty("\n"))
        self.assertIn("Connect Alma to Claude Code (MCP + prompt hook)? [Y/n]", buf.getvalue())
        install.assert_called_once_with(cfg)
        buf = io.StringIO()
        with mock.patch("teambrain.connect.install", return_value=True) as install, \
             redirect_stdout(buf):
            initmod.maybe_connect(cfg, args, Tty("n\n"))
        install.assert_not_called()
        self.assertIn("Claude Code not connected.", buf.getvalue())


class PromptTest(unittest.TestCase):
    def test_enter_copies(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        scan = {"kind": "folder", "name": "notes", "files": 2, "bytes": 10, "top_folders": ["travel"]}
        buf = io.StringIO()
        with redirect_stdout(buf):
            mode = initmod.choose_mode(scan, Path("/tmp/brain"), "notes",
                                       argparse.Namespace(yes=False, in_place=False), Tty("\n"))
        self.assertEqual(mode, "copy")
        self.assertIn("Press Enter to copy", buf.getvalue())


class TxtNotesTest(unittest.TestCase):
    def test_txt_notes_are_collected_when_wiki_is_empty(self):
        import tempfile
        from teambrain import config as cfgmod
        from teambrain.index import collect_files
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "teambrain.yaml").write_text("name: t\n")
            (root / "wiki").mkdir()
            (root / "raw" / "imports" / "memory").mkdir(parents=True)
            (root / "raw" / "imports" / "memory" / "memory.txt").write_text("Tea in the evening.\n")
            names = [p.name for p, _ in collect_files(cfgmod.Config(root))]
        self.assertEqual(names, ["memory.txt"])
