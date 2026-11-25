"""Opening documents and walking their content streams.

The central abstraction is the `Scope`: one editable content stream, which is
either a page's own content or a Form XObject's. Page content routinely does
nothing but `/Im17 Do`, with all the real text and graphics living inside
Form XObjects, so anything that looks only at page streams sees almost
nothing. Scopes are collected recursively and deduplicated by object id, so
a stream shared by twenty pages is examined -- and edited -- exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

import pikepdf

from app.actions.watermarks.textmap import DecodedBlock, FontInfo, decode_blocks, load_fonts

#: Guard against pathological or cyclic Form XObject nesting.
MAX_DEPTH = 12

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def matmul(m: Matrix, c: Matrix) -> Matrix:
    """Concatenate `m` onto CTM `c`, PDF-style (CTM' = M x CTM)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = c
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def is_rotated(m: Matrix, tol: float = 1e-3) -> bool:
    return abs(m[1]) > tol or abs(m[2]) > tol


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def objkey(obj: Any) -> tuple[int, int] | int:
    """Stable identity for a PDF object; falls back to id() when direct."""
    try:
        og = obj.objgen
        if og and og[0]:
            return (int(og[0]), int(og[1]))
    except Exception:
        pass
    return id(obj)


@dataclass
class Invocation:
    """One `Do` -- an XObject painted somewhere."""

    name: str
    target: tuple[int, int] | int
    obj: Any
    subtype: str
    page: int
    ctm: Matrix
    #: Position among all the `Do` calls on this page, in paint order.
    order: int
    alpha: float = 1.0
    #: The scope whose stream contains this `Do` (where to delete it).
    scope: tuple[int, int] | int | None = None
    instr_idx: int = -1
    depth: int = 0


@dataclass
class Scope:
    """One content stream that can be read and rewritten."""

    key: tuple[int, int] | int
    obj: Any
    instructions: list[Any]
    resources: Any
    #: Which pages this stream ends up painted on, and how deeply nested.
    pages: set[int] = field(default_factory=set)
    depth: int = 0
    is_page: bool = False
    _fonts: dict[str, FontInfo] | None = None
    _blocks: list[DecodedBlock] | None = None
    dirty: bool = False

    @property
    def fonts(self) -> dict[str, FontInfo]:
        if self._fonts is None:
            self._fonts = load_fonts(self.resources)
        return self._fonts

    @property
    def blocks(self) -> list[DecodedBlock]:
        if self._blocks is None:
            self._blocks = decode_blocks(self.instructions, self.fonts)
        return self._blocks

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.blocks)

    def invalidate(self) -> None:
        self._blocks = None

    def write_back(self, pdf: pikepdf.Pdf) -> None:
        """Serialize instructions back into the underlying stream.

        A page whose /Contents is an array of streams (or missing) gets one
        new stream in its place; only a page that was edited is touched, so a
        page with nothing removed is copied as it was."""
        data = pikepdf.unparse_content_stream(self.instructions)
        if isinstance(self.obj, pikepdf.Stream):
            self.obj.write(data)
        else:
            stream = pdf.make_stream(data)
            for pindex in self.pages:
                pdf.pages[pindex].obj.Contents = stream
        self.dirty = False


