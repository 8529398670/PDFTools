"""Imported PDFs and the files actions make. How they are stored is in
app/models/files.py; here is who may do what. Everyone has their own, and someone else's answers 404, like a key
that is not yours. Admins have their own routes for everyone's, and one opening
a file that is not theirs is written to the log.

An upload is three steps, so that no request carries more than one piece:
POST /api/files, one POST per piece (in any order, several at once), then POST
.../finish. Finishing hands the file to the runner for a first look: is it a
PDF, how many pages, how deep its bookmarks go.

A piece's body is the raw bytes, so its csrf token cannot ride in the body like
everywhere else, and comes in the X-CSRF-Token header instead.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from typing import Annotated, Any, ClassVar, Literal
from urllib.parse import quote

import msgspec
from msgspec import UNSET, Meta, UnsetType
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, Response, StreamingResponse

from app.apidocs import ADMIN, PATH, QUERY, SESSION_ONLY, Reply, route
from app.apidocs import Request as RequestType
from app.core.config import FILE_CHUNK_BYTES
from app.core.logs import KIND_ADMIN
from app.core.runner import EVENT_FILES
from app.core.security import Guard, actor_from
from app.models import RestoreError, to_iso, utc_now
from app.models import files as models
from app.models import retention
from app.models import users
from app.routes.admin import OkReply
from app.routes.helpers import DateTime, Dir, Page, Paged, Refused, get_config, get_store, match_rows, not_found, restore_refusal, run, sorted_page
from app.routes.logs import audit
from app.routes.mcp_tools import files_download_url, files_on, files_start_upload

LOST = "upload_lost"
NO_SUCH_FILE = "no such file"

_locks = models.UploadLocks()


class RequireFiles(Guard):
    """Makes /api/files answer 404 while files.enabled is off. Per request,
    because it can be switched while the server runs."""

    statuses = (404,)

    def refuse(self, request: Request) -> Response | None:
        return None if get_config(request).files.enabled else not_found("not found")


class File(Reply):
    """A file as every route answers it. The sealed key is not in it."""

    api_name: ClassVar[str] = "File"
    id: str
    name: str
    type: str
    size: int
    state: Literal["uploading", "ready"]
    chunks: int
    received: int
    created_at: DateTime
    folder: Annotated[str, Meta(description="The folder it was dropped in with, relative to what was dropped.")]
    kind: Literal["import", "output"]
    encrypted: bool
    pdf_state: Annotated[Literal["pending", "ok", "invalid"], Meta(description="pending until the first look has run.")]
    pdf_error: Annotated[str, Meta(description="Why it could not be read: not_pdf, password or damaged.")]
    pages: int
    title: str
    bookmarks: Annotated[int, Meta(description="Bookmarks in all.")]
    levels: Annotated[list[int], Meta(description="How many bookmarks sit at each level, from the top.")]
    expires_at: Annotated[DateTime | None, Meta(description="When retention removes it; null keeps it.")]
    run_id: Annotated[str, Meta(description="For an output, the run that made it.")]


class FileUpload(File):
    """A file with the size of its pieces: what starting an upload, and asking
    where to resume one, answer."""

    api_name: ClassVar[str] = ""
    chunk_bytes: Annotated[int, Meta(description="Every piece but the last is exactly this long.")]
    missing: Annotated[list[int], Meta(description="The pieces still to send, in any order: where to resume.")]


class OwnedFile(File):
    """A file on the admin list, with whose it is."""

    api_name: ClassVar[str] = ""
    user_id: int
    user_name: str


def _row(file: models.File) -> File:
    """Picks the fields by hand, so the sealed key cannot reach a response by
    way of a change to the model."""
    info = file.pdf or {}
    return File(
        id=file.id,
        name=file.name,
        type=file.type,
        size=file.size,
        state=file.state,  # type: ignore[arg-type]
        chunks=file.chunks,
        received=file.received,
        created_at=to_iso(file.created_at),
        folder=file.folder,
        kind=file.kind,  # type: ignore[arg-type]
        encrypted=file.encrypted,
        pdf_state=file.pdf_state,  # type: ignore[arg-type]
        pdf_error=file.pdf_error,
        pages=int(info.get("pages", 0)),
        title=str(info.get("title", "")),
        bookmarks=int(info.get("bookmarks", 0)),
        levels=[int(count) for count in info.get("levels", [])],
        expires_at=to_iso(file.expires_at),
        run_id=file.run_id,
    )


def _upload_row(file: models.File) -> FileUpload:
    missing = file.missing() if file.state == models.UPLOADING else []
    return FileUpload(**msgspec.structs.asdict(_row(file)), chunk_bytes=FILE_CHUNK_BYTES, missing=missing)


def content_disposition(name: str, inline: bool = False) -> str:
    """Attachment, unless inline is asked for (only ever for a file read as a
    PDF, see _send): an uploaded page must never run as this site. The plain
    filename is the fallback for old clients, and filename* carries the real
    name (RFC 6266)."""
    plain = "".join(character if character.isascii() and (character.isalnum() or character in "._-") else "_" for character in name)
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='-._~')}"


class FileIDPath(RequestType):
    """The file a route under .../files/{file_id} acts on."""

    file_id: Annotated[str, PATH, Meta(description="The file's id, from GET /api/files (files_list over MCP).")]


class AdminFileIDPath(RequestType):
    """Anyone's file, for the admin routes under /api/admin/files."""

    file_id: Annotated[str, PATH, Meta(description="The file's id, from GET /api/admin/files (admin_list_files over MCP).")]


