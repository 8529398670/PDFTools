"""Removing watermark annotations from a page's /Annots array."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.actions.watermarks.model import Candidate

if TYPE_CHECKING:
    from app.actions.watermarks.pdfdoc import Document
    from app.actions.watermarks.remove import Edits


def plan(doc: "Document", cand: Candidate, edits: "Edits") -> tuple[bool, str]:
    page = cand.payload.get("page")
    index = cand.payload.get("index")
    if page is None or index is None:
        return False, "no recorded annotation"
    edits.drop_annots[int(page)].add(int(index))
    return True, ""
