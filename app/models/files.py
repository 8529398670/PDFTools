"""Uploaded files and the files actions make from them. The record here
describes one; the bytes are on disk.

A file arrives in pieces of CHUNK_BYTES, each its own request, so no proxy has
to take a body of gigabytes and a failed piece is all that is sent again. The
pieces may come in any order and several at once: the upload is created at its
final size, every piece is written at an offset that can be computed from its
index, and the record keeps a bitmap of which have arrived.

How a file is stored is decided when it is created, by files.encrypt, and kept
on the record, so switching the setting never strands a file:

- plain (the default): the bytes exactly as sent. An action opens the file in
  place and a download is a plain file response, with ranges.
- encrypted: each file has its own random key, sealed with the secret key
  (sealed.SEALED_FIELDS, so a rotation rewrites one field, never the bytes).
  Each piece is sealed on its own, bound to the file's id, its index and the
  number of pieces, so it opens only where it belongs.
"""
from __future__ import annotations

import base64
import os
import shutil
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from app.core import config_secret, encryption
from app.core.config import FILE_CHUNK_BYTES as CHUNK_BYTES
from app.core.config import Config
from app.core.db import BUCKET_FILES, Record, Store, Transaction
from app.models import RestoreGoneError, deleted_long_ago, from_iso, mark_deleted, to_iso, unmark_deleted, utc_now
from app.models import users

UPLOADING = "uploading"
READY = "ready"

# What a file is to this app. An import is something someone dropped in; an
# output is a file an action made, which belongs to a run (app/models/runs.py).
KIND_IMPORT = "import"
KIND_OUTPUT = "output"

# What reading a PDF found (pdf_state). Pending until the inspect step has run.
PDF_PENDING = "pending"
PDF_OK = "ok"
PDF_INVALID = "invalid"

# What sealing adds to a piece: nonce and tag.
CHUNK_OVERHEAD = 24 + 16
NAME_MAX = 255
FOLDER_MAX = 1024
TYPE_MAX = 127
# How old a file with no record must be before it is removed. Finishing a file
# renames it before the record says so, and a restore can leave either one
# without the other.
STRAY_AGE_SECONDS = 24 * 60 * 60
# How much a plain read takes at a time.
READ_BYTES = 1024 * 1024


class BadFileError(Exception):
    def __init__(self) -> None:
        super().__init__("a file needs a name and a size")


class BadFileNameError(ValueError):
    def __init__(self) -> None:
        super().__init__("a file name must be 1-255 bytes")


class FileTooLargeError(Exception):
    """The message is a code, worded in language.yaml."""

    def __init__(self) -> None:
        super().__init__("file_too_large")


class FileQuotaError(Exception):
    """The message is a code, worded in language.yaml."""

    def __init__(self) -> None:
        super().__init__("file_quota")


class ChunkSizeError(Exception):
    def __init__(self) -> None:
        super().__init__("that piece is the wrong size")


class FileMissingError(Exception):
    """A record whose bytes are not there."""


