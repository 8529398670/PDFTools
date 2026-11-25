"""Remove watermarks on the server: the stamp is found and goes, everything
else stays. Ported from wmremove's tests, plus one test for each bug fixed
in the move (see app/tests/watermark_fixtures.py)."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pikepdf

from app.actions import ACTIONS, ActionError, Context, parse_options
from app.actions.watermarks import remove
from app.actions.watermarks.detect import Options, run_all
from app.actions.watermarks.model import Kind
from app.actions.watermarks.pdfdoc import Document
from app.tests.watermark_fixtures import build

THRESHOLD = 0.5


def actionable(cands: list, threshold: float = THRESHOLD) -> list:
    return [c for c in cands if c.confidence >= threshold and c.actionable]


class WatermarkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def pdf(self, name: str) -> Path:
        return build(name, self.dir)

    def scan(self, path: Path, **kw: Any) -> list:
        with pikepdf.open(path) as pdf:
            cands, warnings = run_all(Document(pdf), Options(**kw))
        self.assertEqual(warnings, [])
        return cands

    def clean(self, path: Path, **kw: Any) -> tuple[Path, remove.Report]:
        out = self.dir / ("out-" + path.name)
        with pikepdf.open(path) as pdf:
            doc = Document(pdf)
            cands, _ = run_all(doc, Options(**kw))
            edits, report = remove.plan(doc, actionable(cands))
            report = remove.apply(doc, edits, report)
            doc.write_back()
            pdf.save(out)
        return out, report

    def text_of(self, path: Path) -> str:
        with pikepdf.open(path) as pdf:
            return "".join(s.text for s in Document(pdf).scopes.values())

    def contents(self, path: Path, page: int = 0) -> bytes:
        with pikepdf.open(path) as pdf:
            return pikepdf.unparse_content_stream(pikepdf.parse_content_stream(pdf.pages[page]))


class DetectTest(WatermarkTest):
    def test_repeated_full_page_stamp_is_found(self) -> None:
        hits = [c for c in actionable(self.scan(self.pdf("stamped"))) if c.kind is Kind.XOBJECT]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].payload["name"], "X1")
        self.assertGreaterEqual(hits[0].confidence, 0.8)
        self.assertEqual(len(hits[0].pages), 6)

    def test_page_content_forms_are_not_flagged(self) -> None:
        names = {c.payload.get("name") for c in actionable(self.scan(self.pdf("stamped")))}
        self.assertNotIn("Base", names)

    def test_corner_logos_are_not_flagged(self) -> None:
        for name in ("logo", "logo_image"):
            with self.subTest(name):
                self.assertFalse([c for c in actionable(self.scan(self.pdf(name))) if c.kind is Kind.XOBJECT])

    def test_clean_document_yields_nothing(self) -> None:
        self.assertEqual(actionable(self.scan(self.pdf("clean"))), [])

    def test_styled_text_is_found(self) -> None:
        hits = [c for c in actionable(self.scan(self.pdf("text"))) if c.detector == "textstyle"]
        self.assertTrue(any("CONFIDENTIAL" in c.description for c in hits))

    def test_text_rotated_with_cm_is_found(self) -> None:
        hits = [c for c in actionable(self.scan(self.pdf("rotated_cm"))) if c.detector == "textstyle"]
        self.assertEqual(len(hits), 1)
        self.assertIn("INTERNAL", hits[0].description)
        self.assertTrue(any("angle" in str(e) for e in hits[0].evidence))

    def test_ocr_text_layer_is_left_alone(self) -> None:
        self.assertEqual(actionable(self.scan(self.pdf("ocr"))), [])

    def test_user_phrase_matches_across_tj_elements(self) -> None:
        hits = [c for c in self.scan(self.pdf("text"), phrases=["Watermark here"]) if c.detector == "phrase"]
        self.assertTrue(hits)
        self.assertGreaterEqual(hits[0].confidence, 0.9)

    def test_a_phrase_on_many_pages_is_one_finding(self) -> None:
        hits = [c for c in self.scan(self.pdf("many_pages")) if c.detector == "phrase"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].pages, list(range(10)))

    def test_builtin_phrases_skip_running_prose(self) -> None:
        self.assertFalse([c for c in actionable(self.scan(self.pdf("prose"))) if c.detector == "phrase"])

    def test_user_phrase_still_matches_prose_but_warns(self) -> None:
        hits = [c for c in self.scan(self.pdf("prose"), phrases=["Accepted Manuscript"]) if c.detector == "phrase"]
        self.assertTrue(hits)
        self.assertTrue(any("running text" in str(e) for e in hits[0].evidence))

    def test_stamp_annotation_is_found_and_link_ignored(self) -> None:
        cands = self.scan(self.pdf("annot"))
        hits = [c for c in actionable(cands) if c.kind is Kind.ANNOT]
        self.assertEqual([c.payload["subtype"] for c in hits], ["/Stamp"])
        self.assertTrue(all(c.payload.get("subtype") != "/Link" for c in cands))

    def test_watermark_layer_is_found(self) -> None:
        hits = [c for c in actionable(self.scan(self.pdf("ocg"))) if c.kind is Kind.OCG]
        self.assertEqual(len(hits), 1)

    def test_flattened_page_is_reported_not_actioned(self) -> None:
        cands = self.scan(self.pdf("scan"))
        self.assertEqual(len([c for c in cands if c.kind is Kind.IMAGE_PAGE]), 1)
        self.assertEqual(actionable(cands), [])


class RemoveTest(WatermarkTest):
    def test_stamp_is_removed_and_content_survives(self) -> None:
        out, report = self.clean(self.pdf("stamped"))
        self.assertTrue(report.changed)
        with pikepdf.open(out) as pdf:
            doc = Document(pdf)
            self.assertFalse([i for i in doc.invocations if i.name == "X1"])
            self.assertEqual(len({i.page for i in doc.invocations if i.name == "Base"}), 6)
            for page in pdf.pages:
                self.assertNotIn("/X1", page.Resources.XObject)
        self.assertIn("Real page content number 0", self.text_of(out))

    def test_phrase_removal_leaves_neighbouring_text(self) -> None:
        out, _ = self.clean(self.pdf("text"), phrases=["Watermark here"], no_builtin=True)
        body = self.text_of(out)
        self.assertNotIn("Watermark", body)
        self.assertIn("Ordinary body text that must survive removal untouched.", body)

    def test_whole_block_keeps_the_state_later_text_uses(self) -> None:
        out, report = self.clean(self.pdf("state_block"), phrases=["SECRETSTAMP"], no_builtin=True)
        self.assertGreater(report.glyphs_removed, 0)
        content = self.contents(out)
        self.assertNotIn(b"SECRETSTAMP", content)
        self.assertIn(b"/F1 12 Tf", content)
        self.assertIn(b"0.2 g", content)
        self.assertIn("Text that relies on the font set above.", self.text_of(out))

    def test_text_after_a_cut_stays_where_it_was(self) -> None:
        out, _ = self.clean(self.pdf("kept_positions"), phrases=["REMOVEME"], no_builtin=True)
        content = self.contents(out)
        # 8 glyphs of 500/1000 em each: a gap of 4000 where they were.
        self.assertRegex(content, rb"\[\s*\(KEEP \)\s*-4000(\.0)?\s*\( TAIL\)\s*\]\s*TJ")

    def test_a_ligature_before_the_phrase_does_not_shift_the_cut(self) -> None:
        out, _ = self.clean(self.pdf("ligature"), phrases=["REMOVE"], no_builtin=True)
        self.assertEqual(self.text_of(out), "Confidential  KEEP")

    def test_line_starting_stamp_goes_whole(self) -> None:
        out, _ = self.clean(self.pdf("many_pages"))
        body = self.text_of(out)
        self.assertNotIn("Downloaded", body)
        self.assertNotIn("example.org", body)
        self.assertIn("Page body 9", body)

    def test_annotation_removal_keeps_other_annots(self) -> None:
        out, _ = self.clean(self.pdf("annot"))
        with pikepdf.open(out) as pdf:
            self.assertEqual([str(a.Subtype) for a in pdf.pages[0].Annots], ["/Link"])

    def test_layer_goes_with_its_content(self) -> None:
        out, report = self.clean(self.pdf("ocg"))
        self.assertEqual(report.ocgs_removed, 1)
        body = self.text_of(out)
        self.assertNotIn("CONFIDENTIAL", body)
        self.assertIn("Real content that must stay.", body)
        with pikepdf.open(out) as pdf:
            props = pdf.Root.OCProperties
            self.assertEqual([str(o.Name) for o in props.OCGs], ["Notes"])
            nested = props.D.Order[1]
            self.assertEqual([str(o.Name) for o in nested], ["Notes"])

    def test_pages_with_nothing_removed_are_not_rewritten(self) -> None:
        path = self.pdf("many_pages")
        with pikepdf.open(path) as pdf:
            doc = Document(pdf)
            cands, _ = run_all(doc, Options(phrases=["Page body 3"], no_builtin=True))
            edits, report = remove.plan(doc, actionable(cands))
            remove.apply(doc, edits, report)
            dirty = sorted(p for scope in doc.scopes.values() if scope.dirty for p in scope.pages)
        self.assertEqual(dirty, [3])

    def test_flattened_scan_is_never_modified(self) -> None:
        _, report = self.clean(self.pdf("scan"))
        self.assertFalse(report.changed)


def run_action(source: Path, options: dict) -> tuple[dict, list]:
    made: list = []
    action = ACTIONS["remove_watermarks"]
    context = Context(run_id="t", source=source, source_name="Book.pdf", work=source.parent, source_info={},
                      progress=lambda *_: None, cancelled=lambda: False,
                      add_output=lambda name, path, info: made.append((name, path, info)))
    return action.run(context, parse_options(action, options)), made


class ActionTest(WatermarkTest):
    def test_check_lists_findings_and_writes_nothing(self) -> None:
        result, made = run_action(self.pdf("text"), {"mode": "check"})
        self.assertEqual(made, [])
        self.assertEqual(result["mode"], "check")
        ids = [f["id"] for f in result["findings"]]
        self.assertTrue(ids and all(re.fullmatch(r"[0-9a-f]{12}", i) for i in ids))
        again, _ = run_action(self.pdf("text"), {"mode": "check"})
        self.assertEqual(ids, [f["id"] for f in again["findings"]])

    def test_remove_picked_takes_only_those(self) -> None:
        path = self.pdf("text")
        check, _ = run_action(path, {"mode": "check", "phrases": ["Watermark here"]})
        phrase = next(f for f in check["findings"] if f["detector"] == "phrase")
        result, made = run_action(path, {"phrases": ["Watermark here"], "picked": [phrase["id"]]})
        self.assertEqual(made[0][0], "Book - no watermarks.pdf")
        self.assertEqual(result["removed"], 1)
        body = self.text_of(made[0][1])
        self.assertNotIn("Watermark", body)
        self.assertIn("CONFIDENTIAL", body)

    def test_nothing_found_keeps_the_file(self) -> None:
        path = self.pdf("clean")
        result, made = run_action(path, {})
        self.assertEqual(result["removed"], 0)
        self.assertEqual(made[0][1].read_bytes(), path.read_bytes())

    def test_bad_regex_is_refused(self) -> None:
        with self.assertRaises(ActionError):
            run_action(self.pdf("clean"), {"regexes": ["("]})

    def test_check_keeps_the_upload(self) -> None:
        action = ACTIONS["remove_watermarks"]
        self.assertTrue(action.keeps_upload(parse_options(action, {"mode": "check"})))
        self.assertFalse(action.keeps_upload(parse_options(action, {})))


if __name__ == "__main__":
    unittest.main()
