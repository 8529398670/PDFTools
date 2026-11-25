"""Detector registry.

Each detector is a callable taking (Document, Options) and returning
Candidates. They are independent: one raising must not sink the scan.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Callable

from app.actions.watermarks.model import Candidate
from app.actions.watermarks.pdfdoc import Document


@dataclass
class Options:
    """Scan configuration."""

    phrases: list[str] = field(default_factory=list)
    regexes: list[str] = field(default_factory=list)
    #: Skip the builtin phrase vocabulary, matching only what the user gave.
    no_builtin: bool = False
    #: Fraction of pages an object must appear on to count as "repeated".
    repeat_threshold: float = 0.6
    verbose: bool = False


_REGISTRY: dict[str, Callable[[Document, Options], list[Candidate]]] = {}


def register(name: str):
    def deco(fn):
        fn.name = name
        _REGISTRY[name] = fn
        return fn
    return deco


def load_detectors() -> None:
    """Import the detector modules so they register themselves.

    Deferred rather than done at module scope because each detector imports
    from this module, which would be a cycle.
    """
    from app.actions.watermarks.detect import (  # noqa: F401
        annots, imagepage, ocg, phrases, textstyle, xobjects,
    )


def detector_names() -> list[str]:
    load_detectors()
    return list(_REGISTRY)


def run_all(
    doc: Document,
    opts: Options,
    only: set[str] | None = None,
    skip: set[str] | None = None,
) -> tuple[list[Candidate], list[str]]:
    """Run detectors, returning (candidates, warnings)."""
    load_detectors()

    found: list[Candidate] = []
    warnings: list[str] = []
    for name, fn in _REGISTRY.items():
        if only and name not in only:
            continue
        if skip and name in skip:
            continue
        try:
            found.extend(fn(doc, opts))
        except Exception as exc:  # a broken detector must not kill the scan
            warnings.append(f"detector {name!r} failed: {exc}")
            if opts.verbose:
                warnings.append(traceback.format_exc())
    found.sort(key=lambda c: (-c.confidence, c.detector, c.description))
    return found, warnings
