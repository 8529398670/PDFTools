"""Shared bytes (app/models/files.py): the same content is stored once whoever
holds it, plain or encrypted; a client that already has a file the server
holds can claim it by answering for random ranges, and not without them; an
output joins the same way; and a blob goes only when no record names it."""
from __future__ import annotations

import hashlib
import os
import unittest
from dataclasses import replace

from app.core.db import BUCKET_BLOBS, BUCKET_FILES
from app.models import files

try:
    from app.tests.route_support import RoutesTestCase
except unittest.SkipTest:  # without httpx2 only the fingerprint checks run
    RoutesTestCase = None  # type: ignore[assignment,misc]

# Over one fingerprint piece and one upload piece, so both seams are crossed.
DATA = os.urandom(files.FINGERPRINT_PIECE + files.CHUNK_BYTES // 2 + 123)


def reference_fingerprint(data: bytes) -> str:
    """The fingerprint as the browser takes it: each piece hashed, then those."""
    piece = files.FINGERPRINT_PIECE
    digests = b"".join(hashlib.sha256(data[start:start + piece]).digest() for start in range(0, len(data), piece))
    return hashlib.sha256(digests).hexdigest()


class FingerprintTest(unittest.TestCase):
    def test_parts_of_any_size_give_the_same_fingerprint(self) -> None:
        whole = files.fingerprint_of(iter([DATA]))
        sizes = [1, 4096, files.FINGERPRINT_PIECE - 1, 10**6]
        parts, start = [], 0
        for size in sizes * 10:
            if start >= len(DATA):
                break
            parts.append(DATA[start:start + size])
            start += size
        parts.append(DATA[start:])
        self.assertEqual(files.fingerprint_of(iter(parts)), whole)
        self.assertEqual(whole, reference_fingerprint(DATA))

    def test_empty(self) -> None:
        self.assertEqual(files.fingerprint_of(iter([])), hashlib.sha256(b"").hexdigest())


@unittest.skipIf(RoutesTestCase is None, "needs httpx2")
class SharedFilesTest(RoutesTestCase or unittest.TestCase):  # type: ignore[misc]
    config_changes = {}

    def setUp(self) -> None:
        super().setUp()
        cfg = self.holder.get()
        self.set_config(files=replace(cfg.files, max_file_bytes=10**9, quota_bytes_per_user=10**9))

    @property
    def config(self):  # type: ignore[no-untyped-def]
        return self.holder.get()

    def encrypt(self, on: bool) -> None:
        self.set_config(files=replace(self.config.files, encrypt=on))

    def upload(self, user_id: int, data: bytes = DATA, name: str = "book.pdf") -> files.File:
        made = files.create_file(self.store, self.config, user_id, name, "application/pdf", len(data))
        for index in range(made.chunks):
            files.write_chunk(self.store, self.config, made, index, data[index * files.CHUNK_BYTES:(index + 1) * files.CHUNK_BYTES])
        files.finish_file(self.store, self.config, files.get_file(self.store, made.id))
        files.adopt_blob(self.store, self.config, made.id)
        return files.get_file(self.store, made.id)

    def read(self, file: files.File) -> bytes:
        return b"".join(files.FileReader(self.config, file))

    def blob_files(self) -> list[str]:
        directory = files.blobs_dir(self.config)
        return sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []

    def test_two_accounts_same_content_one_copy(self) -> None:
        first = self.upload(self.owner.id)
        second = self.upload(self.user.id, name="renamed.pdf")
        self.assertEqual(first.blob, reference_fingerprint(DATA))
        self.assertEqual(first.blob, second.blob)
        self.assertEqual(self.blob_files(), [first.blob])
        self.assertFalse(files.finished_path(self.config, first.id).exists())
        self.assertFalse(files.finished_path(self.config, second.id).exists())
        self.assertEqual(self.read(first), DATA)
        self.assertEqual(self.read(second), DATA)
        # Quotas count each account's file in full; the disk holds it once.
        self.assertEqual(files.storage_used(self.store, self.user.id), len(DATA))
        self.assertEqual(files.storage_used(self.store), 2 * len(DATA))
        self.assertEqual(files.disk_used(self.store), len(DATA))

    def test_encrypted_blob_is_shared_with_a_plain_upload(self) -> None:
        self.encrypt(True)
        first = self.upload(self.owner.id)
        self.encrypt(False)
        second = self.upload(self.user.id)
        self.assertTrue(second.encrypted)
        self.assertEqual(first.blob, second.blob)
        self.assertEqual(self.read(second), DATA)
        # Not stored as plain text.
        self.assertNotIn(DATA[:4096], files.blob_path(self.config, first.blob).read_bytes()[:20000])

    def test_different_content_two_blobs(self) -> None:
        one = self.upload(self.owner.id)
        two = self.upload(self.owner.id, data=DATA[:-1] + b"x")
        self.assertNotEqual(one.blob, two.blob)
        self.assertEqual(len(self.blob_files()), 2)

    def claim(self, cookie: str, data: bytes = DATA, fingerprint: str | None = None) -> tuple[int, dict]:
        body = {"name": "mine.pdf", "size": len(data), "type": "application/pdf", "fingerprint": fingerprint or reference_fingerprint(data)}
        return self.call("POST", "/api/claims", cookie=cookie, body={**body, "csrf_token": self.csrf(cookie)})

    def answer(self, cookie: str, claim_id: str, hashes: list[str]) -> tuple[int, dict]:
        return self.call("POST", f"/api/claims/{claim_id}", cookie=cookie, body={"hashes": hashes, "csrf_token": self.csrf(cookie)})

    def test_claim_with_the_bytes_adds_the_file_without_sending_it(self) -> None:
        held = self.upload(self.owner.id)
        status, asked = self.claim(self.user_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(asked["found"])
        hashes = [hashlib.sha256(DATA[offset:offset + length]).hexdigest() for offset, length in asked["ranges"]]
        status, made = self.answer(self.user_cookie, asked["claim_id"], hashes)
        self.assertEqual(status, 201, made)
        mine = files.get_file(self.store, made["id"])
        self.assertEqual((mine.user_id, mine.blob, mine.name), (self.user.id, held.blob, "mine.pdf"))
        self.assertEqual(self.read(mine), DATA)
        self.assertEqual(self.blob_files(), [held.blob])
        # Answered once: the same answer again is refused.
        self.assertEqual(self.answer(self.user_cookie, asked["claim_id"], hashes)[0], 403)

    def test_claim_against_an_encrypted_blob(self) -> None:
        self.encrypt(True)
        self.upload(self.owner.id)
        _, asked = self.claim(self.user_cookie)
        hashes = [hashlib.sha256(DATA[offset:offset + length]).hexdigest() for offset, length in asked["ranges"]]
        status, made = self.answer(self.user_cookie, asked["claim_id"], hashes)
        self.assertEqual(status, 201, made)
        self.assertEqual(self.read(files.get_file(self.store, made["id"])), DATA)

    def test_knowing_the_fingerprint_is_not_enough(self) -> None:
        self.upload(self.owner.id)
        _, asked = self.claim(self.user_cookie)
        status, _ = self.answer(self.user_cookie, asked["claim_id"], ["0" * 64] * len(asked["ranges"]))
        self.assertEqual(status, 403)
        before = len(files.list_files(self.store, self.user.id))
        self.assertEqual(before, 0)

    def test_someone_elses_claim_is_refused(self) -> None:
        self.upload(self.owner.id)
        _, asked = self.claim(self.user_cookie)
        hashes = [hashlib.sha256(DATA[offset:offset + length]).hexdigest() for offset, length in asked["ranges"]]
        self.assertEqual(self.answer(self.admin_cookie, asked["claim_id"], hashes)[0], 403)

    def test_unknown_content_must_be_uploaded(self) -> None:
        status, asked = self.claim(self.user_cookie, fingerprint="a" * 64)
        self.assertEqual(status, 200)
        self.assertFalse(asked["found"])

    def test_claim_checks_the_quota_first(self) -> None:
        self.upload(self.owner.id)
        self.set_config(files=replace(self.config.files, quota_bytes_per_user=len(DATA) - 1))
        self.assertEqual(self.claim(self.user_cookie)[0], 409)

    def test_outputs_share_too(self) -> None:
        held = self.upload(self.owner.id)
        for user_id in (self.owner.id, self.user.id):
            source = files.work_dir(self.config) / f"out-{user_id}.pdf"
            source.write_bytes(DATA)
            made = files.add_output(self.store, self.config, user_id, "part.pdf", source, "run", held.id, {}, None)
            self.assertEqual(made.blob, held.blob)
            self.assertFalse(source.exists())
            self.assertEqual(self.read(files.get_file(self.store, made.id)), DATA)
        self.assertEqual(self.blob_files(), [held.blob])

    def test_blob_stays_until_the_last_record_goes(self) -> None:
        first = self.upload(self.owner.id)
        second = self.upload(self.user.id)
        self.store.delete_where(BUCKET_FILES, lambda key, record: key == first.id)
        files.sweep_files(self.store, self.config)
        self.assertEqual(self.blob_files(), [second.blob])
        self.assertEqual(self.read(second), DATA)
        self.store.delete_where(BUCKET_FILES, lambda key, record: key == second.id)
        files.sweep_files(self.store, self.config)
        self.assertEqual(self.blob_files(), [])
        self.assertEqual(list(self.store.all(BUCKET_BLOBS)), [])

    def test_missing_blob_bytes_are_made_again(self) -> None:
        first = self.upload(self.owner.id)
        files.blob_path(self.config, first.blob).unlink()
        second = self.upload(self.user.id)
        self.assertEqual(second.blob, first.blob)
        self.assertEqual(self.read(first), DATA)


if __name__ == "__main__":
    unittest.main()
