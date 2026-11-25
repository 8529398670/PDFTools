"""Repeated XObject overlays -- the detector that catches real watermarks.

Most production watermarks are not searchable text. They are a Form XObject
painted onto every page, often with the lettering converted to vector
outlines so no text extraction can find it. The bundled Elsevier example is
exactly this: a full-page form whose glyphs are Bezier paths and whose only
text operator emits NUL codes.

What gives such an object away is structural: the same object, painted at the
same place, on page after page, on top of everything else.
"""

from __future__ import annotations

from collections import defaultdict

from app.actions.watermarks.detect import Options, register
from app.actions.watermarks.vocab import BENIGN_HINTS, NAME_HINTS, looks_like_watermark_text
from app.actions.watermarks.model import Candidate, Kind
from app.actions.watermarks.pdfdoc import Document, Invocation, is_rotated

#: Path-painting operators, used to tell vector-outline lettering from a
#: form that merely holds a bit of line art.
_PAINT_OPS = {"m", "l", "c", "v", "y", "re", "f", "f*", "F", "B", "B*", "b", "b*", "S", "s"}

#: A form whose box covers at least this fraction of the page is an overlay,
#: not a spot element.
_FULL_PAGE_AREA = 0.55


def _metadata_strings(obj) -> list[str]:
    """Strings worth pattern-matching for a name hint."""
    out = []
    for key in ("/PTEX.FileName", "/Name", "/Title", "/OCGName"):
        try:
            val = obj.get(key)
        except Exception:
            val = None
        if val is not None:
            out.append(str(val))
    return out


def _area_fraction(inv: Invocation, page_w: float, page_h: float) -> float:
    """How much of the page one painting covers. An image is the unit
    square mapped by the CTM, so its area is the CTM's determinant; a form
    is its /BBox, transformed."""
    if page_w <= 0 or page_h <= 0:
        return 0.0
    if inv.subtype == "Image":
        a, b, c, d = inv.ctm[:4]
        return min(1.0, abs(a * d - b * c) / (page_w * page_h))
    return _bbox_area_fraction(inv.obj, page_w, page_h, inv.ctm)


def _bbox_area_fraction(obj, page_w: float, page_h: float, ctm) -> float:
    """How much of the page this form's /BBox covers once transformed."""
    try:
        box = obj.get("/BBox")
        x0, y0, x1, y1 = (float(v) for v in list(box)[:4])
    except Exception:
        return 0.0
    w, h = abs(x1 - x0), abs(y1 - y0)
    # Scale by the CTM's linear part.
    sx = (ctm[0] ** 2 + ctm[1] ** 2) ** 0.5
    sy = (ctm[2] ** 2 + ctm[3] ** 2) ** 0.5
    w, h = w * sx, h * sy
    if page_w <= 0 or page_h <= 0:
        return 0.0
    return min(1.0, (w * h) / (page_w * page_h))


def _ctms_agree(invs: list[Invocation], tol: float = 2.0) -> bool:
    """Is the object painted at essentially the same spot every time?"""
    if len(invs) < 2:
        return True
    first = invs[0].ctm
    for inv in invs[1:]:
        for a, b in zip(first, inv.ctm):
            if abs(a - b) > tol:
                return False
    return True


