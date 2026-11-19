"""brain schedule: job validation, launchd plist and crontab block, without touching the system."""
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import schedule

JOBS = [{"name": "retro", "run": "retro run", "at": "01:00"},
        {"name": "index", "run": "index --incremental", "at": "3:15"}]


def make_cfg(root, jobs=JOBS, **extra):
    return cfgmod.Config(root, {"name": "Demo Brain", "schedule": {"jobs": jobs, **extra}})


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_has_no_jobs(self):
        self.assertEqual(schedule.jobs(cfgmod.Config(self.root, {})), [])

    def test_jobs_parsed(self):
        specs = schedule.jobs(make_cfg(self.root), path_env="/x/bin:/usr/bin")
        self.assertEqual([(j["label"], j["args"], j["hour"], j["minute"]) for j in specs], [
            ("teambrain.demo-brain.retro", ["retro", "run"], 1, 0),
            ("teambrain.demo-brain.index", ["index", "--incremental"], 3, 15),
        ])
        self.assertTrue(specs[0]["log"].endswith(".brain/logs/retro.log"))
        self.assertEqual(specs[0]["path"], "/x/bin:/usr/bin")

    def test_configured_path_wins(self):
        specs = schedule.jobs(make_cfg(self.root, path="/only/this"), path_env="/x")
        self.assertEqual(specs[0]["path"], "/only/this")

    def test_rejects_bad_jobs(self):
        for bad in ([{"name": "a", "run": "mcp", "at": "01:00"}],
                    [{"name": "a", "run": "", "at": "01:00"}],
                    [{"name": "a", "run": "lint", "at": "25:00"}],
                    [{"name": "a", "run": "lint", "at": "1am"}],
                    [{"name": "a", "run": "lint", "at": "01:00"}, {"name": "a", "run": "lint", "at": "02:00"}]):
            with self.assertRaises(ValueError, msg=bad):
                schedule.jobs(make_cfg(self.root, jobs=bad))

    def test_plist(self):
        cfg = make_cfg(self.root)
        job = schedule.jobs(cfg, path_env="/x")[0]
        d = plistlib.loads(schedule.plist(cfg, job))
        self.assertEqual(d["Label"], "teambrain.demo-brain.retro")
        self.assertEqual(d["ProgramArguments"][1:], ["retro", "run"])
        self.assertTrue(d["ProgramArguments"][0].endswith("bin/brain"))
        self.assertEqual(d["StartCalendarInterval"], {"Hour": 1, "Minute": 0})
        self.assertEqual(d["EnvironmentVariables"]["BRAIN_ROOT"], str(cfg.root))
        self.assertEqual(d["WorkingDirectory"], str(cfg.root))

    def test_cron_block_keeps_other_lines_and_is_idempotent(self):
        cfg = make_cfg(self.root)
        specs = schedule.jobs(cfg, path_env="/x")
        mine = "0 9 * * * echo hello\n"
        once = schedule.cron_merge(cfg, mine, specs)
        self.assertTrue(once.startswith("0 9 * * * echo hello\n"))
        self.assertEqual(once.count("teambrain.demo-brain (managed"), 1)
        self.assertIn("0 1 * * * cd ", once)
        self.assertIn("15 3 * * * cd ", once)
        self.assertEqual(schedule.cron_merge(cfg, once, specs), once)
        self.assertEqual(schedule.cron_merge(cfg, once, []), mine)

    def test_missing_crontab_raises_clean_error(self):
        cfg = make_cfg(self.root)
        with mock.patch("teambrain.schedule.subprocess.run", side_effect=FileNotFoundError(2, "crontab")):
            with self.assertRaises(schedule.SchedulerMissing) as caught:
                schedule.install(cfg)
        self.assertIn("not installed", str(caught.exception))
        self.assertIn("brain schedule install", str(caught.exception))
        self.assertEqual(caught.exception.tool, "crontab")

    def test_missing_launchctl_raises_clean_error(self):
        with mock.patch("teambrain.schedule.subprocess.run", side_effect=FileNotFoundError(2, "launchctl")):
            with self.assertRaises(schedule.SchedulerMissing) as caught:
                schedule._launchctl("bootstrap", "gui/1", "x.plist")
        self.assertEqual(caught.exception.tool, "launchctl")
        self.assertIn("brain schedule install", str(caught.exception))

    def test_cron_block_leaves_other_brains_alone(self):
        a, b = make_cfg(self.root), cfgmod.Config(self.root, {"name": "other", "schedule": {"jobs": JOBS}})
        both = schedule.cron_merge(b, schedule.cron_merge(a, "", schedule.jobs(a)), schedule.jobs(b))
        only_b = schedule.cron_merge(a, both, [])
        self.assertNotIn("demo-brain", only_b)
        self.assertIn("teambrain.other (managed", only_b)


if __name__ == "__main__":
    unittest.main()