@dataclass
class File:
    id: str
    user_id: int
    name: str
    # What the uploader said it is. It is shown, and never served: a download
    # is always application/octet-stream.
    type: str
    size: int
    chunks: int
    received: int
    state: str
    # This file's own key, sealed with the secret key; "" for a plain file. It
    # is in SEALED_FIELDS, so it follows a rotation.
    key: str
    created_at: datetime
    # When the last piece arrived.
    updated_at: datetime
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    encrypted: bool = True
    # Which pieces have arrived, one bit each, base64. Empty once ready.
    have: str = ""
    # The folder it was dropped in with, relative to what was dropped. Shown
    # only: paths on disk use the id.
    folder: str = ""
    kind: str = KIND_IMPORT
    # For an output: the run that made it and the file it was made from.
    run_id: str = ""
    source_id: str = ""
    # What reading it as a PDF found: pdf_state, and the details.
    pdf_state: str = PDF_PENDING
    pdf_error: str = ""
    pdf: dict[str, Any] = field(default_factory=dict)
    # When retention removes it; None keeps it. See app/models/retention.py.
    expires_at: datetime | None = None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    def chunk_length(self, index: int) -> int:
        """How many bytes piece index holds."""
        return self.size - index * CHUNK_BYTES if index == self.chunks - 1 else CHUNK_BYTES

    @property
    def stored_size(self) -> int:
        """How long the file is on disk."""
        return self.size + self.chunks * CHUNK_OVERHEAD if self.encrypted else self.size

    def stored_offset(self, index: int) -> int:
        """Where piece index starts on disk."""
        return index * (CHUNK_BYTES + CHUNK_OVERHEAD) if self.encrypted else index * CHUNK_BYTES

    def bound(self, index: int) -> bytes:
        """What a piece is sealed to. Without the count, a file cut off after
        a whole piece would still open."""
        return f"{self.id}|{index}|{self.chunks}".encode()

    def missing(self) -> list[int]:
        """The pieces still to send."""
        bits = _bits(self.have, self.chunks)
        return [index for index in range(self.chunks) if not bits[index >> 3] & (1 << (index & 7))]

    def to_record(self) -> Record:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "type": self.type,
            "size": self.size,
            "chunks": self.chunks,
            "received": self.received,
            "state": self.state,
            "key": self.key,
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
            "deleted_at": to_iso(self.deleted_at),
            "deleted_by": self.deleted_by,
            "encrypted": self.encrypted,
            "have": self.have,
            "folder": self.folder,
            "kind": self.kind,
            "run_id": self.run_id,
            "source_id": self.source_id,
            "pdf_state": self.pdf_state,
            "pdf_error": self.pdf_error,
            "pdf": self.pdf,
            "expires_at": to_iso(self.expires_at),
        }

    @classmethod
    def from_record(cls, record: Record) -> "File":
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            name=record["name"],
            type=record["type"],
            size=record["size"],
            chunks=record["chunks"],
            received=record["received"],
            state=record["state"],
            key=record["key"],
            created_at=from_iso(record["created_at"]),
            updated_at=from_iso(record["updated_at"]),
            deleted_at=from_iso(record.get("deleted_at")),
            deleted_by=record.get("deleted_by"),
            encrypted=record.get("encrypted", True),
            have=record.get("have", ""),
            folder=record.get("folder", ""),
            kind=record.get("kind", KIND_IMPORT),
            run_id=record.get("run_id", ""),
            source_id=record.get("source_id", ""),
            pdf_state=record.get("pdf_state", PDF_PENDING),
            pdf_error=record.get("pdf_error", ""),
            pdf=record.get("pdf") or {},
            expires_at=from_iso(record.get("expires_at")),
        )


def _bits(have: str, chunks: int) -> bytearray:
    raw = bytearray(base64.b64decode(have)) if have else bytearray()
    size = (chunks + 7) // 8
    return raw + bytearray(size - len(raw)) if len(raw) < size else raw


def chunk_count(size: int) -> int:
    return (size + CHUNK_BYTES - 1) // CHUNK_BYTES


def upload_path(cfg: Config, file_id: str) -> Path:
    return cfg.files.uploads_dir / file_id


def finished_path(cfg: Config, file_id: str) -> Path:
    return cfg.files.dir / file_id


def work_dir(cfg: Config) -> Path:
    """Scratch space for actions, created 0700."""
    cfg.files.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return cfg.files.work_dir


