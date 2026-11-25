"""The run queue in the database (app/models/runs.py): a run is claimed by one
worker only, a run whose worker went quiet is claimed again once its lease
runs out, a stopping worker hands its runs back, and a cancel reaches a run
held by a worker in another process through the record."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from app.core import db
from app.models import files, runs, users
from app.tests.support import new_holder

DATA = b"%PDF-1.4\n" + b"x" * 2000


class ClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        holder, _ = new_holder(self, app_dir=str(Path(directory.name) / "data"))
        self.cfg = holder.get()
        self.cfg.app_dir.mkdir(parents=True, exist_ok=True)
        self.store = db.open_store(self.cfg.database_path, self.cfg.secret_key, self.cfg.encrypt_at_rest)
        self.user = users.create_user(self.store, "User", users.ROLE_USER)
        made = files.create_file(self.store, self.cfg, self.user.id, "book.pdf", "application/pdf", len(DATA))
        files.write_chunk(self.store, self.cfg, made, 0, DATA)
        files.finish_file(self.store, self.cfg, files.get_file(self.store, made.id))
        self.file = files.get_file(self.store, made.id)

    def queue(self, count: int) -> list[runs.Run]:
        return [runs.create_run(self.store, self.user.id, "rotate", self.file, {}) for _ in range(count)]

    def test_oldest_first_and_never_twice(self) -> None:
        queued = self.queue(20)
        taken: list[str] = []
        lock = threading.Lock()

        def worker(name: str) -> None:
            while True:
                run = runs.claim_next(self.store, name)
                if run is None:
                    return
                with lock:
                    taken.append(run.id)

        threads = [threading.Thread(target=worker, args=(f"w{index}",)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(taken), sorted(run.id for run in queued))
        self.assertEqual(len(taken), len(set(taken)))

    def test_order(self) -> None:
        first, second = self.queue(2)
        self.assertEqual(runs.claim_next(self.store, "a").id, first.id)
        self.assertEqual(runs.claim_next(self.store, "a").id, second.id)
        self.assertIsNone(runs.claim_next(self.store, "a"))

    def test_an_expired_lease_is_claimed_again(self) -> None:
        (one,) = self.queue(1)
        claimed = runs.claim_next(self.store, "gone", lease=60)
        self.assertEqual((claimed.state, claimed.owner), (runs.RUNNING, "gone"))
        self.assertIsNone(runs.claim_next(self.store, "other"))
        again = runs.claim_next(self.store, "other", now=claimed.lease_until + 1)
        self.assertEqual((again.id, again.owner), (one.id, "other"))
        self.assertFalse(runs.renew(self.store, one.id, "gone"))
        self.assertTrue(runs.renew(self.store, one.id, "other"))

    def test_release_puts_runs_back(self) -> None:
        self.queue(2)
        runs.claim_next(self.store, "a")
        runs.claim_next(self.store, "a")
        self.assertEqual(runs.release(self.store, "a"), 2)
        self.assertEqual({run.state for run in runs.unfinished(self.store)}, {runs.QUEUED})
        self.assertIsNotNone(runs.claim_next(self.store, "b"))

    def test_cancel_through_the_record(self) -> None:
        queued, running = self.queue(2)
        runs.claim_next(self.store, "a")  # takes queued
        self.assertTrue(runs.request_cancel(self.store, queued.id).cancel_requested)
        self.assertTrue(runs.cancel_requested(self.store, queued.id))
        self.assertEqual(runs.request_cancel(self.store, running.id).state, runs.CANCELLED)

    def test_work_counter_moves(self) -> None:
        before = runs.work_version(self.store)
        self.queue(1)
        self.assertGreater(runs.work_version(self.store)[0], before[0])

    def test_workers_check_in(self) -> None:
        runs.beat(self.store, {"id": "w1", "host": "h"})
        self.assertEqual([worker["id"] for worker in runs.workers(self.store)], ["w1"])
        runs.gone(self.store, "w1")
        self.assertEqual(runs.workers(self.store), [])


if __name__ == "__main__":
    unittest.main()
