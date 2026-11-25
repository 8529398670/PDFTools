"""Optional-content (layer) watermarks.

Tools that want a removable watermark often put it on its own layer. The
layer name is usually a dead giveaway.
"""

from __future__ import annotations

from app.actions.watermarks.detect import Options, register
from app.actions.watermarks.vocab import NAME_HINTS
from app.actions.watermarks.model import Candidate, Kind
from app.actions.watermarks.pdfdoc import Document, objkey


@register("ocg")
def detect(doc: Document, opts: Options) -> list[Candidate]:
    try:
        ocprops = doc.pdf.Root.get("/OCProperties")
    except Exception:
        ocprops = None
    if ocprops is None:
        return []
    groups = ocprops.get("/OCGs")
    if groups is None:
        return []
    try:
        items = list(groups)
    except Exception:
        return []

    out: list[Candidate] = []
    for ocg in items:
        try:
            name = str(ocg.get("/Name") or "")
        except Exception:
            continue
        if not NAME_HINTS.search(name):
            continue
        cand = Candidate(
            detector="ocg",
            kind=Kind.OCG,
            description=f"optional-content layer named {name.strip('()')!r}",
            pages=list(range(doc.page_count)),
            payload={"target": objkey(ocg), "name": name},
        )
        cand.add(f"layer name matches watermark vocabulary: {name.strip('()')!r}", 0.3)
        # A layer hidden by default is already invisible; lower the stakes.
        try:
            default = ocprops.get("/D")
            off = list(default.get("/OFF") or []) if default is not None else []
            if any(objkey(o) == objkey(ocg) for o in off):
                cand.add("layer is off by default (already not shown)", -0.2)
        except Exception:
            pass
        out.append(cand)
    return out
