"""brain doctor: one failing check prints what is wrong and a fix command."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import doctor


class DoctorTest(unittest.TestCase):
    def test_one_failing_check_prints_a_fix_line(self):
        checks = [doctor.Check(False, "index missing", "brain index")]
        text = doctor.format_report(checks)
        self.assertIn("fail  index missing\n", text)
        self.assertIn("fix: brain index\n", text)
        self.assertEqual(doctor.exit_code(checks), 1)
        self.assertNotIn("brain doctor: ok", text)

    def test_connection_is_optional_until_installed(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            home.mkdir()
            root = Path(d) / "brain"
            root.mkdir()
            (root / "teambrain.yaml").write_text("name: doctor-fixture\n")
            cfg = cfgmod.Config(root)
            with mock.patch("teambrain.connect.Path.home", return_value=home):
                mcp = doctor.mcp_status(cfg)
                hook = doctor.prompt_hook_status(cfg)
            self.assertTrue(mcp.ok and hook.ok)
            self.assertEqual(mcp.detail, "mcp not connected (optional)")
            self.assertEqual(hook.detail, "prompt hook not installed (optional)")
            text = doctor.format_report([mcp, hook])
            self.assertIn("ok    mcp not connected (optional)\n", text)
            self.assertIn("fix: brain init --yes <path-to-notes>\n", text)
            self.assertIn("brain doctor: ok", text)
            self.assertEqual(doctor.exit_code([mcp, hook]), 0)
            (home / ".claude").mkdir()
            (home / ".claude.json").write_text(json.dumps({
                "mcpServers": {"alma": {"command": "brain", "args": ["mcp"], "env": {}}},
            }))
            (home / ".claude" / "settings.json").write_text(json.dumps({
                "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "brain hook-search"}]}]},
            }))
            with mock.patch("teambrain.connect.Path.home", return_value=home):
                mcp = doctor.mcp_status(cfg)
                hook = doctor.prompt_hook_status(cfg)
        self.assertEqual(mcp.detail, "mcp connected (claude)")
        self.assertEqual(hook.detail, "prompt hook installed")

    def test_optional_status_stays_green(self):
        checks = [doctor.Check(True, "hooks not installed (optional)")]
        self.assertEqual(doctor.exit_code(checks), 0)
        self.assertIn("brain doctor: ok", doctor.format_report(checks))

    def test_missing_index_on_a_brain_has_a_fix(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "teambrain.yaml").write_text("name: doctor-fixture\n")
            (root / "wiki").mkdir()
            (root / "raw").mkdir()
            cfg = cfgmod.Config(root)
            with mock.patch("teambrain.doctor.model_cached", return_value=True):
                checks = doctor.diagnose(cfg)
            text = doctor.format_report(checks)
            failed = [c for c in checks if not c.ok]
            self.assertTrue(failed)
            for check in failed:
                self.assertTrue(check.fix)
                self.assertIn("fail  " + check.detail, text)
                self.assertIn("fix: " + check.fix, text)
            index = [c for c in failed if c.detail == "index missing"]
            self.assertEqual(len(index), 1)
            self.assertEqual(index[0].fix, "brain index")
            self.assertNotEqual(doctor.exit_code(checks), 0)

    def test_scheduler_counts_installed_jobs(self):
        import tempfile
        from teambrain import config as cfgmod
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "teambrain.yaml").write_text("name: doctor-fixture\n")
            cfg = cfgmod.Config(root)
            block = (
                "# >>> teambrain.doctor-fixture (managed by brain schedule)\n"
                "15 3 * * * echo index\n"
                "30 2 * * * echo lint\n"
                "45 2 * * * echo snapshot\n"
                "# <<< teambrain.doctor-fixture (managed by brain schedule)\n"
            )
            with mock.patch("teambrain.schedule._is_mac", return_value=False), \
                 mock.patch("teambrain.schedule._cron_read", return_value=block):
                check = doctor.scheduler_status(cfg)
        self.assertTrue(check.ok)
        self.assertEqual(check.detail, "scheduler installed (3 jobs)")
        self.assertIn("ok    scheduler installed (3 jobs)\n", doctor.format_report([check]))

    def test_fix_line_notes_when_brain_is_not_on_path(self):
        checks = [doctor.Check(False, "embedding model not downloaded (example)", "brain index")]
        with mock.patch("teambrain.doctor.shutil.which", return_value=None):
            text = doctor.format_report(checks)
        self.assertIn("fix: brain index\n", text)
        self.assertIn("not on PATH", text)
        self.assertTrue(text.strip().endswith("brain doctor: 1 problem"))

    def test_missing_venv_fix_is_setup(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"TEAMBRAIN_VENV": d + "/nope"}):
            check = doctor.venv_status()
        self.assertFalse(check.ok)
        self.assertIn("venv missing", check.detail)
        self.assertEqual(check.fix, "brain setup")
