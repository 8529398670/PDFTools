"""Turn pages a quarter, half or three quarters of a turn, clockwise.

Only each page's /Rotate entry changes: the page's content is not touched, so
a rotation costs no more than copying the file, and is undone by rotating the
other way. qpdf's --rotate does exactly this in the browser twin
(static/js/local/rotate.js).
"""
from __future__ import annotations

from typing import Annotated, Literal

import msgspec
import pikepdf
from msgspec import Meta

from app.actions import Action, Context
from app.actions.pages import parse_pages, stem
from app.actions.pdf import open_pdf

NAME = "rotate"


class Options(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    angle: Annotated[Literal[90, 180, 270], Meta(description="How far to turn each page, clockwise, in degrees.")] = 90
    pages: Annotated[str, Meta(max_length=500, description='Which pages, such as "1-3, 7, 10-". Empty or "all" is every page.')] = "all"


def run(context: Context, options: Options) -> dict[str, int]:
    context.progress(0.0, "")
    target = context.work / "rotated.pdf"
    with open_pdf(context.source) as pdf:
        chosen = parse_pages(options.pages, len(pdf.pages))
        for done, index in enumerate(chosen, start=1):
            if done % 200 == 0:
                context.check()
                context.progress(done / len(chosen) * 0.5, "")
            pdf.pages[index].rotate(options.angle, relative=True)
        context.check()
        pdf.save(
            target,
            stream_decode_level=pikepdf.StreamDecodeLevel.none,
            object_stream_mode=pikepdf.ObjectStreamMode.preserve,
        )
        page_count = len(pdf.pages)
    name = f"{stem(context.source_name)} - rotated.pdf"
    context.add_output(name, target, {"pages": page_count, "first_page": 1, "last_page": page_count, "title": context.source_info.get("title", "")})
    context.progress(1.0, name)
    return {"pages": len(chosen), "angle": options.angle}


ACTION = Action(name=NAME, options=Options, run=run)
