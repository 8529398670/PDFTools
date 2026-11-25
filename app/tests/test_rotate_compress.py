"""Rotate and compress on the server: pages turned, a page list read the way
people type it, and pictures scaled down only when asked."""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import pikepdf
from PIL import Image

from app.actions import ACTIONS, ActionError, Context, parse_options
from app.actions.pages import parse_pages


def run(tool: str, source: Path, options: dict) -> tuple[dict, list[tuple[str, Path, dict]]]:
    made: list[tuple[str, Path, dict]] = []
    action = ACTIONS[tool]
    context = Context(run_id="t", source=source, source_name="Book.pdf", work=source.parent, source_info={},
                      progress=lambda *_: None, cancelled=lambda: False,
                      add_output=lambda name, path, info: made.append((name, path, info)))
    return action.run(context, parse_options(action, options)), made


class PagesTest(unittest.TestCase):
    def test_ranges(self) -> None:
        self.assertEqual(parse_pages("", 3), [0, 1, 2])
        self.assertEqual(parse_pages("all", 3), [0, 1, 2])
        self.assertEqual(parse_pages("1-2, 5, 7-", 8), [0, 1, 4, 6, 7])
        self.assertEqual(parse_pages("-2", 8), [0, 1])
        self.assertEqual(parse_pages("3,3,2", 8), [1, 2])

    def test_bad(self) -> None:
        for text in ("0", "9", "3-1", "a", "-", "1--2"):
            with self.assertRaises(ActionError, msg=text):
                parse_pages(text, 8)


class RotateCompressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def book(self, picture: bool = False) -> Path:
        pdf = pikepdf.Pdf.new()
        for _ in range(4):
            pdf.add_blank_page(page_size=(200, 200))
        if picture:
            image = Image.radial_gradient("L").resize((2000, 2000)).convert("RGB")
            raw = pdf.make_stream(image.tobytes(), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                                  Width=2000, Height=2000, ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8)
            page = pdf.pages[0]
            page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=raw))
            page.Contents = pdf.make_stream(b"q 200 0 0 200 0 0 cm /Im0 Do Q")
        path = self.dir / "book.pdf"
        pdf.save(path)
        return path

    def test_rotate(self) -> None:
        result, made = run("rotate", self.book(), {"angle": 270, "pages": "2-3"})
        self.assertEqual(result, {"pages": 2, "angle": 270})
        self.assertEqual(made[0][0], "Book - rotated.pdf")
        with pikepdf.open(made[0][1]) as pdf:
            self.assertEqual([int(page.obj.get("/Rotate", 0)) for page in pdf.pages], [0, 270, 270, 0])

    def test_rotate_refuses_a_page_past_the_end(self) -> None:
        with self.assertRaises(ActionError):
            run("rotate", self.book(), {"pages": "5"})

    def test_compress_lossless_keeps_pictures(self) -> None:
        result, made = run("compress", self.book(picture=True), {})
        self.assertEqual(result["images"], 0)
        self.assertLessEqual(result["after"], result["before"])
        with pikepdf.open(made[0][1]) as pdf:
            self.assertEqual(int(pdf.pages[0].Resources.XObject.Im0.Width), 2000)

    def test_compress_images_scales_them_down(self) -> None:
        result, made = run("compress", self.book(picture=True), {"level": "images", "image_dpi": 100})
        self.assertEqual(result["images"], 1)
        with pikepdf.open(made[0][1]) as pdf:
            image = pdf.pages[0].Resources.XObject.Im0
            # A 200 pt page is 2.78 in: 100 dpi keeps 278 pixels.
            self.assertEqual(int(image.Width), 278)
            self.assertEqual(image.Filter, pikepdf.Name.DCTDecode)
            Image.open(io.BytesIO(image.read_raw_bytes())).verify()


if __name__ == "__main__":
    unittest.main()
