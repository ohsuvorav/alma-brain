"""Claude Code hooks. All fail silently — they must never block a message.

    brain hook-search          UserPromptSubmit: inject top chunks as additionalContext
    brain hook-stop            Stop: append the last assistant reply to the trace log
    brain hook-session-start   SessionStart: offer `brain onboard` until this person has onboarded
                               (the launcher also starts the incremental re-index)
"""
import datetime
import json
import os
import sys

from teambrain import config as cfgmod

MAX_RESPONSE = 1000


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _append(path, entry):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _prompt(data):
    message = data.get("prompt") or data.get("message") or data.get("content") or ""
    if isinstance(message, list):
        message = " ".join(b.get("text", "") for b in message if isinstance(b, dict))
    return str(message).strip()


def skip_prompt(message, r):
    """True for prompts that carry no retrievable intent: very short ones and, optionally, slash commands."""
    if len(message) < 8:
        return True
    if r.get("skip_slash_commands") and message.startswith("/"):
        return True
    return len(message.split()) < (r.get("min_words") or 0)


def on_prompt(data):
    cfg = cfgmod.load(data.get("cwd"))
    if cfg is None:
        return
    r = cfg["retrieval"]
    if any(os.environ.get(v) == "1" for v in r["skip_env"]):
        return
    message = _prompt(data)
    if skip_prompt(message, r):
        return

    from teambrain import search as core
    results = core.search(cfg, message[:2000], r["limit"], r["max_per_file"], r["min_score"],
                          exclude_session=data.get("session_id") or None)
    if not results:
        return

    from teambrain.passages import display_text
    parts = [f"{core.header(row, s)}\n{display_text(row['text'])[:r['preview_chars']]}" for s, row in results]
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": r["header"] + "\n" + "\n---\n".join(parts),
    }}))

    try:
        now, top = _now(), round(results[0][0], 3)
        _append(cfg.hook_log, {"ts": now, "query": message[:80], "hits": len(results), "top_score": top,
                               "files": [row["file"].split("/")[-1] for _, row in results]})
        _append(cfg.trace_log, {
            "ts": now, "session_id": data.get("session_id", ""), "type": "search",
            "query": message[:200], "hits": len(results), "top_score": top,
            "context": [{"file": row["file"], "heading": row.get("heading") or "",
                         "score": round(s, 3), "text": display_text(row["text"])[:400]} for s, row in results],
        })
    except Exception:
        pass


def _text(content):
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content or "")


def last_response(data):
    """Last assistant text. Claude Code sends transcript_path (JSONL), not the messages."""
    if data.get("last_assistant_message"):
        return _text(data["last_assistant_message"]).strip()
    path = data.get("transcript_path")
    if path and os.path.isfile(path):
        last = ""
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                msg = entry.get("message") if isinstance(entry.get("message"), dict) else entry
                if entry.get("type") == "assistant" or msg.get("role") == "assistant":
                    text = _text(msg.get("content")).strip()
                    if text:
                        last = text
        return last
    for key in ("conversation", "messages", "transcript"):
        msgs = data.get(key)
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if isinstance(m, dict) and m.get("role") == "assistant":
                    return _text(m.get("content")).strip()
    return ""


def on_stop(data):
    cfg = cfgmod.load(data.get("cwd"))
    session_id = data.get("session_id", "")
    if cfg is None or not session_id:
        return
    response = last_response(data)
    if response:
        _append(cfg.trace_log, {"ts": _now(), "session_id": session_id,
                                "type": "response", "response": response[:MAX_RESPONSE]})


def session_start_message(cfg, brain):
    """additionalContext offering onboarding, or None when there is nothing to offer."""
    from teambrain import onboard
    if onboard.schedule_failed(cfg):
        return (f"The {cfg['name']} onboarding answers are saved, but the nightly jobs were not installed "
                f"(the scheduler was missing). In your first reply, briefly offer to install them: "
                f"they type `! {brain} schedule install` once cron (Linux) or launchd is available. "
                "Don't run it without their yes. Offer once per session.")
    if not cfg["onboarding"]["offer"] or onboard.onboarded(cfg):
        return None
    if not cfg["onboarding"]["questions"] and cfg.db_path.exists():
        return None
    return (f"The {cfg['name']} brain is not set up for this person yet (no onboarding answers"
            f"{'' if cfg.db_path.exists() else ', no search index'}). In your first reply, briefly offer to run it: "
            f"they type `! {brain} onboard` (a few minutes; it builds the index and asks a few yes/no questions). "
            "Don't run it without their yes. Offer once per session.")


def on_session_start(data):
    cfg = cfgmod.load(data.get("cwd"))
    if cfg is None:
        return
    brain = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "brain")
    msg = session_start_message(cfg, brain)
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))


if __name__ == "__main__":
    try:
        handler = {"search": on_prompt, "stop": on_stop, "session-start": on_session_start}[sys.argv[1]]
        handler(json.loads(sys.stdin.read()))
    except Exception:
        pass  # never block the user's message
