#!/usr/bin/env python3
"""Local bookkeeping for app-mediated reflection; no credentials or network calls."""
import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from teambrain.backlog import Backlog
from teambrain.config import Config, load


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def truncated(value):
    if isinstance(value, dict):
        return value.get('truncated') is True or any(truncated(v) for v in value.values())
    return isinstance(value, list) and any(truncated(v) for v in value)


class Loop:
    def __init__(self, root, cfg=None):
        self.cfg = cfg or Config(root)
        self.root = self.cfg.root
        self.private = self.cfg.private_dir / 'chat-reflection'
        self.private.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.private / 'state.sqlite3', timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS turns (
          key TEXT PRIMARY KEY, source TEXT NOT NULL, thread TEXT NOT NULL,
          turn TEXT NOT NULL, hash TEXT NOT NULL, payload TEXT NOT NULL,
          reviewed_hash TEXT, review TEXT);
        CREATE TABLE IF NOT EXISTS outbox (
          id TEXT PRIMARY KEY, target TEXT NOT NULL, body TEXT NOT NULL,
          published INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events (
          at TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, detail TEXT);
        ''')

    def ingest(self, page):
        thread = page['thread']
        if thread['kind'] not in ('codex', 'chatgpt'):
            raise ValueError('Unsupported source')
        counts = {'new_or_changed': 0, 'unchanged': 0, 'blocked_truncated': 0, 'skipped_incomplete': 0}
        with self.db:
            for turn in page['turns']:
                if turn['status'] != 'completed':
                    counts['skipped_incomplete'] += 1
                    continue
                messages = [m for m in turn['items'] if m['type'] in ('userMessage', 'agentMessage')]
                if truncated(messages):
                    counts['blocked_truncated'] += 1
                    continue
                # Tools, reasoning, previews and attachments are not reflection evidence.
                payload = {'title': thread['title'], 'startedAt': turn.get('startedAt'),
                           'messages': messages, 'coverage': 'app-returned text; upstream completeness unverified'}
                h = digest(payload)
                key = f"{thread['kind']}:{thread['id']}:{turn['id']}"
                previous = self.db.execute('SELECT hash FROM turns WHERE key=?', (key,)).fetchone()
                if previous and previous['hash'] == h:
                    counts['unchanged'] += 1
                    continue
                self.db.execute('''INSERT INTO turns(key,source,thread,turn,hash,payload)
                  VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET hash=excluded.hash,payload=excluded.payload''',
                  (key, thread['kind'], thread['id'], turn['id'], h, json.dumps(payload, ensure_ascii=False)))
                counts['new_or_changed'] += 1
            self.db.execute('INSERT INTO events(kind,detail) VALUES(?,?)', ('ingest', json.dumps({'thread': thread['id'], **counts, 'page': page['page']})))
        return counts

    def pending(self):
        rows = self.db.execute('SELECT * FROM turns WHERE reviewed_hash IS NULL OR reviewed_hash != hash ORDER BY rowid').fetchall()
        return [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]

    def finish(self, review):
        with self.db:
            row = self.db.execute('SELECT * FROM turns WHERE key=?', (review['key'],)).fetchone()
            if not row or row['hash'] != review['hash']:
                raise ValueError('Stale or unknown turn; re-read pending evidence')
            if row['reviewed_hash'] == review['hash']:
                return {'already_reviewed': True}
            if review['outcome'] not in ('no_change', 'duplicate', 'proposed', 'insufficient_evidence'):
                raise ValueError('Invalid review outcome')
            proposals = review.get('proposals', [])
            if len(proposals) > 2 or bool(proposals) != (review['outcome'] == 'proposed'):
                raise ValueError('Proposed outcome requires 1-2 proposals; other outcomes require none')
            if not review.get('reason'):
                raise ValueError('Review reason required')
            user_text = '\n'.join(b.get('text', '') for m in json.loads(row['payload'])['messages']
                                  if m['type'] == 'userMessage' for b in m.get('content', []))
            for p in proposals:
                if p['target'] not in self.cfg['backlogs']:
                    raise ValueError('Only proposal backlogs are writable')
                if not p.get('evidence') or p['evidence'] not in user_text:
                    raise ValueError('Proposal needs a verbatim user evidence fragment')
                if not all(p.get(k) for k in ('title', 'observation', 'change', 'eval', 'dedup_key')):
                    raise ValueError('Missing proposal fields')
                pid = digest([p['target'], p['dedup_key']])[:24]
                body = (f"\n<!-- chat-reflection:{pid} -->\n## Chat reflection — {p['title']}\n"
                        f"**Source:** {row['source']} task `{row['thread']}`, turn `{row['turn']}`; app-returned text.\n"
                        f"**Raw observation:** {p['observation']}\n**Change:** {p['change']}\n**Eval:** {p['eval']}\n\n---\n")
                self.db.execute('INSERT OR IGNORE INTO outbox(id,target,body) VALUES(?,?,?)', (pid, p['target'], body))
            self.db.execute('UPDATE turns SET reviewed_hash=?,review=? WHERE key=?',
                            (row['hash'], json.dumps(review, ensure_ascii=False), row['key']))
        return {'reviewed': review['key'], 'outcome': review['outcome']}

    def publish(self):
        # Transaction serializes our writers. Embedded IDs recover a crash after append but before DB commit.
        self.db.execute('BEGIN IMMEDIATE')
        count = 0
        try:
            for p in self.db.execute('SELECT * FROM outbox WHERE published=0').fetchall():
                marker = f"<!-- chat-reflection:{p['id']} -->"
                if Backlog(self.root, self.cfg).append(p['target'], p['body'], marker):
                    count += 1
                self.db.execute('UPDATE outbox SET published=1 WHERE id=?', (p['id'],))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {'published': count}

    def status(self):
        return {'captured_turns': self.db.execute('SELECT count(*) FROM turns').fetchone()[0],
                'pending_turns': len(self.pending()),
                'unpublished_proposals': self.db.execute('SELECT count(*) FROM outbox WHERE published=0').fetchone()[0],
                'recent_events': [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY rowid DESC LIMIT 8')]}


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['ingest', 'pending', 'finish', 'publish', 'status'])
    parser.add_argument('input', nargs='?')
    args = parser.parse_args()
    cfg = load()
    if cfg is None: parser.error('Not inside a brain (no teambrain.yaml; set BRAIN_ROOT)')
    loop = Loop(cfg.root, cfg)
    method = getattr(loop, args.command)
    result = method(json.loads(Path(args.input).read_text())) if args.command in ('ingest', 'finish') else method()
    print(json.dumps(result, ensure_ascii=False, indent=2))