@register("xobject")
def detect(doc: Document, opts: Options) -> list[Candidate]:
    by_target: dict[object, list[Invocation]] = defaultdict(list)
    for inv in doc.invocations:
        by_target[inv.target].append(inv)

    # Per page, which top-level Do came first -- the base content.
    first_order: dict[int, int] = {}
    for inv in doc.invocations:
        if inv.depth == 0:
            cur = first_order.get(inv.page)
            if cur is None or inv.order < cur:
                first_order[inv.page] = inv.order

    total_pages = max(doc.page_count, 1)
    out: list[Candidate] = []

    for target, invs in by_target.items():
        pages = sorted({i.page for i in invs})
        if invs[0].subtype not in ("Form", "Image"):
            continue

        obj = invs[0].obj
        frac = len(pages) / total_pages
        px0, py0, px1, py1 = doc.page_box(pages[0])
        page_w, page_h = px1 - px0, py1 - py0
        area = _area_fraction(invs[0], page_w, page_h)
        meta = _metadata_strings(obj)
        names = [invs[0].name] + meta

        scope = doc.scopes.get(target)
        inner_text = scope.text if scope is not None else ""
        decodable = sum(1 for ch in inner_text if not ch.isspace() and ch != "�")

        cand = Candidate(
            detector="xobject",
            kind=Kind.XOBJECT,
            description=(
                f"{invs[0].subtype} XObject /{invs[0].name} "
                f"(object {_fmt_target(target)}) painted on "
                f"{len(pages)}/{total_pages} pages"
            ),
            pages=pages,
            payload={
                "target": target,
                "invocations": invs,
                "name": invs[0].name,
                "subtype": invs[0].subtype,
            },
        )

        # --- evidence for ---------------------------------------------
        if frac >= 0.99 and total_pages > 1:
            cand.add(f"painted on every page ({len(pages)}/{total_pages})", 0.22)
        elif frac >= opts.repeat_threshold and total_pages > 1:
            cand.add(f"painted on most pages ({len(pages)}/{total_pages})", 0.18)

        if len(pages) > 1 and _ctms_agree(invs):
            cand.add("painted at an identical position on every page", 0.12)

        if area >= _FULL_PAGE_AREA:
            cand.add(f"covers {area:.0%} of the page (full-page overlay)", 0.18)

        hinted = [s for s in names if NAME_HINTS.search(s)]
        if hinted:
            cand.add(f"name/metadata says {_shorten(hinted[0])!r}", 0.28)

        overlay = all(
            inv.order > first_order.get(inv.page, -1) for inv in invs
        ) and len(invs) > 0
        repeated = len(pages) > 1
        if overlay and area >= 0.2:
            cand.add("drawn on top of the page's main content", 0.12)
        elif not overlay and invs[0].subtype == "Image" and area >= 0.8:
            # A picture under everything that fills the page is the page
            # itself (a scan) or its paper (a letterhead), however often it
            # repeats. A background watermark looks the same, so it is left
            # for a person to pick rather than removed unasked.
            cand.add(
                "a full-page picture under everything: the scan itself or "
                "the page's paper",
                -0.55,
            )
        elif not overlay and not repeated:
            # First thing painted, and painted only once: this is the page's
            # own content. Without this a single-page scan would have its one
            # full-page image flagged, and removal would blank the page.
            # Repetition is exempt, since a background watermark painted under
            # the text on every page is still a watermark.
            cand.add(
                "painted first and only once: this is the page's own content",
                -0.4,
            )

        min_alpha = min((i.alpha for i in invs), default=1.0)
        if min_alpha < 1.0:
            cand.add(f"painted with transparency (alpha {min_alpha:g})", 0.15)

        if any(is_rotated(i.ctm) for i in invs):
            cand.add("painted at an angle", 0.12)

        # Only trust wording when the object is short. A phrase found among
        # thousands of characters of body copy says nothing.
        phrase_hits = looks_like_watermark_text(inner_text) if decodable < 200 else []
        if phrase_hits:
            cand.add(f"contains watermark wording: {', '.join(phrase_hits[:3])}", 0.2)

        # Lettering converted to outlines: lots of path painting, little or
        # no decodable text. This is the hallmark of a stamping tool, and the
        # reason phrase search alone cannot find these.
        if scope is not None and len(pages) > 1 and area >= _FULL_PAGE_AREA:
            paint = sum(
                1 for ins in scope.instructions
                if str(getattr(ins, "operator", "")) in _PAINT_OPS
            )
            if paint >= 50 and decodable < 10:
                cand.add(
                    f"{paint} path-painting operators but no readable text "
                    "(lettering drawn as vector outlines)",
                    0.2,
                )

        # --- evidence against -----------------------------------------
        if len(pages) == 1 and total_pages > 1:
            cand.add("appears on only one page", -0.35)

        if decodable > 200:
            cand.add(
                f"holds {decodable} characters of readable text "
                "(looks like page content)",
                -0.35,
            )

        if 0 < area < 0.05:
            cand.add(f"covers only {area:.1%} of the page (spot element)", -0.35)

        benign = [s for s in names if BENIGN_HINTS.search(s)]
        if benign and not hinted:
            cand.add(f"name suggests branding, not a watermark: {_shorten(benign[0])!r}", -0.15)

        out.append(cand)

    return out


def _fmt_target(target) -> str:
    if isinstance(target, tuple):
        return f"{target[0]}"
    return str(target)


def _shorten(s: str, limit: int = 60) -> str:
    s = s.strip("()/ ")
    return s if len(s) <= limit else "..." + s[-(limit - 3):]
