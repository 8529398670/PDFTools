"""What a PDF link does for a person, kept on the account so it follows them
to every browser: "open" (the default) shows the PDF in a new tab, in the
browser's own viewer; "download" saves it, as every link did before.

Only a choice someone made is stored: an empty value is open."""
from __future__ import annotations

from app.core.db import BUCKET_USERS, Record, Store

OPEN = "open"
DOWNLOAD = "download"
CHOICES = (OPEN, DOWNLOAD)


class PdfLinksError(ValueError):
    """What is wrong with a choice, worded for the caller."""


def effective(stored: str) -> str:
    return stored if stored in CHOICES else OPEN


def set_pdf_links(store: Store, user_id: int, choice: str) -> bool:
    """Stores the choice; the default (open) is stored as nothing. False if
    there is no such account."""
    if choice not in CHOICES:
        raise PdfLinksError(f"pdf_links must be one of {', '.join(CHOICES)}")

    def mutate(record: Record) -> None:
        if choice == OPEN:
            record.pop("pdf_links", None)
        else:
            record["pdf_links"] = choice

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None
