"""Chains (app/models/chains.py), run by a real worker on real PDFs: each step
runs on every file the step before made, the chain ends exactly once with
only the last step's files left, a failed step stops it, and a stopped chain
can start again."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pikepdf

from app.actions import pdf as pdf_tools
from app.core import db, run_worker
from app.models import chains, files, runs, users
from app.tests.support import new_holder

ROTATE = {"action": "rotate", "options": {"angle": 90, "pages": "all"}}
SPLIT = {"action": "split_bookmarks", "options": {"level": 1, "front_matter": True, "inner_bookmarks": True, "numbered": True}}
COMPRESS = {"action": "compress", "options": {"level": "lossless", "image_dpi": 150}}


def book(path: Path, bookmarks: bool = True) -> bytes:
    pdf = pikepdf.Pdf.new()
    for index in range(9):
        pdf.add_blank_page(page_size=(200, 200))
        pdf.pages[index].Contents = pdf.make_stream(f"BT /F1 24 Tf 20 100 Td (Page {index + 1}) Tj ET".encode())
    if bookmarks:
        with pdf.open_outline() as outline:
            outline.root.extend([pikepdf.OutlineItem("One", 0), pikepdf.OutlineItem("Two", 3), pikepdf.OutlineItem("Three", 6)])
    pdf.save(path)
    return path.read_bytes()


class ChainTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.holder, _ = new_holder(self, app_dir=str(self.dir / "data"))
        self.holder._current = replace(self.holder.get(), files=replace(self.holder.get().files, max_file_bytes=10**9, quota_bytes_per_user=10**9))
        self.holder._boot = self.holder.get()
        self.cfg = self.holder.get()
        self.cfg.app_dir.mkdir(parents=True, exist_ok=True)
        self.store = db.open_store(self.cfg.database_path, self.cfg.secret_key, self.cfg.encrypt_at_rest)
        self.user = users.create_user(self.store, "User", users.ROLE_USER)
        self.worker = run_worker.RunWorker(self.store, self.holder, after_run=lambda run: chains.after_run(self.store, run))

    def upload(self, bookmarks: bool = True) -> files.File:
        data = book(self.dir / "book.pdf", bookmarks)
        made = files.create_file(self.store, self.cfg, self.user.id, "Book.pdf", "application/pdf", len(data))
        files.write_chunk(self.store, self.cfg, made, 0, data)
        files.finish_file(self.store, self.cfg, files.get_file(self.store, made.id))
        files.set_pdf_info(self.store, made.id, files.PDF_OK, pdf_tools.inspect(self.dir / "book.pdf"))
        return files.get_file(self.store, made.id)

    def final_files(self, chain: chains.Chain) -> list[files.File]:
        return [made for run in chains.final_runs(self.store, chain) for made in runs.outputs_of(self.store, run)]

    def test_three_steps_fan_out(self) -> None:
        chain, _ = chains.create_chain(self.store, self.user.id, self.upload(), [ROTATE, SPLIT, COMPRESS])
        self.worker.run_once()
        done = chains.get_chain(self.store, chain.id)
        self.assertEqual((done.state, done.pending), (chains.DONE, 0))
        chain_runs = chains.runs_of(self.store, chain.id)
        self.assertEqual([run.step_index for run in chain_runs], [0, 1, 2, 2, 2])
        self.assertTrue(all(run.state == runs.DONE for run in chain_runs))
        made = self.final_files(done)
        self.assertEqual([file.name for file in made], ["01 - One - compressed.pdf", "02 - Two - compressed.pdf", "03 - Three - compressed.pdf"])
        for file in made:
            with pikepdf.open(files.readable_path(self.cfg, file)) as pdf:
                self.assertEqual([int(page.obj.get("/Rotate", 0)) for page in pdf.pages], [90, 90, 90])
        # What the steps before the last made is in the bin.
        between = [file_id for run in chain_runs if run.step_index < 2 for file_id in run.outputs]
        self.assertTrue(all(files.get_file(self.store, file_id).deleted for file_id in between))
        self.assertEqual(chains.progress(done, chain_runs), 1.0)

    def test_a_failed_step_stops_the_chain(self) -> None:
        chain, _ = chains.create_chain(self.store, self.user.id, self.upload(bookmarks=False), [ROTATE, SPLIT, COMPRESS])
        self.worker.run_once()
        stopped = chains.get_chain(self.store, chain.id)
        self.assertEqual((stopped.state, stopped.message, stopped.pending), (chains.FAILED, "no_bookmarks", 0))
        self.assertEqual([run.state for run in chains.runs_of(self.store, chain.id)], [runs.DONE, runs.FAILED])

    def test_cancel_then_restart(self) -> None:
        chain, _ = chains.create_chain(self.store, self.user.id, self.upload(), [ROTATE, COMPRESS])
        chains.cancel_chain(self.store, chain.id)
        cancelled = chains.get_chain(self.store, chain.id)
        self.assertEqual((cancelled.state, cancelled.pending), (chains.CANCELLED, 0))
        self.assertEqual(chains.restart_chain(self.store, chain.id), [chains.runs_of(self.store, chain.id)[0].id])
        self.worker.run_once()
        done = chains.get_chain(self.store, chain.id)
        self.assertEqual(done.state, chains.DONE)
        self.assertEqual([file.name for file in self.final_files(done)], ["Book - rotated - compressed.pdf"])
        self.assertIsNone(chains.restart_chain(self.store, chain.id))

    def test_a_run_of_no_chain_is_left_alone(self) -> None:
        one = runs.create_run(self.store, self.user.id, "rotate", self.upload(), {})
        self.worker.run_once()
        self.assertEqual(runs.get_run(self.store, one.id).state, runs.DONE)
        self.assertEqual(chains.after_run(self.store, runs.get_run(self.store, one.id)), [])


if __name__ == "__main__":
    unittest.main()
