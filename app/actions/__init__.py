"""Actions: what can be done to an imported PDF. Each is one module here,
registered in ACTIONS below, and run by the runner (app/core/runner.py) in a
worker thread, one run per file.

An action is:

- name: the id in URLs and on the run record, never renamed once shipped;
- options: a msgspec Struct, which checks what a person sent before anything
  runs, and whose defaults are what the page starts from;
- run(context, options): does the work, reading context.source (a readable
  path to the PDF), calling context.progress() as it goes, checking
  context.cancelled() between steps, and handing each file it makes to
  context.add_output(). It answers a few counts for the run's result, which
  the page words with language.yaml (actions.<name>.result).

Its labels and help live in language.yaml under actions.<name>.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import msgspec


class ActionError(Exception):
    """A failure worth showing as it is: the message is a language.yaml code
    under actions.errors, or plain words."""


class Cancelled(Exception):
    """Raised by context.check() once the run has been cancelled."""


@dataclass
class Context:
    """What an action gets. Built by the runner for one run."""

    run_id: str
    source: Path
    work: Path
    source_info: dict[str, Any]
    progress: Callable[[float, str], None]
    cancelled: Callable[[], bool]
    add_output: Callable[[str, Path, dict[str, Any]], None]

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled()


@dataclass(frozen=True)
class Action:
    name: str
    options: type[msgspec.Struct]
    run: Callable[[Context, Any], dict[str, Any]]
    # What it needs the source to have, checked before it is queued.
    needs_bookmarks: bool = False


def _registry() -> dict[str, Action]:
    from app.actions import split_bookmarks

    actions = [split_bookmarks.ACTION]
    return {action.name: action for action in actions}


ACTIONS: dict[str, Action] = _registry()


def parse_options(action: Action, raw: dict[str, Any]) -> msgspec.Struct:
    """The options a person sent, checked. Raises ActionError with words to
    show when they do not fit."""
    try:
        return msgspec.convert(raw, action.options, strict=False)
    except msgspec.ValidationError as error:
        raise ActionError(str(error)) from None


def options_record(options: msgspec.Struct) -> dict[str, Any]:
    return msgspec.to_builtins(options)