def clean_name(name: str) -> str:
    """The last part of whatever path a client sent, without control
    characters. It is only ever shown and offered as a download name: paths on
    disk use the id."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(character for character in name if unicodedata.category(character) != "Cc" and character != "�").strip()


def clean_folder(folder: str) -> str:
    """A relative folder path as dropped, each part cleaned like a name, with
    nothing that climbs out ("..") or starts at the root."""
    parts = [clean_name(part) for part in folder.replace("\\", "/").split("/")]
    kept = "/".join(part for part in parts if part and part not in (".", ".."))
    return kept[:FOLDER_MAX]


def _file_key(cfg: Config, file: File) -> bytes | str:
    return encryption.xchacha_decrypt_string(encryption.subkey(cfg.secret_key, encryption.PURPOSE_FILES), file.key)


def _new_key(cfg: Config) -> str:
    return encryption.xchacha_encrypt_string(encryption.subkey(cfg.secret_key, encryption.PURPOSE_FILES), config_secret.generate_secret())


def _used_bytes(transaction: Transaction, user_id: int) -> int:
    """What an account holds against its quota. Uploads still arriving count
    at their full size, or several at once could pass the check together."""
    records = (record for _, record in transaction.all(BUCKET_FILES))
    return sum(record["size"] for record in records if record["user_id"] == user_id and record.get("deleted_at") is None)


def storage_used(store: Store, user_id: int | None = None) -> int:
    """_used_bytes outside a transaction, for showing it: one account, or every
    account for None."""
    records = (record for _, record in store.all(BUCKET_FILES))
    return sum(
        record["size"]
        for record in records
        if (user_id is None or record["user_id"] == user_id) and record.get("deleted_at") is None
    )


def create_file(
    store: Store, cfg: Config, user_id: int, name: str, declared_type: str, size: int,
    folder: str = "", expires_at: datetime | None = None,
) -> File:
    """Start an upload. The quota is checked in the same transaction that adds
    the record, so two uploads cannot both take the last of it. The upload is
    made at its full size now, so pieces can land in any order."""
    name = clean_name(name)
    if not name or len(name.encode()) > NAME_MAX or size < 0 or len(declared_type.encode()) > TYPE_MAX:
        raise BadFileError()
    if size > cfg.files.max_file_bytes:
        raise FileTooLargeError()
    now = utc_now()
    encrypted = cfg.files.encrypt
    file = File(
        id=encryption.url_token(12),
        user_id=user_id,
        name=name,
        type=declared_type,
        size=size,
        chunks=chunk_count(size),
        received=0,
        state=UPLOADING,
        key=_new_key(cfg) if encrypted else "",
        created_at=now,
        updated_at=now,
        encrypted=encrypted,
        folder=clean_folder(folder),
        expires_at=expires_at,
    )
    with store.transaction() as transaction:
        if _used_bytes(transaction, user_id) + size > cfg.files.quota_bytes_per_user:
            raise FileQuotaError()
        transaction.put(BUCKET_FILES, file.id, file.to_record())
    cfg.files.uploads_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(upload_path(cfg, file.id), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        # Sparse: no bytes are written until the pieces come.
        os.ftruncate(descriptor, file.stored_size)
    finally:
        os.close(descriptor)
    return file


def get_file(store: Store, file_id: str) -> File | None:
    """A file, deleted or not."""
    record = store.get(BUCKET_FILES, file_id)
    return None if record is None else File.from_record(record)


def all_files(store: Store) -> list[File]:
    return [File.from_record(record) for _, record in store.all(BUCKET_FILES)]


def list_files(store: Store, user_id: int | None = None, kind: str | None = KIND_IMPORT) -> list[File]:
    """The finished files, newest first: one account's, or everyone's; of
    one kind, or every kind for None."""
    files = [
        file for file in all_files(store)
        if file.state == READY and not file.deleted and user_id in (None, file.user_id) and kind in (None, file.kind)
    ]
    files.sort(key=lambda file: file.created_at, reverse=True)
    return files


def write_chunk(store: Store, cfg: Config, file: File, index: int, plain: bytes) -> int:
    """Put one piece at its place in the upload, sealing it first for an
    encrypted file, and answer how many pieces have now arrived. Writing a
    piece that is already there writes the same bytes again, so a retry after
    a lost reply is harmless. The caller holds the UploadLocks entry for this
    piece."""
    if len(plain) != file.chunk_length(index):
        raise ChunkSizeError()
    data = encryption.xchacha_encrypt_bound(_file_key(cfg, file), plain, file.bound(index)) if file.encrypted else plain
    try:
        descriptor = os.open(upload_path(cfg, file.id), os.O_WRONLY)
    except FileNotFoundError:
        raise FileMissingError() from None
    try:
        if os.fstat(descriptor).st_size != file.stored_size:
            raise FileMissingError()
        view = memoryview(data)
        offset = file.stored_offset(index)
        while view:
            written = os.pwrite(descriptor, view, offset)
            view = view[written:]
            offset += written
        # Before the record, which is durable as soon as it is written, says
        # the piece is here.
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    def mutate(record: Record) -> None:
        bits = _bits(record.get("have", ""), record["chunks"])
        bits[index >> 3] |= 1 << (index & 7)
        record["have"] = base64.b64encode(bytes(bits)).decode()
        record["received"] = sum(bin(byte).count("1") for byte in bits)
        record["updated_at"] = to_iso(utc_now())

    record = store.update_value(BUCKET_FILES, file.id, mutate)
    if record is None:
        raise FileMissingError()
    return int(record["received"])


def finish_file(store: Store, cfg: Config, file: File) -> File:
    """Move a complete upload into place and mark it ready. Asked again after a
    crash between the two, it finds the file already moved and goes on."""
    cfg.files.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = upload_path(cfg, file.id)
    target = finished_path(cfg, file.id)
    try:
        if source.stat().st_size != file.stored_size:
            raise FileMissingError()
        source.rename(target)
    except FileNotFoundError:
        if not target.exists() or target.stat().st_size != file.stored_size:
            raise FileMissingError() from None

    def mutate(record: Record) -> None:
        record["state"] = READY
        record["have"] = ""
        record["updated_at"] = to_iso(utc_now())

    record = store.update_value(BUCKET_FILES, file.id, mutate)
    if record is None:
        raise FileMissingError()
    return File.from_record(record)


def add_output(
    store: Store, cfg: Config, user_id: int, name: str, source: Path, run_id: str, source_id: str,
    pdf: dict[str, Any], expires_at: datetime | None,
) -> File:
    """Keep a file an action wrote at source (in the work directory) as an
    output of run_id. A plain one is renamed into place, which costs nothing;
    an encrypted one is sealed piece by piece into place and source removed.
    Counts against the quota like an upload."""
    name = clean_name(name)[:NAME_MAX] or "output.pdf"
    size = source.stat().st_size
    now = utc_now()
    encrypted = cfg.files.encrypt
    file = File(
        id=encryption.url_token(12),
        user_id=user_id,
        name=name,
        type="application/pdf",
        size=size,
        chunks=chunk_count(size),
        received=chunk_count(size),
        state=UPLOADING,
        key=_new_key(cfg) if encrypted else "",
        created_at=now,
        updated_at=now,
        encrypted=encrypted,
        kind=KIND_OUTPUT,
        run_id=run_id,
        source_id=source_id,
        pdf_state=PDF_OK,
        pdf=pdf,
        expires_at=expires_at,
    )
    with store.transaction() as transaction:
        if _used_bytes(transaction, user_id) + size > cfg.files.quota_bytes_per_user:
            raise FileQuotaError()
        transaction.put(BUCKET_FILES, file.id, file.to_record())
    cfg.files.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = finished_path(cfg, file.id)
    try:
        if encrypted:
            seal_into(cfg, file, source, target)
            source.unlink(missing_ok=True)
        else:
            os.chmod(source, 0o600)
            source.rename(target)
    except BaseException:
        store.delete_where(BUCKET_FILES, lambda key, record: key == file.id)
        target.unlink(missing_ok=True)
        raise

    def mutate(record: Record) -> None:
        record["state"] = READY

    store.update_value(BUCKET_FILES, file.id, mutate)
    file.state = READY
    return file


def seal_into(cfg: Config, file: File, source: Path, target: Path) -> None:
    """Write source's bytes to target as file's sealed pieces."""
    key = _file_key(cfg, file)
    with source.open("rb") as reader, target.open("wb") as writer:
        os.chmod(target, 0o600)
        for index in range(file.chunks):
            plain = reader.read(file.chunk_length(index))
            writer.write(encryption.xchacha_encrypt_bound(key, plain, file.bound(index)))
        writer.flush()
        os.fsync(writer.fileno())


def plain_copy(cfg: Config, file: File, target: Path) -> None:
    """The file's bytes, opened, written to target (0600): how an action gets
    a readable copy of an encrypted file."""
    reader = FileReader(cfg, file)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as writer:
        for piece in reader:
            writer.write(piece)


def readable_path(cfg: Config, file: File) -> Path:
    """Where the file's bytes can be read as they are, for a plain file."""
    return finished_path(cfg, file.id)


