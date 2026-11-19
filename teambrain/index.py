"""Chunk and embed the brain's markdown into LanceDB.

    brain index                  # full rebuild for the brain containing cwd
    brain index --incremental    # re-embed only changed files (used by the SessionStart hook)
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from teambrain import config as cfgmod


def note_extensions(cfg):
    raw = cfg["index"].get("extensions") or [".md", ".txt"]
    out = set()
    for ext in raw:
        ext = str(ext).lower()
        if not ext.startswith("."):
            ext = "." + ext
        out.add(ext)
    return out


def iter_notes(folder, extensions, skip):
    """Markdown and text notes under folder, skipping symlinks and index.skip path fragments."""
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if p.suffix.lower() not in extensions:
            continue
        if any(s in str(p) for s in skip):
            continue
        yield p


def fingerprint(cfg):
    """Canonical corpus fingerprint over root-relative index dirs; no embeddings or downloads."""
    h = hashlib.sha256()
    root = cfg.root
    exts = note_extensions(cfg)
    skip = cfg["index"]["skip"]
    for folder, forced in cfg.index_dirs():
        if forced is not None or not folder.exists():
            continue  # extra dirs live outside the brain and are not canonical
        for p in iter_notes(folder, exts, skip):
            try:
                if not p.resolve().is_relative_to(root):
                    continue
            except OSError:
                continue
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def chunk_file(cfg, path, forced_type=None):
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return []
    from teambrain.passages import strip_frontmatter
    text = strip_frontmatter(text)
    if not text.strip():
        return []

    rel = rel_key(cfg, path)
    return chunk_text(cfg, text, rel, forced_type or cfg.source_type(rel))


def chunk_text(cfg, text, rel, src_type, heading="", session=""):
    """Paragraph-packed chunks of at most chunk_size chars; text stays verbatim (the query adapter checks it)."""
    size = cfg["index"]["chunk_size"]

    chunks, current = [], ""
    for para in re.split(r"\n{2,}", text.strip()):
        para = para.strip()
        if not para:
            continue
        if re.match(r"^#{1,4}\s", para):
            heading = re.sub(r"^#{1,4}\s+", "", para).strip()
        if len(current) + len(para) + 2 > size and current:
            chunks.append({"text": current.strip(), "file": rel, "heading": heading,
                           "source_type": src_type, "session": session})
            current = para + "\n\n"
        else:
            current += para + "\n\n"
    if current.strip():
        chunks.append({"text": current.strip(), "file": rel, "heading": heading,
                       "source_type": src_type, "session": session})
    return chunks


def rel_key(cfg, path):
    """The `file` value stored on chunks: root-relative, or absolute for extra dirs outside the root."""
    try:
        return str(path.relative_to(cfg.root))
    except ValueError:
        return str(path)


def collect_files(cfg):
    """[(path, forced_type)] for every indexable note (.md and .txt by default)."""
    skip = cfg["index"]["skip"]
    exts = note_extensions(cfg)
    out = []
    for dir_path, forced in cfg.index_dirs():
        if not dir_path.exists():
            continue
        for path in iter_notes(dir_path, exts, skip):
            out.append((path, forced))
    return out


def collect_chunks(cfg, files=None):
    out = []
    for md, forced in (files if files is not None else collect_files(cfg)):
        out.extend(chunk_file(cfg, md, forced))
    return out


def file_hashes(cfg, files):
    hashes = {}
    for md, _ in files:
        try:
            hashes[rel_key(cfg, md)] = hashlib.sha256(md.read_bytes()).hexdigest()
        except OSError:
            continue
    return hashes


def diff_files(old, new):
    """(changed_or_added, removed) file keys between two {file: sha256} maps."""
    changed = sorted(k for k, h in new.items() if old.get(k) != h)
    removed = sorted(k for k in old if k not in new)
    return changed, removed


def chat_docs(cfg):
    c = cfg["index"].get("chats") or {}
    if not c.get("enabled"):
        return {}
    from teambrain.transcripts import chat_docs as read
    # No default glob: an empty or cross-project pattern indexes nothing.
    return read(c.get("glob") or "", c.get("min_words", 4), c.get("label", "User"))


def chat_chunks(cfg, docs, keys=None):
    out = []
    for key, d in docs.items():
        if keys is None or key in keys:
            out.extend(chunk_text(cfg, d["text"], key, "chat", heading=d["title"][:200], session=d["session"]))
    return out


def create_fts(table):
    """Full-text index on chunk text, used by retrieval.keyword_boost. Optional: failures leave vector-only search."""
    try:
        from lancedb.index import FTS
        table.create_index("text", config=FTS(), replace=True)
    except Exception:
        try:
            table.create_fts_index("text", replace=True)
        except Exception:
            pass


def _lock(cfg):
    """Non-blocking exclusive lock in the state dir; None when another indexer holds it."""
    import fcntl
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    f = open(cfg.state_dir / ".index.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def _schema(cfg):
    import pyarrow as pa
    return pa.schema([
        pa.field("text", pa.string()),
        pa.field("file", pa.string()),
        pa.field("heading", pa.string()),
        pa.field("source_type", pa.string()),
        pa.field("session", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), list_size=cfg["index"]["vector_dim"])),
    ])


def _embed(cfg, chunks):
    from teambrain.search import embed_texts
    vectors = embed_texts(cfg, [c["text"] for c in chunks], "passage")
    dim = cfg["index"]["vector_dim"]
    rows = []
    for c, v in zip(chunks, vectors):
        if len(v) != dim:
            raise ValueError(
                f"Model {cfg['index']['embed_model']} produced dimension {len(v)}, "
                f"but index.vector_dim is {dim}. Set vector_dim: {len(v)} in teambrain.yaml and run brain index."
            )
        rows.append({**c, "vector": v})
    return rows


SCHEMA_VERSION = 3  # 2 = chunks carry `session`; 3 = unit-normalized vectors. Older indexes get a full rebuild
TEXT_PREP = 1  # chunks are stored without YAML frontmatter. Older indexes get a full rebuild.


def corpus_hashes(cfg, files=None, chats=None):
    """{file key: sha256} for notes and enabled chat docs. The manifest and doctor share this."""
    if files is None:
        files = collect_files(cfg)
    if chats is None:
        chats = chat_docs(cfg)
    hashes = file_hashes(cfg, files)
    hashes.update({k: hashlib.sha256(d["text"].encode()).hexdigest() for k, d in chats.items()})
    return hashes


def can_increment(old, cfg):
    """False when the manifest is missing or the model, prefixes, or schema changed.

    A model change (or an e5 prefix change) falls through to a full rebuild.
    """
    from teambrain.search import passage_prefix, query_prefix
    if not isinstance(old, dict) or not isinstance(old.get("files"), dict):
        return False
    return (old.get("schema") == SCHEMA_VERSION
            and old.get("text_prep") == TEXT_PREP
            and old.get("embed_model") == cfg["index"]["embed_model"]
            and old.get("query_prefix", "") == query_prefix(cfg)
            and old.get("passage_prefix", "") == passage_prefix(cfg))


def _write_manifest(cfg, fingerprint_value, files):
    from teambrain.search import passage_prefix, query_prefix
    manifest = {"fingerprint": fingerprint_value, "built_at": datetime.now(timezone.utc).isoformat(),
                "schema": SCHEMA_VERSION,
                "text_prep": TEXT_PREP,
                "embed_model": cfg["index"]["embed_model"],
                "query_prefix": query_prefix(cfg),
                "passage_prefix": passage_prefix(cfg),
                "files": files}
    tmp = cfg.manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest))
    tmp.replace(cfg.manifest_path)


def _read_manifest(cfg):
    try:
        return json.loads(cfg.manifest_path.read_text())
    except (OSError, ValueError):
        return {}


def build_index(cfg, verbose=True, incremental=False):
    """Full rebuild, or with incremental=True re-embed only files whose content changed.

    Incremental falls back to a full rebuild when there is no table yet, no per-file manifest,
    or the embedding model changed. Returns the number of chunks embedded.
    """
    import lancedb

    lock = _lock(cfg)
    if lock is None:
        if verbose:
            print("Index already running; skipped.")
        return 0
    try:
        before = fingerprint(cfg)
        files = collect_files(cfg)
        chats = chat_docs(cfg)
        hashes = corpus_hashes(cfg, files, chats)
        db = lancedb.connect(str(cfg.db_path))
        old = _read_manifest(cfg)
        table = None
        if incremental and can_increment(old, cfg):
            try:
                table = db.open_table("chunks")
            except Exception:
                table = None

        if table is not None:
            changed, removed = diff_files(old["files"], hashes)
            if changed or removed:
                stale = changed + removed
                for i in range(0, len(stale), 200):
                    table.delete("file IN (%s)" % ",".join("'%s'" % k.replace("'", "''") for k in stale[i:i + 200]))
                wanted = set(changed)
                chunks = collect_chunks(cfg, [(p, t) for p, t in files if rel_key(cfg, p) in wanted])
                chunks += chat_chunks(cfg, chats, wanted)
                if chunks:
                    table.add(_embed(cfg, chunks))
                create_fts(table)
            else:
                chunks = []
            _write_manifest(cfg, before, hashes)
            if verbose:
                print(f"Index updated: {len(changed)} changed, {len(removed)} removed, {len(chunks)} chunks embedded")
            return len(chunks)

        chunks = collect_chunks(cfg, files) + chat_chunks(cfg, chats)
        if not chunks:
            print("No notes found to index.")
            return 0
        if verbose:
            from teambrain.search import passage_prefix, query_prefix
            print(f"Embedding model {cfg['index']['embed_model']} "
                  f"(query prefix {query_prefix(cfg)!r}, passage prefix {passage_prefix(cfg)!r})")
            print(f"Indexing {len(chunks)} chunks from {len({c['file'] for c in chunks})} files...")
        rows = _embed(cfg, chunks)
        # mode="overwrite" replaces atomically; list_tables() membership broke in lancedb 0.33.
        table = db.create_table("chunks", data=rows, schema=_schema(cfg), mode="overwrite")
        create_fts(table)
        _write_manifest(cfg, before, hashes)
        if verbose:
            print(f"Index built: {len(rows)} chunks in {cfg.db_path}")
        return len(rows)
    finally:
        lock.close()


if __name__ == "__main__":
    cfg = cfgmod.load()
    if cfg is None:
        sys.exit("Not inside a brain (no teambrain.yaml found; set BRAIN_ROOT).")
    build_index(cfg, incremental="--incremental" in sys.argv[1:])
