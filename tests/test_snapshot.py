"""`brain snapshot`: local history for a git-ignored folder (shell, no Python venv needed)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "bin" / "brain"


@unittest.skipUnless(shutil.which("git"), "git not installed")
class SnapshotTest(unittest.TestCase):
    def run_snapshot(self, root, *args):
        env = {**os.environ, "BRAIN_ROOT": str(root)}
        return subprocess.run([str(BRAIN), "snapshot", *args], env=env, capture_output=True, text=True)

    def test_creates_history_and_skips_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "teambrain.yaml").write_text("name: snap\n")
            (Path(d) / "raw").mkdir()
            (Path(d) / "raw" / "note.md").write_text("one\n")
            self.assertIn("saved", self.run_snapshot(d).stdout)
            self.assertIn("no changes", self.run_snapshot(d).stdout)
            (Path(d) / "raw" / "note.md").write_text("two\n")
            self.run_snapshot(d)
            log = subprocess.run(["git", "-C", str(Path(d) / "raw"), "log", "--oneline"],
                                 capture_output=True, text=True).stdout
            self.assertEqual(len(log.strip().splitlines()), 2)

    def test_refuses_a_folder_with_a_remote(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "teambrain.yaml").write_text("name: snap\n")
            raw = Path(d) / "raw"
            raw.mkdir()
            subprocess.run(["git", "-C", str(raw), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(raw), "remote", "add", "origin", "https://example.invalid/x.git"], check=True)
            r = self.run_snapshot(d)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("refusing", r.stderr)

    def test_refuses_escape_symlink_worktree_and_foreign_git_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "brain"
            outside = Path(d) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "teambrain.yaml").write_text("name: snap\n")
            (outside / "note.md").write_text("kept\n")
            escaped = self.run_snapshot(root, "../outside")
            self.assertNotEqual(escaped.returncode, 0)
            self.assertFalse((outside / ".git").exists())
            self.assertIn("refusing", escaped.stderr)

            (root / "raw").symlink_to(outside, target_is_directory=True)
            linked = self.run_snapshot(root)
            self.assertNotEqual(linked.returncode, 0)
            self.assertFalse((outside / ".git").exists())
            self.assertIn("refusing", linked.stderr)

        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / "mainrepo"
            brain = Path(d) / "brain"
            main.mkdir()
            brain.mkdir()
            (brain / "teambrain.yaml").write_text("name: snap\n")
            env = {**os.environ, "GIT_AUTHOR_NAME": "snapshot", "GIT_AUTHOR_EMAIL": "snapshot@localhost",
                   "GIT_COMMITTER_NAME": "snapshot", "GIT_COMMITTER_EMAIL": "snapshot@localhost"}
            subprocess.run(["git", "-C", str(main), "init", "-q"], check=True)
            (main / "base.txt").write_text("base\n")
            subprocess.run(["git", "-C", str(main), "add", "base.txt"], check=True)
            subprocess.run(["git", "-C", str(main), "commit", "-q", "-m", "base"], check=True, env=env)
            subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(brain / "raw"), "HEAD"], check=True)
            before = subprocess.run(["git", "-C", str(brain / "raw"), "rev-list", "--count", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
            refused = self.run_snapshot(brain)
            after = subprocess.run(["git", "-C", str(brain / "raw"), "rev-list", "--count", "HEAD"],
                                   capture_output=True, text=True, check=True).stdout.strip()
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(before, after)
            self.assertIn("refusing", refused.stderr)

        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "brain"
            other = Path(d) / "other"
            root.mkdir()
            other.mkdir()
            (root / "teambrain.yaml").write_text("name: snap\n")
            (root / "raw").mkdir()
            (root / "raw" / "note.md").write_text("one\n")
            env = {**os.environ, "GIT_AUTHOR_NAME": "snapshot", "GIT_AUTHOR_EMAIL": "snapshot@localhost",
                   "GIT_COMMITTER_NAME": "snapshot", "GIT_COMMITTER_EMAIL": "snapshot@localhost"}
            subprocess.run(["git", "-C", str(other), "init", "-q"], check=True)
            (other / "keep.txt").write_text("keep\n")
            subprocess.run(["git", "-C", str(other), "add", "keep.txt"], check=True)
            subprocess.run(["git", "-C", str(other), "commit", "-q", "-m", "keep"], check=True, env=env)
            before = subprocess.run(["git", "-C", str(other), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
            run = subprocess.run([str(BRAIN), "snapshot"], env={**os.environ, "BRAIN_ROOT": str(root),
                                 "GIT_DIR": str(other / ".git")}, capture_output=True, text=True)
            after = subprocess.run(["git", "-C", str(other), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(before, after)
            self.assertTrue((root / "raw" / ".git" / "brain-snapshot").is_file())


if __name__ == "__main__":
    unittest.main()
