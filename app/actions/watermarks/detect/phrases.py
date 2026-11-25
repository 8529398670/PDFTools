"""Phrase and regex matching -- the manual-entry path.

Matching is whitespace-insensitive by necessity: PDFs very often encode word
gaps as positioning operators rather than space glyphs, so text that renders
as "Journal Pre-proof" decodes as "JournalPre-proof". A literal search would
silently never match, which is the worst possible failure for a feature whose
whole point is that the user told us what to look for.
"""

from __future__ import annotations

from app.actions.watermarks.detect import Options, register
from app.actions.watermarks.vocab import BUILTIN_PHRASES, LINE_STARTERS, needs_boundary
from app.actions.watermarks.model import Candidate, Kind
from app.actions.watermarks.pdfdoc import Document

#: The user asked for these explicitly, so believe them.
USER_CONFIDENCE = 0.95
#: Guessed from the builtin vocabulary: actionable, but clearly less certain.
BUILTIN_CONFIDENCE = 0.6

#: A real watermark is its own short text block. Builtin phrases are only
#: trusted inside blocks at most this long, so a guessed phrase can never
#: carve words out of a running sentence -- "...is no longer the Accepted
#: Manuscript, but..." is prose, not a stamp. Phrases the user supplied are
#: deliberately exempt: they asked for them, so they match anywhere.
BUILTIN_MAX_BLOCK = 120


def _excerpt(text: str, start: int, end: int, pad: int = 24) -> str:
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    snippet = text[lo:hi].replace("\n", " ")
    return ("..." if lo > 0 else "") + snippet + ("..." if hi < len(text) else "")


@register("phrase")
def detect(doc: Document, opts: Options) -> list[Candidate]:
    jobs: list[tuple[str, str, float, bool]] = []
    for phrase in opts.phrases:
        if phrase.strip():
            jobs.append(("phrase", phrase, USER_CONFIDENCE, False))
    for rx in opts.regexes:
        if rx.strip():
            jobs.append(("regex", rx, USER_CONFIDENCE, False))
    if not opts.no_builtin:
        for phrase in BUILTIN_PHRASES:
            jobs.append(("builtin", phrase, BUILTIN_CONFIDENCE, needs_boundary(phrase)))

    if not jobs:
        return []

    out: list[Candidate] = []
    for source, needle, conf, boundary in jobs:
        # One finding per phrase, wherever it is: hits are
        # (scope key, block index, first slot, slot after the last).
        hits: list[tuple[object, int, int, int]] = []
        pages: set[int] = set()
        samples: list[str] = []
        prose_hits = 0
        whole = False
        for scope in doc.scopes.values():
            if not scope.blocks:
                continue
            found = False
            for bi, block in enumerate(scope.blocks):
                spans = (
                    block.search_regex(needle)
                    if source == "regex"
                    else block.search(needle, boundary=boundary)
                )
                if not spans:
                    continue
                long_block = len(block.text.strip()) > BUILTIN_MAX_BLOCK
                if source == "builtin" and long_block:
                    continue  # prose, not a stamp
                if long_block:
                    prose_hits += len(spans)
                if source == "builtin" and needle in LINE_STARTERS:
                    whole = True
                    spans = [(0, len(block.text))]
                for s, e in spans:
                    hits.append((scope.key, bi, *block.slot_span(s, e)))
                    if len(samples) < 2:
                        samples.append(_excerpt(block.text, s, e))
                found = True
            if found:
                pages.update(scope.pages)
        if not hits:
            continue

        label = "pattern" if source == "regex" else "phrase"
        cand = Candidate(
            detector="phrase",
            kind=Kind.TEXT,
            description=(
                f"{len(hits)} match(es) for {label} {needle!r}"
                + (" (from the builtin list)" if source == "builtin" else "")
            ),
            pages=sorted(pages),
            payload={"hits": hits, "needle": needle, "source": source},
            forced_confidence=conf,
        )
        cand.add(f"found in: {samples[0]!r}")
        if len(samples) > 1:
            cand.add(f"also: {samples[1]!r}")
        if source == "builtin":
            cand.add("matched the builtin vocabulary, not a phrase you supplied")
            cand.add("only standalone text blocks were considered")
        if whole:
            cand.add("removes the whole line it begins, not just these words")
        if prose_hits:
            cand.add(
                f"{prose_hits} match(es) sit inside running text -- check "
                "these are really watermarks before removing"
            )
        out.append(cand)
    return out
