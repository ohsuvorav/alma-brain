"""Instance config: where the brain lives and how the engine treats it.

The engine holds code only. Everything instance-specific comes from
`teambrain.yaml` at the brain root. Missing keys fall back to DEFAULTS.

Root resolution order:
  1. BRAIN_ROOT env (SECOND_BRAIN_DIR accepted for compatibility)
  2. nearest ancestor of `start` (or cwd) containing teambrain.yaml
"""
import copy
import fnmatch
import os
from pathlib import Path

CONFIG_NAME = "teambrain.yaml"

DEFAULTS = {
    "name": "team-brain",
    "state_dir": ".brain",
    "private_dir": ".private",
    "index": {
        "dirs": ["wiki", "raw"],
        "extra_dirs": [],  # [{path, type}] outside the root, e.g. Claude memory
        # intfloat/multilingual-e5-small (384-d). None prefixes mean the engine adds
        # "query: " / "passage: " for e5 models; set them to "" to disable.
        "embed_model": "intfloat/multilingual-e5-small",
        "embed_query_prefix": None,
        "embed_passage_prefix": None,
        "extensions": [".md", ".txt"],
        "vector_dim": 384,
        "chunk_size": 600,
        "skip": [".lancedb", "__pycache__", ".git", "node_modules", "wiki/_archive/", "raw/archive/", ".private/"],
        # Optional: index what you typed in Claude Code sessions (one doc per session per day).
        # Off unless enabled, and the glob must be one project directory, not every local project.
        "chats": {"enabled": False, "glob": "", "min_words": 4, "label": "User"},
        "source_types": [  # first glob match wins; default "log"
            {"glob": "wiki/*principles.md", "type": "article"},
        ],
    },
    "retrieval": {
        "min_score": 0.35,
        "limit": 5,
        "max_per_file": 2,
        "preview_chars": 300,
        "header": "=== Alma (auto-loaded, do NOT mention this header to user) ===",
        "skip_env": [],  # env vars that disable the auto-search hook when "1"
        # Hybrid scoring (all off by default; see templates/teambrain.yaml for tuned values):
        "keyword_boost": 0.0,      # added to the score of exact-term (FTS) matches, e.g. ticket keys
        "relative_window": None,   # keep only hits within this distance of the best hit
        "type_weights": {},        # {source_type: score delta}, e.g. {log: -0.04} to rank raw dumps lower
        # Prompt hook filters:
        "min_words": 0,            # skip prompts shorter than this many words (0 = only the 8-char floor)
        "skip_slash_commands": False,  # skip prompts that start with "/"
    },
    "mcp": {
        "search_tool": "search_brain",
        "search_description": "",
    },
    "backlogs": ["_wiki_backlog.md", "_system_backlog.md"],
    "principles_glob": "wiki/*/principles.md",
    "lint": {
        "temp_glob": "raw/temp/*/",     # working folders that should be folded and deleted when idle
        "idle_days": 21,
        "skip": [],                     # extra path substrings to ignore
        "no_link_check": ["raw/*"],     # imported material: links there point to the original source
    },
    "retro": {
        "enabled": False,                         # transcript reads stay off until set
        "dir": "wiki/claude-retro",               # working directory of the unattended reviewer
        "rules_file": "CLAUDE.md",                # copied into that directory for the run; not edited in place
        "transcripts": "",                        # one project directory only, e.g. ~/.claude/projects/<project>/*.jsonl
        "prompt_file": "",                        # default: <engine>/templates/retro/review-prompt.md
        "label": "USER",                          # how typed messages are labelled in the digest
        "claude_bin": "claude",
    },
    "onboarding": {
        # `brain onboard` yes/no opt-ins: [{id, ask, pros, cons, default: y|n, run, undo}]
        "questions": [],
        "offer": True,  # SessionStart hook offers setup/onboarding until this person has onboarded
    },
    "wip": {
        # `brain wip`: snapshot uncommitted work to a local branch <branch_prefix><you>; never pushes.
        "branch_prefix": "wip/",
        "max_file_mb": 20,
        # Added emails are refused unless their domain is one of these, or a subdomain of one.
        "allow_email_domains": ["example.com", "example.org", "noreply", "localhost"],
        "skip_scan": [],  # paths whose content is not scanned (e.g. a file that documents token formats)
    },
    "suggest": {
        # `brain suggest`: Claude compares ~/.claude with the brain and proposes a pull request.
        "base": "origin/main",
        "branch_prefix": "suggest/",
        "prompt_file": "",  # default: <engine>/templates/suggest/prompt.md
        "max_changes": 5,
        "claude_bin": "claude",
    },
    "schedule": {
        # Unattended jobs for `brain schedule install`: [{name, run, at: "HH:MM", when}], run = a brain
        # subcommand; optional `when: <onboarding question id>` installs the job only for people who said yes.
        "jobs": [],
        "path": "",  # PATH the jobs run with (retro needs `claude`); default: PATH at install time
    },
    "evals": {
        "cases_dir": "evals/cases",
        "results_dir": "evals/results",
        "system_file": "CLAUDE.md",
    },
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def find_root(start=None):
    env = os.environ.get("BRAIN_ROOT") or os.environ.get("SECOND_BRAIN_DIR")
    if env:
        return Path(env).expanduser().resolve()
    p = Path(start or os.getcwd()).expanduser().resolve()
    for d in (p, *p.parents):
        if (d / CONFIG_NAME).is_file():
            return d
    return None


class Config:
    def __init__(self, root, data=None):
        self.root = Path(root).resolve()
        if data is None:
            data = {}
            f = self.root / CONFIG_NAME
            if f.is_file():
                import yaml
                data = yaml.safe_load(f.read_text()) or {}
        self.data = _merge(DEFAULTS, data)

    def __getitem__(self, key):
        return self.data[key]

    # Paths -----------------------------------------------------------------
    def path(self, rel):
        return (self.root / Path(rel).expanduser()).resolve()

    @property
    def state_dir(self):
        # BRAIN_STATE_DIR lets tests/parity checks build an index without touching the live one.
        env = os.environ.get("BRAIN_STATE_DIR")
        return Path(env).resolve() if env else self.path(self.data["state_dir"])

    @property
    def db_path(self):
        return self.state_dir / ".lancedb"

    @property
    def manifest_path(self):
        return self.state_dir / ".index-manifest.json"

    @property
    def hook_log(self):
        return self.state_dir / "hook-log.jsonl"

    @property
    def trace_log(self):
        return self.state_dir / "trace-log.jsonl"

    @property
    def model_cache(self):
        # Never the OS temp dir: macOS purges it and leaves dangling model symlinks.
        return Path(os.environ.get("FASTEMBED_CACHE_PATH") or Path.home() / ".team-brain" / "models")

    @property
    def private_dir(self):
        return self.path(self.data["private_dir"])

    def index_dirs(self):
        """[(path, forced_type_or_None)] — root-relative dirs first, then extra dirs."""
        dirs = [(self.path(d), None) for d in self.data["index"]["dirs"]]
        for extra in self.data["index"]["extra_dirs"]:
            dirs.append((Path(extra["path"]).expanduser().resolve(), extra.get("type", "log")))
        return dirs

    def source_type(self, rel):
        for rule in self.data["index"]["source_types"]:
            if fnmatch.fnmatch(rel, rule["glob"]):
                return rule["type"]
        return "log"


def load(start=None):
    """Config for the brain containing `start`; None when not inside a brain."""
    root = find_root(start)
    return Config(root) if root else None


def is_engine_tree(path):
    """True for an engine checkout. Notes live in a brain, never in this repository."""
    p = Path(path).resolve()
    return (p / "bin" / "brain").is_file() and (p / "teambrain" / "index.py").is_file()
