"""JSON stdin/stdout adapter for runtimes that inject recall explicitly (e.g. a chat bot). Read-only.

Never builds or downloads an index on behalf of a query.
stdin: {"query": "..."}  stdout: {"status": ok|stale|freshness_unknown|no_confident_match|index_missing|unavailable, "text": ...}
"""
import json
import os
import sys

from teambrain import config as cfgmod


def query(cfg, message):
    from teambrain.index import fingerprint
    if not cfg.db_path.exists():
        return {"status": "index_missing", "text": ""}
    status = "freshness_unknown"
    try:
        manifest = json.loads(cfg.manifest_path.read_text())
        status = "ok" if manifest["fingerprint"] == fingerprint(cfg) else "stale"
    except (OSError, ValueError, KeyError):
        pass
    # Offline mode prevents a conversational query fetching embedding models.
    os.environ["HF_HUB_OFFLINE"] = "1"
    from teambrain import search as core
    try:
        table = core.open_table(cfg)
    except Exception:
        return {"status": "index_missing", "text": ""}
    results = core.search(cfg, message[:4000], 5, 2, 0.35, table=table)
    if not results:
        return {"status": "no_confident_match" if status == "ok" else status, "text": "",
                "note": "No confident match; this does not prove the fact is absent."}
    # Never inject an old chunk as current knowledge; out-of-root sources are not canonical.
    kept = []
    for score, row in results:
        if row.get("source_type") == "chat":
            continue  # past chats are context for the prompt hook, never canonical recall
        p = (cfg.root / row["file"]).resolve()
        try:
            if p.is_relative_to(cfg.root) and row["text"].strip() in p.read_text():
                kept.append(f"{core.header(row, score)}\n{row['text']}")
            else:
                status = "stale"
        except OSError:
            status = "stale"
    return {"status": status, "text": "\n---\n".join(kept)[:10000]}


if __name__ == "__main__":
    try:
        cfg = cfgmod.load()
        request = json.load(sys.stdin)
        response = query(cfg, str(request.get("query", ""))) if cfg else {"status": "unavailable", "text": ""}
    except Exception:
        response = {"status": "unavailable", "text": ""}
    print(json.dumps(response, ensure_ascii=False))
