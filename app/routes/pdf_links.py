"""The caller's own choice of what a PDF link does, from the Account screen
(static/js/pdf_links.js). See app/models/pdf_links.py."""
from __future__ import annotations

from typing import Annotated, Literal

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import Reply, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_AUTH
from app.core.security import actor_from
from app.models import pdf_links
from app.routes.helpers import Refused, get_store
from app.routes.logs import audit


class SetMyPdfLinks(RequestType):
    pdf_links: Annotated[str, Meta(description="open (the default): a PDF link opens in a new tab in the browser's own viewer. download: it is saved, as an attachment.")]


class SetMyPdfLinksReply(Reply):
    ok: bool
    pdf_links: Literal["open", "download"]


@route(
    "POST /api/account/pdf-links", summary="Choose what PDF links do",
    tag="Account",
    description="Choose what a PDF link does on every screen: open (the default) shows it in a new tab in the "
    "browser's own PDF viewer; download saves it. Both GET /api/files/{file_id}/view and .../download stay "
    "available whatever you pick; this only changes which one the pages link to.",
)
def set_my_pdf_links(request: Request, body: SetMyPdfLinks) -> SetMyPdfLinksReply:
    try:
        stored = pdf_links.set_pdf_links(get_store(request), actor_from(request).user.id, body.pdf_links)
    except pdf_links.PdfLinksError as invalid:
        raise Refused(400, str(invalid)) from None
    if not stored:
        raise Refused.internal("pdf links: the signed-in account has no record")
    audit(request, KIND_AUTH, "changed own pdf links", {"pdf_links": body.pdf_links})
    return SetMyPdfLinksReply(ok=True, pdf_links=body.pdf_links)  # type: ignore[arg-type]
