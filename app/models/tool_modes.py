"""Where a person's tools run, kept per account so the choice follows them to
every browser: in the page, with qpdf compiled to WebAssembly ("device"), on
the server ("server"), or wherever the device is up to it ("auto", the
default, worked out by static/js/local.js on each device).

"*" holds the person's own default; a tool id (app.actions.TOOL_IDS) holds an
override for that tool alone. A missing "*" is auto, and a tool with no entry
follows the default, so only choices someone made are stored."""
from __future__ import annotations

from app.actions import TOOL_IDS
from app.core.db import BUCKET_USERS, Record, Store

DEFAULT_KEY = "*"
MODES = ("auto", "device", "server")


class ToolModesError(ValueError):
    """What is wrong with a set of run modes, worded for the caller."""


def check(modes: object) -> dict[str, str]:
    """The set, checked before it replaces the stored one."""
    if not isinstance(modes, dict):
        raise ToolModesError("tool_modes must be an object")
    for key, mode in modes.items():
        if key != DEFAULT_KEY and key not in TOOL_IDS:
            raise ToolModesError(f"unknown tool {key!r}")
        if mode not in MODES:
            raise ToolModesError(f"{key}: mode must be one of {', '.join(MODES)}")
    # Stored in catalog order, the default first, so a set reads the same
    # however it was sent.
    order = (DEFAULT_KEY, *TOOL_IDS)
    return {key: modes[key] for key in order if key in modes}


def set_tool_modes(store: Store, user_id: int, modes: dict[str, str]) -> bool:
    """Replaces the account's run modes. An empty dict puts every tool back to
    auto. False if there is no such account."""
    checked = check(modes)

    def mutate(record: Record) -> None:
        if checked:
            record["tool_modes"] = checked
        else:
            record.pop("tool_modes", None)

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None
