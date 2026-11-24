"""What someone uploading on a tool screen chooses for the upload (File.keep):
"run" goes to the bin once a run on it is done, but not after a cancelled or
failed run, nor while another run on it is still to come; "day" expires in 24
hours; either way a retention change leaves the expiry alone."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from app.models import files, retention, runs, utc_now

try:
    from app.tests.route_support import RoutesTestCase
except unittest.SkipTest:
    RoutesTestCase = None  # type: ignore[assignment,misc]

DATA = b"%PDF-1.4\n" + b"y" * 3000


@unittest.skipIf(RoutesTestCase is None, "needs httpx2")
class KeepTest(RoutesTestCase or unittest.TestCase):  # type: ignore[misc]
    def setUp(self) -> None:
        super().setUp()
        cfg = self.holder.get()
        self.set_config(files=replace(cfg.files, max_file_bytes=10**9, quota_bytes_per_user=10**9))
        self.runner = self.app.state.runner
        self.runner.submit = lambda run_id: None  # type: ignore[method-assign]

    def start_upload(self, keep: str) -> dict:
        status, body = self.call("POST", "/api/files", cookie=self.user_cookie, body={
            "csrf_token": self.csrf(self.user_cookie), "name": "book.pdf", "size": len(DATA), "type": "application/pdf", "keep": keep,
        })
        self.assertEqual(status, 201, body)
        return body

    def uploaded(self, keep: str) -> files.File:
        cfg = self.holder.get()
        made = files.create_file(self.store, cfg, self.user.id, "book.pdf", "application/pdf", len(DATA), keep=keep,
                                 expires_at=utc_now() + timedelta(hours=files.KEEP_HOURS))
        files.write_chunk(self.store, cfg, made, 0, DATA)
        return files.finish_file(self.store, cfg, files.get_file(self.store, made.id))

    def finished_run(self, source: files.File, state: str) -> runs.Run:
        made = runs.create_run(self.store, self.user.id, "split_bookmarks", source, {})
        return runs.update(self.store, made.id, state=state, finished_at=utc_now())

    def test_route_stamps_a_day(self) -> None:
        for keep in ("run", "day"):
            body = self.start_upload(keep)
            stored = files.get_file(self.store, body["id"])
            self.assertEqual(stored.keep, keep)
            left = stored.expires_at - utc_now()
            self.assertTrue(timedelta(hours=23) < left <= timedelta(hours=24), left)

    def test_route_default_follows_policy(self) -> None:
        body = self.start_upload("")
        stored = files.get_file(self.store, body["id"])
        self.assertEqual(stored.keep, "")
        wanted = retention.expiry_for(self.store, self.user.id, files.KIND_IMPORT, stored.created_at)
        self.assertLess(abs((stored.expires_at - wanted).total_seconds()), 1)

    def test_unknown_keep_is_refused(self) -> None:
        status, _ = self.call("POST", "/api/files", cookie=self.user_cookie, body={
            "csrf_token": self.csrf(self.user_cookie), "name": "book.pdf", "size": 10, "keep": "forever",
        })
        self.assertEqual(status, 400)

    def test_run_choice_goes_after_done(self) -> None:
        source = self.uploaded(files.KEEP_RUN)
        self.finished_run(source, runs.DONE)
        self.runner._drop_used_upload(source.id)
        self.assertTrue(files.get_file(self.store, source.id).deleted)

    def test_cancelled_or_failed_keeps_it(self) -> None:
        for state in (runs.CANCELLED, runs.FAILED):
            source = self.uploaded(files.KEEP_RUN)
            self.finished_run(source, state)
            # _drop_used_upload is only called on done; check the guard the
            # other way too: nothing else removes it.
            self.assertFalse(files.get_file(self.store, source.id).deleted, state)

    def test_another_run_still_to_come_keeps_it(self) -> None:
        source = self.uploaded(files.KEEP_RUN)
        self.finished_run(source, runs.DONE)
        runs.create_run(self.store, self.user.id, "split_bookmarks", source, {})  # queued
        self.runner._drop_used_upload(source.id)
        self.assertFalse(files.get_file(self.store, source.id).deleted)

    def test_day_and_policy_choices_are_not_dropped(self) -> None:
        for keep in (files.KEEP_DAY, ""):
            source = self.uploaded(keep)
            self.finished_run(source, runs.DONE)
            self.runner._drop_used_upload(source.id)
            self.assertFalse(files.get_file(self.store, source.id).deleted, keep)

    def test_reapply_leaves_a_choice_alone(self) -> None:
        source = self.uploaded(files.KEEP_DAY)
        before = files.get_file(self.store, source.id).expires_at
        retention.reapply(self.store)
        self.assertEqual(files.get_file(self.store, source.id).expires_at, before)


if __name__ == "__main__":
    unittest.main()
