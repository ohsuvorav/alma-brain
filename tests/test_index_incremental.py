"""Incremental indexing: per-file diff, lock, and an end-to-end update on a temp copy of the fixture."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambrain import config as cfgmod
from teambrain import index as idx

FIXTURE = Path(__file__).parent / "fixture-brain"


class DiffTest(unittest.TestCase):
    def test_changed_added_removed(self):
        old = {"a.md": "1", "b.md": "2", "gone.md": "3"}
        new = {"a.md": "1", "b.md": "22", "new.md": "4"}
        self.assertEqual(idx.diff_files(old, new), (["b.md", "new.md"], ["gone.md"]))


class LockTest(unittest.TestCase):
    def test_second_lock_is_refused(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"BRAIN_STATE_DIR": d}):
            cfg = cfgmod.load(FIXTURE)
            first = idx._lock(cfg)
            self.assertIsNotNone(first)
            self.assertIsNone(idx._lock(cfg))
            first.close()
            again = idx._lock(cfg)
            self.assertIsNotNone(again)
            again.close()


def _model_available():
    try:
        import fastembed  # noqa: F401
        import lancedb  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_model_available(), "fastembed/lancedb not installed")
class IncrementalTest(unittest.TestCase):
    def test_reembeds_only_changed_files(self):
        with tempfile.TemporaryDirectory() as d:
            brain = Path(d) / "brain"
            shutil.copytree(FIXTURE, brain)
            with mock.patch.dict(os.environ, {"BRAIN_STATE_DIR": str(Path(d) / "state")}):
                os.environ.pop("BRAIN_ROOT", None)
                cfg = cfgmod.load(brain)
                self.assertGreater(idx.build_index(cfg, verbose=False), 0)
                self.assertEqual(idx.build_index(cfg, verbose=False, incremental=True), 0)  # nothing changed

                (brain / "raw" / "timeline.md").write_text("# Timeline\n\nA synthetic network partition lasted ten minutes.\n")
                (brain / "wiki" / "eng" / "new-page.md").write_text("# New page\n\nRunbooks live next to the service.\n")
                embedded = idx.build_index(cfg, verbose=False, incremental=True)
                self.assertEqual(embedded, 2)

                from teambrain import search as core
                files = [r["file"] for _, r in core.search(cfg, "network partition", 5, 2, 0.0)]
                self.assertIn("raw/timeline.md", files)
                table = core.open_table(cfg)
                texts = " ".join(r["text"] for r in table.search().limit(100).to_list())
                self.assertNotIn("backups were never restored", texts)  # old chunk deleted


if __name__ == "__main__":
    unittest.main()
