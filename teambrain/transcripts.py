"""Read Claude Code session transcripts from one explicitly configured project directory.

Shared by the optional chat index source and the retro digest. Keeps only what a human typed,
the assistant text just before each message (context for corrections), interrupts and denied
tool calls. Subagent (sidechain) and meta entries are skipped.

Event = (timestamp, kind, text, assistant_context) with kind in USER | INTERRUPT | DENIED.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

CTX_CHARS = 400
SKIP_COMMANDS = {"/mcp", "/clear", "/exit", "/model", "/config", "/resume", "/status", "/cost"}


def project_transcript_pattern(pattern):
    """One directory of ``*.jsonl`` files, or None when the pattern is missing or spans directories.

    ``~/.claude/projects/<one-project>/*.jsonl`` is accepted. A wildcard in any earlier
    component, a ``..`` component, or the ``~/.claude/projects`` directory itself is not.
    """
    if not pattern or not str(pattern).strip():
        return None
    raw = os.path.expanduser(str(pattern).strip())
    if not os.path.isabs(raw):
        return None
    path = Path(raw)
    if ".." in path.parts:
        return None
    if any(ch in part for part in path.parts[:-1] for ch in "*?["):
        return None
    name = path.name
    if any(ch in name for ch in "*?["):
        if name != "*.jsonl":
            return None
        parent = path.parent
    else:
        parent = path
        name = "*.jsonl"
    if parent.name == "projects" and parent.parent.name == ".claude":
        return None
    return str(parent / name)


def parse_ts(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def parse(path):
    """{"id", "titles", "events", "cwd"} for one transcript; unreadable lines are skipped."""
    sid = os.path.basename(path)
    sid = sid[:-6] if sid.endswith(".jsonl") else sid
    s = {"id": sid, "titles": [], "events": [], "cwd": None}
    last_asst = ""
    with open(path, errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get("type")
            if t == "custom-title" and d.get("customTitle") not in s["titles"]:
                s["titles"].append(d["customTitle"])
            if t == "ai-title" and not s["titles"]:
                s["titles"].append(d.get("aiTitle"))
            if t == "assistant":
                txt = text_of((d.get("message") or {}).get("content", []))
                if txt.strip():
                    last_asst = txt.strip()
                continue
            if t != "user" or d.get("isMeta") or d.get("isSidechain"):
                continue
            c, ts = (d.get("message") or {}).get("content"), d.get("timestamp")
            origin = (d.get("origin") or {}).get("kind")
            ev = None
            if isinstance(c, list):
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result" and b.get("is_error"):
                        r = b.get("content")
                        r = text_of(r) if isinstance(r, list) else str(r)
                        if "rejected" in r or "denied" in r.lower() or "doesn't want" in r:
                            ev = ("DENIED", " ".join(r.split())[:200])
                    if b.get("type") == "text" and "[Request interrupted" in b.get("text", ""):
                        ev = ("INTERRUPT", "")
            if origin == "human" or (origin is None and isinstance(c, str) and "<command-name>" in c):
                txt = text_of(c).strip()
                if txt.startswith("<command-name>"):
                    m = re.search(r"<command-name>(.*?)</command-name>.*?<command-args>(.*?)</command-args>", txt, re.S)
                    txt = f"{m.group(1)} {m.group(2)}".strip() if m else txt
                    if txt.split(" ")[0] in SKIP_COMMANDS:
                        continue
                if txt:
                    ev = ("USER", txt)
            if ev and ts:
                s["events"].append((ts, ev[0], ev[1], last_asst[-CTX_CHARS:] if ev[0] == "USER" else ""))
                s["cwd"] = s["cwd"] or d.get("cwd")
    return s


def title(s):
    return " → ".join(t for t in s["titles"] if t) or "untitled"


def chat_docs(pattern, min_words=4, label="User"):
    """One pseudo-document per session per local day: the typed messages, each with a little assistant context.

    {key: {"text", "title", "session", "day"}}; key = chat/<session prefix>/<day>.
    A pattern that is not a single project directory yields no documents.
    """
    import glob
    scoped = project_transcript_pattern(pattern)
    if scoped is None:
        return {}
    docs = {}
    for p in sorted(glob.glob(scoped)):
        try:
            s = parse(p)
        except OSError:
            continue
        days = {}
        for ts, kind, txt, ctx in s["events"]:
            if kind != "USER" or len(txt.split()) < min_words:
                continue
            day = parse_ts(ts).astimezone().strftime("%Y-%m-%d")
            msg = f"{label}: {txt[:1500]}"
            if ctx:
                msg += f"\n(assistant before: …{ctx[-250:]})"
            days.setdefault(day, []).append(msg)
        for day, msgs in days.items():
            docs[f"chat/{s['id'][:8]}/{day}"] = {"text": "\n\n".join(msgs), "title": title(s),
                                                  "session": s["id"], "day": day}
    return docs