def set_pdf_info(store: Store, file_id: str, state: str, info: dict[str, Any], error: str = "") -> None:
    def mutate(record: Record) -> None:
        record["pdf_state"] = state
        record["pdf"] = info
        record["pdf_error"] = error

    store.update_value(BUCKET_FILES, file_id, mutate)


def set_expiry(store: Store, file_id: str, expires_at: datetime | None) -> None:
    def mutate(record: Record) -> None:
        record["expires_at"] = to_iso(expires_at)

    store.update_value(BUCKET_FILES, file_id, mutate)


def rename_file(store: Store, file_id: str, name: str, expect: str | None = None) -> str | None:
    """Change the name a file is shown and downloaded under, and answer it as
    cleaned. Only the record changes: paths on disk use the id, and a piece is
    sealed to the id too. None when there is no such file, it is deleted, or it
    is still uploading.

    expect, when given, is the name the caller believes is stored, as in
    users.rename_user: RenameConflictError if it is not."""
    clean = clean_name(name)
    if not clean or len(clean.encode()) > NAME_MAX:
        raise BadFileNameError()
    found = False

    def mutate(record: Record) -> None:
        nonlocal found
        if record.get("deleted_at") is not None or record["state"] != READY:
            return
        found = True
        if expect is not None and record["name"] != expect:
            raise users.RenameConflictError(record["name"])
        record["name"] = clean

    if store.update_value(BUCKET_FILES, file_id, mutate) is None or not found:
        return None
    return clean


