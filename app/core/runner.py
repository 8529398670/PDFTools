"""Runs actions, and takes the first look at each imported PDF, in worker
threads.

This is a queue of work people asked for, not work on a schedule, so it is not
a job (app/core/jobs.py): a split of a 3 GB book takes minutes, and many can be
asked for at once. Two pools:

- runs: files.workers threads, for actions;
- looks: two threads for inspecting new imports, so a long split never keeps a
  fresh upload waiting to show its pages and bookmarks.

What is queued lives in the database, not here. On start, every run left queued
or running by a stop or a crash is started again from the beginning, after what
it had made so far is put in the bin, and every import not yet looked at is
looked at. Stopping ends what is running at its next step and leaves it queued.

Every change is announced on the work hub as "runs" or "files", and the page
fetches what it shows again.
"""
from __future__ import annotations

import asyncio
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.actions import ACTIONS, ActionError, Cancelled, Context, parse_options
from app.actions import pdf as pdf_tools
from app.core import config_live, db, sse
from app.models import files, retention, runs, utc_now

# How often a run's progress is written, and announced, while it moves.
PROGRESS_SECONDS = 1.0
LOOK_WORKERS = 2

EVENT_RUNS = sse.event("runs", "1")
EVENT_FILES = sse.event("files", "1")


class Runner:
    def __init__(self, store: db.Store, settings: config_live.Holder, hub: sse.Hub) -> None:
        self.store = store
        self.settings = settings
        self.hub = hub
        workers = settings.boot().files.workers
        self.runs = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="run")
        self.looks = ThreadPoolExecutor(max_workers=LOOK_WORKERS, thread_name_prefix="look")
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stopping = threading.Event()
        self._lock = threading.Lock()
        self._cancelled: set[str] = set()
        self._queued: set[str] = set()

    # -- the outside ---------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Pick up what a stop left. From the event loop; the reading happens
        in a worker."""
        self.loop = loop
        self.looks.submit(self._pick_up)

    def stop(self) -> None:
        """Ask what is running to stop at its next step, and drop what has not
        started. Does not wait: the records say where each one got to."""
        self.stopping.set()
        self.runs.shutdown(wait=False, cancel_futures=True)
        self.looks.shutdown(wait=False, cancel_futures=True)

    def submit(self, run_id: str) -> None:
        with self._lock:
            if run_id in self._queued:
                return
            self._queued.add(run_id)
        self.runs.submit(self._run, run_id)

    def look_at(self, file_id: str) -> None:
        self.looks.submit(self._look, file_id)

    def cancel(self, run_id: str) -> None:
        """A queued run is marked at once; a running one stops at its next
        step, and its worker marks it."""
        with self._lock:
            self._cancelled.add(run_id)
        run = runs.get_run(self.store, run_id)
        if run is not None and run.state == runs.QUEUED:
            runs.update(self.store, run_id, state=runs.CANCELLED, finished_at=utc_now())
            self.publish(EVENT_RUNS)

    def publish(self, message: bytes) -> None:
        if self.loop is not None:
            sse.publish_from_thread(self.loop, self.hub, message)

    # -- the workers ---------------------------------------------------------

    def _pick_up(self) -> None:
        try:
            for run in runs.unfinished(self.store):
                if run.state == runs.RUNNING:
                    runs.update(self.store, run.id, state=runs.QUEUED)
                self.submit(run.id)
            for file in files.all_files(self.store):
                if file.state == files.READY and not file.deleted and file.kind == files.KIND_IMPORT and file.pdf_state == files.PDF_PENDING:
                    self.look_at(file.id)
        except Exception:  # noqa: BLE001 -- a bad record must not stop the server
            traceback.print_exc()

    def _is_cancelled(self, run_id: str) -> bool:
        with self._lock:
            return self.stopping.is_set() or run_id in self._cancelled

    def _look(self, file_id: str) -> None:
        """The first look at an import: is it a PDF, how many pages, how deep
        do its bookmarks go."""
        if self.stopping.is_set():
            return
        cfg = self.settings.get()
        file = files.get_file(self.store, file_id)
        if file is None or file.deleted or file.state != files.READY:
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

    def _run(self, run_id: str) -> None:
        with self._lock:
            self._queued.discard(run_id)
        if self.stopping.is_set():
            return
        run = runs.get_run(self.store, run_id)
        if run is None or run.deleted or run.state in runs.FINISHED:
            return
        cfg = self.settings.get()
        work = files.work_dir(cfg) / f"run-{run.id}"
        try:
            self._execute(run, cfg, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            with self._lock:
                self._cancelled.discard(run_id)
            self.publish(EVENT_RUNS)
            self.publish(EVENT_FILES)

    def _execute(self, run: runs.Run, cfg: Any, work: Path) -> None:
        action = ACTIONS.get(run.action)
        source = files.get_file(self.store, run.file_id)
        if action is None or source is None or source.deleted or source.state != files.READY:
            runs.update(self.store, run.id, state=runs.FAILED, message="source_gone" if action else "unknown_action", finished_at=utc_now())
            return
        if run.outputs:
            runs.drop_outputs(self.store, run)
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(mode=0o700, parents=True)
        runs.update(self.store, run.id, state=runs.RUNNING, started_at=utc_now(), progress=0.0, message="", result={})
        self.publish(EVENT_RUNS)

        last_write = 0.0

        def progress(fraction: float, step: str) -> None:
            nonlocal last_write
            now = time.monotonic()
            if now - last_write < PROGRESS_SECONDS and fraction < 1:
                return
            last_write = now
            runs.update(self.store, run.id, progress=round(max(0.0, min(fraction, 1.0)), 4), step=step)
            self.publish(EVENT_RUNS)

        def add_output(name: str, path: Path, info: dict[str, Any]) -> None:
            expires = retention.expiry_for(self.store, run.user_id, files.KIND_OUTPUT)
            made = files.add_output(self.store, cfg, run.user_id, name, path, run.id, source.id, info, expires)
            runs.add_output(self.store, run.id, made.id)

        try:
            options = parse_options(action, run.options)
            if source.encrypted:
                readable = work / "source.pdf"
                files.plain_copy(cfg, source, readable)
            else:
                readable = files.readable_path(cfg, source)
            context = Context(
                run_id=run.id,
                source=readable,
                work=work,
                source_info=source.pdf,
                progress=progress,
                cancelled=lambda: self._is_cancelled(run.id),
                add_output=add_output,
            )
            result = action.run(context, options)
        except Cancelled:
            if self.stopping.is_set():
                # Picked up again on the next start, from the beginning.
                runs.update(self.store, run.id, state=runs.QUEUED, progress=0.0)
            else:
                current = runs.get_run(self.store, run.id)
                if current is not None:
                    runs.drop_outputs(self.store, current)
                runs.update(self.store, run.id, state=runs.CANCELLED, finished_at=utc_now())
            return
        except files.FileQuotaError:
            self._fail(run, "file_quota")
            return
        except (ActionError, pdf_tools.NotAPDFError) as refusal:
            self._fail(run, str(refusal))
            return
        except Exception:  # noqa: BLE001 -- the run fails, the server goes on
            traceback.print_exc()
            self._fail(run, "internal")
            return
        runs.update(self.store, run.id, state=runs.DONE, progress=1.0, step="", result=result, finished_at=utc_now())

    def _fail(self, run: runs.Run, code: str) -> None:
        current = runs.get_run(self.store, run.id)
        if current is not None:
            runs.drop_outputs(self.store, current)
        runs.update(self.store, run.id, state=runs.FAILED, message=code, step="", finished_at=utc_now())
