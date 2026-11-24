"""Split a PDF into one file per bookmark at a chosen level.

A section starts at each bookmark at that level. A bookmark above the level
with nothing under it (an index, an afterword) is a section of its own, so
nothing is lost by choosing a deep level. The pages a parent bookmark opens
before its first child (a part's title page) go with that first child.

Two bookmarks on the same page cannot be told apart in a split, so the second
is folded into the first, and the run's message says how many were. Pages
before the first section are the front matter, kept or left out by an option.

Pages are copied with their streams as they are, never decoded and encoded
again, so a section costs roughly its own size in disk time, and memory stays
flat however large the book or the section.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import msgspec
import pikepdf
from msgspec import Meta

from app.actions import Action, ActionError, Context
from app.actions.pdf import DEPTH_LIMIT, Mark, open_pdf, outline_marks

NAME = "split_bookmarks"
TITLE_MAX = 150
FRONT_MATTER = "Front matter"


class Options(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    level: Annotated[int, Meta(ge=1, le=DEPTH_LIMIT, description="The bookmark level to split at: 1 is the top.")] = 1
    front_matter: Annotated[bool, Meta(description="Keep the pages before the first section as a section of their own.")] = True
    inner_bookmarks: Annotated[bool, Meta(description="Give each section the bookmarks under its own.")] = True
    numbered: Annotated[bool, Meta(description="Start each file name with its number, so they sort in order.")] = True


@dataclass
class Section:
    first: int
    title: str
    order: int
    mark: Mark | None
    last: int = 0


def plan_sections(marks: list[Mark], level: int, page_count: int, front_matter: bool) -> tuple[list[Section], int, int]:
    """The sections a split at level makes, in page order, and how many
    bookmarks were folded into another on the same page and how many point
    nowhere."""
    starts: list[Section] = []
    nowhere = 0
    # The page of a parent whose pages still need a section: its first one.
    pending: int | None = None

    def collect(items: list[Mark]) -> None:
        nonlocal nowhere, pending
        for mark in items:
            if mark.depth >= level or not mark.children:
                if mark.page is None:
                    nowhere += 1
                    continue
                first = mark.page if pending is None else min(pending, mark.page)
                pending = None
                starts.append(Section(first=first, title=mark.title, order=mark.order, mark=mark))
            else:
                if mark.page is not None:
                    pending = mark.page if pending is None else min(pending, mark.page)
                collect(mark.children)
                pending = None

    collect(marks)
    if not starts:
        return [], 0, nowhere
    starts.sort(key=lambda section: (section.first, section.order))
    kept: list[Section] = []
    folded = 0
    for section in starts:
        if kept and kept[-1].first == section.first:
            folded += 1
            continue
        kept.append(section)
    if kept[0].first > 0:
        if front_matter:
            kept.insert(0, Section(first=0, title=FRONT_MATTER, order=0, mark=None))
    for index, section in enumerate(kept):
        section.last = kept[index + 1].first - 1 if index + 1 < len(kept) else page_count - 1
    return kept, folded, nowhere


def file_name(section: Section, number: int, width: int, numbered: bool) -> str:
    title = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", " ", section.title).strip(" .") or f"Section {number}"
    title = re.sub(r"\s+", " ", title)[:TITLE_MAX].strip()
    return f"{number:0{width}d} - {title}.pdf" if numbered else f"{title}.pdf"


def _outline(section: Section) -> list[pikepdf.OutlineItem]:
    """The section's own bookmark and those under it, pointed at the new page
    numbers. A child outside the section's pages is left out."""

    def item(mark: Mark) -> pikepdf.OutlineItem | None:
        if mark.page is None or not section.first <= mark.page <= section.last:
            return None
        made = pikepdf.OutlineItem(mark.title, mark.page - section.first)
        made.children.extend(child for child in (item(child) for child in mark.children) if child is not None)
        return made

    if section.mark is None:
        return []
    top = pikepdf.OutlineItem(section.title, 0)
    top.children.extend(child for child in (item(child) for child in section.mark.children) if child is not None)
    return [top]


def extract(source: Path, first: int, last: int, target: Path) -> None:
    """Pages first..last (from 0) of source into a new file at target,
    through qpdf's own page selection (QPDFJob), which streams page data from
    the source as it writes. Copying pages with pikepdf's page list instead
    held every stream it copied in memory: a 1.6 GB section took 1.7 GB."""
    pikepdf.Job(["pikepdf", "--empty", "--pages", str(source), f"{first + 1}-{last + 1}", "--", str(target)]).run()


def run(context: Context, options: Options) -> dict[str, int]:
    """Plans the sections from one look at the outline, then writes each. The
    section's own bookmarks are added in a second pass over the new file, which
    also drops links to pages it no longer has."""
    context.progress(0.0, "")
    with open_pdf(context.source) as source:
        page_count = len(source.pages)
        sections, folded, nowhere = plan_sections(outline_marks(source), options.level, page_count, options.front_matter)
    if not sections:
        raise ActionError("no_bookmarks")
    total_pages = sum(section.last - section.first + 1 for section in sections) or 1
    done_pages = 0
    width = max(2, len(str(len(sections))))
    for number, section in enumerate(sections, start=1 if sections[0].mark is not None else 0):
        context.check()
        name = file_name(section, number, width, options.numbered)
        target = context.work / f"{number:05d}.pdf"
        if options.inner_bookmarks:
            pages_only = context.work / f"{number:05d}.pages.pdf"
            extract(context.source, section.first, section.last, pages_only)
            with pikepdf.open(pages_only) as part:
                _drop_outside_links(part)
                with part.open_outline() as outline:
                    outline.root.extend(_outline(section))
                part.save(
                    target,
                    stream_decode_level=pikepdf.StreamDecodeLevel.none,
                    object_stream_mode=pikepdf.ObjectStreamMode.preserve,
                )
            pages_only.unlink(missing_ok=True)
        else:
            extract(context.source, section.first, section.last, target)
        pages = section.last - section.first + 1
        context.add_output(name, target, {
            "pages": pages,
            "first_page": section.first + 1,
            "last_page": section.last + 1,
            "title": section.title,
        })
        done_pages += pages
        context.progress(done_pages / total_pages, name)
    return {"sections": len(sections), "folded": folded, "nowhere": nowhere}


def _drop_outside_links(part: pikepdf.Pdf) -> None:
    """A link to a page outside this section would point at nothing once the
    section stands alone, so it is removed."""
    inside = {page.obj.objgen for page in part.pages}
    for page in part.pages:
        annots = page.obj.get("/Annots")
        if not isinstance(annots, pikepdf.Array):
            continue
        keep = pikepdf.Array()
        for annot in annots:
            if isinstance(annot, pikepdf.Dictionary) and annot.get("/Subtype") == pikepdf.Name.Link:
                target = annot.get("/Dest")
                action = annot.get("/A")
                if target is None and isinstance(action, pikepdf.Dictionary) and action.get("/S") == pikepdf.Name.GoTo:
                    target = action.get("/D")
                if isinstance(target, pikepdf.Array) and len(target) and isinstance(target[0], pikepdf.Dictionary):
                    if target[0].objgen not in inside:
                        continue
            keep.append(annot)
        if len(keep) != len(annots):
            page.obj.Annots = keep


ACTION = Action(name=NAME, options=Options, run=run, needs_bookmarks=True)
