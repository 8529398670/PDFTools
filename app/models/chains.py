"""A chain: several actions run one after another on one file, as one thing to
start, follow, stop and download.

Each step is an ordinary run (app/models/runs.py) with this chain's id and its
step's index, so progress, cancelling and the files each makes work as they
do for any run. The first step runs on the chain's file; each later step runs
once on every file the step before it made, so Split by bookmarks then
Compress compresses each section. What the last step makes is what the chain
made; what the steps before it made goes to the bin once the chain is done.

pending counts the chain's runs not yet finished. It changes in the same
write transaction as the runs it counts, so however many workers finish steps
at once, exactly one of them sees it reach 0 and ends the chain.

A step that fails or is cancelled stops the whole chain: its other runs are
cancelled. Restarting the chain queues again every run of it that failed or
was cancelled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core import encryption
from app.core.db import BUCKET_CHAINS, BUCKET_FILES, BUCKET_RUNS, Record, Store
from app.models import from_iso, mark_deleted, to_iso, utc_now
from app.models import files, runs

RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
FINISHED = (DONE, FAILED, CANCELLED)
MAX_STEPS = 10


@dataclass
class Chain:
    id: str
    user_id: int
    file_id: str
    file_name: str
    # [{"action": name, "options": {...}}], checked when the chain was made.
    steps: list[dict[str, Any]]
    state: str
    created_at: datetime
    pending: int = 0
    message: str = ""
    finished_at: datetime | None = None
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    def to_record(self) -> Record:
        return {
            "id": self.id, "user_id": self.user_id, "file_id": self.file_id, "file_name": self.file_name,
            "steps": self.steps, "state": self.state, "created_at": to_iso(self.created_at),
            "pending": self.pending, "message": self.message, "finished_at": to_iso(self.finished_at),
            "deleted_at": to_iso(self.deleted_at), "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_record(cls, record: Record) -> "Chain":
        return cls(
            id=record["id"], user_id=record["user_id"], file_id=record["file_id"], file_name=record.get("file_name", ""),
            steps=list(record.get("steps") or []), state=record["state"], created_at=from_iso(record["created_at"]),
            pending=int(record.get("pending") or 0), message=record.get("message", ""),
            finished_at=from_iso(record.get("finished_at")), deleted_at=from_iso(record.get("deleted_at")),
            deleted_by=record.get("deleted_by"),
        )


def create_chain(store: Store, user_id: int, file: files.File, steps: list[dict[str, Any]]) -> tuple[Chain, runs.Run]:
    """The chain and its first step's run, queued, written together."""
    chain = Chain(id=encryption.url_token(12), user_id=user_id, file_id=file.id, file_name=file.name,
                  steps=steps, state=RUNNING, created_at=utc_now(), pending=1)
    first = runs.new_run(user_id, steps[0]["action"], file, steps[0]["options"], chain.id, 0)
    with store.transaction() as transaction:
        transaction.put(BUCKET_CHAINS, chain.id, chain.to_record())
        transaction.put(BUCKET_RUNS, first.id, first.to_record())
    runs.bump_work(store)
    return chain, first


def get_chain(store: Store, chain_id: str) -> Chain | None:
    record = store.get(BUCKET_CHAINS, chain_id)
    return None if record is None else Chain.from_record(record)


def list_chains(store: Store, user_id: int | None = None) -> list[Chain]:
    chains = [Chain.from_record(record) for _, record in store.all(BUCKET_CHAINS)]
    chains = [chain for chain in chains if not chain.deleted and user_id in (None, chain.user_id)]
    chains.sort(key=lambda chain: chain.created_at, reverse=True)
    return chains


def runs_of(store: Store, chain_id: str) -> list[runs.Run]:
    """Every run of the chain, by step then age."""
    found = [runs.Run.from_record(record) for _, record in store.all(BUCKET_RUNS) if record.get("chain_id") == chain_id]
    found = [run for run in found if not run.deleted]
    found.sort(key=lambda run: (run.step_index, run.created_at))
    return found


def final_runs(store: Store, chain: Chain) -> list[runs.Run]:
    last = len(chain.steps) - 1
    return [run for run in runs_of(store, chain.id) if run.step_index == last]


def progress(chain: Chain, chain_runs: list[runs.Run]) -> float:
    """About how far along it is: each step an equal share, a step's share
    split among its runs."""
    if chain.state == DONE:
        return 1.0
    total = 0.0
    for index in range(len(chain.steps)):
        step = [run for run in chain_runs if run.step_index == index]
        if step:
            total += sum(1.0 if run.state == runs.DONE else run.progress for run in step) / len(step)
    return round(min(total / max(len(chain.steps), 1), 1.0), 4)