def _mine(request: Request, file_id: str) -> models.File | None:
    """The signed-in account's own, not deleted. Anything else is None, which
    does not say whether the id exists. Reads SQLite: from a worker thread,
    or through run()."""
    file = models.get_file(get_store(request), file_id)
    if file is None or file.deleted or file.user_id != actor_from(request).user.id:
        return None
    return file


class MyStorage(Reply):
    used_bytes: int
    quota_bytes: int


@route(
    "GET /api/account/storage", summary="Your storage",
    tag="Files", feature="files",
    description="How many bytes your files use, and your quota (0 is no limit).",
    mcp="my_storage", read_only=True, enabled=files_on,
)
def my_storage(request: Request) -> MyStorage:
    """How much of the quota an account has used, so it finds out before an
    upload is refused rather than from the refusal. Over HTTP and as the MCP
    my_storage tool."""
    used = models.storage_used(get_store(request), actor_from(request).user.id)
    return MyStorage(used_bytes=used, quota_bytes=get_config(request).files.quota_bytes_per_user)


# What the system says about the disk, which it may not.
DiskBytes = Annotated[int, Meta(description="Left out where the system will not say.")]


class AllStorage(Reply, kw_only=True):
    used_bytes: Annotated[int, Meta(description="Every account's files added up, the way quotas count them: a file several accounts hold counts for each.")]
    stored_bytes: Annotated[int, Meta(description="What those files take on disk: content several files share is stored once.")]
    disk_free_bytes: DiskBytes | UnsetType = UNSET
    disk_total_bytes: DiskBytes | UnsetType = UNSET


@route(
    "GET /api/admin/storage", summary="Storage for everyone",
    tag="Files", role=ADMIN, feature="files",
    description="How many bytes everyone's files use together as quotas count them, what they take on "
    "disk with shared content stored once, and the disk's free and total bytes where the system says.",
    mcp="admin_storage", read_only=True, enabled=files_on,
)
def all_storage(request: Request) -> AllStorage:
    """Every account's files together, and what room the disk has left, which
    no quota looks at. The disk figures are left out where the system will not
    say. Over HTTP and as the MCP admin_storage tool."""
    store = get_store(request)
    body = AllStorage(used_bytes=models.storage_used(store), stored_bytes=models.disk_used(store))
    try:
        disk = shutil.disk_usage(get_config(request).files.dir)
    except OSError:
        return body
    body.disk_free_bytes = disk.free
    body.disk_total_bytes = disk.total
    return body


