"""Pages whose content is a single flattened image.

Nothing here is removable structurally -- any watermark is baked into the
pixels. By deliberate design this detector only reports; it never alters a
page, so the tool can never silently degrade a scan into a worse scan.
"""

from __future__ import annotations

from app.actions.watermarks.detect import Options, register
from app.actions.watermarks.model import Candidate, Kind
from app.actions.watermarks.pdfdoc import Document

#: An image covering at least this much of the page is "the whole page".
_COVERAGE = 0.8


@register("imagepage")
def detect(doc: Document, opts: Options) -> list[Candidate]:
    flattened: list[int] = []

    for pindex in range(doc.page_count):
        on_page = [i for i in doc.invocations if i.page == pindex]
        images = [i for i in on_page if i.subtype == "Image"]
        if not images:
            continue

        text_chars = 0
        for scope in doc.scopes.values():
            if pindex in scope.pages:
                text_chars += sum(1 for ch in scope.text if not ch.isspace())
        if text_chars > 50:
            continue  # has a real text layer; not a flattened page

        px0, py0, px1, py1 = doc.page_box(pindex)
        page_area = max((px1 - px0) * (py1 - py0), 1.0)
        for inv in images:
            sx = (inv.ctm[0] ** 2 + inv.ctm[1] ** 2) ** 0.5
            sy = (inv.ctm[2] ** 2 + inv.ctm[3] ** 2) ** 0.5
            if (sx * sy) / page_area >= _COVERAGE:
                flattened.append(pindex)
                break

    if not flattened:
        return []

    cand = Candidate(
        detector="imagepage",
        kind=Kind.IMAGE_PAGE,
        description=(
            f"{len(flattened)} page(s) are a single full-page image with no "
            "text layer -- any watermark is part of the pixels"
        ),
        pages=flattened,
        payload={"pages": flattened},
    )
    cand.add("page content is one full-page image", 0.0)
    cand.add("nothing to remove structurally; reported for information only", 0.0)
    cand.forced_confidence = 0.0
    return [cand]
