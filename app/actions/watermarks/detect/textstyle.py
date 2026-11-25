"""Text that *looks* like a watermark, whatever it says.

Catches the common "diagonal grey CONFIDENTIAL across the page" shape without
relying on the wording, so watermarks in any language or phrasing still get
found. Graphics state is tracked directly from the content stream, so this
needs no optional dependency.

The transformation matrix is followed through q/Q/cm as well as Tm, since the
usual diagonal stamp is rotated with cm before its BT. The same words styled
the same way on many pages are one finding, not one per page. Invisible text
(Tr 3) is not a sign of anything: it is how a scanned book keeps a searchable
text layer, and removing it would take that away.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.actions.watermarks.detect import Options, register
from app.actions.watermarks.model import Candidate, Kind
from app.actions.watermarks.pdfdoc import IDENTITY, Document, Matrix, Scope, get_key, is_rotated, matmul

#: Fill lightness above which grey text reads as a wash rather than ink.
_LIGHT_GREY = 0.55
#: Font size (in text-space units) above which text is a banner, not prose.
_BIG_FONT = 24.0
_ROT_TOL = 1e-3


@dataclass
class _Style:
    rotated: bool = False
    #: Largest effective glyph height: font size times the scale of the
    #: text matrix and the CTM together.
    max_size: float = 0.0
    min_alpha: float = 1.0
    #: Lightness of the lightest non-white fill used, or None.
    grey: float | None = None
    #: Running state, since Tf and Tm can appear in either order.
    font_size: float = 0.0
    #: Drawn in render mode 3, invisible: an OCR layer, never a stamp.
    invisible: bool = False
    ctm: Matrix = IDENTITY
    tm: Matrix = IDENTITY

    def note(self) -> None:
        full = matmul(self.tm, self.ctm)
        if is_rotated(full):
            self.rotated = True
        scale = max((full[0] ** 2 + full[1] ** 2) ** 0.5, (full[2] ** 2 + full[3] ** 2) ** 0.5)
        self.max_size = max(self.max_size, self.font_size * scale)


_COLOUR_OPS = ("g", "rg", "k", "sc", "scn")


def _gray_of(operands: list, op: str) -> float | None:
    """Approximate lightness for the grey/RGB/CMYK fill operators."""
    vals = []
    for v in operands:
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
    if op == "g" and len(vals) >= 1:
        return vals[0]
    if op == "rg" and len(vals) >= 3:
        return sum(vals[:3]) / 3.0
    if op == "k" and len(vals) >= 4:
        c, m, y, kk = vals[:4]
        return max(0.0, 1.0 - min(1.0, max(c, m, y) + kk))
    if op in ("sc", "scn") and vals:
        return sum(vals) / len(vals)
    return None


def _six(operands: list) -> Matrix | None:
    try:
        return tuple(float(o) for o in operands[:6])  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _alpha(gstates, operands) -> float | None:
    if not operands or gstates is None:
        return None
    gs = get_key(gstates, str(operands[0]))
    ca = get_key(gs, "/ca") if gs is not None else None
    try:
        return float(ca) if ca is not None else None
    except (TypeError, ValueError):
        return None


def _styles(scope: Scope) -> dict[int, _Style]:
    """Style of each BT..ET block, keyed by its start instruction index."""
    gstates = get_key(scope.resources, "/ExtGState")
    out: dict[int, _Style] = {}

    alpha, grey, ctm = 1.0, None, IDENTITY
    # The render mode is text state: it outlives ET.
    render = 0
    stack: list[tuple[float, float | None, Matrix]] = []
    cur: _Style | None = None
    start = -1

    for idx, instr in enumerate(scope.instructions):
        op = str(getattr(instr, "operator", ""))
        operands = list(getattr(instr, "operands", []) or [])

        if op == "q":
            stack.append((alpha, grey, ctm))
        elif op == "Q":
            if stack:
                alpha, grey, ctm = stack.pop()
        elif op == "cm" and len(operands) >= 6 and cur is None:
            m = _six(operands)
            if m is not None:
                ctm = matmul(m, ctm)
        elif op == "gs":
            value = _alpha(gstates, operands)
            if value is not None:
                alpha = value
                if cur is not None:
                    cur.min_alpha = min(cur.min_alpha, value)
        elif op in _COLOUR_OPS:
            val = _gray_of(operands, op)
            if val is not None:
                grey = val
                if cur is not None:
                    cur.grey = val
        elif op == "BT":
            cur, start = _Style(min_alpha=alpha, grey=grey, ctm=ctm), idx
        elif op == "ET":
            if cur is not None and start >= 0:
                cur.invisible = render == 3
                out[start] = cur
            cur, start = None, -1
        elif op == "Tr" and operands:
            try:
                render = int(operands[0])
            except (TypeError, ValueError):
                pass
        elif cur is not None:
            if op == "Tf" and len(operands) >= 2:
                try:
                    cur.font_size = abs(float(operands[1]))
                except (TypeError, ValueError):
                    pass
                cur.note()
            elif op == "Tm" and len(operands) >= 6:
                m = _six(operands)
                if m is not None:
                    cur.tm = m
                    cur.note()

    return out


@register("textstyle")
def detect(doc: Document, opts: Options) -> list[Candidate]:
    # The same words drawn on several pages are one finding: (text) -> the
    # blocks, with the style of each.
    groups: dict[str, list[tuple[Scope, int, _Style]]] = {}

    for scope in doc.scopes.values():
        if not scope.blocks:
            continue
        styles = _styles(scope)
        for bi, block in enumerate(scope.blocks):
            body = block.text.strip()
            # Watermarks are short. Long runs are prose.
            if not body or len(body) > 120:
                continue
            st = styles.get(block.start_instr)
            if st is None or st.invisible:
                continue
            groups.setdefault(body, []).append((scope, bi, st))

    out: list[Candidate] = []
    total_pages = max(doc.page_count, 1)
    for body, members in groups.items():
        pages = sorted({p for scope, _, _ in members for p in scope.pages})
        rotated = any(st.rotated for _, _, st in members)
        min_alpha = min(st.min_alpha for _, _, st in members)
        max_size = max(st.max_size for _, _, st in members)
        greys = [st.grey for _, _, st in members if st.grey is not None and _LIGHT_GREY <= st.grey < 1.0]

        cand = Candidate(
            detector="textstyle",
            kind=Kind.TEXT,
            description=f"styled text {body[:48]!r}",
            pages=pages,
            payload={
                "hits": [(scope.key, bi, 0, len(scope.blocks[bi].slots)) for scope, bi, _ in members],
                "needle": body[:48],
                "source": "style",
            },
        )

        style, strong = 0, False
        if rotated:
            cand.add("drawn at an angle", 0.2)
            style, strong = style + 1, True
        if min_alpha < 0.9:
            cand.add(f"semi-transparent (alpha {min_alpha:g})", 0.2)
            style, strong = style + 1, True
        if max_size >= _BIG_FONT:
            cand.add(f"oversized text ({max_size:g}pt)", 0.15)
            style, strong = style + 1, True
        if greys:
            cand.add(f"painted in light grey ({max(greys):.2f})", 0.15)
            style += 1
        repeated = len(pages) > 1
        if repeated:
            cand.add(f"repeated across {len(pages)}/{total_pages} pages", 0.15)

        # One weak signal is just normal typography; require corroboration.
        # Grey and repeated alone is a running header, not a stamp.
        if style >= 2 or (strong and repeated):
            out.append(cand)

    return out
