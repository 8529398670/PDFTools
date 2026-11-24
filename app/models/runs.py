"""One action run on one file: which action, with which options, how far it
has got, and the files it made (files with kind "output" and this run's id).

A run is queued when someone starts it, and the runner (app/core/runner.py)
takes it from there. The record is the truth a restart starts from: a run left
queued or running is started again from the beginning, after what it had made
so far is removed, so an action never has to be resumable part way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core import encryption
from app.core.db import BUCKET_FILES, BUCKET_RUNS, Record, Store
from app.models import RestoreGoneError, deleted_long_ago, from_iso, mark_deleted, to_iso, unmark_deleted, utc_now
from app.models import files, users

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
FINISHED = (DONE, FAILED, CANCELLED)


@dataclass
class Run:
    id: str
    user_id: int
    action: str
    file_id: str
    # The source's name when the run started, so the list still reads after the
    # source is gone.
    file_name: str
    options: dict[str, Any]
    state: str
    progress: float
    message: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    outputs: list[str] = field(default_factory=list)
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    # What the action is doing now (the section it is writing), and what it
    # reported when it finished: counts the page words with language.yaml.
    step: str = ""
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    def to_record(self) -> Record:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "options": self.options,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "created_at": to_iso(self.created_at),
            "started_at": to_iso(self.started_at),
            "finished_at": to_iso(self.finished_at),
            "outputs": self.outputs,
            "deleted_at": to_iso(self.deleted_at),
            "deleted_by": self.deleted_by,
            "step": self.step,
            "result": self.result,
        }

    @classmethod
    def from_record(cls, record: Record) -> "Run":
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            action=record["action"],
            file_id=record["file_id"],
            file_name=record.get("file_name", ""),
            options=record.get("options") or {},
            state=record["state"],
            progress=record.get("progress", 0.0),
            message=record.get("message", ""),
            created_at=from_iso(record["created_at"]),
            started_at=from_iso(record.get("started_at")),
            finished_at=from_iso(record.get("finished_at")),
            outputs=list(record.get("outputs") or []),
            deleted_at=from_iso(record.get("deleted_at")),
            deleted_by=record.get("deleted_by"),
            step=record.get("step", ""),
            result=record.get("result") or {},
        )


def create_run(store: Store, user_id: int, action: str, file: files.File, options: dict[str, Any]) -> Run:
    run = Run(
        id=encryption.url_token(12),
        user_id=user_id,
        action=action,
        file_id=file.id,
        file_name=file.name,
        options=options,
        state=QUEUED,
        progress=0.0,
        message="",
        created_at=utc_now(),
    )
    store.put(BUCKET_RUNS, run.id, run.to_record())
    return run


def get_run(store: Store, run_id: str) -> Run | None:
    record = store.get(BUCKET_RUNS, run_id)
    return None if record is None else Run.from_record(record)


def list_runs(store: Store, user_id: int | None = None) -> list[Run]:
    """Not deleted, newest first: one account's, or everyone's."""
    runs = [Run.from_record(record) for _, record in store.all(BUCKET_RUNS)]
    runs = [run for run in runs if not run.deleted and user_id in (None, run.user_id)]
    runs.sort(key=lambda run: run.created_at, reverse=True)
    return runs


def unfinished(store: Store) -> list[Run]:
    """Queued or running, oldest first: what a restart picks up again."""
    runs = [Run.from_record(record) for _, record in store.all(BUCKET_RUNS)]
    runs = [run for run in runs if run.state not in FINISHED and not run.deleted]
    runs.sort(key=lambda run: run.created_at)
    return runs


def update(store: Store, run_id: str, **changes: Any) -> Run | None:
    """Set fields on a run. Datetimes are stored as text."""

    def mutate(record: Record) -> None:
        for name, value in changes.items():
            record[name] = to_iso(value) if isinstance(value, datetime) else value

    record = store.update_value(BUCKET_RUNS, run_id, mutate)
    return None if record is None else Run.from_record(record)


def add_output(store: Store, run_id: str, file_id: str) -> None:
    def mutate(record: Record) -> None:
        record.setdefault("outputs", []).append(file_id)

    store.update_value(BUCKET_RUNS, run_id, mutate)


def outputs_of(store: Store, run: Run) -> list[files.File]:
    """The run's files still here, in the order they were made."""
    found = [files.get_file(store, file_id) for file_id in run.outputs]
    return [file for file in found if file is not None and not file.deleted and file.state == files.READY]


def drop_outputs(store: Store, run: Run) -> None:
    """Before a run starts again: what it had made is put straight in the bin,
    for the sweep."""
    for record_key, record in store.all(BUCKET_FILES):
        if record.get("run_id") == run.id and record.get("deleted_at") is None:
            files.delete_file(store, str(record_key), run.user_id)
    update(store, run.id, outputs=[])


def delete_run(store: Store, run_id: str, actor_id: int) -> bool:
    """The run and every file it made go to the bin together."""
    found = False

    def mutate(record: Record) -> None:
        nonlocal found
        found = record.get("deleted_at") is None
        mark_deleted(record, actor_id)

    if store.update_value(BUCKET_RUNS, run_id, mutate) is None or not found:
        return False
    run = get_run(store, run_id)
    for file_id in run.outputs if run else []:
        files.delete_file(store, file_id, actor_id)
    return True


def restore_run(store: Store, cfg: Any, run_id: str, actor_id: int, actor_is_admin: bool) -> Run:
    """Undo delete_run, with its files. Raises a RestoreError when it may not
    happen; a file that cannot come back (its own window passed) stays gone."""
    with store.transaction() as transaction:
        record = transaction.get(BUCKET_RUNS, run_id)
        if record is None:
            raise RestoreGoneError()
        unmark_deleted(record, actor_id, actor_is_admin, users.owner_id_tx(transaction))
        transaction.put(BUCKET_RUNS, run_id, record)
    run = Run.from_record(record)
    for file_id in run.outputs:
        try:
            files.restore_file(store, cfg, file_id, actor_id, actor_is_admin)
        except Exception:  # noqa: BLE001 -- one file that cannot come back does not stop the rest
            continue
    return run


def sweep_runs(store: Store) -> int:
    """For the retention job: a run deleted past its undo window, a finished
    run with no files left, whose files went more than a day ago, and a run of
    an account that is gone. Answers how many records went."""
    accounts = {user.id for user in users.list_users(store)}
    live_files = {str(key) for key, record in store.all(BUCKET_FILES) if record.get("deleted_at") is None}
    day_ago = utc_now() - timedelta(days=1)

    def gone(key: object, record: Record) -> bool:
        if deleted_long_ago(record) or record["user_id"] not in accounts:
            return True
        finished = from_iso(record.get("finished_at"))
        empty = not any(file_id in live_files for file_id in record.get("outputs") or [])
        return record["state"] in FINISHED and empty and finished is not None and finished < day_ago

    return store.delete_where(BUCKET_RUNS, gone)
