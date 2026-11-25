"""What a PDF link does (app/models/pdf_links.py, POST /api/account/pdf-links)
and the two ways to fetch a file: .../download always an attachment, .../view
a PDF inline and anything else still an attachment."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.models import files, pdf_links

try:
    from app.tests.route_support import RoutesTestCase
except unittest.SkipTest:  # without httpx2 only the checks below run
    RoutesTestCase = None  # type: ignore[assignment,misc]


class EffectiveTest(unittest.TestCase):
    def test_nothing_stored_is_open(self) -> None:
        self.assertEqual(pdf_links.effective(""), "open")
        self.assertEqual(pdf_links.effective("download"), "download")
        self.assertEqual(pdf_links.effective("junk"), "open")


@unittest.skipIf(RoutesTestCase is None, "needs httpx2")
class RouteTest(RoutesTestCase or unittest.TestCase):  # type: ignore[misc]
    def setUp(self) -> None:
        super().setUp()
        cfg = self.holder.get()
        self.set_config(files=replace(cfg.files, max_file_bytes=10**9, quota_bytes_per_user=10**9))
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)

    def choose(self, choice: str) -> tuple[int, dict]:
        return self.call("POST", "/api/account/pdf-links", cookie=self.user_cookie,
                         body={"pdf_links": choice, "csrf_token": self.csrf(self.user_cookie)})

    def test_default_is_open_and_choice_round_trips(self) -> None:
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["pdf_links"], "open")
        status, reply = self.choose("download")
        self.assertEqual((status, reply["pdf_links"]), (200, "download"))
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["pdf_links"], "download")
        _, other = self.call("GET", "/api/me", cookie=self.owner_cookie)
        self.assertEqual(other["pdf_links"], "open")
        self.choose("open")
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["pdf_links"], "open")

    def test_bad_choice_is_refused(self) -> None:
        status, _ = self.choose("print")
        self.assertEqual(status, 400)

    def output(self) -> files.File:
        cfg = self.holder.get()
        path = self.scratch / "out.pdf"
        path.write_bytes(b"%PDF-1.4 made")
        return files.add_output(self.store, cfg, self.user.id, "Out.pdf", path, "", "", {}, None)

    def test_view_is_inline_pdf_and_download_stays_attachment(self) -> None:
        made = self.output()
        viewed = self.request("GET", f"/api/files/{made.id}/view", cookie=self.user_cookie)
        self.assertEqual(viewed.status_code, 200)
        self.assertTrue(viewed.headers["content-disposition"].startswith("inline;"))
        self.assertEqual(viewed.headers["content-type"], "application/pdf")
        self.assertEqual(viewed.content, b"%PDF-1.4 made")
        downloaded = self.request("GET", f"/api/files/{made.id}/download", cookie=self.user_cookie)
        self.assertTrue(downloaded.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(downloaded.headers["content-type"], "application/octet-stream")

    def test_view_of_an_unread_file_is_still_an_attachment(self) -> None:
        cfg = self.holder.get()
        data = b"<html>not a pdf</html>"
        upload = files.create_file(self.store, cfg, self.user.id, "page.pdf", "application/pdf", len(data))
        files.write_chunk(self.store, cfg, upload, 0, data)
        upload = files.finish_file(self.store, cfg, files.get_file(self.store, upload.id))
        self.assertNotEqual(upload.pdf_state, files.PDF_OK)
        viewed = self.request("GET", f"/api/files/{upload.id}/view", cookie=self.user_cookie)
        self.assertEqual(viewed.status_code, 200)
        self.assertTrue(viewed.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(viewed.headers["content-type"], "application/octet-stream")

    def test_someone_elses_file_is_not_found(self) -> None:
        made = self.output()
        viewed = self.request("GET", f"/api/files/{made.id}/view", cookie=self.owner_cookie)
        self.assertEqual(viewed.status_code, 404)


if __name__ == "__main__":
    unittest.main()
