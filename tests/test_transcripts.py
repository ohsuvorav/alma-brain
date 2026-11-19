"""Transcript parsing and the optional chat index source, on a synthetic transcript."""
import os
import unittest
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import transcripts

DIR = Path(__file__).parent / "fixture-transcripts"
ONE = DIR / "demo-project" / "11111111-aaaa-bbbb-cccc-000000000001.jsonl"


class ParseTest(unittest.TestCase):
    def test_keeps_typed_messages_interrupts_and_denials(self):
        s = transcripts.parse(ONE)
        kinds = [e[1] for e in s["events"]]
        self.assertEqual(kinds, ["USER", "USER", "DENIED", "INTERRUPT", "USER", "USER"])
        self.assertEqual(s["titles"], ["Outage write-up"])
        self.assertEqual(s["cwd"], "/work/demo")

    def test_correction_carries_preceding_assistant_text(self):
        s = transcripts.parse(ONE)
        correction = s["events"][1]
        self.assertIn("63% of what", correction[2])
        self.assertIn("63% of it waiting", correction[3])

    def test_skips_sidechain_and_skip_commands(self):
        texts = " ".join(e[2] for e in transcripts.parse(ONE)["events"])
        self.assertNotIn("subagent", texts)
        self.assertNotIn("/clear", texts)


class ChatDocsTest(unittest.TestCase):
    def test_one_doc_per_session_per_day_with_min_words(self):
        import time
        with mock.patch.dict(os.environ, {"TZ": "UTC"}):
            time.tzset()
            docs = transcripts.chat_docs(str(DIR / "demo-project" / "*.jsonl"), min_words=4, label="User")
        time.tzset()  # back to the caller's zone
        keys = sorted(docs)
        self.assertEqual(keys, ["chat/11111111/2026-01-05", "chat/11111111/2026-01-06"])
        day2 = docs["chat/11111111/2026-01-06"]["text"]
        self.assertIn("User: next day", day2)
        self.assertNotIn("User: ok", day2)  # under min_words
        self.assertEqual(docs["chat/11111111/2026-01-05"]["session"], "11111111-aaaa-bbbb-cccc-000000000001")

    def test_cross_project_pattern_indexes_nothing(self):
        self.assertIsNone(transcripts.project_transcript_pattern("~/.claude/projects/*/*.jsonl"))
        self.assertEqual(transcripts.chat_docs("~/.claude/projects/*/*.jsonl"), {})
        self.assertFalse(cfgmod.DEFAULTS["index"]["chats"]["enabled"])
        self.assertFalse(cfgmod.DEFAULTS["retro"]["enabled"])
        self.assertEqual(cfgmod.DEFAULTS["index"]["chats"]["glob"], "")
        self.assertEqual(cfgmod.DEFAULTS["retro"]["transcripts"], "")


if __name__ == "__main__":
    unittest.main()