class Document:
    """A PDF plus its walked content scopes."""

    def __init__(self, pdf: pikepdf.Pdf) -> None:
        self.pdf = pdf
        self.scopes: dict[Any, Scope] = {}
        self.invocations: list[Invocation] = []
        self._walk()

    @property
    def page_count(self) -> int:
        return len(self.pdf.pages)

    def write_back(self) -> None:
        """Put every edited content stream back into the PDF (in memory)."""
        for scope in self.scopes.values():
            if scope.dirty:
                scope.write_back(self.pdf)

    # -- walking --------------------------------------------------------
    def _walk(self) -> None:
        for pindex, page in enumerate(self.pdf.pages):
            try:
                instrs = list(pikepdf.parse_content_stream(page))
            except Exception:
                continue

            # Not coalesced here: that would rewrite every page, even those
            # nothing is removed from. An array of streams is replaced by one
            # stream only when the page is edited (Scope.write_back).
            contents = page.obj.get("/Contents")
            if isinstance(contents, pikepdf.Stream):
                key: Any = objkey(contents)
            else:
                key = ("page", objkey(page.obj))
            scope = self._scope(
                key=key,
                obj=contents,
                instructions=instrs,
                resources=page.obj.get("/Resources"),
                depth=0,
                is_page=True,
            )
            scope.pages.add(pindex)
            counter = [0]
            self._descend(scope, pindex, IDENTITY, 0, set(), counter)

    def _scope(
        self, key: Any, obj: Any, instructions: list[Any], resources: Any,
        depth: int, is_page: bool = False,
    ) -> Scope:
        existing = self.scopes.get(key)
        if existing is not None:
            existing.depth = min(existing.depth, depth)
            return existing
        scope = Scope(
            key=key, obj=obj, instructions=instructions,
            resources=resources, depth=depth, is_page=is_page,
        )
        self.scopes[key] = scope
        return scope

    def _descend(
        self, scope: Scope, pindex: int, base_ctm: Matrix, depth: int,
        seen: set[Any], counter: list[int],
    ) -> None:
        """Record `Do` calls in `scope`, recursing into Form XObjects."""
        if depth > MAX_DEPTH:
            return
        xobjects = get_key(scope.resources, "/XObject")
        gstates = get_key(scope.resources, "/ExtGState")

        ctm = base_ctm
        stack: list[Matrix] = []
        alpha = 1.0
        alpha_stack: list[float] = []

        for idx, instr in enumerate(scope.instructions):
            op = str(getattr(instr, "operator", ""))
            operands = list(getattr(instr, "operands", []) or [])

            if op == "q":
                stack.append(ctm)
                alpha_stack.append(alpha)
            elif op == "Q":
                if stack:
                    ctm = stack.pop()
                if alpha_stack:
                    alpha = alpha_stack.pop()
            elif op == "cm" and len(operands) >= 6:
                ctm = matmul(tuple(_num(o) for o in operands[:6]), ctm)  # type: ignore[arg-type]
            elif op == "gs" and operands and gstates is not None:
                gs = get_key(gstates, str(operands[0]))
                if gs is not None:
                    ca = get_key(gs, "/ca")
                    if ca is not None:
                        alpha = _num(ca, 1.0)
            elif op == "Do" and operands and xobjects is not None:
                name = str(operands[0])
                target = get_key(xobjects, name)
                if target is None:
                    continue
                subtype = str(get_key(target, "/Subtype") or "")
                inv = Invocation(
                    name=name.lstrip("/"), target=objkey(target), obj=target,
                    subtype=subtype.lstrip("/"), page=pindex, ctm=ctm,
                    order=counter[0], alpha=alpha, scope=scope.key,
                    instr_idx=idx, depth=depth,
                )
                counter[0] += 1
                self.invocations.append(inv)

                if subtype == "/Form":
                    tkey = objkey(target)
                    if tkey in seen:
                        continue  # cycle
                    try:
                        sub_instrs = list(pikepdf.parse_content_stream(target))
                    except Exception:
                        continue
                    # A form without /Resources of its own uses those of
                    # whatever paints it (allowed by older PDFs, still met).
                    own = get_key(target, "/Resources")
                    sub = self._scope(
                        key=tkey, obj=target, instructions=sub_instrs,
                        resources=own if own is not None else scope.resources,
                        depth=depth + 1,
                    )
                    sub.pages.add(pindex)
                    form_ctm = ctm
                    mtx = get_key(target, "/Matrix")
                    if mtx is not None:
                        try:
                            form_ctm = matmul(
                                tuple(_num(x) for x in list(mtx)[:6]),  # type: ignore[arg-type]
                                ctm,
                            )
                        except Exception:
                            pass
                    self._descend(sub, pindex, form_ctm, depth + 1,
                                  seen | {tkey}, counter)

    # -- convenience ----------------------------------------------------
    def page_box(self, pindex: int) -> tuple[float, float, float, float]:
        page = self.pdf.pages[pindex]
        for key in ("/CropBox", "/MediaBox"):
            box = page.obj.get(key)
            if box is not None:
                try:
                    x0, y0, x1, y1 = (float(v) for v in list(box)[:4])
                    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
                except Exception:
                    continue
        return (0.0, 0.0, 612.0, 792.0)

    def scopes_on_pages(self) -> Iterator[Scope]:
        yield from self.scopes.values()


def get_key(container: Any, key: str) -> Any:
    """Dict lookup that tolerates missing keys and non-dict objects."""
    if container is None:
        return None
    if not key.startswith("/"):
        key = "/" + key
    try:
        return container.get(key)
    except Exception:
        return None