class ListMyFiles(Page):
    q: Annotated[str, QUERY, Meta(description="Keep files whose name contains this, in any case.")] = ""
    sort: Annotated[Literal["name", "size", "created_at"], QUERY, Meta(description="Field to sort the whole list by. Rows without it go last.")] = ""  # type: ignore[assignment]
    dir: Dir = ""  # type: ignore[assignment]


class FilesReply(Paged):
    files: list[File]


@route(
    "GET /api/files", summary="List your files",
    tag="Files", feature="files",
    description="Your uploaded files, a page at a time: id, name, type, size, state (uploading or ready) "
    "and when. next is the offset of the following page, or null on the last one.",
    mcp="files_list", read_only=True, enabled=files_on,
)
def list_my_files(request: Request, body: ListMyFiles) -> FilesReply:
    """The caller's files, over HTTP and as the MCP files_list tool."""
    rows = [_row(file) for file in models.list_files(get_store(request), actor_from(request).user.id)]
    page = sorted_page(match_rows(rows, body.q, "name"), body.sort, body.dir, body)
    return FilesReply(files=page.pop("rows"), **page)


class ListAllFiles(Page):
    q: Annotated[str, QUERY, Meta(description="Keep files whose name or owner contains this, in any case.")] = ""
    sort: Annotated[Literal["name", "user_name", "size", "created_at"], QUERY, Meta(description="Field to sort the whole list by. Rows without it go last.")] = ""  # type: ignore[assignment]
    dir: Dir = ""  # type: ignore[assignment]


class OwnedFilesReply(Paged):
    files: list[OwnedFile]


@route(
    "GET /api/admin/files", summary="List everyone's files",
    tag="Files", role=ADMIN, feature="files",
    description="Every account's files, a page at a time, with whose each one is (user_id, user_name). next "
    "is the offset of the following page, or null on the last one.",
    mcp="admin_list_files", read_only=True, enabled=files_on,
)
def list_all_files(request: Request, body: ListAllFiles) -> OwnedFilesReply:
    """Adds who each file belongs to. The names, sizes and owners are what an
    admin needs to keep the disk in order. Over HTTP and as the MCP
    admin_list_files tool."""
    store = get_store(request)
    names = {user.id: user.display_name for user in users.list_users(store)}
    rows = [
        OwnedFile(**msgspec.structs.asdict(_row(file)), user_id=file.user_id, user_name=names.get(file.user_id, ""))
        for file in models.list_files(store)
    ]
    page = sorted_page(match_rows(rows, body.q, "name", "user_name"), body.sort, body.dir, body)
    return OwnedFilesReply(files=page.pop("rows"), **page)


# The two things every upload must say. create_file checks them (and the type)
# again, cleaned, with the same words.
BAD_FILE = str(models.BadFileError())


class CreateFile(RequestType):
    name: Annotated[str, Meta(extra={"error": BAD_FILE})]
    size: Annotated[int, Meta(ge=0, extra={"error": BAD_FILE})]
    type: Annotated[str, Meta(description="Shown in the list. Downloads are always application/octet-stream.")] = ""
    folder: Annotated[str, Meta(description="The folder it came in, relative to a dropped folder: shown, never a path on disk.")] = ""
    keep: Annotated[Literal["", "run", "day"], Meta(description="For an upload made to run a tool on: \"run\" deletes it once a run on it is done, \"day\" keeps it 24 hours, \"\" (the default) follows the retention policy. Either choice expires in 24 hours at the latest.")] = ""


