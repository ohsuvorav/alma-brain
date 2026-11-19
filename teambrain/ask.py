"""Debug search. Prints the context a prompt hook would inject. Alma does not answer.

Wiki may be empty; raw notes are enough. The command never calls an LLM.
"""
import sys

from teambrain import config as cfgmod
from teambrain.passages import display_text


def format_passages(results):
    from teambrain.search import header
    parts = []
    for score, row in results:
        parts.append(f"{header(row, score)}\n{display_text(row.get('text', ''))}")
    return "\n\n".join(parts)


def retrieve(cfg, question):
    from teambrain import search as core
    limit = cfg["retrieval"]["limit"]
    per_file = cfg["retrieval"]["max_per_file"]
    floor = cfg["retrieval"]["min_score"]
    results = core.search(cfg, question, limit, per_file, floor)
    low = False
    if not results:
        results = core.search(cfg, question, limit, per_file, 0.0)
        low = bool(results)
    return results, low


def answer(cfg, question, retrieve_fn=None):
    """(text, exit code). Exit 0 when there is nothing to show except a fix line."""
    if not cfg.db_path.exists():
        return "No index yet.\nfix: brain index\n", 0
    try:
        results, _low = (retrieve_fn or retrieve)(cfg, question)
    except Exception as exc:
        return f"Search failed ({exc}).\nfix: brain index\n", 0
    if not results:
        return "No notes are indexed yet.\nfix: brain init <path-to-notes>\n", 0
    return "Context Alma would inject:\n\n" + format_passages(results) + "\n", 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv or argv == ["-h"] or argv == ["--help"]:
        print('brain ask "your question"')
        return 0 if argv else 2
    question = " ".join(argv).strip()
    if not question:
        print('brain ask "your question"')
        return 2
    cfg = cfgmod.load()
    if cfg is None:
        print("Not inside a brain (no teambrain.yaml).\nfix: brain init <path-to-notes>")
        return 1
    text, code = answer(cfg, question)
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
