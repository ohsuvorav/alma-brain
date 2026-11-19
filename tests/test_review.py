"""brain review: keep, archive, and undo from stdin. Never deletes, never pushes."""
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import review


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
    ).stdout.strip()


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "teambrain.yaml").write_text("name: review-fixture\n")
        (self.root / "wiki").mkdir()
        (self.root / "raw").mkdir()
        self.cfg = cfgmod.Config(self.root)
        for key in ("BRAIN_ROOT", "SECOND_BRAIN_DIR"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.tmp.cleanup()

    def stale(self, rel="wiki/old.md", text="# Old plan (superseded by new-plan.md)\n\nBody.\n"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def play(self, script):
        with redirect_stdout(io.StringIO()):
            return review.run(self.cfg, stdin=io.StringIO(script), isatty=False)

    def test_skip_and_quit_are_acknowledged(self):
        self.stale()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = review.run(self.cfg, stdin=io.StringIO("skip\nquit\n"), isatty=False)
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Skipped.", out)
        self.assertIn("Done.", out)

    def test_archive_undo_and_keep(self):
        path = self.stale()
        original = path.read_text()
        self.assertEqual(self.play("archive\nundo\nkeep\nquit\n"), 0)
        self.assertEqual(path.read_text(), original)
        self.assertFalse((self.root / "wiki" / "_archive" / "old.md").exists())
        kept = review.load_kept(self.cfg)
        self.assertTrue(any(key.startswith("lint:wiki/old.md:") for key in kept))
        self.assertEqual(self.play("quit\n"), 0)  # kept, so it is not shown again

    def test_archive_moves_and_keeps_the_bytes(self):
        path = self.stale()
        original = path.read_text()
        self.assertEqual(self.play("archive\nquit\n"), 0)
        dest = self.root / "wiki" / "_archive" / "old.md"
        self.assertFalse(path.exists())
        self.assertEqual(dest.read_text(), original)

    def test_idle_folder_is_archived_not_deleted(self):
        folder = self.root / "raw" / "temp" / "old-topic"
        readme = folder / "README.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Old topic\n\nStill here.\n")
        old = time.time() - 30 * 86400
        os.utime(readme, (old, old))
        self.assertEqual(self.play("archive\nquit\n"), 0)
        dest = self.root / "raw" / "archive" / "temp" / "old-topic" / "README.md"
        self.assertFalse(folder.exists())
        self.assertEqual(dest.read_text(), "# Old topic\n\nStill here.\n")

    def test_suggestion_archive_and_undo(self):
        backlog = self.root / "_wiki_backlog.md"
        original = "# Backlog\n\n## [2026-01-02] candidate tea\nBrew ivan tea.\n"
        backlog.write_text(original)
        (self.root / "_system_backlog.md").write_text("# Backlog\n\n## Rejected\n- none\n")
        self.assertEqual(self.play("archive\nundo\nquit\n"), 0)
        self.assertEqual(backlog.read_text(), original)
        self.assertFalse((self.root / "raw" / "archive" / "suggestions.md").exists())

    def test_fix_then_undo_restores_the_file(self):
        path = self.stale()
        original = path.read_text()
        script = self.root / "edit.py"
        script.write_text(
            "import pathlib, sys\n"
            "p = pathlib.Path(sys.argv[1])\n"
            "pathlib.Path(str(p) + '.editlog').write_text('yes')\n"
            "p.write_text(p.read_text() + '\\nedited\\n')\n"
        )
        editor = f"{sys.executable} {script}"
        with mock.patch.dict(os.environ, {"EDITOR": editor}):
            self.assertEqual(self.play("fix\nundo\nquit\n"), 0)
        self.assertEqual(path.read_text(), original)
        self.assertEqual(Path(str(path) + ".editlog").read_text(), "yes")

    def test_noninteractive_archive_does_not_commit(self):
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "tester@example.com")
        git(self.root, "config", "user.name", "Tester")
        self.stale()
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        self.assertEqual(self.play("archive\nyes\nquit\n"), 0)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "init")
        self.assertFalse((self.root / "wiki" / "old.md").exists())

    def test_commit_only_on_yes_and_never_pushes(self):
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "tester@example.com")
        git(self.root, "config", "user.name", "Tester")
        (self.root / "wiki" / "note.md").write_text("# Note\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        (self.root / "wiki" / "note.md").write_text("# Note\n\nEdited.\n")
        calls = []
        real = subprocess.run

        def wrapped(args, **kwargs):
            calls.append(list(args))
            return real(args, **kwargs)

        with mock.patch("teambrain.review.subprocess.run", side_effect=wrapped), redirect_stdout(io.StringIO()):
            review.maybe_commit(self.cfg, "review: archive note", io.StringIO("no\n"), True)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "init")
        calls.clear()
        with mock.patch("teambrain.review.subprocess.run", side_effect=wrapped), redirect_stdout(io.StringIO()):
            review.maybe_commit(self.cfg, "review: archive note", io.StringIO("yes\n"), False)
        self.assertEqual(calls, [])
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "init")
        with mock.patch("teambrain.review.subprocess.run", side_effect=wrapped), redirect_stdout(io.StringIO()):
            review.maybe_commit(self.cfg, "review: archive note", io.StringIO("yes\n"), True)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "review: archive note")
        self.assertFalse(any("push" in cmd for cmd in calls))