@route(
    "POST /api/files", summary="Start an upload",
    tag="Files", feature="files", status=201, errors=(409,),
    description="Then send every piece, in any order and several at once, and finish. A file over files.max_file_bytes, or one that "
    "would pass files.quota_bytes_per_user, is a 409.",
    reply_description="Created",
    mcp_title="Start uploading a file",
    mcp_description="Reserve room for a file and get where to send it. The bytes do not go through MCP: "
    "POST each piece of chunk_bytes bytes (the last may be shorter), in order from index 0, as the raw body "
    "(Content-Type: application/octet-stream) to chunk_url with {index} filled in and the same "
    "Authorization: Bearer header this MCP connection uses. curl is a shell recipe that does all of it. "
    "Then call files_finish_upload.",
    mcp="files_start_upload", enabled=files_on, call=files_start_upload,
)
def create_file(request: Request, body: CreateFile) -> FileUpload:
    """Start an upload, over HTTP and as the MCP files_start_upload tool."""
    store, user_id = get_store(request), actor_from(request).user.id
    try:
        file = models.create_file(
            store, get_config(request), user_id, body.name, body.type, body.size,
            folder=body.folder, expires_at=_expiry(store, user_id, body.keep), keep=body.keep,
        )
    except models.BadFileError as refusal:
        raise Refused(400, str(refusal)) from None
    except (models.FileTooLargeError, models.FileQuotaError) as refusal:
        raise Refused(409, str(refusal)) from None
    return _upload_row(file)


def _expiry(store: Any, user_id: int, keep: str) -> datetime | None:
    """When a new upload expires: a day from now when its uploader chose how
    long to keep it, else as the retention policy says."""
    if keep:
        return utc_now() + timedelta(hours=models.KEEP_HOURS)
    return retention.expiry_for(store, user_id, models.KIND_IMPORT)


class ClaimFile(CreateFile, kw_only=True):
    fingerprint: Annotated[str, Meta(description="The file's content: SHA-256 over the SHA-256 of each 8 MiB piece of it in turn, as 64 lowercase hex digits.", extra={"error": BAD_FILE})]


class ClaimReply(Reply):
    found: Annotated[bool, Meta(description="Whether the server already has this content. When it does not, upload the file as usual (POST /api/files).")]
    claim_id: Annotated[str, Meta(description="Where to send the answer. Empty when found is false.")] = ""
    ranges: Annotated[list[list[int]], Meta(description="[offset, length] pairs: send the SHA-256 of each of these ranges of the file, in hex, in this order. Empty when found is false.")] = []


@route(
    "POST /api/claims", summary="Ask whether the server already has a file",
    tag="Files", feature="files", errors=(409,),
    description="Before uploading, say the file's fingerprint. When the server already holds that content "
    "(anyone's), it asks for the SHA-256 of a few random ranges of the file; a right answer to "
    "POST /api/claims/{claim_id} adds the file without sending it. The same checks as an upload come "
    "first: a file over files.max_file_bytes, or one that would pass your quota, is a 409. Ten minutes to answer.",
)
def claim_file(request: Request, body: ClaimFile) -> ClaimReply:
    """The first half of an upload that may not be needed. Over HTTP only:
    the answer needs the file's bytes, which an MCP client would send anyway."""
    store, user_id = get_store(request), actor_from(request).user.id
    try:
        asked = models.start_claim(
            store, get_config(request), user_id, body.fingerprint, body.name, body.type, body.size,
            folder=body.folder, expires_at=_expiry(store, user_id, body.keep), keep=body.keep,
        )
    except models.BadFileError as refusal:
        raise Refused(400, str(refusal)) from None
    except (models.FileTooLargeError, models.FileQuotaError) as refusal:
        raise Refused(409, str(refusal)) from None
    if asked is None:
        return ClaimReply(found=False)
    claim_id, ranges = asked
    return ClaimReply(found=True, claim_id=claim_id, ranges=[[offset, length] for offset, length in ranges])


class AnswerClaim(RequestType):
    claim_id: Annotated[str, PATH, Meta(description="From POST /api/claims.")]
    hashes: Annotated[list[str], Meta(description="The SHA-256 of each range asked for, in hex, in the same order.")]


