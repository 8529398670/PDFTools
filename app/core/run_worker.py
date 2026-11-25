"""Runs actions: claims queued runs from the database and does them.

The same code runs in two places:

- inside the web server, when files.separate_worker is off;
- in a process of its own, `python -m app worker` (app/worker/run.py), which
  scripts/run.sh starts beside the server and docker/run.sh runs as a
  container of its own, so a heavy action never slows a page.

Either way the queue is the runs bucket (app/models/runs.py): each of
files.workers threads claims the oldest queued run with a lease, a heartbeat
thread renews the lease while it works, and a run whose worker died is claimed
again once its lease runs out. A new run touches a nudge file in the app
directory, which wakes an idle worker at once; without one it looks every
few seconds anyway.

Stopping ends what is running at its next step and puts it back in the queue,
for this worker or another, which starts it again from the beginning.
"""
from __future__ import annotations

import os
import shutil
import socket
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

from app.actions import ACTIONS, ActionError, Cancelled, Context, parse_options
from app.actions import pdf as pdf_tools
from app.core import config_live, db
from app.models import files, retention, runs, utc_now

# How often a run's progress is written while it moves, and how often its
# cancel flag is read.
PROGRESS_SECONDS = 1.0
CANCEL_CHECK_SECONDS = 1.0
# How long an idle worker waits before looking at the queue again, when no
# nudge comes.
IDLE_SECONDS = 3.0
NUDGE_POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = runs.LEASE_SECONDS / 3
NUDGE_NAME = "runs.nudge"


def nudge_path(app_dir: Path) -> Path:
    return app_dir / NUDGE_NAME


def nudge(app_dir: Path) -> None:
    """Wake the workers: a run was queued. Touching a file works across
    processes and containers that share the app directory."""
    path = nudge_path(app_dir)
    try:
        path.touch(mode=0o600)
        os.utime(path, None)
    except OSError:
        pass  # they look every IDLE_SECONDS anyway


