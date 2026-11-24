"""What every PDF action needs: opening a file, finding which page a bookmark
points at, and the quick look taken at a PDF when it is imported. The only
module besides the actions themselves that imports pikepdf.

pikepdf (qpdf) opens a file by reading its cross-reference table, and loads an
object only when something touches it, so opening a book of several GB costs
about as much as opening a pamphlet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pikepdf

# How far down an outline is walked: past this it is almost certainly a loop.
DEPTH_LIMIT = 32
# The most bookmarks looked at, for the same reason.
ITEMS_LIMIT = 200_000


class NotAPDFError(Exception):
    """The message is a code, worded in language.yaml (pdf.errors.*)."""


def open_pdf(path: Path) -> pikepdf.Pdf:
    """Open for reading. A file that is not a PDF, or needs a password to
    open, raises NotAPDFError with the reason's code."""
    with path.open("rb") as handle:
        if b"%PDF-" not in handle.read(1024):
            raise NotAPDFError("not_pdf")
    try:
        return pikepdf.open(path)
    except pikepdf.PasswordError:
        raise NotAPDFError("password") from None
    except pikepdf.PdfError:
        raise NotAPDFError("damaged") from None


@dataclass
class Mark:
    """One bookmark: where it sits in the outline and the page it opens.
    page is None when it points nowhere this file can say."""

    title: str
    depth: int
    page: int | None
    order: int
    children: list["Mark"] = field(default_factory=list)


class Destinations:
    """Turns an outline item's target into a page index."""

    def __init__(self, pdf: pikepdf.Pdf) -> None:
        self.pdf = pdf
        self.pages = {page.obj.objgen: index for index, page in enumerate(pdf.pages)}
        self._names: Any = None
        self._old_names: Any = None
        root = pdf.Root
        try:
            if "/Names" in root and "/Dests" in root.Names:
                self._names = pikepdf.NameTree(root.Names.Dests)
        except Exception:  # noqa: BLE001 -- a broken name tree only loses named targets
            self._names = None
        if "/Dests" in root:
            self._old_names = root.Dests

    def _named(self, name: Any) -> Any:
        key = str(name)
        if isinstance(name, pikepdf.Name):
            key = key.lstrip("/")
            if self._old_names is not None and name in self._old_names:
                return self._old_names[name]
        if self._names is not None:
            try:
                return self._names[key]
            except KeyError:
                pass
        if self._old_names is not None and ("/" + key) in self._old_names:
            return self._old_names["/" + key]
        return None

    def page_of(self, destination: Any, action: Any) -> int | None:
        target = destination
        if target is None and action is not None and action.get("/S") == pikepdf.Name.GoTo:
            target = action.get("/D")
        for _ in range(3):
            if isinstance(target, (pikepdf.Name, pikepdf.String, str)):
                target = self._named(target)
            elif isinstance(target, pikepdf.Dictionary) and "/D" in target:
                target = target.D
            else:
                break
        if isinstance(target, pikepdf.Array) and len(target) > 0:
            first = target[0]
            if isinstance(first, pikepdf.Dictionary):
                return self.pages.get(first.objgen)
            if isinstance(first, int) and 0 <= int(first) < len(self.pdf.pages):
                # A page number, as in a remote target; taken at its word.
                return int(first)
        return None


def outline_marks(pdf: pikepdf.Pdf) -> list[Mark]:
    """The outline as a tree of Marks, in document order."""
    destinations = Destinations(pdf)
    counter = 0

    def walk(items: Any, depth: int) -> list[Mark]:
        nonlocal counter
        marks: list[Mark] = []
        if depth > DEPTH_LIMIT:
            return marks
        for item in items:
            if counter >= ITEMS_LIMIT:
                break
            counter += 1
            try:
                page = destinations.page_of(item.destination, item.action)
            except Exception:  # noqa: BLE001 -- one odd bookmark is skipped, not fatal
                page = None
            mark = Mark(title=str(item.title or "").strip(), depth=depth, page=page, order=counter)
            mark.children = walk(item.children, depth + 1)
            marks.append(mark)
        return marks

    try:
        outline = pdf.open_outline()
    except Exception:  # noqa: BLE001 -- an outline that cannot be read is no outline
        return []
    return walk(outline.root, 1)


def walk_marks(marks: list[Mark]) -> Iterator[Mark]:
    for mark in marks:
        yield mark
        yield from walk_marks(mark.children)


def inspect(path: Path) -> dict[str, Any]:
    """The quick look taken at a PDF when it is imported: its pages, title,
    and how deep its bookmarks go, with how many sit at each level (which is
    how many sections a split at that level would make, roughly)."""
    with open_pdf(path) as pdf:
        marks = outline_marks(pdf)
        levels: dict[int, int] = {}
        for mark in walk_marks(marks):
            levels[mark.depth] = levels.get(mark.depth, 0) + 1
        title = ""
        try:
            title = str(pdf.docinfo.get("/Title", "") or "").strip()
        except Exception:  # noqa: BLE001 -- no title is fine
            title = ""
        return {
            "pages": len(pdf.pages),
            "title": title[:300],
            "bookmarks": sum(levels.values()),
            "levels": [levels[depth] for depth in sorted(levels)],
            "version": str(pdf.pdf_version),
        }
