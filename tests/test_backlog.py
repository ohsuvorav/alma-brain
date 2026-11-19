import tempfile
import unittest
import multiprocessing
from pathlib import Path
from teambrain.backlog import Backlog, entries


def writer(root, prefix):
    b=Backlog(root)
    for n in range(8):
        marker=f'<!-- proposal:{prefix}-{n} -->'
        b.append('_system_backlog.md', f'{marker}\n## Chat reflection — {prefix}-{n}\nEvidence\n', marker)


class BacklogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ('_wiki_backlog.md', '_system_backlog.md'):
            (self.root/name).write_text('# Backlog\n\n## [2026-09-01] candidate — existing\nOriginal evidence\n\n## Rejected\n- Never repeat this\n')
        self.b = Backlog(self.root)

    def tearDown(self): self.tmp.cleanup()

    def test_shared_writer_idempotent_outside_rejected(self):
        body='<!-- proposal:test -->\n## Chat reflection — new\nNew evidence'
        self.assertTrue(self.b.append('_wiki_backlog.md',body,'<!-- proposal:test -->'))
        self.assertFalse(self.b.append('_wiki_backlog.md',body,'<!-- proposal:test -->'))
        text=(self.root/'_wiki_backlog.md').read_text()
        self.assertLess(text.index('New evidence'),text.index('## Rejected'))
        self.assertIn('Original evidence',text)
        self.assertIn('Never repeat this',text)

    def test_receipts_preserve_content_and_id(self):
        e=self.b.list()[0]
        with self.assertRaises(ValueError): self.b.mark(e['id'],'needs_decision','Ask user')
        self.b.mark(e['id'],'needs_decision','Unapproved principle','Rewrite or reject','owner','2026-09-28')
        updated=self.b.list()[0]
        self.assertEqual(e['id'],updated['id'])
        self.assertIn('Original evidence',updated['body'])
        self.assertEqual(updated['status'],'needs_decision')
        self.b.mark(e['id'],'duplicate','Surviving canonical item ID abc')
        self.assertEqual(self.b.status()['_wiki_backlog.md']['duplicate'],1)
        self.assertEqual((self.root/'_wiki_backlog.md').read_text().count('backlog-state:'),1)

    def test_ignore_fenced_and_comment_headings(self):
        text='<!--\n## [2026-01-01] candidate fake\n-->\n```\n## [2026-01-01] fake\n```\n## [2026-01-02] candidate real\nEvidence\n'
        self.assertEqual(len(entries(text,'_wiki_backlog.md')),1)

    def test_rejected_only_and_target_guard(self):
        (self.root/'_wiki_backlog.md').write_text('# Backlog\n## Rejected\n- Keep\n')
        body='<!-- proposal:test -->\n## Chat reflection — new\nEvidence'
        self.b.append('_wiki_backlog.md',body,'<!-- proposal:test -->')
        text=(self.root/'_wiki_backlog.md').read_text()
        self.assertLess(text.index('Evidence'),text.index('## Rejected'))
        with self.assertRaises(ValueError):self.b.append('raw/identity.md',body,'<!-- proposal:test -->')

    def test_two_writers_preserve_every_proposal(self):
        procs=[multiprocessing.Process(target=writer,args=(self.root,p)) for p in ('claude','codex')]
        for p in procs:p.start()
        for p in procs:
            p.join(10)
            self.assertEqual(p.exitcode,0)
        self.assertEqual(self.b.status()['_system_backlog.md']['total'],17)

    def test_corroboration_stays_with_original_item(self):
        e=self.b.list()[0]
        body='<!-- evidence:one -->\nAdditional source.'
        self.assertTrue(self.b.support(e['id'],body,'<!-- evidence:one -->'))
        self.assertFalse(self.b.support(e['id'],body,'<!-- evidence:one -->'))
        self.assertIn('Additional source.',self.b.list()[0]['body'])

    def test_parking_and_routing_review(self):
        wiki, system = self.b.list()
        self.b.mark(wiki['id'], 'parked', 'Approved', 'Wake on selection', 'owner')
        self.b.mark(system['id'], 'routed', 'Approved', 'Review with project', 'owner', project='alpha')
        self.assertEqual(self.b.review(), [])
        self.assertEqual([e['id'] for e in self.b.review('alpha')], [system['id']])
        self.assertEqual(self.b.review('other'), [])
        self.b.support(wiki['id'], '<!-- support:new --> More evidence', '<!-- support:new -->')
        self.assertEqual(self.b.review(), [])
        self.assertEqual(len(self.b.list()), 2)
        self.assertIn('Original evidence', self.b.list()[0]['body'])

    def test_routing_validation_and_packages(self):
        e=self.b.list()[0]
        with self.assertRaises(ValueError):
            self.b.mark(e['id'], 'routed', 'Approved', 'Review', 'owner')
        with self.assertRaises(ValueError):
            self.b.mark(e['id'], 'parked', 'Approved', 'Review', 'owner', '2026-09-28')
        self.b.mark(e['id'], 'ready', 'Scoped proposal', 'Select implementation', 'owner', '2026-09-28', package='navigation')
        self.assertEqual(self.b.review()[0]['package'], 'navigation')


if __name__=='__main__': unittest.main()
