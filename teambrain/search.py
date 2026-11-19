"""Shared retrieval core for the hook, the MCP server and the query adapter."""
import os
import re

_models = {}

# Exact terms the embedding tends to miss: ticket-style keys (ABC-123) and longer words/identifiers.
_TERMS = re.compile(r"[A-Z]{2,}-\d+|[\w-]{4,}")


# fastembed 0.9 does not ship this model and does not apply E5 prefixes itself.
_E5_SMALL = "intfloat/multilingual-e5-small"


def _auto_prefixes(model_name):
    leaf = str(model_name).lower().rsplit("/", 1)[-1]
    if "e5" in leaf:
        return "query: ", "passage: "
    return "", ""


def query_prefix(cfg):
    raw = cfg["index"].get("embed_query_prefix", None)
    if raw is not None:
        return str(raw)
    return _auto_prefixes(cfg["index"]["embed_model"])[0]


def passage_prefix(cfg):
    raw = cfg["index"].get("embed_passage_prefix", None)
    if raw is not None:
        return str(raw)
    return _auto_prefixes(cfg["index"]["embed_model"])[1]


def apply_prefix(prefix, text):
    if not prefix or text.startswith(prefix):
        return text
    return prefix + text


def ensure_supported_model(name):
    """Register multilingual-e5-small when this fastembed build does not list it."""
    if name != _E5_SMALL:
        return
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    known = {m["model"].lower() for m in TextEmbedding.list_supported_models()}
    if name.lower() in known:
        return
    TextEmbedding.add_custom_model(
        model=name,
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf=name),
        dim=384,
        model_file="onnx/model.onnx",
        description="Multilingual E5 small. The engine adds query: and passage: prefixes.",
        license="mit",
        size_in_gb=0.45,
    )


def model(cfg):
    name = cfg["index"]["embed_model"]
    if name not in _models:
        from fastembed import TextEmbedding
        ensure_supported_model(name)
        _models[name] = TextEmbedding(name, cache_dir=str(cfg.model_cache),
                                      local_files_only=os.environ.get("HF_HUB_OFFLINE") == "1")
    return _models[name]


def embed_texts(cfg, texts, kind):
    """Unit vectors. `kind` is "query" or "passage"; E5 models get the matching prefix."""
    texts = list(texts)
    if not texts:
        return []
    prefix = query_prefix(cfg) if kind == "query" else passage_prefix(cfg)
    vectors = list(model(cfg).embed([apply_prefix(prefix, t) for t in texts]))
    if len(vectors) != len(texts):
        raise ValueError(f"embedder returned {len(vectors)} vectors for {len(texts)} texts")
    return [unit(v) for v in vectors]


def unit(vec):
    """L2-normalize. Scores are 1 - L2 distance, which assumes unit vectors; some fastembed models
    (e.g. paraphrase-multilingual-MiniLM) return unnormalized ones. A no-op for normalized models."""
    import math
    vec = [float(x) for x in vec]
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def open_table(cfg):
    import lancedb
    return lancedb.connect(str(cfg.db_path)).open_table("chunks")


def _key(row):
    return (row.get("file"), row.get("heading"), (row.get("text") or "")[:200])


def keyword_hits(table, query, k):
    """Keys of rows matching the query's exact terms via the full-text index; empty if there is none."""
    terms = " ".join(_TERMS.findall(query)[:12])
    if not terms:
        return set()
    try:
        return {_key(r) for r in table.search(terms, query_type="fts").limit(k).to_list()}
    except Exception:
        return set()  # no FTS index (older index or lancedb without FTS): vector-only


def rank(candidates, min_score, max_per_file, limit, keyword_keys=(), keyword_boost=0.0,
         type_weights=None, relative_window=None, exclude_session=None):
    """Pure scoring step, split out so it can be tested without a model.

    score = 1 - distance, + keyword_boost for exact-term matches, + type_weights[source_type].
    A hit survives when score >= min_score and, if relative_window is set, score >= best - relative_window
    (drops the long tail of weak hits when one strong hit exists). Rows from exclude_session are dropped
    so a chat never retrieves itself.
    """
    type_weights = type_weights or {}
    scored = []
    for r in candidates:
        if exclude_session and r.get("session") == exclude_session:
            continue
        score = 1 - r.get("_distance", 0)
        if keyword_boost and _key(r) in keyword_keys:
            score += keyword_boost
        score += type_weights.get(r.get("source_type", "log"), 0.0)
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []
    floor = min_score
    if relative_window:
        floor = max(floor, scored[0][0] - relative_window)
    counts, results = {}, []
    for score, r in scored:
        if score < floor:
            break
        f = r["file"]
        if counts.get(f, 0) < max_per_file:
            results.append((score, r))
            counts[f] = counts.get(f, 0) + 1
        if len(results) >= limit:
            break
    return results


def search(cfg, query, limit, max_per_file, min_score, table=None, exclude_session=None):
    """[(score, row)] above min_score, at most max_per_file rows per file."""
    r = cfg["retrieval"]
    table = table or open_table(cfg)
    vec = embed_texts(cfg, [query], "query")[0]
    candidates = table.search(vec).limit(limit * max_per_file * 4).to_list()
    boost = r.get("keyword_boost") or 0.0
    keys = keyword_hits(table, query, limit * max_per_file * 2) if boost else set()
    return rank(candidates, min_score, max_per_file, limit, keyword_keys=keys, keyword_boost=boost,
                type_weights=r.get("type_weights"), relative_window=r.get("relative_window"),
                exclude_session=exclude_session)


def header(row, score):
    h = f"[{row.get('source_type', 'log')}] {row['file']}"
    if row.get("heading"):
        h += f" › {row['heading']}"
    return f"{h}  (relevance {round(score, 3)})"
