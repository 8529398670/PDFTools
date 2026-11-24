"""Actions and their runs: start an action on one of your PDFs, follow it,
download what it made one file at a time or all together as a zip, cancel it,
delete it. Everyone has their own runs; someone else's answers 404.

The work itself happens in app/core/runner.py; the actions are app/actions/.
"""
from __future__ import annotations

import zipfile
from pathlib import PurePosixPath
from typing import Annotated, Any, Iterator, Literal

import msgspec
from msgspec import Meta
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.actions import ACTIONS, ActionError, options_record, parse_options
from app.apidocs import PATH, QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core import sse
from app.core.config import Config
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from, decrypt_cookie, still_signed_in
from app.models import RestoreError, to_iso
from app.models import files as file_models
from app.models import runs as models
from app.routes.admin import OkReply
from app.routes.files import File, _row, content_disposition
from app.routes.helpers import DateTime, Dir, Page, Paged, Refused, error, get_config, get_store, match_rows, restore_refusal, run, sorted_page
from app.routes.logs import audit

NO_SUCH_RUN = "no such run"


class ActionInfo(Reply):
    name: str
    defaults: Annotated[dict[str, Any], Meta(description="Every option and the value it has unless one is sent.")]
    needs_bookmarks: bool


class ActionsReply(Reply):
    actions: list[ActionInfo]


@route(
    "GET /api/actions", summary="What can be done to a PDF",
    tag="Actions", feature="files",
    description="Each action and its options with their defaults. Words for them are in language.yaml under "
    "actions.<name>.",
)
def list_actions(request: Request) -> ActionsReply:
    return ActionsReply(actions=[
        ActionInfo(name=action.name, defaults=options_record(action.options()), needs_bookmarks=action.needs_bookmarks)
        for action in ACTIONS.values()
    ])


class RunRow(Reply):
    id: str
    action: str
    file_id: str
    file_name: str
    options: dict[str, Any]
    state: Literal["queued", "running", "done", "failed", "cancelled"]
    progress: Annotated[float, Meta(description="0 to 1.")]
    step: Annotated[str, Meta(description="What it is doing now: the file it is writing.")]
    message: Annotated[str, Meta(description="Why it failed, as a code.")]
    result: Annotated[dict[str, Any], Meta(description="What it reported when done, such as how many sections.")]
    outputs: Annotated[int, Meta(description="How many of the files it made are still here.")]
    output_bytes: int
    created_at: DateTime
    started_at: DateTime | None
    finished_at: DateTime | None


class RunDetail(RunRow):
    files: list[File]


def _mine(request: Request, run_id: str) -> models.Run | None:
    found = models.get_run(get_store(request), run_id)
    if found is None or found.deleted or found.user_id != actor_from(request).user.id:
        return None
    return found


def _run_row(request: Request, one: models.Run, made: list[file_models.File] | None = None) -> RunRow:
    made = models.outputs_of(get_store(request), one) if made is None else made
    return RunRow(
        id=one.id,
        action=one.action,
        file_id=one.file_id,
        file_name=one.file_name,
        options=one.options,
        state=one.state,  # type: ignore[arg-type]
        progress=one.progress,
        step=one.step,
        message=one.message,
        result=one.result,
        outputs=len(made),
        output_bytes=sum(file.size for file in made),
        created_at=to_iso(one.created_at),
        started_at=to_iso(one.started_at),
        finished_at=to_iso(one.finished_at),
    )


class StartAction(RequestType):
    file_id: Annotated[str, PATH, Meta(description="One of your imported PDFs.")]
    action: Annotated[str, PATH, Meta(description="An action's name, from GET /api/actions.")]
    options: Annotated[dict[str, Any], Meta(description="The action's options; any left out take their default.")] = {}


@route(
    "POST /api/files/{file_id}/actions/{action}", summary="Start an action on a PDF",
    tag="Actions", feature="files", status=201, errors=(404, 409),
    description="Queues a run and answers it. A file that is not a readable PDF, or one with no bookmarks for "
    "an action that needs them, is a 409.",
)
def start_action(request: Request, body: StartAction) -> RunRow:
    started = _start(request, body.action, body.file_id, body.options)
    request.app.state.runner.publish(sse.event("runs", "1"))
    return _run_row(request, started, [])