class RunWorker:
    def __init__(self, store: db.Store, settings: config_live.Holder, where: str = "server",
                 after_run: Callable[[runs.Run], Any] | None = None) -> None:
        self.store = store
        self.settings = settings
        boot = settings.boot()
        self.app_dir = boot.app_dir
        self.threads = boot.files.workers
        self.where = where
        # Called after each run ends, whatever became of it (chains hang the
        # next step off it; app/models/chains.py).
        self.after_run = after_run
        self.id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.started = time.time()
        self.stopping = threading.Event()
        self._doing: dict[str, str] = {}
        self._lock = threading.Lock()
        self._pool: list[threading.Thread] = []
        self._beat: threading.Thread | None = None

    # -- the outside ---------------------------------------------------------

    def start(self) -> None:
        self.beat()
        self._beat = threading.Thread(target=self._heartbeat, name="run-heartbeat", daemon=True)
        self._beat.start()
        for index in range(self.threads):
            thread = threading.Thread(target=self._loop, name=f"run-{index}", daemon=True)
            thread.start()
            self._pool.append(thread)

    def stop(self, wait: float = 0.0) -> None:
        """Ask what is running to stop at its next step. With wait, give the
        threads that long to hand their runs back; whatever is still held then
        is released so another worker can take it at once."""
        self.stopping.set()
        deadline = time.monotonic() + wait
        for thread in self._pool:
            thread.join(max(0.0, deadline - time.monotonic()))
        try:
            runs.release(self.store, self.id)
            runs.gone(self.store, self.id)
        except Exception:  # noqa: BLE001 -- the leases run out by themselves
            traceback.print_exc()

    def run_once(self) -> int:
        """Claim and run what is due, one at a time, then answer how many ran.
        For `python -m app worker --once` and the tests."""
        done = 0
        while not self.stopping.is_set():
            run = runs.claim_next(self.store, self.id)
            if run is None:
                return done
            self._do(run)
            done += 1
        return done

    # -- checking in -----------------------------------------------------------

    def beat(self) -> None:
        with self._lock:
            doing = list(self._doing.values())
        runs.beat(self.store, {
            "id": self.id, "host": socket.gethostname(), "pid": os.getpid(), "where": self.where,
            "started": self.started, "threads": self.threads, "doing": doing,
        })

    def _heartbeat(self) -> None:
        while not self.stopping.wait(HEARTBEAT_SECONDS):
            try:
                with self._lock:
                    held = list(self._doing)
                for run_id in held:
                    runs.renew(self.store, run_id, self.id)
                self.beat()
            except Exception as error:  # noqa: BLE001 -- a busy database: try again next beat
                print(f"[worker] heartbeat: {error!r}", flush=True)

    # -- the loop --------------------------------------------------------------

    def _wait_for_nudge(self) -> None:
        path = nudge_path(self.app_dir)

        def stamp() -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        seen = stamp()
        deadline = time.monotonic() + IDLE_SECONDS
        while time.monotonic() < deadline and not self.stopping.is_set():
            if stamp() != seen:
                return
            self.stopping.wait(NUDGE_POLL_SECONDS)

    def _loop(self) -> None:
        while not self.stopping.is_set():
            try:
                run = runs.claim_next(self.store, self.id)
            except Exception as error:  # noqa: BLE001 -- a busy database: try again soon
                print(f"[worker] claim: {error!r}", flush=True)
                run = None
            if run is None:
                self._wait_for_nudge()
                continue
            self._do(run)

    def _do(self, run: runs.Run) -> None:
        with self._lock:
            self._doing[run.id] = run.id
        cfg = self.settings.get()
        work = files.work_dir(cfg) / f"run-{run.id}"
        try:
            self._execute(run, cfg, work)
        except Exception:  # noqa: BLE001 -- the worker goes on
            traceback.print_exc()
        finally:
            shutil.rmtree(work, ignore_errors=True)
            with self._lock:
                self._doing.pop(run.id, None)
            runs.bump_work(self.store, "files")
        if self.after_run is not None:
            try:
                finished = runs.get_run(self.store, run.id)
                if finished is not None and self.after_run(finished):
                    nudge(self.app_dir)
            except Exception:  # noqa: BLE001 -- a chain step that cannot be queued is reported on the chain
                traceback.print_exc()

    def _held(self, run_id: str) -> bool:
        run = runs.get_run(self.store, run_id)
        return run is not None and run.owner == self.id and run.state == runs.RUNNING

    def _execute(self, run: runs.Run, cfg: Any, work: Path) -> None:
        if run.cancel_requested:
            runs.update(self.store, run.id, state=runs.CANCELLED, owner="", lease_until=0.0, cancel_requested=False, finished_at=utc_now())
            return
        action = ACTIONS.get(run.action)
        source = files.get_file(self.store, run.file_id)
        if action is None or source is None or source.deleted or source.state != files.READY:
            self._fail(run, "source_gone" if action else "unknown_action")
            return
        if run.outputs:
            runs.drop_outputs(self.store, run)
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(mode=0o700, parents=True)
        runs.update(self.store, run.id, started_at=utc_now(), progress=0.0, message="", result={})

        last_write = 0.0
        last_check = 0.0
        asked = False

        def progress(fraction: float, step: str) -> None:
            nonlocal last_write
            now = time.monotonic()
            if now - last_write < PROGRESS_SECONDS and fraction < 1:
                return
            last_write = now
            runs.update(self.store, run.id, progress=round(max(0.0, min(fraction, 1.0)), 4), step=step)

        def cancelled() -> bool:
            nonlocal last_check, asked
            if self.stopping.is_set() or asked:
                return True
            now = time.monotonic()
            if now - last_check >= CANCEL_CHECK_SECONDS:
                last_check = now
                asked = runs.cancel_requested(self.store, run.id)
            return asked

        def add_output(name: str, path: Path, info: dict[str, Any]) -> None:
            kind_expiry = retention.expiry_for(self.store, run.user_id, files.KIND_OUTPUT)
            made = files.add_output(self.store, cfg, run.user_id, name, path, run.id, source.id, info, kind_expiry)
            runs.add_output(self.store, run.id, made.id)

        try:
            options = parse_options(action, run.options)
            if source.encrypted:
                readable = work / "source.pdf"
                files.plain_copy(cfg, source, readable)
            else:
                readable = files.readable_path(cfg, source)
            info = source.pdf
            if run.chain_id or (action.needs_bookmarks and not info.get("levels")):
                # A step of a chain gets a file another step made, whose
                # record says only what that step knew: look again.
                info = pdf_tools.inspect(readable)
            if action.needs_bookmarks and not info.get("bookmarks"):
                raise ActionError("no_bookmarks")
            context = Context(
                run_id=run.id,
                source=readable,
                source_name=source.name,
                work=work,
                source_info=info,
                progress=progress,
                cancelled=cancelled,
                add_output=add_output,
            )
            result = action.run(context, options)
        except Cancelled:
            current = runs.get_run(self.store, run.id)
            if current is not None:
                runs.drop_outputs(self.store, current)
            if self.stopping.is_set() and not asked:
                # Picked up again, by this worker's next start or another one.
                runs.update(self.store, run.id, state=runs.QUEUED, owner="", lease_until=0.0, progress=0.0, step="")
            else:
                runs.update(self.store, run.id, state=runs.CANCELLED, owner="", lease_until=0.0, cancel_requested=False, step="", finished_at=utc_now())
            return
        except files.FileQuotaError:
            self._fail(run, "file_quota")
            return
        except (ActionError, pdf_tools.NotAPDFError) as refusal:
            self._fail(run, str(refusal))
            return
        except Exception:  # noqa: BLE001 -- the run fails, the worker goes on
            traceback.print_exc()
            self._fail(run, "internal")
            return
        if not self._held(run.id):
            # Another worker took it over while this one was stalled: its
            # result is the one that counts.
            return
        runs.update(self.store, run.id, state=runs.DONE, owner="", lease_until=0.0, progress=1.0, step="", result=result, finished_at=utc_now())
        if not run.chain_id:
            drop_used_upload(self.store, run.file_id)

    def _fail(self, run: runs.Run, code: str) -> None:
        current = runs.get_run(self.store, run.id)
        if current is not None:
            runs.drop_outputs(self.store, current)
        runs.update(self.store, run.id, state=runs.FAILED, owner="", lease_until=0.0, message=code, step="", finished_at=utc_now())


def drop_used_upload(store: db.Store, file_id: str) -> None:
    """An upload its owner chose to keep only for the run (files.KEEP_RUN)
    goes to the bin once a run on it is done, unless another run on it is
    still to come. A cancelled or failed run leaves it, so it can be
    restarted; it expires in a day anyway."""
    source = files.get_file(store, file_id)
    if source is None or source.deleted or source.keep != files.KEEP_RUN:
        return
    if any(other.file_id == file_id for other in runs.unfinished(store)):
        return
    files.delete_file(store, file_id, source.user_id)
    runs.bump_work(store, "files")
