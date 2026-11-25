"""The web server's side of the work: the first look at each imported PDF,
queueing runs, and telling open pages when anything moved.

Actions themselves are run by a RunWorker (app/core/run_worker.py): in a
process of their own (`python -m app worker`) when files.separate_worker is
on, the default, or on threads here when it is off. Either way the queue is
the runs bucket, so this side only writes a run as queued, nudges the
workers, and asks for cancels on the record.

Looks stay here, on two threads of their own: they are quick pikepdf reads,
and a fresh upload should never wait behind a long split to show its pages and
bookmarks.

Every change, made here or by a worker in another process, bumps the work
counter (runs.bump_work). A watcher thread reads it every WATCH_SECONDS and
announces "runs" or "files" on the work hub, and the page fetches what it
shows again.
"""
from __future__ import annotations

import asyncio
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.actions import pdf as pdf_tools
from app.core import config_live, db, run_worker, sse
from app.models import files, runs

LOOK_WORKERS = 2
WATCH_SECONDS = 0.5

EVENT_RUNS = sse.event("runs", "1")
EVENT_FILES = sse.event("files", "1")


class Runner:
    def __init__(self, store: db.Store, settings: config_live.Holder, hub: sse.Hub) -> None:
        self.store = store
        self.settings = settings
        self.hub = hub
        boot = settings.boot()
        self.app_dir = boot.app_dir
        self.looks = ThreadPoolExecutor(max_workers=LOOK_WORKERS, thread_name_prefix="look")
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stopping = threading.Event()
        # Off: this process runs actions too.
        self.inline: run_worker.RunWorker | None = None
        if not boot.files.separate_worker:
            from app.models import chains

            self.inline = run_worker.RunWorker(store, settings, where="server", after_run=lambda run: chains.after_run(store, run))
        self._watcher: threading.Thread | None = None

    # -- the outside ---------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Pick up what a stop left, and start watching for changes. From the
        event loop; the reading happens in a worker."""
        self.loop = loop
        self.looks.submit(self._pick_up)
        self._watcher = threading.Thread(target=self._watch, name="work-watch", daemon=True)
        self._watcher.start()
        if self.inline is not None:
            self.inline.start()

    def stop(self) -> None:
        """Ask what is running to stop at its next step, and drop what has not
        started. Does not wait: the records say where each one got to."""
        self.stopping.set()
        self.looks.shutdown(wait=False, cancel_futures=True)
        if self.inline is not None:
            self.inline.stop()

    def submit(self, run_id: str) -> None:
        """A run was written as queued: wake whichever worker is idle."""
        run_worker.nudge(self.app_dir)

    def look_at(self, file_id: str) -> None:
        self.looks.submit(self._look, file_id)

    def cancel(self, run_id: str) -> None:
        """A queued run is marked at once; a running one stops at its next
        step, and its worker marks it."""
        runs.request_cancel(self.store, run_id)

    def restart(self, run_id: str) -> None:
        """runs.restart_run has put the run back to queued."""
        self.submit(run_id)

    def publish(self, message: bytes) -> None:
        if self.loop is not None:
            sse.publish_from_thread(self.loop, self.hub, message)

    def _drop_used_upload(self, file_id: str) -> None:
        run_worker.drop_used_upload(self.store, file_id)

    # -- the watcher -----------------------------------------------------------

    def _watch(self) -> None:
        seen = None
        while not self.stopping.wait(WATCH_SECONDS):
            try:
                now = runs.work_version(self.store)
            except Exception:  # noqa: BLE001 -- a busy database: look again next time
                continue
            if seen is not None and now != seen:
                if now[0] != seen[0]:
                    self.publish(EVENT_RUNS)
                if now[1] != seen[1]:
                    self.publish(EVENT_FILES)
            seen = now

    # -- the looks -------------------------------------------------------------

    def _pick_up(self) -> None:
        try:
            looking = set()
            for file in files.all_files(self.store):
                if file.state == files.READY and not file.deleted and file.kind == files.KIND_IMPORT and file.pdf_state == files.PDF_PENDING:
                    looking.add(file.id)
                    self.look_at(file.id)
            # Files that still have their own bytes, from before an adoption
            # was cut off or from before bytes were shared at all.
            for file_id in files.files_to_adopt(self.store):
                if file_id not in looking:
                    self.looks.submit(self._adopt, file_id)
        except Exception:  # noqa: BLE001 -- a bad record must not stop the server
            traceback.print_exc()

    def _adopt(self, file_id: str) -> None:
        """Move a file onto the shared bytes (files.adopt_blob). A failure is
        logged and the file keeps its own bytes; the next start tries again."""
        if self.stopping.is_set():
            return
        try:
            files.adopt_blob(self.store, self.settings.get(), file_id)
        except Exception:  # noqa: BLE001 -- the file is fine as it is
            traceback.print_exc()

    def _look(self, file_id: str) -> None:
        """The first look at an import: its bytes shared with any file that
        has the same content, then is it a PDF, how many pages, how deep do
        its bookmarks go. What another file with the same bytes found is taken
        as it is."""
        if self.stopping.is_set():
            return
        self._adopt(file_id)
        cfg = self.settings.get()
        file = files.get_file(self.store, file_id)
        if file is None or file.deleted or file.state != files.READY:
            return
        if file.blob:
            found = files.sibling_pdf(self.store, file.blob, file.id)
            if found is not None:
                files.set_pdf_info(self.store, file.id, found[0], found[1], found[2])
                self.publish(EVENT_FILES)
                return
        scratch: Path | None = None
        try:
            if file.encrypted:
                scratch = files.work_dir(cfg) / f"look-{file.id}.pdf"
                files.plain_copy(cfg, file, scratch)
                path = scratch
            else:
                path = files.readable_path(cfg, file)
            info = pdf_tools.inspect(path)
            files.set_pdf_info(self.store, file.id, files.PDF_OK, info)
        except pdf_tools.NotAPDFError as refusal:
            files.set_pdf_info(self.store, file.id, files.PDF_INVALID, {}, str(refusal))
        except Exception:  # noqa: BLE001 -- whatever it was, this file cannot be read
            traceback.print_exc()
            files.set_pdf_info(self.store, file.id, files.PDF_INVALID, {}, "damaged")
        finally:
            if scratch is not None:
                scratch.unlink(missing_ok=True)
        self.publish(EVENT_FILES)