def _start(request: Request, action_name: str, file_id: str, raw_options: dict[str, Any]) -> models.Run:
    """One run of action on one of the caller's files, queued. Raises Refused
    the way the single route answers."""
    action = ACTIONS.get(action_name)
    if action is None:
        raise Refused(404, "no such action")
    store, user = get_store(request), actor_from(request).user
    file = file_models.get_file(store, file_id)
    if file is None or file.deleted or file.user_id != user.id or file.state != file_models.READY:
        raise Refused(404, "no such file")
    if file.pdf_state != file_models.PDF_OK:
        raise Refused(409, "not_readable")
    if action.needs_bookmarks and not (file.pdf or {}).get("bookmarks"):
        raise Refused(409, "no_bookmarks")
    try:
        options = parse_options(action, raw_options)
    except ActionError as refusal:
        raise Refused(400, str(refusal)) from None
    started = models.create_run(store, user.id, action.name, file, options_record(options))
    request.app.state.runner.submit(started.id)
    audit(request, KIND_ADMIN, "action started", {"run_id": started.id, "action": action.name, "file_id": file.id})
    return started


class StartMany(RequestType):
    action: Annotated[str, PATH, Meta(description="An action's name, from GET /api/actions.")]
    file_ids: Annotated[list[str], Meta(min_length=1, max_length=1000, description="Your imported PDFs, up to 1000.", extra={"error": "file_ids must hold 1-1000 ids"})]
    options: Annotated[dict[str, Any], Meta(description="The action's options, the same for every file.")] = {}


class Skipped(Reply):
    file_id: str
    error: Annotated[str, Meta(description="Why it was not started: no such file, not_readable, no_bookmarks.")]


class StartManyReply(Reply):
    runs: list[RunRow]
    skipped: list[Skipped]


@route(
    "POST /api/actions/{action}/start", summary="Start an action on many PDFs",
    tag="Actions", feature="files", status=201, errors=(404,),
    description="One run per file, in one request: what a dropped folder needs. A file that cannot take the "
    "action is listed in skipped with why, and the rest still start.",
)
def start_many(request: Request, body: StartMany) -> StartManyReply:
    if body.action not in ACTIONS:
        raise Refused(404, "no such action")
    started: list[RunRow] = []
    skipped: list[Skipped] = []
    for file_id in dict.fromkeys(body.file_ids):
        try:
            started.append(_run_row(request, _start(request, body.action, file_id, body.options), []))
        except Refused as refusal:
            if refusal.status == 400:
                raise
            skipped.append(Skipped(file_id=file_id, error=refusal.message))
    request.app.state.runner.publish(sse.event("runs", "1"))
    return StartManyReply(runs=started, skipped=skipped)


class ListRuns(Page):
    q: Annotated[str, QUERY, Meta(description="Keep runs whose file name contains this, in any case.")] = ""
    sort: Annotated[Literal["file_name", "state", "created_at"], QUERY, Meta(description="Field to sort the whole list by.")] = ""  # type: ignore[assignment]
    dir: Dir = ""  # type: ignore[assignment]


class RunsReply(Paged):
    runs: list[RunRow]


@route(
    "GET /api/runs", summary="List your runs",
    tag="Actions", feature="files",
    description="Newest first unless sorted: each run, how far it has got, and how many files it made.",
)
def list_runs(request: Request, body: ListRuns) -> RunsReply:
    store = get_store(request)
    everything = file_models.all_files(store)
    by_id = {file.id: file for file in everything}
    rows = []
    for one in models.list_runs(store, actor_from(request).user.id):
        made = [by_id[file_id] for file_id in one.outputs if file_id in by_id and not by_id[file_id].deleted]
        rows.append(_run_row(request, one, made))
    page = sorted_page(match_rows(rows, body.q, "file_name"), body.sort, body.dir, body)
    return RunsReply(runs=page.pop("rows"), **page)


class RunIDPath(RequestType):
    run_id: Annotated[str, PATH, Meta(description="The run's id, from GET /api/runs.")]


@route(
    "GET /api/runs/{run_id}", summary="One of your runs",
    tag="Actions", feature="files",
    description="The run and the files it made, in order.",
)
def get_run(request: Request, body: RunIDPath) -> RunDetail:
    one = _mine(request, body.run_id)
    if one is None:
        raise Refused(404, NO_SUCH_RUN)
    made = models.outputs_of(get_store(request), one)
    return RunDetail(**msgspec.structs.asdict(_run_row(request, one, made)), files=[_row(file) for file in made])


