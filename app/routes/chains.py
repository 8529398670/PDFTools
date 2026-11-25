"""Chains: several actions run one after another on a PDF, started, followed,
stopped and downloaded as one. Each step is a run (app/routes/runs.py); see
app/models/chains.py for how a step hands its files to the next.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

import msgspec
from msgspec import Meta
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.actions import ACTIONS, ActionError, options_record, parse_options
from app.apidocs import PATH, QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from
from app.mcp.registry import Call, Refusal
from app.models import chains as models
from app.models import files as file_models
from app.models import runs as run_models
from app.models import to_iso
from app.routes.admin import OkReply
from app.routes.files import File, _row, content_disposition
from app.routes.helpers import DateTime, Refused, get_config, get_store, run
from app.routes.logs import audit
from app.routes.mcp_tools import file_url, files_on
from app.routes.runs import RunRow, _run_row, zip_stream

NO_SUCH_CHAIN = "no such chain"


class Step(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    action: Annotated[str, Meta(description="An action's name, from GET /api/actions.")]
    options: Annotated[dict[str, Any], Meta(description="Its options; any left out take their default.")] = {}


class ChainRow(Reply):
    id: str
    file_id: str
    file_name: str
    steps: list[dict[str, Any]]
    state: Literal["running", "done", "failed", "cancelled"]
    progress: Annotated[float, Meta(description="0 to 1, each step an equal share.")]
    message: Annotated[str, Meta(description="Why it stopped, as a code: the failed step's.")]
    runs: Annotated[int, Meta(description="How many runs its steps have made so far.")]
    outputs: Annotated[int, Meta(description="How many files its last step made that are still here.")]
    output_bytes: int
    created_at: DateTime
    finished_at: DateTime | None


class ChainDetail(ChainRow):
    step_runs: Annotated[list[RunRow], Meta(description="Every run of every step, by step.")]
    files: Annotated[list[File], Meta(description="What the last step made: what the chain made.")]


def _mine(request: Request, chain_id: str) -> models.Chain | None:
    found = models.get_chain(get_store(request), chain_id)
    if found is None or found.deleted or found.user_id != actor_from(request).user.id:
        return None
    return found


def _final_files(request: Request, chain: models.Chain, chain_runs: list[run_models.Run]) -> list[file_models.File]:
    store = get_store(request)
    last = len(chain.steps) - 1
    made: list[file_models.File] = []
    for one in chain_runs:
        if one.step_index == last:
            made.extend(run_models.outputs_of(store, one))
    return made


def _chain_row(request: Request, chain: models.Chain) -> ChainRow:
    chain_runs = models.runs_of(get_store(request), chain.id)
    made = _final_files(request, chain, chain_runs)
    return ChainRow(
        id=chain.id, file_id=chain.file_id, file_name=chain.file_name, steps=chain.steps,
        state=chain.state,  # type: ignore[arg-type]
        progress=models.progress(chain, chain_runs), message=chain.message, runs=len(chain_runs),
        outputs=len(made), output_bytes=sum(file.size for file in made),
        created_at=to_iso(chain.created_at), finished_at=to_iso(chain.finished_at),
    )


def _detail(request: Request, chain: models.Chain) -> ChainDetail:
    chain_runs = models.runs_of(get_store(request), chain.id)
    made = _final_files(request, chain, chain_runs)
    return ChainDetail(
        **msgspec.structs.asdict(_chain_row(request, chain)),
        step_runs=[_run_row(request, one) for one in chain_runs],
        files=[_row(file) for file in made],
    )


class StartChains(RequestType):
    file_ids: Annotated[list[str], Meta(min_length=1, max_length=1000, description="Your imported PDFs, up to 1000: one chain each.", extra={"error": "file_ids must hold 1-1000 ids"})]
    steps: Annotated[list[Step], Meta(min_length=1, max_length=models.MAX_STEPS, description="The actions, in order. Each later one runs on every file the one before made.", extra={"error": f"steps must hold 1-{models.MAX_STEPS} actions"})]


class ChainSkipped(Reply):
    file_id: str
    error: Annotated[str, Meta(description="Why it was not started: no such file, not_readable, no_bookmarks.")]


class StartChainsReply(Reply):
    chains: list[ChainRow]
    skipped: list[ChainSkipped]


def _checked_steps(steps: list[Step]) -> list[dict[str, Any]]:
    checked = []
    for index, step in enumerate(steps):
        action = ACTIONS.get(step.action)
        if action is None:
            raise Refused(404, f"no such action: {step.action}")
        try:
            options = parse_options(action, step.options)
        except ActionError as refusal:
            raise Refused(400, f"step {index + 1}: {refusal}") from None
        if getattr(options, "mode", "") == "check":
            # A check makes no file, so no step could follow it.
            raise Refused(400, f"step {index + 1}: a chain cannot check, only remove")
        checked.append({"action": action.name, "options": options_record(options)})
    return checked


@route(
    "POST /api/chains", summary="Start a chain of actions on PDFs",
    tag="Chains", feature="files", status=201, errors=(400, 404),
    description="One chain per file: its first step runs on the file, and each later step on every file the "
    "step before made, so split then compress compresses each section. Every step's options are checked before "
    "anything starts. A file that cannot take the first step is listed in skipped with why.",
    mcp_note="Follow each with chains_get until its state is done, then chains_download_url.",
    mcp="chains_start", enabled=files_on,
)
def start_chains(request: Request, body: StartChains) -> StartChainsReply:
    steps = _checked_steps(body.steps)
    first = ACTIONS[steps[0]["action"]]
    store, user = get_store(request), actor_from(request).user
    started: list[ChainRow] = []
    skipped: list[ChainSkipped] = []
    for file_id in dict.fromkeys(body.file_ids):
        file = file_models.get_file(store, file_id)
        if file is None or file.deleted or file.user_id != user.id or file.state != file_models.READY:
            skipped.append(ChainSkipped(file_id=file_id, error="no such file"))
            continue
        if file.pdf_state != file_models.PDF_OK:
            skipped.append(ChainSkipped(file_id=file_id, error="not_readable"))
            continue
        if first.needs_bookmarks and not (file.pdf or {}).get("bookmarks"):
            skipped.append(ChainSkipped(file_id=file_id, error="no_bookmarks"))
            continue
        chain, _ = models.create_chain(store, user.id, file, steps)
        audit(request, KIND_ADMIN, "chain started", {"chain_id": chain.id, "file_id": file.id, "steps": [step["action"] for step in steps]})
        started.append(_chain_row(request, chain))
    if started:
        request.app.state.runner.submit("")
    return StartChainsReply(chains=started, skipped=skipped)


class ChainsReply(Reply):
    chains: list[ChainRow]


@route(
    "GET /api/chains", summary="List your chains",
    tag="Chains", feature="files",
    description="Newest first: each chain, how far it has got, and how many files its last step made.",
    mcp="chains_list", read_only=True, enabled=files_on,
)
def list_chains(request: Request) -> ChainsReply:
    store = get_store(request)
    return ChainsReply(chains=[_chain_row(request, chain) for chain in models.list_chains(store, actor_from(request).user.id)])


class ChainIDPath(RequestType):
    chain_id: Annotated[str, PATH, Meta(description="The chain's id, from GET /api/chains.")]


@route(
    "GET /api/chains/{chain_id}", summary="One of your chains",
    tag="Chains", feature="files",
    description="The chain, every run of its steps, and the files its last step made.",
    mcp="chains_get", read_only=True, enabled=files_on,
)
def get_chain(request: Request, body: ChainIDPath) -> ChainDetail:
    chain = _mine(request, body.chain_id)
    if chain is None:
        raise Refused(404, NO_SUCH_CHAIN)
    return _detail(request, chain)


@route(
    "POST /api/chains/{chain_id}/cancel", summary="Stop a chain",
    tag="Chains", feature="files", errors=(409,),
    description="Every step still to finish is cancelled, a running one at its next step.",
    mcp="chains_cancel", destructive=True, enabled=files_on,
)
def cancel_chain(request: Request, body: ChainIDPath) -> OkReply:
    chain = _mine(request, body.chain_id)
    if chain is None:
        raise Refused(404, NO_SUCH_CHAIN)
    if chain.state in models.FINISHED:
        raise Refused(409, "that chain has finished")
    models.cancel_chain(get_store(request), chain.id)
    audit(request, KIND_ADMIN, "chain cancelled", {"chain_id": chain.id})
    return OkReply(ok=True)


@route(
    "POST /api/chains/{chain_id}/restart", summary="Start a stopped chain again",
    tag="Chains", feature="files", errors=(409,),
    description="Every run of a failed or cancelled chain that failed or was cancelled is queued again; what "
    "its steps finished stays.",
    mcp="chains_restart", enabled=files_on,
)
def restart_chain(request: Request, body: ChainIDPath) -> ChainRow:
    store = get_store(request)
    chain = _mine(request, body.chain_id)
    if chain is None:
        raise Refused(404, NO_SUCH_CHAIN)
    source = file_models.get_file(store, chain.file_id)
    if source is None or source.deleted or source.state != file_models.READY:
        raise Refused(409, "the PDF it ran on is gone")
    if models.restart_chain(store, chain.id) is None:
        raise Refused(409, "only a failed or cancelled chain can start again")
    request.app.state.runner.submit("")
    audit(request, KIND_ADMIN, "chain restarted", {"chain_id": chain.id})
    return _chain_row(request, models.get_chain(store, chain.id) or chain)


@route(
    "POST /api/chains/{chain_id}/delete", summary="Delete a chain",
    tag="Chains", feature="files",
    description="The chain, its runs and every file they made go to the bin. A chain still going is stopped first.",
    mcp="chains_delete", destructive=True, enabled=files_on,
)
def delete_chain(request: Request, body: ChainIDPath) -> OkReply:
    store = get_store(request)
    chain = _mine(request, body.chain_id)
    if chain is None:
        raise Refused(404, NO_SUCH_CHAIN)
    if chain.state not in models.FINISHED:
        models.cancel_chain(store, chain.id)
    models.delete_chain(store, chain.id, actor_from(request).user.id)
    audit(request, KIND_ADMIN, "chain deleted", {"chain_id": chain.id})
    return OkReply(ok=True)


def chain_download_url(call: Call, body: Any, serve: Any) -> dict[str, Any]:  # noqa: ARG001 -- serve is the zip route
    """Where to GET a finished chain's zip, and each file it made."""
    detail = get_chain.__declared__.serve(call.request, body)
    if detail.state != models.DONE:
        raise Refusal("that chain has not finished")
    return {
        "id": detail.id, "zip_url": file_url(call, f"/api/chains/{detail.id}/download"),
        "files": [{"id": file.id, "name": file.name, "size": file.size, "url": file_url(call, f"/api/files/{file.id}/download")}
                  for file in detail.files],
    }


