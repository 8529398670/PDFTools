"""The tools /mcp offers (see app/mcp for the protocol and the rules a tool
follows). A tool is declared with its route, by mcp="tool_name" in the
handler's @route(...), and build_registry makes each one with Tool.for_route:
its arguments are the route's own request type, and it runs the route's own
handler, so the two doors answer the same way and refuse for the same
reasons. A tool that adds to its route's answer (where to send a file's bytes)
names a call that does; those live here and in mcp_tools_accounts.py.

The rule: every route an API key may call has a tool, or an mcp_http reason
in its @route(...) for staying HTTP only. app/tests/test_mcp_parity.py fails
until that holds. What a key may not call -- managing API keys, setting your
own password, PIN or two-factor, other people's files, and the owner's
screens -- needs a browser session (access=SESSION_ONLY), so it has no tool
either.

After adding or changing a tool, run scripts/api_docs.sh to rewrite
config/mcp.json and config/api.md; app/tests/test_api_docs.py fails until
they are current.

An app's tools that stand for no route are registered in build_registry,
from a new module in this package (mcp_tools_<feature>.py).
"""
from __future__ import annotations

from typing import Any, Callable

import msgspec

from app.apidocs import ADMIN
from app.core.config import Config
from app.core.config import FILE_CHUNK_BYTES
from app.mcp.registry import Registry, Tool
from app.mcp.registry import Call, Refusal


# What every client is told when it connects (initialize's instructions): the
# tools are the API, but a PDF's bytes never go through them.
INSTRUCTIONS = """PDFTools does things to PDFs: split by bookmarks, rotate, compress, remove watermarks, and chains of these.

File bytes never travel through MCP. Send and fetch them over plain HTTP, with the same `Authorization: Bearer <key>` header this connection uses:

1. Upload: call files_start_upload (name, size, type). It answers the file's id, chunk_url, chunk_bytes and a ready curl loop. POST each piece of the file, in order, as application/octet-stream to chunk_url with {index} = 0, 1, 2 ... Then call files_finish_upload. Wait until files_get says pdf_state is "ok" (the server reads the PDF first); "invalid" means it is not a usable PDF.
2. Run: actions_list says what each action takes. actions_start runs one action on one file; chains_start runs several in order on each file, each later step on every file the step before made (split then compress compresses each section).
   remove_watermarks with mode "check" makes no file: its result lists findings, each with an id, confidence and evidence. Start it again with picked set to the ids to take out just those.
3. Follow: poll runs_get (or chains_get) every few seconds until state is done, failed or cancelled. message says why one failed.
4. Download: runs_download_url (or chains_download_url) gives a zip_url and each file's url. GET them over HTTP with the same header. files_download_url does the same for one file.

Everything you start belongs to the key's account and shows on its Runs screen."""


def files_on(cfg: Config) -> bool:
    return cfg.files.enabled


def file_url(call: Call, path: str) -> str:
    """Where a file route is, from the address this agent reached /mcp at: the
    bytes of a file go there over plain HTTP with the same key, never through
    an MCP message (clients cap those well below a file's size)."""
    return str(call.request.base_url).rstrip("/") + path


def files_start_upload(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The route's answer, with where each piece goes and a shell recipe that
    sends them all."""
    row = msgspec.to_builtins(serve(call.request, body))
    chunk_url = file_url(call, f"/api/files/{row['id']}/chunks/{{index}}")
    base = file_url(call, f"/api/files/{row['id']}/chunks/")
    curl = (
        f"for ((i = 0; i < {row['chunks']}; i++)); do dd if=FILE bs={FILE_CHUNK_BYTES} skip=$i count=1 2>/dev/null | "
        f"curl -sf -o /dev/null -H \"Authorization: Bearer $KEY\" -H 'Content-Type: application/octet-stream' --data-binary @- \"{base}$i\"; done"
    )
    return {**row, "chunk_url": chunk_url, "finish_tool": "files_finish_upload", "curl": curl}


def files_download_url(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """Where to GET a file, for the download route, whose bytes cannot come
    through MCP."""
    from app.routes import files

    row = files.get_my_file.__declared__.serve(call.request, body)
    if row.state != files.models.READY:
        raise Refusal("that file has not finished uploading")
    return {"id": body.file_id, "name": row.name, "size": row.size, "url": file_url(call, f"/api/files/{body.file_id}/download")}


def build_registry() -> Registry:
    """A tool for every route with mcp=, by name. Its title is mcp_title, or
    else the route's summary, with " (admin)" for an admin-only tool; its
    description is mcp_description, or else the route's description, then
    mcp_note. Go's generator (server/apidoc/routegen) has the same rules."""
    from app.routes import declared_routes

    registry = Registry()
    declared = [route for route in declared_routes() if route.tool is not None]
    for route in sorted(declared, key=lambda route: route.tool["name"]):
        keys = dict(route.tool)
        admin_only = keys.pop("admin_only", route.op.role == ADMIN)
        title = keys.pop("mcp_title", "") or (route.op.summary + " (admin)" if admin_only else route.op.summary)
        note = keys.pop("mcp_note", "")
        description = keys.pop("mcp_description", "") or " ".join(part for part in (route.op.description, note) if part)
        if not title or not description:
            raise TypeError(f"{route.method} {route.path}: tool {keys['name']} needs a summary (or mcp_title) and a description, mcp_note or mcp_description")
        make = Tool.for_bulk if route.bulk_of is not None else Tool.for_route
        registry.register(make(route.endpoint, title=title, description=description, admin_only=admin_only, **keys))
    return registry
