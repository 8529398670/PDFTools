"""PDFs built from scratch, each showing one shape of watermark (or one thing
that must not be taken for one). Used by test_watermarks.py and by the
browser twin's parity check (scripts/check_local_watermarks.py).

Ported from wmremove's tests/conftest.py, plus the cases its bugs were found
with: a block whose font later text relies on, a phrase inside a run of
text with widths, a corner logo image, a stamp rotated with cm, an OCR text
layer, and a phrase repeated on many pages.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pikepdf
from pikepdf import Array, Dictionary, Name

PAGE_W, PAGE_H = 595, 842


def _helvetica(pdf: pikepdf.Pdf, widths: bool = False) -> pikepdf.Object:
    font = Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica)
    if widths:
        # Every character 500/1000 em wide, so positions are easy to check.
        font.FirstChar = 32
        font.LastChar = 126
        font.Widths = Array([500] * 95)
    return pdf.make_indirect(font)


def _form(pdf: pikepdf.Pdf, content: bytes, bbox: tuple, resources=None) -> pikepdf.Object:
    stream = pdf.make_stream(content)
    stream.Type = Name.XObject
    stream.Subtype = Name.Form
    stream.BBox = Array([*bbox])
    if resources is not None:
        stream.Resources = resources
    return pdf.make_indirect(stream)


def _body_text(label: str) -> bytes:
    return b"BT /F1 11 Tf 1 0 0 1 72 700 Tm (" + label.encode() + b") Tj ET\n"


def _outline_paths(count: int) -> bytes:
    """Path painting standing in for lettering converted to outlines."""
    out = [b"q 0.6 g\n"]
    for i in range(count):
        y = 400 + (i % 40)
        out.append(f"{100 + i} {y} m {110 + i} {y + 8} l {120 + i} {y} l f\n".encode())
    out.append(b"Q\n")
    return b"".join(out)


def _one_page(pdf: pikepdf.Pdf, content: bytes, font: pikepdf.Object) -> None:
    page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
    page.Contents = pdf.make_stream(content)
    page.Resources = Dictionary(Font=Dictionary(F1=font))


def stamped(pdf: pikepdf.Pdf) -> None:
    """A full-page stamp form painted over every page, with a neutral name
    and no helpful metadata, so only its structure gives it away."""
    stamp = _form(pdf, _outline_paths(80), (0, 0, PAGE_W, PAGE_H))
    font = _helvetica(pdf)
    for i in range(6):
        page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
        base = _form(pdf, _body_text(f"Real page content number {i}"), (0, 0, PAGE_W, PAGE_H),
                     Dictionary(Font=Dictionary(F1=font)))
        page.Contents = pdf.make_stream(b"q /Base Do Q\nq /X1 Do Q\n")
        page.Resources = Dictionary(XObject=Dictionary(Base=base, X1=stamp))


def logo(pdf: pikepdf.Pdf) -> None:
    """A small corner logo form on every page: furniture, not a watermark."""
    mark = _form(pdf, _outline_paths(60), (0, 0, 40, 20))
    font = _helvetica(pdf)
    for i in range(6):
        page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
        base = _form(pdf, _body_text(f"Real page content number {i}"), (0, 0, PAGE_W, PAGE_H),
                     Dictionary(Font=Dictionary(F1=font)))
        page.Contents = pdf.make_stream(b"q /Base Do Q\nq 1 0 0 1 20 800 cm /Logo Do Q\n")
        page.Resources = Dictionary(XObject=Dictionary(Base=base, Logo=mark))


def logo_image(pdf: pikepdf.Pdf) -> None:
    """A small unnamed image in the same corner of every page, after the
    text. wmremove scored it 0.84 (an image has no /BBox, so its area read
    as 0) and removed it."""
    picture = pdf.make_stream(b"\x80" * 4, Type=Name.XObject, Subtype=Name.Image, Width=2, Height=2,
                              ColorSpace=Name.DeviceGray, BitsPerComponent=8)
    font = _helvetica(pdf)
    for i in range(6):
        page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
        page.Contents = pdf.make_stream(_body_text(f"Real page content number {i}") + b"q 40 0 0 20 20 800 cm /I0 Do Q\n")
        page.Resources = Dictionary(Font=Dictionary(F1=font), XObject=Dictionary(I0=picture))


def text(pdf: pikepdf.Pdf) -> None:
    """A plain text watermark, plus a phrase split across TJ elements."""
    _one_page(pdf, (
        b"BT /F1 48 Tf 0.7 g 0.7071 0.7071 -0.7071 0.7071 150 300 Tm (CONFIDENTIAL) Tj ET\n"
        b"BT /F1 12 Tf 0 g 1 0 0 1 72 700 Tm [(W)-3(ater)5(mark)-2( here)] TJ ET\n"
        b"BT /F1 12 Tf 0 g 1 0 0 1 72 650 Tm (Ordinary body text that must survive removal untouched.) Tj ET\n"
    ), _helvetica(pdf))


def rotated_cm(pdf: pikepdf.Pdf) -> None:
    """The usual diagonal stamp: rotated with cm before BT, its Tm plain.
    wmremove only looked at Tm, so it never saw the angle."""
    _one_page(pdf, (
        b"q 0.7071 0.7071 -0.7071 0.7071 150 300 cm\n"
        b"BT /F1 40 Tf 0.75 g 1 0 0 1 0 0 Tm (INTERNAL) Tj ET Q\n"
        b"BT /F1 12 Tf 0 g 1 0 0 1 72 650 Tm (Ordinary body text.) Tj ET\n"
    ), _helvetica(pdf))


def state_block(pdf: pikepdf.Pdf) -> None:
    """A watermark block that also sets the font and colour the next block
    goes on using without setting them again."""
    _one_page(pdf, (
        b"BT /F1 12 Tf 0.2 g 1 0 0 1 72 760 Tm (SECRETSTAMP) Tj ET\n"
        b"BT 1 0 0 1 72 650 Tm (Text that relies on the font set above.) Tj ET\n"
    ), _helvetica(pdf))


def kept_positions(pdf: pikepdf.Pdf) -> None:
    """A phrase in the middle of a run, with a font that gives widths: what
    follows the phrase must stay where it was."""
    _one_page(pdf, b"BT /F1 10 Tf 1 0 0 1 72 700 Tm (KEEP REMOVEME TAIL) Tj ET\n", _helvetica(pdf, widths=True))


def ligature(pdf: pikepdf.Pdf) -> None:
    """A ToUnicode map that turns code 1 into the two letters "fi", as a
    ligature glyph does, ahead of the phrase to remove. wmremove read match
    positions as glyph positions, so it cut one byte too far along."""
    cmap = pdf.make_stream(
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        b"1 begincodespacerange <00> <FF> endcodespacerange\n"
        b"1 beginbfchar <01> <00660069> endbfchar\n"
        b"1 beginbfrange <20> <7E> <0020> endbfrange\n"
        b"endcmap CMapName currentdict /CMap defineresource pop end end\n")
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica, ToUnicode=cmap))
    _one_page(pdf, b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (Con\001dential REMOVE KEEP) Tj ET\n", font)


def ocr(pdf: pikepdf.Pdf) -> None:
    """A scanned page with an invisible OCR text layer (Tr 3), short lines
    in a large font: the layer is what makes the scan searchable."""
    picture = pdf.make_stream(b"\x80", Type=Name.XObject, Subtype=Name.Image, Width=1, Height=1,
                              ColorSpace=Name.DeviceGray, BitsPerComponent=8)
    font = _helvetica(pdf)
    for _ in range(3):
        page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
        page.Contents = pdf.make_stream(
            f"q {PAGE_W} 0 0 {PAGE_H} 0 0 cm /Im1 Do Q\n".encode()
            + b"BT 3 Tr /F1 30 Tf 1 0 0 1 72 700 Tm (Chapter One) Tj ET\n")
        page.Resources = Dictionary(Font=Dictionary(F1=font), XObject=Dictionary(Im1=picture))


def many_pages(pdf: pikepdf.Pdf) -> None:
    """The same phrase on ten pages, each with its own content stream."""
    font = _helvetica(pdf)
    for i in range(10):
        _one_page(pdf, (
            b"BT /F1 9 Tf 1 0 0 1 72 30 Tm (Downloaded from example.org) Tj ET\n"
            + _body_text(f"Page body {i}")
        ), font)


def annot(pdf: pikepdf.Pdf) -> None:
    """A /Stamp annotation plus a legitimate /Link."""
    page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
    page.Contents = pdf.make_stream(b"")
    stamp = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Stamp, Rect=Array([100, 400, 400, 500]),
                                         Contents=pikepdf.String("CONFIDENTIAL"), F=4))
    link = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([0, 0, 10, 10])))
    page.Annots = Array([stamp, link])


def clean(pdf: pikepdf.Pdf) -> None:
    """No watermark at all: the false-positive control."""
    font = _helvetica(pdf)
    for _ in range(4):
        _one_page(pdf, b"BT /F1 11 Tf 1 0 0 1 72 700 Tm (Just an ordinary document page with nothing stamped on it.) Tj ET\n", font)


def prose(pdf: pikepdf.Pdf) -> None:
    """A builtin phrase inside a long legitimate sentence."""
    _one_page(pdf, (
        b"BT /F1 11 Tf 1 0 0 1 72 700 Tm (This version is no longer the Accepted Manuscript, but it is not yet "
        b"the final published record of this particular article, and may still change before then.) Tj ET\n"
    ), _helvetica(pdf))


def ocg(pdf: pikepdf.Pdf) -> None:
    """A watermark on its own optional-content layer, plus real text. The
    layer sits in a nested /Order group, as Acrobat writes them."""
    font = _helvetica(pdf)
    layer = pdf.make_indirect(Dictionary(Type=Name.OCG, Name=pikepdf.String("Watermark")))
    other = pdf.make_indirect(Dictionary(Type=Name.OCG, Name=pikepdf.String("Notes")))
    pdf.Root.OCProperties = Dictionary(
        OCGs=Array([layer, other]),
        D=Dictionary(ON=Array([layer, other]), Order=Array([pikepdf.String("Group"), Array([layer, other])])),
    )
    page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
    page.Contents = pdf.make_stream(
        b"/OC /oc1 BDC\n"
        b"BT /F1 48 Tf 0.7 g 1 0 0 1 150 400 Tm (CONFIDENTIAL) Tj ET\n"
        b"EMC\n"
        b"BT /F1 11 Tf 0 g 1 0 0 1 72 700 Tm (Real content that must stay.) Tj ET\n"
    )
    page.Resources = Dictionary(Font=Dictionary(F1=font), Properties=Dictionary(oc1=layer))


def scan(pdf: pikepdf.Pdf) -> None:
    """A flattened page: one full-page image, no text layer."""
    picture = pdf.make_stream(b"\x80", Type=Name.XObject, Subtype=Name.Image, Width=1, Height=1,
                              ColorSpace=Name.DeviceGray, BitsPerComponent=8)
    page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
    page.Contents = pdf.make_stream(f"q {PAGE_W} 0 0 {PAGE_H} 0 0 cm /Im1 Do Q\n".encode())
    page.Resources = Dictionary(XObject=Dictionary(Im1=picture))


FIXTURES: dict[str, Callable[[pikepdf.Pdf], None]] = {
    "stamped": stamped, "logo": logo, "logo_image": logo_image, "text": text, "rotated_cm": rotated_cm,
    "state_block": state_block, "kept_positions": kept_positions, "ligature": ligature, "ocr": ocr, "many_pages": many_pages,
    "annot": annot, "clean": clean, "prose": prose, "ocg": ocg, "scan": scan,
}


def build(name: str, folder: Path) -> Path:
    pdf = pikepdf.new()
    FIXTURES[name](pdf)
    path = folder / f"{name}.pdf"
    pdf.save(path)
    return path