@route(
    "POST /api/runs/{run_id}/cancel", summary="Cancel a run",
    tag="Actions", feature="files", errors=(409,),
    description="A queued run is cancelled at once, a running one at its next step; what it made so far goes "
    "to the bin.",
)
def cancel_run(request: Request, body: RunIDPath) -> OkReply:
    one = _mine(request, body.run_id)
    if one is None:
        raise Refused(404, NO_SUCH_RUN)
    if one.state in models.FINISHED:
        raise Refused(409, "that run has finished")
    request.app.state.runner.cancel(one.id)
    audit(request, KIND_ADMIN, "run cancelled", {"run_id": one.id})
    return OkReply(ok=True)


@route(
    "POST /api/runs/{run_id}/restart", summary="Start a cancelled or failed run again",
    tag="Actions", feature="files", errors=(409,),
    description="Queues the run again from the beginning, on the same file with the same options. A run that "
    "is queued, running or done, or one whose PDF is gone, is a 409.",
)
def restart_run(request: Request, body: RunIDPath) -> RunRow:
    store = get_store(request)
    one = _mine(request, body.run_id)
    if one is None:
        raise Refused(404, NO_SUCH_RUN)
    if one.state not in models.RESTARTABLE:
        raise Refused(409, "only a cancelled or failed run can start again")
    source = file_models.get_file(store, one.file_id)
    if source is None or source.deleted or source.state != file_models.READY:
        raise Refused(409, "the PDF it ran on is gone")
    restarted = models.restart_run(store, one.id)
    if restarted is None:
        raise Refused(409, "only a cancelled or failed run can start again")
    request.app.state.runner.restart(restarted.id)
    audit(request, KIND_ADMIN, "run restarted", {"run_id": restarted.id})
    return _run_row(request, restarted, [])


@route(
    "POST /api/runs/{run_id}/delete", summary="Delete a run",
    tag="Actions", feature="files",
    description="The run and every file it made go to the bin, and can be restored for ten minutes. A run "
    "still going is cancelled first.",
)
def delete_run(request: Request, body: RunIDPath) -> OkReply:
    one = _mine(request, body.run_id)
    if one is None:
        raise Refused(404, NO_SUCH_RUN)
    if one.state not in models.FINISHED:
        request.app.state.runner.cancel(one.id)
    models.delete_run(get_store(request), one.id, actor_from(request).user.id)
    request.app.state.runner.publish(sse.event("runs", "1"))
    audit(request, KIND_ADMIN, "run deleted", {"run_id": one.id})
    return OkReply(ok=True)


@route(
    "POST /api/runs/{run_id}/restore", summary="Restore a deleted run",
    tag="Actions", feature="files", errors=(409,),
    description="Brings back a run you deleted, with its files, while they are still in the bin.",
)
def restore_run(request: Request, body: RunIDPath) -> RunRow:
    store, user = get_store(request), actor_from(request).user
    existing = models.get_run(store, body.run_id)
    if existing is None or existing.user_id != user.id:
        raise Refused(404, "it is not there to restore")
    try:
        restored = models.restore_run(store, get_config(request), body.run_id, user.id, False)
    except RestoreError as refused:
        raise restore_refusal(refused) from None
    request.app.state.runner.publish(sse.event("runs", "1"))
    audit(request, KIND_ADMIN, "run restored", {"run_id": restored.id})
    return _run_row(request, restored)