@route(
    "POST /api/claims/{claim_id}", summary="Answer a claim",
    tag="Files", feature="files", status=201, errors=(403, 409),
    description="The SHA-256 of each range POST /api/claims asked for. Right, and the file is yours, "
    "ready, without being sent: it shares the bytes the server already has. Wrong, unknown or expired is a "
    "403, and the file has to be uploaded. A claim is answered once.",
    reply_description="Created",
)
def answer_claim(request: Request, body: AnswerClaim) -> File:
    store = get_store(request)
    try:
        file = models.answer_claim(store, get_config(request), actor_from(request).user.id, body.claim_id, body.hashes)
    except models.ClaimError as refusal:
        raise Refused(403, str(refusal)) from None
    except models.FileQuotaError as refusal:
        raise Refused(409, str(refusal)) from None
    if file.pdf_state == models.PDF_PENDING:
        request.app.state.runner.look_at(file.id)
    else:
        request.app.state.runner.publish(EVENT_FILES)
    audit(request, KIND_ADMIN, "file claimed", {"file_id": file.id, "size": file.size})
    return _row(file)


@route(
    "GET /api/files/{file_id}", summary="One of your files",
    tag="Files", feature="files",
    description="One file: its details, and for an unfinished upload which pieces are still to send "
    "(missing), which is where to resume.",
    mcp="files_get", read_only=True, enabled=files_on,
)
def get_my_file(request: Request, body: FileIDPath) -> FileUpload:
    """How a client finds out where to resume: see missing."""
    file = _mine(request, body.file_id)
    if file is None:
        raise Refused(404, NO_SUCH_FILE)
    return _upload_row(file)


class PutChunk(FileIDPath):
    # Checked by hand too: it must also be the next piece, and one the file has.
    index: Annotated[int, PATH, Meta(ge=0, extra={"error": "bad piece number"})]


class PutChunkReply(Reply):
    received: int


@route(
    "POST /api/files/{file_id}/chunks/{index}", summary="Send one piece of an upload",
    tag="Files", feature="files", errors=(409,), body_type="application/octet-stream",
    description="The body is the raw bytes. Pieces may come in any order and several at once; sending one "
    "that already arrived is harmless. A browser session sends its csrf token in the X-CSRF-Token header. "
    "Counts against server.rate_limit_upload_max.",
    mcp_http="File bytes: MCP messages are JSON, and clients cap their size.",
)
async def put_chunk(request: Request, body: PutChunk) -> PutChunkReply:
    """Take one piece. Two requests for the same piece at once: the second is
    a 409, and its retry finds the piece there. The body is the raw bytes, so
    its csrf token comes in the X-CSRF-Token header, which @route checks
    (body_type)."""
    index = body.index
    if not _locks.hold(body.file_id, index):
        raise Refused(409, "another request is writing this piece")
    try:
        file = await run(_mine, request, body.file_id)
        if file is None:
            raise Refused(404, NO_SUCH_FILE)
        if file.state != models.UPLOADING:
            raise Refused(409, "that upload is finished", received=file.received)
        if index >= file.chunks:
            raise Refused(400, "bad piece number")
        try:
            piece = await request.body()
        except ClientDisconnect:
            raise Refused(400, "the piece did not arrive") from None
        try:
            received = await run(models.write_chunk, get_store(request), get_config(request), file, index, piece)
        except models.ChunkSizeError as refusal:
            raise Refused(400, str(refusal)) from None
        except models.FileMissingError:
            raise Refused(404, LOST) from None
        return PutChunkReply(received=received)
    finally:
        _locks.release(body.file_id, index)


