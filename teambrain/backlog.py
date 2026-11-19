#!/usr/bin/env python3
"""One shared Markdown backlog writer and lifecycle reader for every agent."""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from teambrain.config import Config, load

STATES = ('inbox', 'ready', 'needs_decision', 'in_progress', 'blocked', 'parked', 'routed', 'resolved', 'duplicate', 'rejected')
META = re.compile(r'^<!-- backlog-state: (.+) -->$', re.M)


def entries(text, target):
    # Exclude headings inside fences/comments while retaining exact file offsets.
    masked = re.sub(r'<!--.*?-->|```.*?```', lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text, flags=re.S)
    headings = list(re.finditer(r'^## (.+)$', masked, re.M))
    result = []
    for n, h in enumerate(headings):
        title = h[1].strip()
        if not (re.search(r'\[\d{4}-\d{2}-\d{2}\]|candidate|suggest for|Chat reflection|Proposal [A-Z]', title, re.I)):
            continue
        end = headings[n + 1].start() if n + 1 < len(headings) else len(text)
        body = text[h.start():end]
        item_id = hashlib.sha256((target + ':' + title).encode()).hexdigest()[:12]
        m = META.search(body)
        state = json.loads(m[1]) if m else {'status': 'resolved' if 'resolved for ' in title.lower() else 'inbox'}
        result.append({'id': item_id, 'target': target, 'title': title,
                       'line': text.count('\n', 0, h.start()) + 1, 'start': h.start(), 'end': end,
                       'body': body, **state})
    return result


class Backlog:
    def __init__(self, root, cfg=None):
        self.cfg = cfg or Config(root)
        self.root = self.cfg.root
        self.targets = tuple(self.cfg['backlogs'])

    @contextlib.contextmanager
    def lock(self):
        path = self.cfg.private_dir / 'chat-reflection/backlog.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def path(self, target):
        if target not in self.targets: raise ValueError('Canonical proposal backlogs only')
        p = self.root / target
        if p.is_symlink(): raise ValueError('Refusing symlink backlog')
        return p

    def write(self, path, old, new):
        # Detect a noncooperating editor changing the source while preparing an update.
        if (path.read_text() if path.exists() else '') != old:
            raise ValueError('Backlog changed; reload and retry')
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.backlog-')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(new); f.flush(); os.fsync(f.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name): os.unlink(name)

    def append(self, target, body, marker):
        if not marker or marker not in body: raise ValueError('Stable marker required in body')
        with self.lock():
            path = self.path(target)
            old = path.read_text() if path.exists() else ''
            if marker in old: return False
            # Insert before the first real proposal, never underneath the Rejected heading.
            found = entries(old, target)
            rejected = re.search(r'^## Rejected\s*$', old, re.M)
            at = found[0]['start'] if found else (rejected.start() if rejected else len(old))
            self.write(path, old, old[:at] + body.strip() + '\n\n' + old[at:])
            return True

    def list(self):
        return [e for target in self.targets for e in entries(self.path(target).read_text(), target)]

    def review(self, project=None):
        excluded = {'resolved', 'duplicate', 'rejected', 'parked'}
        if project is None: excluded.add('routed')
        return [e for e in self.list() if e['status'] not in excluded
                and (project is None or e.get('project') == project)]

    def support(self, item_id, body, marker):
        if not marker or marker not in body: raise ValueError('Evidence marker required')
        with self.lock():
            matches = [e for e in self.list() if e['id'] == item_id]
            if len(matches) != 1: raise ValueError('Missing or ambiguous item ID')
            e = matches[0]; path = self.path(e['target']); old = path.read_text()
            if marker in old: return False
            if old[e['start']:e['end']] != e['body']: raise ValueError('Backlog changed')
            self.write(path, old, old[:e['end']] + body.strip() + '\n\n' + old[e['end']:])
        return True

    def mark(self, item_id, status, evidence, next_action='', owner='', due='', project='', package=''):
        if status not in STATES: raise ValueError('Invalid status')
        if not evidence: raise ValueError('Evidence or rationale required')
        if status in ('parked', 'routed'):
            if not (next_action and owner) or due:
                raise ValueError('Parked/routed items need owner and wake action, with no recurring review date')
            if status == 'routed' and not project:
                raise ValueError('Routed items require an owning project/workstream')
        elif status not in ('resolved', 'duplicate', 'rejected') and not (next_action and owner and due):
            raise ValueError('Open items require owner, next action and ISO review date')
        if due: datetime.date.fromisoformat(due)
        with self.lock():
            matches = [e for e in self.list() if e['id'] == item_id]
            if len(matches) != 1: raise ValueError('Missing or ambiguous item ID')
            e = matches[0]; path = self.path(e['target']); old = path.read_text()
            if old[e['start']:e['end']] != e['body']:
                raise ValueError('Backlog changed; reload and retry')
            meta = {'status': status, 'evidence': evidence, 'next_action': next_action,
                    'owner': owner, 'review_on': due, 'updated': str(datetime.date.today())}
            if project: meta['project'] = project
            if package: meta['package'] = package
            line = '<!-- backlog-state: ' + json.dumps(meta, ensure_ascii=False) + ' -->'
            body = META.sub('', e['body'])
            first, rest = body.split('\n', 1)
            body = first + '\n' + line + '\n' + rest.lstrip('\n')
            self.write(path, old, old[:e['start']] + body + old[e['end']:])
        return meta

    def status(self):
        data = self.list()
        return {t: {'total': sum(e['target'] == t for e in data),
                    **{s: sum(e['target'] == t and e['status'] == s for e in data) for s in STATES}}
                for t in self.targets}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['status', 'list', 'review', 'mark', 'append', 'support'])
    p.add_argument('--project', help='Owning project/workstream for a scoped review')
    p.add_argument('--input', help='JSON object for mark or append')
    args = p.parse_args(); cfg = load()
    if cfg is None: p.error('Not inside a brain (no teambrain.yaml; set BRAIN_ROOT)')
    b = Backlog(cfg.root, cfg)
    if args.project and args.command != 'review': p.error('--project requires review')
    if args.command in ('mark', 'append', 'support'):
        result = getattr(b, args.command)(**json.loads(Path(args.input).read_text()))
    else:
        result = b.review(args.project) if args.command == 'review' else getattr(b, args.command)()
        if args.command in ('list', 'review'): result = [{k:v for k,v in e.items() if k not in ('start','end','body')} for e in result]
    print(json.dumps(result, ensure_ascii=False, indent=2))