class _Sink:
    """Where zipfile writes: held until the generator hands it on. It has no
    tell(), so zipfile writes a stream (data descriptors) and never seeks."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data = b"".join(self.parts)
        self.parts.clear()
        return data


def zip_stream(cfg: Config, made: list[file_models.File], folders: list[str] | None = None) -> Iterator[bytes]:
    """A zip of made, written as it is read: nothing is staged on disk or held
    in memory beyond one piece. Stored, not deflated: a PDF's streams are
    compressed already, and deflating gigabytes again would only cost time.
    folders, one per file, puts each in a folder of that name."""
    sink = _Sink()
    used: set[str] = set()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:  # type: ignore[arg-type]
        for index, file in enumerate(made):
            folder = folders[index] if folders else ""
            name = f"{folder}/{file.name}" if folder else file.name
            stem, suffix = PurePosixPath(file.name).stem, PurePosixPath(file.name).suffix
            counter = 2
            while name.lower() in used:
                name = f"{folder}/{stem} ({counter}){suffix}" if folder else f"{stem} ({counter}){suffix}"
                counter += 1
            used.add(name.lower())
            info = zipfile.ZipInfo(name, date_time=file.created_at.timetuple()[:6])
            info.compress_type = zipfile.ZIP_STORED
            info.file_size = file.size
            with archive.open(info, "w", force_zip64=file.size >= 0xFFFFFFFF) as writer:
                for piece in file_models.FileReader(cfg, file):
                    writer.write(piece)
                    yield sink.take()
            yield sink.take()
    yield sink.take()


@route(
    "GET /api/runs/{run_id}/download", summary="Download everything a run made",
    tag="Actions", feature="files", reply_type="application/zip",
    reply_description="A zip of the run's files, stored as they are, always as an attachment",
)
async def download_run(request: Request, body: RunIDPath) -> Response:
    one = await run(_mine, request, body.run_id)
    if one is None:
        raise Refused(404, NO_SUCH_RUN)
    made = await run(models.outputs_of, get_store(request), one)
    if not made:
        raise Refused(404, "that run made nothing to download")
    stem = PurePosixPath(one.file_name).stem or "sections"
    headers = {"Content-Disposition": content_disposition(f"{stem} - sections.zip"), "Cache-Control": "private, no-store"}
    if request.method == "HEAD":
        return Response(media_type="application/zip", headers=headers)
    return StreamingResponse(zip_stream(get_config(request), made), media_type="application/zip", headers=headers)


class RunIDs(RequestType):
    ids: Annotated[str, QUERY, Meta(description="Your runs' ids, comma-separated, up to 1000.")] = ""


@route(
    "GET /api/runs/download", summary="Download everything several runs made",
    tag="Actions", feature="files", reply_type="application/zip",
    reply_description="One zip, a folder per run named after its PDF, always as an attachment",
    description="What a tool screen offers once a batch is done. A run that is not yours, or made nothing, is "
    "left out; none left is a 404.",
)
async def download_runs(request: Request, body: RunIDs) -> Response:
    ids = list(dict.fromkeys(part for part in body.ids.split(",") if part))[:1000]

    def gather() -> tuple[list[file_models.File], list[str]]:
        store = get_store(request)
        made: list[file_models.File] = []
        folders: list[str] = []
        taken: set[str] = set()
        for run_id in ids:
            one = _mine(request, run_id)
            files = models.outputs_of(store, one) if one is not None else []
            if not files:
                continue
            folder = PurePosixPath(one.file_name).stem or "sections"
            base, counter = folder, 2
            while folder.lower() in taken:
                folder = f"{base} ({counter})"
                counter += 1
            taken.add(folder.lower())
            made.extend(files)
            folders.extend([folder] * len(files))
        return made, folders

    made, folders = await run(gather)
    if not made:
        raise Refused(404, "those runs made nothing to download")
    several = len(set(folders)) > 1
    name = f"PDFTools - {len(made)} files.zip" if several else f"{folders[0]} - sections.zip"
    headers = {"Content-Disposition": content_disposition(name), "Cache-Control": "private, no-store"}
    if request.method == "HEAD":
        return Response(media_type="application/zip", headers=headers)
    return StreamingResponse(zip_stream(get_config(request), made, folders if several else None),
                             media_type="application/zip", headers=headers)


@route(
    "GET /api/runs/stream", summary="Hear when your runs or files change",
    tag="Actions", feature="files", reply_type="text/event-stream", errors=(403, 503),
    description="Server-sent events: \"runs\" when a run moves, \"files\" when an import has been read. Each "
    "only says something changed; fetch the list again.",
)
async def stream_changes(request: Request) -> Response:
    if request.method == "HEAD":
        return Response(headers=sse.HEADERS)
    cfg, store = get_config(request), get_store(request)
    actor = actor_from(request)
    if actor is None or actor.session is None:
        raise Refused(403, "a browser session is needed")
    credential = decrypt_cookie(cfg, request.cookies.get(cfg.session_cookie_name, ""))
    user_id = actor.user.id
    hub: sse.Hub = request.app.state.work_hub
    client = hub.join()
    if client is None:
        return error(503, "too many live streams")

    async def allowed() -> bool:
        return await run(still_signed_in, store, credential, user_id)

    return sse.EventStream(hub, client, allowed, opening=(sse.retry(sse.RETRY_MS),))