@route(
    "POST /api/files/{file_id}/finish", summary="Finish an upload",
    tag="Files", feature="files", errors=(409,),
    description="Seal an upload once every piece has arrived; the file is then ready to download. Asked "
    "again, it answers the same. If pieces are missing it says how many arrived (received).",
    mcp="files_finish_upload", enabled=files_on,
)
def finish_file(request: Request, body: FileIDPath) -> File:
    """Seal an upload whose pieces have all arrived, over HTTP and as the MCP
    files_finish_upload tool."""
    if not _locks.hold(body.file_id, -1):
        raise Refused(409, "another request is writing this upload")
    try:
        file = _mine(request, body.file_id)
        if file is None:
            raise Refused(404, NO_SUCH_FILE)
        # Asked twice, the second answer is the same as the first.
        if file.state == models.READY:
            return _row(file)
        if file.received != file.chunks:
            raise Refused(409, "some of the file has not arrived", received=file.received, missing=file.missing()[:1000])
        try:
            finished = models.finish_file(get_store(request), get_config(request), file)
        except models.FileMissingError:
            raise Refused(404, LOST) from None
    finally:
        _locks.release(body.file_id, -1)
    request.app.state.runner.look_at(finished.id)
    audit(request, KIND_ADMIN, "file uploaded", {"file_id": finished.id, "size": finished.size})
    return _row(finished)


# The policy for a PDF sent inline. The site's own (app/core/middleware.py) has
# object-src 'none', which stops a browser's PDF viewer from showing it at all;
# this one lets the PDF itself be shown and nothing else load or run.
PDF_VIEW_CSP = "default-src 'none'; object-src 'self'; frame-ancestors 'none'"


async def _send(request: Request, file: models.File, view: bool = False) -> Response:
    """Send a finished file. It is an attachment of an opaque type: nosniff is
    on every response, and nothing the uploader said about the file reaches
    the headers except its cleaned name.

    With view, a file the server has read as a PDF (pdf_state ok) is sent
    inline as application/pdf instead, so the browser shows it in its own PDF
    viewer; anything else still goes as an attachment, so the view route can
    never be used to have a page run as this site.

    A plain file goes straight from disk (Starlette's FileResponse), with
    ranges, so a large download can be resumed. An encrypted one is opened a
    piece at a time: Starlette walks the reader in a worker thread, so the
    reads and the decryption stay off the event loop, and the fixed length
    means a piece that fails to open ends the connection short rather than
    looking complete."""
    if file.state != models.READY:
        raise Refused(404, NO_SUCH_FILE)
    inline = view and file.pdf_state == models.PDF_OK
    media_type = "application/pdf" if inline else "application/octet-stream"
    disposition = content_disposition(file.name, inline)
    extra = {"Content-Security-Policy": PDF_VIEW_CSP} if inline else {}
    if not file.encrypted:
        path = models.readable_path(get_config(request), file)
        try:
            stat = await run(path.stat)
        except FileNotFoundError:
            raise Refused(404, NO_SUCH_FILE) from None
        if stat.st_size != file.size:
            print(f"[files] file {file.id} has a record but not the right data on disk", flush=True)
            raise Refused(404, NO_SUCH_FILE)
        return FileResponse(
            path, stat_result=stat, media_type=media_type,
            headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store", **extra},
        )
    try:
        reader = await run(models.FileReader, get_config(request), file)
    except models.FileMissingError:
        print(f"[files] file {file.id} has a record but not the right data on disk", flush=True)
        raise Refused(404, NO_SUCH_FILE) from None
    headers = {
        "Content-Disposition": disposition,
        "Content-Length": str(file.size),
        "Cache-Control": "private, no-store",
        **extra,
    }
    if request.method == "HEAD":
        reader.close()
        return Response(media_type=media_type, headers=headers)
    return StreamingResponse(iter(reader), media_type=media_type, headers=headers)


@route(
    "GET /api/files/{file_id}/download", summary="Download one of your files",
    tag="Files", feature="files", reply_type="application/octet-stream",
    reply_description="The file, always as an attachment",
    mcp_title="Where to download a file",
    mcp_description="The address of one of your files. GET it over HTTP with the same Authorization: Bearer "
    "header this MCP connection uses; the bytes do not come through MCP. url is the download (an attachment); "
    "view_url is the same PDF inline, for showing it in a browser.",
    mcp="files_download_url", read_only=True, enabled=files_on, call=files_download_url,
)
async def download_my_file(request: Request, body: FileIDPath) -> Response:
    file = await run(_mine, request, body.file_id)
    if file is None:
        raise Refused(404, NO_SUCH_FILE)
    return await _send(request, file)


