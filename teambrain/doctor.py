"""Check that this brain can give an agent context. Exit non-zero when a required check fails.

Each problem is one line saying what is wrong and one line with a fix command.
Hooks and the scheduler are reported and do not fail the run.
"""
import os
import shutil
import sys
from pathlib import Path

from teambrain import config as cfgmod


class Check:
    def __init__(self, ok, detail, fix=""):
        self.ok = bool(ok)
        self.detail = detail
        self.fix = fix or ""


def python_status():
    v = sys.version_info
    label = f"python {v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 10):
        return Check(True, label)
    return Check(False, f"{label} is older than 3.10", "install Python 3.10+ and run brain setup")


def venv_status():
    root = Path(os.environ.get("TEAMBRAIN_VENV") or Path.home() / ".team-brain" / "venv")
    if not (root / "bin" / "python").is_file():
        return Check(False, f"venv missing at {root}", "brain setup")
    missing = []
    for name in ("fastembed", "lancedb", "yaml"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        return Check(False, "venv is missing " + ", ".join(missing), "brain setup")
    return Check(True, f"venv {root}")


def model_cached(cfg):
    cache = cfg.model_cache
    name = cfg["index"]["embed_model"]
    if not cache.is_dir():
        return False
    slug = cache / ("models--" + name.replace("/", "--"))
    if slug.is_dir() and any(slug.rglob("*.onnx")):
        return True
    token = name.split("/")[-1]
    return any(p.suffix == ".onnx" and token in str(p) for p in cache.rglob("*.onnx"))


def model_status(cfg):
    name = cfg["index"]["embed_model"]
    if model_cached(cfg):
        return Check(True, f"embedding model {name}")
    return Check(False, f"embedding model not downloaded ({name})", "brain index")


def index_status(cfg):
    from teambrain import index as idx
    from teambrain.search import passage_prefix, query_prefix
    if not cfg.db_path.exists():
        return Check(False, "index missing", "brain index")
    manifest = idx._read_manifest(cfg)
    if not isinstance(manifest.get("files"), dict):
        return Check(False, "index has no manifest", "brain index")
    if manifest.get("embed_model") != cfg["index"]["embed_model"]:
        return Check(False, "index was built with a different embedding model", "brain index")
    if manifest.get("schema") != idx.SCHEMA_VERSION:
        return Check(False, "index schema is out of date", "brain index")
    if (manifest.get("query_prefix", "") != query_prefix(cfg)
            or manifest.get("passage_prefix", "") != passage_prefix(cfg)):
        return Check(False, "index was built with different embedding prefixes", "brain index")
    if manifest.get("text_prep") != idx.TEXT_PREP:
        return Check(False, "index still stores raw frontmatter", "brain index")
    try:
        current = idx.corpus_hashes(cfg)
    except Exception as exc:
        return Check(False, f"index could not be checked ({exc})", "brain index")
    if manifest.get("files") != current:
        return Check(False, "index is stale", "brain index")
    try:
        from teambrain.search import open_table
        open_table(cfg)
    except Exception:
        return Check(False, "index cannot be opened", "brain index")
    return Check(True, f"index fresh ({len(current)} files)")


def yaml_status(cfg):
    path = cfg.root / cfgmod.CONFIG_NAME
    if not path.is_file():
        return Check(False, "teambrain.yaml missing", "brain init <path-to-notes>")
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        editor = os.environ.get("EDITOR") or "vi"
        return Check(False, f"teambrain.yaml is not valid YAML ({exc.__class__.__name__})", f"{editor} {path}")
    if not isinstance(data, dict):
        editor = os.environ.get("EDITOR") or "vi"
        return Check(False, "teambrain.yaml must be a mapping", f"{editor} {path}")
    index = data.get("index", {}) or {}
    editor = os.environ.get("EDITOR") or "vi"
    if not isinstance(index, dict):
        return Check(False, "index must be a mapping", f"{editor} {path}")
    if "dirs" in index and not isinstance(index["dirs"], list):
        return Check(False, "index.dirs must be a list", f"{editor} {path}")
    if "embed_model" in index and not isinstance(index["embed_model"], str):
        return Check(False, "index.embed_model must be a string", f"{editor} {path}")
    extras = index.get("extra_dirs", [])
    if not isinstance(extras, list) or any(not isinstance(item, dict) or not item.get("path") for item in extras):
        return Check(False, "index.extra_dirs entries need a path", f"{editor} {path}")
    return Check(True, "teambrain.yaml valid")


def mcp_status(cfg):
    from teambrain.connect import connected
    if connected(cfg):
        return Check(True, "mcp connected (claude)")
    return Check(True, "mcp not connected (optional)", "brain init --yes <path-to-notes>")


def prompt_hook_status(cfg):
    from teambrain.connect import hook_installed
    if hook_installed(cfg):
        return Check(True, "prompt hook installed")
    return Check(True, "prompt hook not installed (optional)", "brain init --yes <path-to-notes>")


def scheduler_status(cfg):
    try:
        from teambrain import schedule
        specs = schedule.jobs(cfg)
        installed = schedule.installed_job_count(cfg)
        if installed is None:
            return Check(True, "scheduler not installed (optional)")
        if installed:
            return Check(True, f"scheduler installed ({installed} jobs)")
        if specs:
            return Check(True, "scheduler configured, not installed (optional)")
        return Check(True, "scheduler not installed (optional)")
    except Exception:
        return Check(True, "scheduler not installed (optional)")


def source_checks(cfg):
    missing = []
    for rel in cfg["index"]["dirs"]:
        path = cfg.root / rel
        if not path.exists():
            missing.append(Check(False, f"source missing: {path}", f"mkdir -p {path}"))
    for extra in cfg["index"]["extra_dirs"]:
        raw = str(extra.get("path", "")).strip()
        path = Path(raw).expanduser() if raw else Path("")
        if not raw or not path.exists():
            shown = str(path) if raw else "(empty path)"
            missing.append(Check(False, f"source missing: {shown}", f"brain init {shown} --in-place --yes"))
    if missing:
        return missing
    return [Check(True, "sources present")]


def diagnose(cfg):
    checks = [python_status(), venv_status()]
    if cfg is None:
        checks.append(Check(False, "not inside a brain (no teambrain.yaml)", "brain init <path-to-notes>"))
        return checks
    checks.extend([
        model_status(cfg),
        index_status(cfg),
        yaml_status(cfg),
        mcp_status(cfg),
        prompt_hook_status(cfg),
        scheduler_status(cfg),
        *source_checks(cfg),
    ])
    return checks


def format_report(checks):
    lines = []
    fails = 0
    for check in checks:
        if check.ok:
            lines.append(f"ok    {check.detail}")
            if check.fix:
                lines.append(f"      fix: {check.fix}")
            continue
        fails += 1
        lines.append(f"fail  {check.detail}")
        if check.fix:
            lines.append(f"      fix: {check.fix}")
    if fails and any(c.fix.startswith("brain ") for c in checks if not c.ok) and shutil.which("brain") is None:
        lines.append("note  brain is not on PATH in this terminal. From this checkout run it as ./brain (for example ./brain index). A new terminal can use brain.")
    if fails:
        word = "problem" if fails == 1 else "problems"
        lines.append(f"brain doctor: {fails} {word}")
    else:
        lines.append("brain doctor: ok")
    return "\n".join(lines) + "\n"


def exit_code(checks):
    return 1 if any(not check.ok for check in checks) else 0


def main(argv=None):
    del argv
    try:
        cfg = cfgmod.load()
    except Exception as exc:
        checks = [
            python_status(),
            venv_status(),
            Check(False, f"teambrain.yaml is not valid YAML ({exc.__class__.__name__})",
                  "brain init <path-to-notes>"),
        ]
    else:
        checks = diagnose(cfg)
    sys.stdout.write(format_report(checks))
    return exit_code(checks)


if __name__ == "__main__":
    sys.exit(main())