def _zip_title(chain: models.Chain) -> str:
    stem = PurePosixPath(chain.file_name).stem or "files"
    return f"{stem} - {' + '.join(step['action'].replace('_', ' ') for step in chain.steps)}"


@route(
    "GET /api/chains/{chain_id}/download", summary="Download what a chain made",
    tag="Chains", feature="files", reply_type="application/zip",
    reply_description="A zip of the last step's files, stored as they are, always as an attachment",
    mcp_title="Where to download what a chain made",
    mcp_description="The address of a finished chain's zip, and of each file its last step made. GET them over "
    "HTTP with the same Authorization: Bearer header this MCP connection uses; the bytes do not come through MCP.",
    mcp="chains_download_url", read_only=True, enabled=files_on, call=chain_download_url,
)
async def download_chain(request: Request, body: ChainIDPath) -> Response:
    chain = await run(_mine, request, body.chain_id)
    if chain is None:
        raise Refused(404, NO_SUCH_CHAIN)
    chain_runs = await run(models.runs_of, get_store(request), chain.id)
    made = await run(_final_files, request, chain, chain_runs)
    if not made:
        raise Refused(404, "that chain made nothing to download")
    headers = {"Content-Disposition": content_disposition(_zip_title(chain) + ".zip"), "Cache-Control": "private, no-store"}
    if request.method == "HEAD":
        return Response(media_type="application/zip", headers=headers)
    return StreamingResponse(zip_stream(get_config(request), made), media_type="application/zip", headers=headers)