@route(
    "GET /api/admin/files/{file_id}/download", summary="Download anyone's file",
    tag="Files", access=SESSION_ONLY, role=ADMIN, feature="files", reply_type="application/octet-stream",
    description="Written to the activity log when the file is someone else's.",
    reply_description="The file, always as an attachment",
)
async def download_any_file(request: Request, body: AdminFileIDPath) -> Response:
    file = await run(models.get_file, get_store(request), body.file_id)
    if file is None or file.deleted:
        raise Refused(404, NO_SUCH_FILE)
    if file.user_id != actor_from(request).user.id:
        audit(request, KIND_ADMIN, "file opened by admin", {"file_id": file.id, "user_id": file.user_id})
    return await _send(request, file)


@route(
    "GET /api/files/{file_id}/view", summary="Open one of your PDFs in the browser",
    tag="Files", feature="files", reply_type="application/pdf",
    description="The same file as .../download, but a PDF (pdf_state ok) comes inline as application/pdf, "
    "so a browser shows it in its own viewer. Any other file still comes as an attachment.",
    reply_description="The PDF, inline",
)
async def view_my_file(request: Request, body: FileIDPath) -> Response:
    file = await run(_mine, request, body.file_id)
    if file is None:
        raise Refused(404, NO_SUCH_FILE)
    return await _send(request, file, view=True)


@route(
    "GET /api/admin/files/{file_id}/view", summary="Open anyone's PDF in the browser",
    tag="Files", access=SESSION_ONLY, role=ADMIN, feature="files", reply_type="application/pdf",
    description="As GET /api/files/{file_id}/view, for anyone's file. Written to the activity log when the "
    "file is someone else's.",
    reply_description="The PDF, inline",
)
async def view_any_file(request: Request, body: AdminFileIDPath) -> Response:
    file = await run(models.get_file, get_store(request), body.file_id)
    if file is None or file.deleted:
        raise Refused(404, NO_SUCH_FILE)
    if file.user_id != actor_from(request).user.id:
        audit(request, KIND_ADMIN, "file opened by admin", {"file_id": file.id, "user_id": file.user_id})
    return await _send(request, file, view=True)


class RenameFile(FileIDPath):
    name: Annotated[str, Meta(description="Cleaned like an upload's name. 1-255 bytes.", extra={"error": str(models.BadFileNameError())})]
    expect: Annotated[str | None, Meta(description="The name you think it has. Answers 409 if it has another.")] = None


class RenameAnyFile(AdminFileIDPath):
    name: Annotated[str, Meta(description="Cleaned like an upload's name. 1-255 bytes.", extra={"error": str(models.BadFileNameError())})]
    expect: Annotated[str | None, Meta(description="The name you think it has. Answers 409 if it has another.")] = None


class RenameFileReply(Reply):
    ok: bool
    name: Annotated[str, Meta(description="As stored.")]


def _rename(request: Request, body: RenameFile, own_only: bool) -> RenameFileReply:
    """The two rename routes. own_only is the difference: an admin may rename
    anyone's, as an admin may delete anyone's."""
    file = _mine(request, body.file_id) if own_only else models.get_file(get_store(request), body.file_id)
    if file is None or file.deleted:
        raise Refused(404, NO_SUCH_FILE)
    try:
        cleaned = models.rename_file(get_store(request), file.id, body.name, body.expect)
    except models.BadFileNameError as refusal:
        raise Refused(400, str(refusal)) from None
    except users.RenameConflictError as refusal:
        raise Refused(409, str(refusal), name=refusal.current) from None
    if cleaned is None:
        raise Refused(404, NO_SUCH_FILE)
    audit(request, KIND_ADMIN, "file renamed", {"file_id": file.id, "user_id": file.user_id})
    return RenameFileReply(ok=True, name=cleaned)