def after_run(store: Store, run: runs.Run) -> list[str]:
    """What a finished run of a chain means for it: the next step queued on
    each file the run made, or the chain ended. Called by the worker after
    every run; a run of no chain is left alone. Answers the ids of runs it
    queued."""
    if not run.chain_id or run.state not in runs.FINISHED:
        return []
    queued: list[str] = []
    stop_others = False
    ended = False
    with store.transaction() as transaction:
        record = transaction.get(BUCKET_CHAINS, run.chain_id)
        if record is None:
            return []
        chain = Chain.from_record(record)
        chain.pending = max(chain.pending - 1, 0)
        last = len(chain.steps) - 1
        if chain.state == RUNNING and run.state == runs.DONE and run.step_index < last:
            step = chain.steps[run.step_index + 1]
            for file_id in run.outputs:
                made = transaction.get(BUCKET_FILES, file_id)
                if made is None or made.get("deleted_at") is not None:
                    continue
                following = runs.new_run(run.user_id, step["action"], files.File.from_record(made), step["options"],
                                         chain.id, run.step_index + 1)
                transaction.put(BUCKET_RUNS, following.id, following.to_record())
                queued.append(following.id)
            chain.pending += len(queued)
        elif chain.state == RUNNING and run.state in (runs.FAILED, runs.CANCELLED):
            chain.state = FAILED if run.state == runs.FAILED else CANCELLED
            chain.message = run.message
            stop_others = True
        if chain.pending == 0 and chain.finished_at is None:
            if chain.state == RUNNING:
                chain.state = DONE
            chain.finished_at = utc_now()
            ended = True
        transaction.put(BUCKET_CHAINS, chain.id, chain.to_record())
        runs._bump(transaction)
    if stop_others:
        _stop_all(store, chain.id)
    if ended and chain.state == DONE:
        _drop_between(store, chain)
        from app.core.run_worker import drop_used_upload

        drop_used_upload(store, chain.file_id)
    return queued


def _stop_all(store: Store, chain_id: str) -> None:
    """Ask every run of the chain still to finish to stop. A queued one is
    cancelled on the spot and no worker will see it, so it is counted off
    here; a running one is counted off by its worker."""
    for run in runs_of(store, chain_id):
        if run.state in runs.FINISHED:
            continue
        stopped = runs.request_cancel(store, run.id)
        if stopped is not None and stopped.state == runs.CANCELLED:
            after_run(store, stopped)


def _drop_between(store: Store, chain: Chain) -> None:
    """What the steps before the last made: in the bin, now the chain is done."""
    last = len(chain.steps) - 1
    for run in runs_of(store, chain.id):
        if run.step_index < last:
            for file_id in run.outputs:
                files.delete_file(store, file_id, run.user_id)
    runs.bump_work(store, "files")


def cancel_chain(store: Store, chain_id: str) -> Chain | None:
    """Every run of it still to finish is asked to stop; the chain ends when
    the last of them has."""
    if get_chain(store, chain_id) is None:
        return None
    _stop_all(store, chain_id)
    return get_chain(store, chain_id)


def restart_chain(store: Store, chain_id: str) -> list[str] | None:
    """A failed or cancelled chain running again: every run of it that failed
    or was cancelled is queued again. None when it is not one that can."""
    chain = get_chain(store, chain_id)
    if chain is None or chain.deleted or chain.state not in (FAILED, CANCELLED):
        return None
    again = [run for run in runs_of(store, chain_id) if run.state in runs.RESTARTABLE]
    restarted = []

    def mutate(record: Record) -> None:
        record.update(state=RUNNING, message="", finished_at=None, pending=int(record.get("pending") or 0) + len(again))

    store.update_value(BUCKET_CHAINS, chain_id, mutate)
    for run in again:
        if runs.restart_run(store, run.id) is not None:
            restarted.append(run.id)
    missing = len(again) - len(restarted)
    if missing:
        store.update_value(BUCKET_CHAINS, chain_id, lambda record: record.update(pending=max(int(record.get("pending") or 0) - missing, 0)))
    return restarted


def delete_chain(store: Store, chain_id: str, actor_id: int) -> bool:
    """The chain, its runs and everything they made go to the bin together."""
    found = False

    def mutate(record: Record) -> None:
        nonlocal found
        found = record.get("deleted_at") is None
        mark_deleted(record, actor_id)

    if store.update_value(BUCKET_CHAINS, chain_id, mutate) is None or not found:
        return False
    for run in runs_of(store, chain_id):
        runs.delete_run(store, run.id, actor_id)
    runs.bump_work(store)
    return True


def sweep_chains(store: Store) -> int:
    """For the retention job: a chain whose runs are all gone."""
    live = {record.get("chain_id") for _, record in store.all(BUCKET_RUNS)}
    return store.delete_where(BUCKET_CHAINS, lambda key, record: record["id"] not in live and record.get("state") in FINISHED)