class ChainIDs(RequestType):
    ids: Annotated[str, QUERY, Meta(description="Your chains' ids, comma-separated, up to 1000.")] = ""


@route(
    "GET /api/chains/download", summary="Download what several chains made",
    tag="Chains", feature="files", reply_type="application/zip",
    reply_description="One zip, a folder per chain named after its PDF, always as an attachment",
    description="What the chain screen offers once a batch is done. A chain that is not yours, or made nothing, "
    "is left out; none left is a 404.",
    mcp_http="File bytes: MCP messages are JSON, and clients cap their size. chains_download_url gives each chain's.",
)
async def download_chains(request: Request, body: ChainIDs) -> Response:
    ids = list(dict.fromkeys(part for part in body.ids.split(",") if part))[:1000]

    def gather() -> tuple[list[file_models.File], list[str], str]:
        made: list[file_models.File] = []
        folders: list[str] = []
        taken: set[str] = set()
        title = ""
        for chain_id in ids:
            chain = _mine(request, chain_id)
            if chain is None:
                continue
            files = _final_files(request, chain, models.runs_of(get_store(request), chain.id))
            if not files:
                continue
            title = title or _zip_title(chain)
            folder = PurePosixPath(chain.file_name).stem or "files"
            base, counter = folder, 2
            while folder.lower() in taken:
                folder = f"{base} ({counter})"
                counter += 1
            taken.add(folder.lower())
            made.extend(files)
            folders.extend([folder] * len(files))
        return made, folders, title

    made, folders, title = await run(gather)
    if not made:
        raise Refused(404, "those chains made nothing to download")
    several = len(set(folders)) > 1
    name = f"PDFTools - {len(made)} files.zip" if several else f"{title}.zip"
    headers = {"Content-Disposition": content_disposition(name), "Cache-Control": "private, no-store"}
    if request.method == "HEAD":
        return Response(media_type="application/zip", headers=headers)
    return StreamingResponse(zip_stream(get_config(request), made, folders if several else None),
                             media_type="application/zip", headers=headers)