@route(
    "POST /api/files/{file_id}/rename", summary="Rename a file",
    tag="Files", feature="files", errors=(409,),
    description="Give one of your files a new name. expect, when given, is the name you think it has now; a "
    "rename made meanwhile is refused with the current name.",
    mcp="files_rename", enabled=files_on,
)
def rename_my_file(request: Request, body: RenameFile) -> RenameFileReply:
    """Over HTTP and as the MCP files_rename tool."""
    return _rename(request, body, True)


@route(
    "POST /api/admin/files/{file_id}/rename", summary="Rename any file",
    tag="Files", access=SESSION_ONLY, role=ADMIN, feature="files", errors=(409,),
)
def rename_any_file(request: Request, body: RenameAnyFile) -> RenameFileReply:
    """An admin may rename anyone's, as an admin may delete anyone's."""
    return _rename(request, body, False)


def _delete(request: Request, file_id: str, own_only: bool) -> OkReply:
    """The two delete routes, after each has decided whose files the caller
    may reach. The file goes to the bin, where restore finds it."""
    file = _mine(request, file_id) if own_only else models.get_file(get_store(request), file_id)
    if file is None or file.deleted:
        raise Refused(404, NO_SUCH_FILE)
    if not models.delete_file(get_store(request), file.id, actor_from(request).user.id):
        raise Refused(404, NO_SUCH_FILE)
    audit(request, KIND_ADMIN, "file deleted", {"file_id": file.id, "user_id": file.user_id})
    return OkReply(ok=True)


@route(
    "POST /api/files/{file_id}/delete", summary="Delete a file",
    bulk=True,
    tag="Files", feature="files",
    description="Move one of your files to the bin. It can be restored for ten minutes; after that it is "
    "gone.",
    mcp_note="files_restore brings it back.",
    mcp="files_delete", destructive=True, enabled=files_on,
)
def delete_my_file(request: Request, body: FileIDPath) -> OkReply:
    """Over HTTP and as the MCP files_delete tool."""
    return _delete(request, body.file_id, True)


@route(
    "POST /api/admin/files/{file_id}/delete", summary="Delete anyone's file",
    tag="Files", access=SESSION_ONLY, role=ADMIN, feature="files",
)
def delete_any_file(request: Request, body: AdminFileIDPath) -> OkReply:
    return _delete(request, body.file_id, False)


def _restore(request: Request, file_id: str, as_admin: bool) -> File:
    """Answers an undo, for the two restore routes. Someone else's file looks
    like no file at all, unless the caller is an admin on the admin route."""
    store = get_store(request)
    user = actor_from(request).user
    if not as_admin:
        existing = models.get_file(store, file_id)
        if existing is None or existing.user_id != user.id:
            raise Refused(404, "it is not there to restore")
    try:
        file = models.restore_file(store, get_config(request), file_id, user.id, as_admin)
    except models.FileQuotaError as quota:
        raise Refused(409, str(quota)) from None
    except RestoreError as refused:
        raise restore_refusal(refused) from None
    audit(request, KIND_ADMIN, "file restored", {"file_id": file_id})
    return _row(file)


@route(
    "POST /api/files/{file_id}/restore", summary="Restore a deleted file",
    bulk=True,
    tag="Files", feature="files", errors=(409,),
    description="Bring back a file you deleted, while it is still in the bin and your storage quota has "
    "room.",
    mcp="files_restore", enabled=files_on,
)
def restore_my_file(request: Request, body: FileIDPath) -> File:
    """Over HTTP and as the MCP files_restore tool."""
    return _restore(request, body.file_id, False)


@route(
    "POST /api/admin/files/{file_id}/restore", summary="Put back a deleted file",
    tag="Files", access=SESSION_ONLY, role=ADMIN, feature="files", errors=(409,),
)
def restore_any_file(request: Request, body: AdminFileIDPath) -> File:
    return _restore(request, body.file_id, True)
