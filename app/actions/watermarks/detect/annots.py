"""Annotation-based watermarks.

Acrobat's own "Add Watermark" writes a /Watermark annotation; many stamping
tools use /Stamp or /FreeText instead.
"""

from __future__ import annotations

from app.actions.watermarks.detect import Options, register
from app.actions.watermarks.vocab import NAME_HINTS, looks_like_watermark_text
from app.actions.watermarks.model import Candidate, Kind
from app.actions.watermarks.pdfdoc import Document

#: Confidence floor per annotation subtype. /Watermark is unambiguous;
#: /Stamp is usually decoration; /FreeText is often a legitimate comment, so
#: it only counts when something else about it looks like a watermark.
_SUBTYPES = {
    "/Watermark": 0.95,
    "/Stamp": 0.75,
    "/FreeText": 0.4,
}


@register("annot")
def detect(doc: Document, opts: Options) -> list[Candidate]:
    out: list[Candidate] = []
    for pindex, page in enumerate(doc.pdf.pages):
        annots = page.obj.get("/Annots")
        if annots is None:
            continue
        try:
            items = list(annots)
        except Exception:
            continue
        for aindex, annot in enumerate(items):
            try:
                subtype = str(annot.get("/Subtype") or "")
            except Exception:
                continue
            if subtype not in _SUBTYPES:
                continue

            contents = ""
            for key in ("/Contents", "/T", "/NM"):
                try:
                    val = annot.get(key)
                except Exception:
                    val = None
                if val is not None:
                    contents += " " + str(val)

            cand = Candidate(
                detector="annot",
                kind=Kind.ANNOT,
                description=(
                    f"{subtype.lstrip('/')} annotation on page {pindex + 1}"
                    + (f": {contents.strip()[:60]!r}" if contents.strip() else "")
                ),
                pages=[pindex],
                payload={"page": pindex, "index": aindex, "subtype": subtype},
            )
            base = _SUBTYPES[subtype]
            cand.add(f"annotation subtype is {subtype}", 0.0)

            bump = 0.0
            hits = looks_like_watermark_text(contents)
            if hits:
                cand.add(f"text says {', '.join(hits[:3])}", 0.0)
                bump += 0.2
            if NAME_HINTS.search(contents):
                bump += 0.15
            try:
                flags = int(annot.get("/F") or 0)
            except Exception:
                flags = 0
            if flags & 2:  # Hidden
                cand.add("flagged hidden", 0.0)
                bump -= 0.2
            if flags & 4:  # Print
                cand.add("flagged print-always (stamped onto output)", 0.0)
                bump += 0.1

            cand.forced_confidence = max(0.0, min(1.0, base + bump))
            out.append(cand)
    return out
