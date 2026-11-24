"""Restarting a run (POST /api/runs/{id}/restart): a cancelled or failed run
is queued again on the same file with the same options; anything else is
refused, and a run whose PDF has gone cannot start again. A cancel spent on a
queued run must not stop it once it is restarted."""
from __future__ import annotations

import unittest
from dataclasses import replace

from app.models import files, runs, utc_now

try:
    from app.tests.route_support import RoutesTestCase
except unittest.SkipTest:
    RoutesTestCase = None  # type: ignore[assignment,misc]

DATA = b"%PDF-1.4\n" + b"x" * 2000


@unittest.skipIf(RoutesTestCase is None, "needs httpx2")
class RestartTest(RoutesTestCase or unittest.TestCase):  # type: ignore[misc]
    def setUp(self) -> None:
        super().setUp()
        cfg = self.holder.get()
        self.set_config(files=replace(cfg.files, max_file_bytes=10**9, quota_bytes_per_user=10**9))
        self.submitted: list[str] = []
        runner = self.app.state.runner
        runner.submit = self.submitted.append  # type: ignore[method-assign]

    def upload(self, user_id: int) -> files.File:
        cfg = self.holder.get()
        made = files.create_file(self.store, cfg, user_id, "book.pdf", "application/pdf", len(DATA))
        files.write_chunk(self.store, cfg, made, 0, DATA)
        files.finish_file(self.store, cfg, files.get_file(self.store, made.id))
        return files.get_file(self.store, made.id)

    def run_in(self, state: str, user_id: int | None = None) -> runs.Run:
        user_id = self.user.id if user_id is None else user_id
        source = self.upload(user_id)
        made = runs.create_run(self.store, user_id, "split_bookmarks", source, {"level": 1})
        return runs.update(self.store, made.id, state=state, message="internal" if state == runs.FAILED else "", progress=0.4, finished_at=utc_now())

    def restart(self, run_id: str, cookie: str | None = None) -> tuple[int, dict]:
        cookie = cookie or self.user_cookie
        return self.call("POST", f"/api/runs/{run_id}/restart", cookie=cookie,
                         body={"csrf_token": self.csrf(cookie)})

    def test_cancelled_run_is_queued_again(self) -> None:
        one = self.run_in(runs.CANCELLED)
        status, body = self.restart(one.id)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["state"], "queued")
        again = runs.get_run(self.store, one.id)
        self.assertEqual((again.state, again.progress, again.finished_at, again.options), (runs.QUEUED, 0.0, None, {"level": 1}))
        self.assertEqual(self.submitted, [one.id])

    def test_failed_run_can_restart(self) -> None:
        one = self.run_in(runs.FAILED)
        status, _ = self.restart(one.id)
        self.assertEqual(status, 200)
        self.assertEqual(runs.get_run(self.store, one.id).message, "")

    def test_done_or_queued_run_is_refused(self) -> None:
        for state in (runs.DONE, runs.QUEUED, runs.RUNNING):
            status, _ = self.restart(self.run_in(state).id)
            self.assertEqual(status, 409, state)
        self.assertEqual(self.submitted, [])

    def test_source_gone(self) -> None:
        one = self.run_in(runs.CANCELLED)
        files.delete_file(self.store, one.file_id, self.user.id)
        status, _ = self.restart(one.id)
        self.assertEqual(status, 409)
        self.assertEqual(runs.get_run(self.store, one.id).state, runs.CANCELLED)

    def test_someone_elses_run_is_not_there(self) -> None:
        one = self.run_in(runs.CANCELLED, user_id=self.admin.id)
        status, _ = self.restart(one.id)
        self.assertEqual(status, 404)

    def test_cancel_while_queued_is_spent(self) -> None:
        runner = self.app.state.runner
        source = self.upload(self.user.id)
        one = runs.create_run(self.store, self.user.id, "split_bookmarks", source, {"level": 1})
        runner.cancel(one.id)
        self.assertEqual(runs.get_run(self.store, one.id).state, runs.CANCELLED)
        runner._run(one.id)  # the worker finds it finished
        self.assertNotIn(one.id, runner._cancelled)


if __name__ == "__main__":
    unittest.main()
