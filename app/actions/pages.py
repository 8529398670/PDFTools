"""Page lists a person types, such as "1-3, 7, 10-", read the same way by
every action that takes one and by its browser twin (static/js/local/pages.js).

Pages count from 1. "" or "all" is every page. A range left open at either
end runs to that end ("-3" is 1-3, "10-" is 10 to the last page). A page past
the last is an error, not silently dropped, so a typo is caught.
"""
from __future__ import annotations

import re

from app.actions import ActionError

_PART = re.compile(r"^\s*(\d*)\s*(-\s*(\d*))?\s*$")


def parse_pages(text: str, page_count: int) -> list[int]:
    """The pages text names, from 0, in order, each once."""
    text = (text or "").strip().lower()
    if text in ("", "all"):
        return list(range(page_count))
    chosen: set[int] = set()
    for part in text.split(","):
        if not part.strip():
            continue
        match = _PART.match(part)
        if match is None or (not match.group(1) and not match.group(3)):
            raise ActionError("bad_pages")
        first = int(match.group(1)) if match.group(1) else 1
        if match.group(2):
            last = int(match.group(3)) if match.group(3) else page_count
        else:
            last = first
        if first < 1 or last < first or last > page_count:
            raise ActionError("bad_pages")
        chosen.update(range(first - 1, last))
    if not chosen:
        raise ActionError("bad_pages")
    return sorted(chosen)


def stem(name: str) -> str:
    """A file name without its .pdf, for naming what is made from it."""
    base = name.rsplit("/", 1)[-1]
    return base[:-4] if base.lower().endswith(".pdf") else (base or "document")
