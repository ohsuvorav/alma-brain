"""The engine tree stays free of secrets, personal data, and employer or org slugs."""
import hashlib
from pathlib import Path

import unittest

from teambrain.wip import EMAIL_RE, SECRET_RE, email_allowed

# sha256 of lowercase strings that must not appear. The plaintext is not stored.
BANNED = {
    7: "25d512f724a148561b59c091e58250aade8fe5b9e0fbf3be7df143aabd4f3aca",
    21: "33216f589a308b2b563c5afd7dfb335d6719e89b48ad4dfb71e05914b389433c",
}
ALLOW_EMAILS = ["example.com", "example.org", "noreply", "localhost"]
SKIP = {".git", ".brain", "__pycache__", ".venv", "node_modules", ".lancedb", ".private"}
PERSON = "Oleg" + " Suvorov"


def _repo():
    return Path(__file__).resolve().parents[1]


def _files(root):
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP for part in path.relative_to(root).parts):
            continue
        if path.stat().st_size > 2_000_000:
            continue
        yield path


class RepoHygieneTest(unittest.TestCase):
    def test_tree_has_no_secrets_personal_data_or_org_slugs(self):
        problems = []
        root = _repo()
        for path in _files(root):
            raw = path.read_bytes()
            if b"\0" in raw[:4096]:
                continue
            rel = str(path.relative_to(root))
            text = raw.decode("utf-8", errors="replace")
            if SECRET_RE.search(text):
                problems.append(f"{rel}: secret pattern")
            # tests/ holds synthetic addresses that prove the scanner rejects them.
            if not rel.startswith("tests/"):
                for addr in EMAIL_RE.findall(text):
                    if not email_allowed(addr, ALLOW_EMAILS):
                        problems.append(f"{rel}: email {addr}")
            if PERSON in text and rel != "LICENSE":
                problems.append(f"{rel}: personal name outside LICENSE")
            lowered = text.lower()
            for length, digest in BANNED.items():
                if len(lowered) < length:
                    continue
                step = 1
                for i in range(0, len(lowered) - length + 1, step):
                    if hashlib.sha256(lowered[i:i + length].encode()).hexdigest() == digest:
                        problems.append(f"{rel}: banned slug ({length})")
                        break
        self.assertEqual(problems, [])
