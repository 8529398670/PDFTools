"""GET /api/runs/download: what several runs made, as one zip with a folder
per run; someone else's run, or one that made nothing, is left out."""
from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from app.models import files, runs, utc_now

try:
    from app.tests.route_support import RoutesTestCase
except unittest.SkipTest:
    RoutesTestCase = None  # type: ignore[assignment,misc]


@unittest.skipIf(RoutesTestCase is None, "needs httpx2")
class DownloadRunsTest(RoutesTestCase or unittest.TestCase):  # type: ignore[misc]
    def setUp(self) -> None:
        super().setUp()
        cfg = self.holder.get()
        self.set_config(files=replace(cfg.files, max_file_bytes=10**9, quota_bytes_per_user=10**9))
        self.app.state.runner.submit = lambda run_id: None  # type: ignore[method-assign]
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)

    def done_run(self, user_id: int, source_name: str, outputs: dict[str, bytes]) -> runs.Run:
        cfg = self.holder.get()
        data = b"%PDF-1.4 source"
        source = files.create_file(self.store, cfg, user_id, source_name, "application/pdf", len(data))
        files.write_chunk(self.store, cfg, source, 0, data)
        source = files.finish_file(self.store, cfg, files.get_file(self.store, source.id))
        made = runs.create_run(self.store, user_id, "split_bookmarks", source, {})
        for name, content in outputs.items():
            path = self.scratch / f"{made.id}-{name}"
            path.write_bytes(content)
            output = files.add_output(self.store, cfg, user_id, name, path, made.id, source.id, {}, None)
            runs.add_output(self.store, made.id, output.id)
        return runs.update(self.store, made.id, state=runs.DONE, finished_at=utc_now())

    def fetch(self, ids: list[str]):  # type: ignore[no-untyped-def]
        return self.request("GET", "/api/runs/download?ids=" + ",".join(ids), cookie=self.user_cookie)

    def test_folder_per_run(self) -> None:
        first = self.done_run(self.user.id, "Book.pdf", {"01 One.pdf": b"one", "02 Two.pdf": b"two"})
        second = self.done_run(self.user.id, "Book.pdf", {"01 One.pdf": b"uno"})
        response = self.fetch([first.id, second.id])
        self.assertEqual(response.status_code, 200)
        self.assertIn("PDFTools%20-%203%20files.zip", response.headers["content-disposition"])
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.assertEqual(sorted(archive.namelist()), ["Book (2)/01 One.pdf", "Book/01 One.pdf", "Book/02 Two.pdf"])
        self.assertEqual(archive.read("Book (2)/01 One.pdf"), b"uno")

    def test_one_run_has_no_folder(self) -> None:
        only = self.done_run(self.user.id, "Atlas.pdf", {"a.pdf": b"a"})
        response = self.fetch([only.id])
        self.assertEqual(zipfile.ZipFile(io.BytesIO(response.content)).namelist(), ["a.pdf"])
        self.assertIn("Atlas%20-%20sections.zip", response.headers["content-disposition"])

    def test_someone_elses_run_is_left_out(self) -> None:
        mine = self.done_run(self.user.id, "Mine.pdf", {"m.pdf": b"m"})
        theirs = self.done_run(self.admin.id, "Theirs.pdf", {"t.pdf": b"t"})
        response = self.fetch([mine.id, theirs.id])
        self.assertEqual(zipfile.ZipFile(io.BytesIO(response.content)).namelist(), ["m.pdf"])
        self.assertEqual(self.fetch([theirs.id]).status_code, 404)

    def test_nothing_is_404(self) -> None:
        self.assertEqual(self.fetch([]).status_code, 404)


if __name__ == "__main__":
    unittest.main()
