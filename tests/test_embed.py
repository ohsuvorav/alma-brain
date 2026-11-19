"""Default embedding model is multilingual, and a model change forces a full reindex."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import index as idx
from teambrain.search import apply_prefix, passage_prefix, query_prefix


class EmbedConfigTest(unittest.TestCase):
    def test_default_model_is_multilingual_e5(self):
        self.assertEqual(cfgmod.DEFAULTS["index"]["embed_model"], "intfloat/multilingual-e5-small")
        self.assertEqual(cfgmod.DEFAULTS["index"]["vector_dim"], 384)
        with tempfile.TemporaryDirectory() as d:
            cfg = cfgmod.Config(d)
        self.assertEqual(query_prefix(cfg), "query: ")
        self.assertEqual(passage_prefix(cfg), "passage: ")

    def test_prefixes_follow_the_model_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            english = cfgmod.Config(d, {"index": {"embed_model": "BAAI/bge-small-en-v1.5"}})
            self.assertEqual(query_prefix(english), "")
            self.assertEqual(passage_prefix(english), "")
            custom = cfgmod.Config(d, {"index": {"embed_query_prefix": "q: ", "embed_passage_prefix": ""}})
        self.assertEqual(query_prefix(custom), "q: ")
        self.assertEqual(passage_prefix(custom), "")
        self.assertEqual(apply_prefix("query: ", "query: already"), "query: already")
        self.assertEqual(apply_prefix("query: ", "hello"), "query: hello")

    def test_model_or_prefix_change_is_not_incremental(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"BRAIN_STATE_DIR": d}):
            cfg = cfgmod.Config(d)
            idx._write_manifest(cfg, "fp", {"a.md": "abc"})
            manifest = json.loads(cfg.manifest_path.read_text())
        self.assertEqual(manifest["embed_model"], "intfloat/multilingual-e5-small")
        self.assertEqual(manifest["query_prefix"], "query: ")
        self.assertEqual(manifest["passage_prefix"], "passage: ")
        self.assertTrue(idx.can_increment(manifest, cfg))
        changed = dict(manifest, embed_model="BAAI/bge-small-en-v1.5")
        self.assertFalse(idx.can_increment(changed, cfg))
        other_prefix = dict(manifest, query_prefix="")
        self.assertFalse(idx.can_increment(other_prefix, cfg))
        self.assertIn(".txt", cfgmod.DEFAULTS["index"]["extensions"])
