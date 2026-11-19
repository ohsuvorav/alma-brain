"""brain wip: snapshot to a local branch without touching the user's branch or index; refuses secrets."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from teambrain import config as cfgmod
from teambrain import wip

# Built by concatenation so this file never trips the scanner itself.
FAKE_TOKEN = "xox" + "b-" + "1234567890-abcdefghij"
FAKE_EMAIL = "jane.doe" + "@" + "acme-corp.test"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


class WipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "tester@example.com")
        git(self.root, "config", "user.name", "Tester")
        (self.root / "teambrain.yaml").write_text("name: demo\n")
        (self.root / ".gitignore").write_text("raw/\n")
        (self.root / "wiki").mkdir()
        (self.root / "wiki" / "a.md").write_text("# A\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        self.cfg = cfgmod.Config(self.root)
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def snap(self, **kw):
        return wip.snapshot(self.cfg, out=self.lines.append, **kw)

    def test_nothing_to_commit(self):
        self.assertEqual(self.snap(), 0)
        self.assertIn("nothing to commit", self.lines[-1])
        self.assertEqual(git(self.root, "branch", "--list", "wip/*"), "")

    def test_snapshot_leaves_branch_and_index_alone(self):
        (self.root / "wiki" / "a.md").write_text("# A\nedited\n")
        (self.root / "wiki" / "b.md").write_text("# B\n")
        git(self.root, "add", "wiki/b.md")  # the user's own staging must survive
        (self.root / "raw").mkdir()
        (self.root / "raw" / "private.md").write_text("ignored\n")
        head = git(self.root, "rev-parse", "HEAD")

        self.assertEqual(self.snap(), 0)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        self.assertEqual(git(self.root, "diff", "--cached", "--name-only"), "wiki/b.md")
        files = git(self.root, "ls-tree", "-r", "--name-only", "wip/tester").splitlines()
        self.assertIn("wiki/b.md", files)
        self.assertNotIn("raw/private.md", files)
        self.assertEqual(git(self.root, "show", "wip/tester:wiki/a.md"), "# A\nedited")
        self.assertEqual(git(self.root, "rev-parse", "wip/tester^"), head)

        # Second run with no new edits: no new commit.
        tip = git(self.root, "rev-parse", "wip/tester")
        self.assertEqual(self.snap(), 0)
        self.assertEqual(git(self.root, "rev-parse", "wip/tester"), tip)

    def test_refuses_secret_and_foreign_email(self):
        (self.root / "wiki" / "c.md").write_text(f"token {FAKE_TOKEN}\ncontact {FAKE_EMAIL}\n")
        self.assertEqual(self.snap(), 2)
        out = "\n".join(self.lines)
        self.assertIn("possible secrets", out)
        self.assertIn(FAKE_EMAIL, out)
        self.assertEqual(git(self.root, "branch", "--list", "wip/*"), "")

    def test_allowed_domain_passes(self):
        self.cfg = cfgmod.Config(self.root, {"wip": {"allow_email_domains": ["acme-corp.test"]}})
        (self.root / "wiki" / "c.md").write_text(f"contact {FAKE_EMAIL}\n")
        self.assertEqual(self.snap(), 0)

    def test_scan_ignores_removed_lines(self):
        diff = f"--- a/x\n+++ b/x\n-{FAKE_TOKEN}\n+clean line\n"
        self.assertEqual(wip.scan(diff, []), ([], []))

    def test_engine_source_does_not_trip_itself(self):
        src = Path(wip.__file__).read_text()
        diff = "\n".join("+" + l for l in src.splitlines())
        self.assertEqual(wip.scan(diff, []), ([], []))

    def test_allow_list_is_domain_suffix_not_substring(self):
        allow = ["example.com", "noreply", "localhost"]
        for addr in ("user@notexample.com", "user@example.com.evil.test", "a@noreply.evil.test"):
            _, emails = wip.scan("+" + addr + "\n", allow)
            self.assertEqual(emails, [addr], addr)
        _, emails = wip.scan("+user@example.com\n+dev@a.example.com\n+x@box.localhost\n", allow)
        self.assertEqual(emails, [])

    def test_refuses_when_wip_branch_is_checked_out(self):
        (self.root / "wiki" / "a.md").write_text("# A\none\n")
        self.assertEqual(self.snap(), 0)
        git(self.root, "checkout", "-f", "wip/tester")
        (self.root / "wiki" / "a.md").write_text("# A\none\ntwo\n")
        tip = git(self.root, "rev-parse", "wip/tester")
        main = git(self.root, "rev-parse", "main")
        self.lines.clear()
        self.assertEqual(self.snap(), 2)
        self.assertIn("checked out", self.lines[-1])
        self.assertEqual(git(self.root, "rev-parse", "wip/tester"), tip)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), tip)
        self.assertEqual(git(self.root, "rev-parse", "main"), main)

    def test_non_utf8_snapshot_does_not_crash(self):
        (self.root / "wiki" / "a.md").write_bytes(b"# A\ncaf\xe9\n")
        self.assertEqual(self.snap(), 0)
        self.assertTrue(git(self.root, "rev-parse", "--verify", "wip/tester"))

    def test_oversize_file_is_refused_before_diff_decode(self):
        self.cfg = cfgmod.Config(self.root, {"wip": {"max_file_mb": 0.001}})
        (self.root / "wiki" / "big.md").write_bytes(b"\xe9" * 20000)
        self.assertEqual(self.snap(), 2)
        self.assertIn("files over", "\n".join(self.lines))
        self.assertEqual(git(self.root, "branch", "--list", "wip/*"), "")

    def test_ambient_git_env_does_not_redirect_snapshot(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(other)], check=False))
        git(other, "init", "-q", "-b", "main")
        git(other, "config", "user.email", "other@example.com")
        git(other, "config", "user.name", "Other")
        (other / "other.txt").write_text("other\n")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "init")
        (self.root / "wiki" / "a.md").write_text("# A\nchanged\n")
        saved = os.environ.copy()
        os.environ["GIT_DIR"] = str(other / ".git")
        os.environ["GIT_WORK_TREE"] = str(other)
        os.environ["GIT_INDEX_FILE"] = str(other / "index")
        os.environ["GIT_COMMON_DIR"] = str(other / ".git")
        try:
            rc = self.snap()
        finally:
            os.environ.clear()
            os.environ.update(saved)
        self.assertEqual(rc, 0)
        self.assertTrue(git(self.root, "rev-parse", "--verify", "wip/tester"))
        self.assertEqual(git(self.root, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(git(other, "branch", "--list", "wip/*"), "")
        self.assertEqual(git(other, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
