"""MCP server (stdio) for the brain containing cwd / BRAIN_ROOT.

Tools:
  <search_tool>          semantic search over indexed markdown (name set in teambrain.yaml)
  rebuild_index          re-embed and reindex after content changes
  check_stale_principles [YYYY-MM] principle entries older than N days
"""
import re
import sys
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from teambrain import config as cfgmod
from teambrain import search as core

DEFAULT_DESCRIPTION = """Semantic search over the brain: wiki, raw logs, private facts and memory files.

ALWAYS call this before asking the user for context the brain may already hold
(decisions, principles, project status, people, history).

If the result starts with "NOT_INDEXED:" the topic is not in the brain.
Do NOT guess. Say it is not stored and offer to capture it.

Args:
    query: what context you need; expand with synonyms and related concepts.
    limit: number of chunks to return (default 8)
    max_per_file: max chunks from one file (default 2)
    min_score: minimum relevance (default 0.35); lower scores are noise.
"""

cfg = cfgmod.load()
if cfg is None:
    sys.exit("team-brain MCP: not inside a brain (no teambrain.yaml found; set BRAIN_ROOT).")

mcp = FastMCP("team-brain")


def search_brain(query: str, limit: int = 8, max_per_file: int = 2, min_score: float = 0.35) -> str:
    try:
        table = core.open_table(cfg)
    except Exception:
        return "Index not found. Rebuild it: brain index"
    results = core.search(cfg, query, limit, max_per_file, min_score, table=table)
    if not results:
        return (f"NOT_INDEXED: no confident match for '{query}' (all scores below {min_score}). "
                "Do not guess — ask the user or suggest capturing this.")
    from teambrain.passages import display_text
    return "\n\n".join(f"{core.header(r, s)}\n{display_text(r['text'])}\n---" for s, r in results)


mcp.tool(name=cfg["mcp"]["search_tool"],
         description=cfg["mcp"]["search_description"] or DEFAULT_DESCRIPTION)(search_brain)


@mcp.tool()
def rebuild_index() -> str:
    """Rebuild the brain search index from scratch. Call after significant wiki/ or raw/ changes."""
    try:
        from teambrain.index import build_index
        build_index(cfg, verbose=False)
        return "Index rebuilt successfully."
    except Exception as e:
        return f"Index rebuild failed: {e}"


@mcp.tool()
def check_stale_principles(threshold_days: int = 90) -> str:
    """Scan principles files for [YYYY-MM] entries older than threshold_days.

    Args:
        threshold_days: flag entries older than this many days (default 90)
    """
    stale, now = [], datetime.now()
    for path in sorted(cfg.root.glob(cfg["principles_glob"])):
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        rel = str(path.relative_to(cfg.root))
        for line in text.splitlines():
            m = re.search(r"\[(\d{4}-\d{2})\]\s+(.+)", line)
            if not m:
                continue
            try:
                year, month = map(int, m[1].split("-"))
                age = (now - datetime(year, month, 1)).days
            except ValueError:
                continue
            if age >= threshold_days:
                stale.append((age, m[1], rel, m[2].strip()))

    if not stale:
        return f"No principles older than {threshold_days} days found."
    stale.sort(reverse=True)
    lines = [f"Stale principles (>{threshold_days} days) — {len(stale)} found:\n"]
    for age, date_str, rel, principle in stale:
        lines.append(f"  [{date_str}] {rel}  ({age // 30}mo ago)")
        lines.append(f"    {principle[:120]}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
