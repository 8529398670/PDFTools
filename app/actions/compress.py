"""Make a PDF smaller.

lossless: what qpdf can do without changing how anything looks. Objects are
packed into compressed object streams, every Flate stream is compressed again
at the highest level, and what nothing points at any more is left out. The
browser twin (static/js/local/compress.js) does the same with qpdf's own
flags.

images: lossless, and then every large picture is scaled down to image_dpi
for the page it sits on and stored as JPEG, when that comes out smaller. A
picture with a transparency mask, or one Pillow cannot read, is kept as it
is. This one changes how pictures look, needs Pillow, and runs only on the
server.
"""
from __future__ import annotations

import io
import shutil
from typing import Annotated, Any, Literal

import msgspec
import pikepdf
from msgspec import Meta

from app.actions import Action, Context
from app.actions.pages import stem
from app.actions.pdf import open_pdf

NAME = "compress"
JPEG_QUALITY = 75
# A picture this small is never worth re-encoding.
MIN_PIXELS = 64 * 64


class Options(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    level: Annotated[Literal["lossless", "images"], Meta(description="lossless keeps everything as it looks; images also scales large pictures down and stores them as JPEG.")] = "lossless"
    image_dpi: Annotated[int, Meta(ge=50, le=600, description="With level images: the most pixels per inch a picture keeps on its page.")] = 150


def _page_inches(page: pikepdf.Page) -> float:
    box = page.mediabox
    width = abs(float(box[2]) - float(box[0])) / 72
    height = abs(float(box[3]) - float(box[1])) / 72
    return max(width, height, 1.0)


def _shrink_image(raw: pikepdf.Object, longest: int) -> bool:
    """Scale one picture so its longer side is at most longest pixels, as
    JPEG, if that is smaller than what is there. True when it was replaced."""
    from PIL import Image

    if raw.get("/SMask") is not None or raw.get("/Mask") is not None or raw.get("/ImageMask"):
        return False
    width, height = int(raw.get("/Width", 0)), int(raw.get("/Height", 0))
    if width * height < MIN_PIXELS or max(width, height) <= longest:
        return False
    picture = pikepdf.PdfImage(raw).as_pil_image()
    if picture.mode not in ("RGB", "L"):
        picture = picture.convert("RGB")
    scale = longest / max(width, height)
    picture = picture.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    data = out.getvalue()
    if len(data) >= len(raw.read_raw_bytes()):
        return False
    raw.write(data, filter=pikepdf.Name.DCTDecode)
    raw.Width, raw.Height = picture.width, picture.height
    raw.ColorSpace = pikepdf.Name.DeviceGray if picture.mode == "L" else pikepdf.Name.DeviceRGB
    raw.BitsPerComponent = 8
    for key in ("/DecodeParms", "/Decode"):
        if key in raw:
            del raw[key]
    return True


def _shrink_images(context: Context, pdf: pikepdf.Pdf, dpi: int) -> int:
    seen: set[tuple[int, int]] = set()
    shrunk = 0
    total = len(pdf.pages) or 1
    for number, page in enumerate(pdf.pages, start=1):
        context.check()
        longest = round(_page_inches(page) * dpi)
        try:
            images: Any = page.get_images()
        except Exception:  # noqa: BLE001 -- a page with odd resources keeps its pictures
            continue
        for name in list(images.keys()):
            raw = images[name]
            if raw.objgen in seen:
                continue
            seen.add(raw.objgen)
            try:
                if _shrink_image(raw, longest):
                    shrunk += 1
            except Exception:  # noqa: BLE001 -- one picture that cannot be read is kept as it is
                continue
        context.progress(0.8 * number / total, "")
    return shrunk


def run(context: Context, options: Options) -> dict[str, int]:
    context.progress(0.0, "")
    before = context.source.stat().st_size
    target = context.work / "compressed.pdf"
    pikepdf.settings.set_flate_compression_level(9)
    with open_pdf(context.source) as pdf:
        shrunk = _shrink_images(context, pdf, options.image_dpi) if options.level == "images" else 0
        context.check()
        pdf.remove_unreferenced_resources()
        pdf.save(
            target,
            compress_streams=True,
            recompress_flate=True,
            stream_decode_level=pikepdf.StreamDecodeLevel.generalized,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
        page_count = len(pdf.pages)
    after = target.stat().st_size
    if after >= before:
        # Nothing to gain: the file as it was, so a chain never grows it.
        shutil.copyfile(context.source, target)
        after = before
    name = f"{stem(context.source_name)} - compressed.pdf"
    context.add_output(name, target, {"pages": page_count, "first_page": 1, "last_page": page_count, "title": context.source_info.get("title", "")})
    context.progress(1.0, name)
    return {"before": before, "after": after, "images": shrunk}


ACTION = Action(name=NAME, options=Options, run=run)
