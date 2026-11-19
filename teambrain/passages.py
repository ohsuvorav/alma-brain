"""Turn a note into the text an agent should see.

Frontmatter is dropped before a chunk is stored, so the body stays a verbatim
slice of the file. Wikilinks are left in the index and rewritten when a passage
is shown, because the query adapter checks that stored text still occurs in the file.
"""
import re

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*\r?\n?", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\[\]\n]+?)\]\]")


def strip_frontmatter(text):
    if not text or not text.startswith("---"):
        return text or ""
    match = _FRONTMATTER.match(text)
    return text[match.end():] if match else text


def plain_wikilinks(text):
    """[[page]], [[page#heading]], and [[page|label]] become readable words."""
    def repl(match):
        body = match.group(1).strip()
        if "|" in body:
            return body.split("|", 1)[1].strip()
        return body.split("#", 1)[0].strip()

    return _WIKILINK.sub(repl, text or "")


def display_text(text):
    return plain_wikilinks(strip_frontmatter(text or "")).strip()
