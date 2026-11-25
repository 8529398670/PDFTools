"""`python -m app worker`: the process that runs actions.

The web server only queues runs (app/routes/runs.py, app/routes/chains.py);
with files.separate_worker on, the default, this process does them. It is
scripts/run.sh's second process, and docker/run.sh's second container
(docker/Dockerfile.worker, Debian, so the YOLO section finder's wheels fit
there later). It needs no network and publishes nothing.

It shares only the app directory with the server: the database (SQLite in
WAL mode, so both have it open; a run is claimed with a lease, so several
workers never take the same one, and one that dies gives its runs back when
the lease runs out), the stored files, and the work directory. Several
workers may run at once, on one machine or several containers on the same
data directory.

It never migrates the database: it waits until the server has brought it to
the version this code knows. It holds worker.lock shared, so a restore or a
key rotation refuses while it runs.

SIGTERM or Ctrl-C stops it: each run in hand stops at its next step and goes
back in the queue, to start again from the beginning here or in another
worker.
"""
from __future__ import annotations

import argparse
import signal
import threading
import time
from typing import Any

WAIT_SECONDS = 2.0
STOP_WAIT_SECONDS = 15.0


def parse(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app worker", description="Run queued actions.")
    parser.add_argument("--once", action="store_true", help="run what is queued now, then stop")
    return parser.parse_args(arguments)


def open_store(cfg: Any) -> Any:
    """The server's database, once the server has made it and brought it to
    the version this code knows."""
    from app.core import config, db

    told = False
    while True:
        if cfg.database_path.exists() and cfg.database_path.stat().st_size > 0:
            store = db.Store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
            if store.schema_version() == db.latest_schema_version():
                store.initialise()
                return store
            if store.schema_version() > db.latest_schema_version():
                raise RuntimeError("the database was written by a newer version of this app: update the worker too")
        if not told:
            print(f"[worker] waiting for the server to set up {cfg.database_path}", flush=True)
            told = True
        time.sleep(WAIT_SECONDS)
        cfg = config.load()


def main(arguments: list[str]) -> None:
    from app.core import config, config_live, run_worker, server_lock
    from app.models import chains, files

    args = parse(arguments)
    cfg = config.load()
    if cfg.rotation_pending:
        raise RuntimeError(config.ROTATION_PENDING_MESSAGE)
    store = open_store(cfg)
    lock = server_lock.acquire_shared(cfg.app_dir / server_lock.WORKER_LOCK_NAME)
    files.use_lock_dir(cfg.app_dir)
    settings = config_live.Holder(cfg)
    worker = run_worker.RunWorker(store, settings, where="worker", after_run=lambda run: chains.after_run(store, run))
    stopped = threading.Event()

    def stop(signum: int, frame: Any) -> None:
        print("[worker] stopping: the runs in hand go back in the queue", flush=True)
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"[worker] {worker.id}: {worker.threads} at a time, on {cfg.app_dir}", flush=True)
    try:
        if args.once:
            worker.beat()
            done = worker.run_once()
            print(f"[worker] ran {done}", flush=True)
            return
        worker.start()
        while not stopped.wait(2.0):
            try:
                settings.poll()
            except Exception as error:  # noqa: BLE001 -- a bad edit keeps the last good config
                print(f"[worker] config: {error}", flush=True)
    finally:
        worker.stop(wait=STOP_WAIT_SECONDS)
        if lock is not None:
            lock.release()
        print("[worker] stopped", flush=True)


def healthy(within: float = 60.0) -> None:
    """Raises unless a worker on this host checked in within the last within
    seconds: the worker container's HEALTHCHECK."""
    import socket

    from app.core import config
    from app.models import runs

    cfg = config.load()
    store = open_store(cfg)
    host = socket.gethostname()
    if not any(worker.get("host") == host for worker in runs.workers(store, within)):
        raise RuntimeError(f"no worker on {host} has checked in for {int(within)}s")
