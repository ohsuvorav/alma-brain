import copy
import tempfile
import unittest
from pathlib import Path
from teambrain.loop import Loop


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.loop = Loop(self.root)
        self.page = {'thread': {'id': 'thread1', 'kind': 'chatgpt', 'title': 'Example'},
                     'page': {'hasMore': False}, 'turns': [{'id': 'turn1', 'status': 'completed',
                     'items': [{'type': 'userMessage', 'content': [{'text': 'I chose to test first.'}]}]}]}

    def tearDown(self):
        self.loop.db.close()
        self.tmp.cleanup()

    def review(self):
        p = self.loop.pending()[0]
        return {'key': p['key'], 'hash': p['hash'], 'outcome': 'proposed', 'reason': 'New rule',
                'proposals': [{'target': '_system_backlog.md', 'title': 'Test first',
                'observation': 'User chose testing.', 'change': 'Test before scheduling.',
                'eval': 'Run twice; no duplicate.', 'dedup_key': 'test-before-scheduling',
                'evidence': 'I chose to test first.'}]}

    def test_replay_edit_and_stale_review(self):
        self.loop.ingest(self.page)
        r = self.review()
        self.loop.finish(r)
        self.assertEqual(self.loop.ingest(self.page)['unchanged'], 1)
        self.assertEqual(self.loop.pending(), [])
        self.page['turns'][0]['items'][0]['content'][0]['text'] += ' Changed.'
        self.loop.ingest(self.page)
        self.assertEqual(len(self.loop.pending()), 1)
        with self.assertRaises(ValueError):
            self.loop.finish(r)

    def test_active_and_truncated_are_not_processed(self):
        self.page['turns'][0]['status'] = 'inProgress'
        self.assertEqual(self.loop.ingest(self.page)['skipped_incomplete'], 1)
        self.page['turns'][0]['status'] = 'completed'
        self.page['turns'][0]['items'][0]['content'][0]['truncated'] = True
        self.assertEqual(self.loop.ingest(self.page)['blocked_truncated'], 1)
        self.assertEqual(self.loop.pending(), [])

    def test_publish_crash_recovery_and_idempotency(self):
        self.loop.ingest(self.page)
        r = self.review()
        self.loop.finish(r)
        self.assertEqual(self.loop.publish()['published'], 1)
        self.loop.db.execute('UPDATE outbox SET published=0')
        self.loop.db.commit()
        self.assertEqual(self.loop.publish()['published'], 0)
        self.assertTrue(self.loop.finish(r)['already_reviewed'])
        self.assertEqual((self.root / '_system_backlog.md').read_text().count('<!-- chat-reflection:'), 1)

    def test_unapproved_target_and_fabricated_evidence_fail(self):
        self.loop.ingest(self.page)
        r = self.review()
        r['proposals'][0]['target'] = 'raw/identity.md'
        with self.assertRaises(ValueError): self.loop.finish(r)
        r = self.review()
        r['proposals'][0]['evidence'] = 'Assistant invented this'
        with self.assertRaises(ValueError): self.loop.finish(r)
        self.assertEqual(len(self.loop.pending()), 1)

    def test_source_isolation(self):
        self.loop.ingest(self.page)
        other = copy.deepcopy(self.page)
        other['thread']['kind'] = 'codex'
        self.loop.ingest(other)
        self.assertEqual(len(self.loop.pending()), 2)


if __name__ == '__main__':
    unittest.main()
