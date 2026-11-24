"""The caller's own run modes: where each of their tools runs, from the
Account screen (static/js/tool_modes.js). See app/models/tool_modes.py."""
from __future__ import annotations

from typing import Annotated

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import Reply, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_AUTH
from app.core.security import actor_from
from app.models import tool_modes
from app.routes.helpers import Refused, get_store
from app.routes.logs import audit


class SetMyToolModes(RequestType):
    tool_modes: Annotated[dict[str, str], Meta(description="\"*\" for your default and a tool id for that tool's own override, each auto, device or server, such as {\"*\": \"server\", \"split_bookmarks\": \"device\"}. Replaces the whole set; a tool left out follows your default, and {} puts everything back to auto.")]


class SetMyToolModesReply(Reply):
    ok: bool
    tool_modes: dict[str, str]


@route(
    "POST /api/account/tool-modes", summary="Choose where your tools run",
    tag="Account",
    description='Replace where your tools run: "*" is your default and a tool id an override for that tool, '
    'each auto (this device when it is up to it, else the server), device (in the browser, nothing uploaded) '
    'or server. Send the whole set; a tool left out follows your default, and {} puts everything back to auto.',
)
def set_my_tool_modes(request: Request, body: SetMyToolModes) -> SetMyToolModesReply:
    """Replaces the caller's run modes. The whole set is sent each time, so an
    undo is the same call with the set from before."""
    try:
        wanted = tool_modes.check(body.tool_modes)
    except tool_modes.ToolModesError as invalid:
        raise Refused(400, str(invalid)) from None
    if not tool_modes.set_tool_modes(get_store(request), actor_from(request).user.id, wanted):
        raise Refused.internal("tool modes: the signed-in account has no record")
    audit(request, KIND_AUTH, "changed own tool modes", {"count": len(wanted)})
    return SetMyToolModesReply(ok=True, tool_modes=wanted)
