"""Claude Code connect: merge MCP and the prompt hook, back up, and do not duplicate."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import connect


class ConnectTest(unittest.TestCase):
    def test_install_is_idempotent_and_backs_up(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            (home / ".claude").mkdir(parents=True)
            settings = home / ".claude" / "settings.json"
            settings.write_text(json.dumps({"permissions": {"allow": ["Read"]}}) + "\n")
            claude_json = home / ".claude.json"
            claude_json.write_text(json.dumps({"theme": "dark"}) + "\n")
            root = Path(d) / "brain"
            root.mkdir()
            (root / "teambrain.yaml").write_text("name: alma\n")
            cfg = cfgmod.Config(root)
            with mock.patch("teambrain.connect.Path.home", return_value=home):
                self.assertTrue(connect.install(cfg))
                self.assertTrue(connect.install(cfg))
            data = json.loads(claude_json.read_text())
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["mcpServers"]["alma"]["args"], ["mcp"])
            self.assertEqual(data["mcpServers"]["alma"]["env"]["BRAIN_ROOT"], str(root))
            saved = json.loads(settings.read_text())
            self.assertEqual(saved["permissions"]["allow"], ["Read"])
            commands = []
            for group in saved["hooks"]["UserPromptSubmit"]:
                for hook in group["hooks"]:
                    commands.append(hook["command"])
            self.assertEqual(len(commands), 1)
            self.assertIn("hook-search", commands[0])
            self.assertIn(str(root), commands[0])
            original = json.loads((home / ".claude.json.bak").read_text())
            self.assertEqual(original, {"theme": "dark"})
            self.assertFalse((home / ".claude.json.bak.1").exists())
            self.assertTrue(settings.with_name("settings.json.bak").is_file())
