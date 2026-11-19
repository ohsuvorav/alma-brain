"""brain onboard, the SessionStart offer, schedule `when:` gating and suggest's PR links (no system changes)."""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import hooks, onboard, schedule, suggest

QUESTIONS = [
    {"id": "nightly", "ask": "Snapshot nightly?", "default": "y", "run": "touch ran-nightly", "undo": "touch undo-nightly"},
    {"id": "extras", "ask": "Extras?", "default": "n", "run": "touch ran-extras"},
]
JOBS = [{"name": "wip", "run": "wip", "at": "03:00", "when": "nightly"},
        {"name": "lint", "run": "lint", "at": "02:30"}]


class OnboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = cfgmod.Config(self.root, {"name": "demo", "onboarding": {"questions": QUESTIONS},
                                             "schedule": {"jobs": JOBS}})
        self.cfg.db_path.mkdir(parents=True)  # pretend the index exists
        self.installed = []

    def tearDown(self):
        self.tmp.cleanup()

    def onboard(self, replies):
        it = iter(replies)
        return onboard.run(self.cfg, interactive=True, inp=lambda _: next(it), out=lambda *_: None,
                           install_jobs=self.installed.append)

    def test_defaults_run_yes_commands_and_save(self):
        onboard.run(self.cfg, interactive=False, out=lambda *_: None, install_jobs=self.installed.append)
        self.assertTrue((self.root / "ran-nightly").exists())
        self.assertFalse((self.root / "ran-extras").exists())
        self.assertEqual(onboard.load_answers(self.cfg), {"nightly": True, "extras": False})
        self.assertEqual(len(self.installed), 1)

    def test_undo_only_after_previous_yes(self):
        self.onboard(["n", ""])
        self.assertFalse((self.root / "undo-nightly").exists())
        self.onboard(["y", ""])
        self.onboard(["n", ""])
        self.assertTrue((self.root / "undo-nightly").exists())
        self.assertEqual(onboard.load_answers(self.cfg)["nightly"], False)

    def test_failed_run_is_saved_as_no(self):
        cfg = cfgmod.Config(self.root, {"onboarding": {"questions": [
            {"id": "x", "ask": "X?", "default": "y", "run": "exit 3"}]}})
        onboard.run(cfg, interactive=False, out=lambda *_: None, install_jobs=lambda c: None)
        self.assertEqual(onboard.load_answers(cfg), {"x": False})

    def test_bad_questions_rejected(self):
        for bad in ([{"ask": "no id"}], [{"id": "a"}], [{"id": "a", "ask": "A"}, {"id": "a", "ask": "B"}],
                    [{"id": "a", "ask": "A", "default": "maybe"}]):
            with self.assertRaises(ValueError, msg=bad):
                onboard.questions(cfgmod.Config(self.root, {"onboarding": {"questions": bad}}))

    def test_schedule_when_gates_jobs(self):
        names = lambda ans: [j["name"] for j in schedule.jobs(self.cfg, path_env="/x", answers=ans)]
        self.assertEqual(names({}), ["lint"])
        self.assertEqual(names({"nightly": True}), ["wip", "lint"])
        bad = cfgmod.Config(self.root, {"schedule": {"jobs": [{"name": "a", "run": "wip", "at": "01:00", "when": "nope"}]}})
        with self.assertRaises(ValueError):
            schedule.jobs(bad, answers={})

    def test_interactive_commands_cannot_be_scheduled(self):
        for cmd in ("onboard", "suggest"):
            bad = cfgmod.Config(self.root, {"schedule": {"jobs": [{"name": "a", "run": cmd, "at": "01:00"}]}})
            with self.assertRaises(ValueError):
                schedule.jobs(bad, answers={})

    def test_session_start_offer(self):
        msg = hooks.session_start_message(self.cfg, "/e/bin/brain")
        self.assertIn("/e/bin/brain onboard", msg)
        onboard.run(self.cfg, interactive=False, out=lambda *_: None, install_jobs=lambda c: None)
        self.assertIsNone(hooks.session_start_message(self.cfg, "/e/bin/brain"))
        off = cfgmod.Config(self.root / "other", {"onboarding": {"offer": False}})
        self.assertIsNone(hooks.session_start_message(off, "/e/bin/brain"))

    def test_no_questions_and_index_present_is_silent(self):
        cfg = cfgmod.Config(self.root, {})
        self.assertIsNone(hooks.session_start_message(cfg, "/e/bin/brain"))
        empty = cfgmod.Config(self.root / "fresh", {})
        self.assertIn("no search index", hooks.session_start_message(empty, "/e/bin/brain"))

    def test_answers_file_is_json(self):
        onboard.run(self.cfg, interactive=False, out=lambda *_: None, install_jobs=lambda c: None)
        self.assertIn("ts", json.loads(onboard.answers_path(self.cfg).read_text()))

    def test_missing_scheduler_is_clean_and_hook_keeps_offering(self):
        lines = []
        with mock.patch("teambrain.schedule._scheduler", side_effect=schedule.SchedulerMissing("crontab")):
            rc = onboard.run(self.cfg, interactive=False, out=lines.append)
        text = "\n".join(lines)
        self.assertEqual(rc, 1)
        self.assertNotIn("Traceback", text)
        self.assertIn("not installed", text)
        self.assertIn("brain schedule install", text)
        self.assertEqual(onboard.load_answers(self.cfg)["nightly"], True)
        self.assertTrue(onboard.schedule_failed(self.cfg))
        msg = hooks.session_start_message(self.cfg, "/e/bin/brain")
        self.assertIn("schedule install", msg)
        self.assertNotIn("not set up for this person", msg)
        off = cfgmod.Config(self.root, {"name": "demo", "onboarding": {"offer": False, "questions": QUESTIONS}})
        self.assertIn("schedule install", hooks.session_start_message(off, "/e/bin/brain"))
        onboard.mark_schedule_install(self.cfg, "ok")
        self.assertIsNone(hooks.session_start_message(self.cfg, "/e/bin/brain"))