def delete_file(store: Store, file_id: str, actor_id: int) -> bool:
    """Mark it, for the usual undo window. The bytes stay until the sweep.
    False when there is none or it is already deleted."""
    found = False

    def mutate(record: Record) -> None:
        nonlocal found
        found = record.get("deleted_at") is None
        mark_deleted(record, actor_id)

    return store.update_value(BUCKET_FILES, file_id, mutate) is not None and found


def restore_file(store: Store, cfg: Config, file_id: str, actor_id: int, actor_is_admin: bool) -> File:
    """Undo delete_file. Raises a RestoreError when it may not happen. It
    counts against the quota again, so that is checked here the same way as for
    a new upload."""
    with store.transaction() as transaction:
        record = transaction.get(BUCKET_FILES, file_id)
        if record is None:
            raise RestoreGoneError()
        unmark_deleted(record, actor_id, actor_is_admin, users.owner_id_tx(transaction))
        if _used_bytes(transaction, record["user_id"]) + record["size"] > cfg.files.quota_bytes_per_user:
            raise FileQuotaError()
        transaction.put(BUCKET_FILES, file_id, record)
    return File.from_record(record)


class FileReader:
    """A finished file's plain bytes, a piece at a time, so memory stays flat
    whatever the size. A sealed piece that does not open raises, and nothing
    from it is handed out."""

    def __init__(self, cfg: Config, file: File) -> None:
        self.file = file
        self.key = _file_key(cfg, file) if file.encrypted else b""
        try:
            self.source = finished_path(cfg, file.id).open("rb")
        except FileNotFoundError:
            raise FileMissingError() from None
        if os.fstat(self.source.fileno()).st_size != file.stored_size:
            self.source.close()
            raise FileMissingError()

    def __iter__(self) -> Iterator[bytes]:
        """Closes the file when it ends, however it ends."""
        try:
            if not self.file.encrypted:
                while piece := self.source.read(READ_BYTES):
                    yield piece
                return
            for index in range(self.file.chunks):
                sealed = self.source.read(self.file.chunk_length(index) + CHUNK_OVERHEAD)
                yield encryption.xchacha_decrypt_bound(self.key, sealed, self.file.bound(index))
        finally:
            self.source.close()

    def close(self) -> None:
        self.source.close()


