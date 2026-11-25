"""Shared watermark vocabulary."""

from __future__ import annotations

import re

#: Phrases the tool looks for without being asked. Reported at lower
#: confidence than user-supplied phrases -- the user asked for theirs.
BUILTIN_PHRASES: tuple[str, ...] = (
    "CONFIDENTIAL",
    "DO NOT COPY",
    "DO NOT DISTRIBUTE",
    "NOT FOR DISTRIBUTION",
    "DRAFT",
    "SAMPLE",
    "SPECIMEN",
    "VOID",
    "EXPIRED",
    "SUPERSEDED",
    "Journal Pre-proof",
    "Uncorrected proof",
    "Accepted Manuscript",
    "For review only",
    "For peer review",
    "Downloaded from",
    "Licensed to",
    "Evaluation copy",
    "Evaluation only",
    "Trial version",
    "Demo version",
    "Unregistered version",
    "Unlicensed copy",
    "Created with",
    "This watermark",
    "Internal use only",
    "Preview copy",
)

#: Builtin phrases that only begin a stamp ("Downloaded from <site> on
#: <date>"): in the short standalone block they are trusted in, the whole
#: block is the stamp, so the whole block goes rather than leaving its tail.
LINE_STARTERS = frozenset({"Downloaded from", "Licensed to", "Created with", "This watermark"})

#: Names and metadata strings that mark an object as decoration rather than
#: content. Matched against resource keys, /Name, and /PTEX.FileName.
NAME_HINTS = re.compile(
    r"stamp|watermark|wmark|overlay|background|bg[-_]?mark|"
    r"confidential|draft|banner|ribbon|header[-_]?mark|footer[-_]?mark",
    re.IGNORECASE,
)

#: Hints that a repeated object is legitimate furniture we should leave be.
BENIGN_HINTS = re.compile(r"logo|brand|crest|seal|signature|icon", re.IGNORECASE)


def needs_boundary(phrase: str) -> bool:
    """Should this phrase only match as a whole word?

    Single short words like "DRAFT" or "SAMPLE" turn up inside ordinary prose
    ("samples", "drafted"), so they must match standalone. Multi-word phrases
    are distinctive enough to match as substrings, which matters because
    whitespace-stripped matching is the only thing that works on PDFs that
    encode word gaps as positioning rather than space glyphs.
    """
    return len(phrase.split()) == 1


def looks_like_watermark_text(text: str) -> list[str]:
    """Return the builtin phrases present in `text`."""
    from app.actions.watermarks.textmap import squash

    hay, _ = squash(text)
    hits = []
    for phrase in BUILTIN_PHRASES:
        key, _ = squash(phrase)
        if not key:
            continue
        idx = hay.find(key)
        while idx >= 0:
            if not needs_boundary(phrase) or _standalone(hay, idx, idx + len(key)):
                hits.append(phrase)
                break
            idx = hay.find(key, idx + 1)
    return hits


def _standalone(hay: str, start: int, end: int) -> bool:
    before = hay[start - 1] if start > 0 else ""
    after = hay[end] if end < len(hay) else ""
    return not (before.isalpha() or after.isalpha())