class SuggestTest(unittest.TestCase):
    def test_pr_urls(self):
        cases = {
            "git@github.com:acme/brain.git": "https://github.com/acme/brain/compare/main...suggest/x?expand=1",
            "https://github.com/acme/brain": "https://github.com/acme/brain/compare/main...suggest/x?expand=1",
            "git@bitbucket.org:acme/brain.git":
                "https://bitbucket.org/acme/brain/pull-requests/new?source=suggest/x&dest=main&t=1",
            "ssh://git@gitlab.com/acme/brain.git":
                "https://gitlab.com/acme/brain/-/merge_requests/new?merge_request[source_branch]=suggest/x"
                "&merge_request[target_branch]=main",
        }
        for remote, url in cases.items():
            self.assertEqual(suggest.pr_url(remote, "suggest/x", "main"), url, remote)
        self.assertIsNone(suggest.pr_url("my-alias:acme/brain.git", "suggest/x", "main"))

    def test_prompt_fills_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = suggest.prompt_text(cfgmod.Config(tmp, {"name": "demo", "suggest": {"max_changes": 3}}))
        self.assertIn("demo", text)
        self.assertIn("At most 3 changes", text)
        self.assertNotIn("{", text)

    def _brain(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        bare = Path(tmp.name) / "remote.git"
        root.mkdir()
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        for args in (["user.email", "tester@example.com"], ["user.name", "Tester"],
                     ["commit.gpgsign", "false"]):
            subprocess.run(["git", "-C", str(root), "config", *args], check=True)
        (root / "CLAUDE.md").write_text("# Rules\n")
        (root / ".gitignore").write_text(".brain/\n")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(bare)], check=True)
        subprocess.run(["git", "-C", str(root), "push", "-q", "-u", "origin", "main"], check=True)
        return root, bare

    def _stub(self, root, body):
        path = root.parent / "claude"
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return path

    def _cfg(self, root, stub):
        return cfgmod.Config(root, {"name": "demo", "suggest": {
            "base": "origin/main", "claude_bin": str(stub)}})

    def test_suggest_refuses_secret_and_does_not_push(self):
        root, bare = self._brain()
        token = "xox" + "b-" + "1234567890abcdefghij"
        stub = self._stub(root, f"""
cat > SUGGESTIONS.md << 'EOF'
# Suggestions
| change | source | why |
| --- | --- | --- |
| note | rules | team
EOF
printf '%s\\n' 'token {token}' > note.md
""")
        lines = []
        rc = suggest.run(self._cfg(root, stub), inp=lambda _: "y", out=lines.append)
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", "\n".join(lines))
        refs = subprocess.check_output(["git", "--git-dir", str(bare), "show-ref"], text=True)
        self.assertNotIn("suggest/", refs)

    def test_suggest_ignores_ambient_git_env_and_pushes_brain_repo(self):
        root, bare = self._brain()
        other = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(other)], check=False))
        subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
        stub = self._stub(root, """
cat > SUGGESTIONS.md << 'EOF'
# Suggestions
| change | source | why |
| --- | --- | --- |
| note | rules | team
EOF
printf '%s\\n' 'A generic team note.' > note.md
""")
        saved = os.environ.copy()
        os.environ["GIT_DIR"] = str(other / ".git")
        os.environ["GIT_WORK_TREE"] = str(other)
        os.environ["GIT_INDEX_FILE"] = str(other / "index")
        os.environ["GIT_COMMON_DIR"] = str(other / ".git")
        lines = []
        try:
            rc = suggest.run(self._cfg(root, stub), inp=lambda _: "y", out=lines.append)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        self.assertEqual(rc, 0, "\n".join(lines))
        refs = subprocess.check_output(["git", "--git-dir", str(bare), "show-ref"], text=True)
        self.assertIn("refs/heads/suggest/", refs)
        other_refs = subprocess.run(["git", "-C", str(other), "branch", "--list", "suggest/*"],
                                    capture_output=True, text=True, check=True).stdout
        self.assertEqual(other_refs.strip(), "")


if __name__ == "__main__":
    unittest.main()