def sweep_files(store: Store, cfg: Config) -> tuple[int, int]:
    """The cleanup job's work. A deleted file past its undo window, an upload
    nobody has touched for files.abandoned_upload_hours and a file whose account
    has gone lose their record and then their bytes, so a crash between the two
    leaves a stray rather than a record pointing at nothing. Strays are the last
    step, and old leftovers in the work directory with them. Answers how many of
    each went."""
    accounts = {user.id for user in users.list_users(store)}
    cutoff = utc_now() - timedelta(hours=cfg.files.abandoned_upload_hours)
    doomed: list[str] = []

    def gone(key: object, record: Record) -> bool:
        abandoned = record["state"] == UPLOADING and from_iso(record["updated_at"]) < cutoff
        if deleted_long_ago(record) or abandoned or record["user_id"] not in accounts:
            doomed.append(str(key))
            return True
        return False

    removed = store.delete_where(BUCKET_FILES, gone)
    for file_id in doomed:
        upload_path(cfg, file_id).unlink(missing_ok=True)
        finished_path(cfg, file_id).unlink(missing_ok=True)
    return removed, _remove_strays(store, cfg)


def _remove_strays(store: Store, cfg: Config) -> int:
    """Reads the record ids after the directories, so a file arriving in
    between has its record seen. Its age would keep it safe anyway. Anything in
    the work directory that old is a leftover from an action cut off."""
    old = time.time() - STRAY_AGE_SECONDS
    count = 0
    if cfg.files.work_dir.is_dir():
        for path in cfg.files.work_dir.iterdir():
            if path.stat().st_mtime < old:
                shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
                count += 1
    candidates: list[Path] = []
    for directory in (cfg.files.uploads_dir, cfg.files.dir):
        if directory.is_dir():
            candidates += [path for path in directory.iterdir() if path.is_file() and not path.is_symlink() and path.stat().st_mtime < old]
    if not candidates:
        return count
    known = {str(key) for key, _ in store.all(BUCKET_FILES)}
    strays = [path for path in candidates if path.name not in known]
    for path in strays:
        path.unlink(missing_ok=True)
    return count + len(strays)


class UploadLocks:
    """Keeps two requests from writing the same piece, or finishing an upload
    while a piece is being written. It lives in the process, like the rate
    limiter, because this template is one process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: set[tuple[str, int]] = set()

    def hold(self, file_id: str, index: int) -> bool:
        """Claim one piece; False means another request has it. index -1 is
        the whole upload, which no piece may be held alongside."""
        with self._lock:
            taken = {(held_id, held_index) for held_id, held_index in self._held if held_id == file_id}
            if (file_id, index) in taken or (file_id, -1) in taken or (index == -1 and taken):
                return False
            self._held.add((file_id, index))
            return True

    def release(self, file_id: str, index: int) -> None:
        with self._lock:
            self._held.discard((file_id, index))
