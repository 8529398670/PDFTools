"""Findings produced by detectors and consumed by removers."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Kind(str, enum.Enum):
    """What sort of thing was found, and which remover can handle it."""

    XOBJECT = "xobject"
    TEXT = "text"
    ANNOT = "annot"
    OCG = "ocg"
    # Informational only: there is nothing to remove structurally.
    IMAGE_PAGE = "image_page"


#: Kinds that no remover can act on. Reported, never modified.
INFO_ONLY = frozenset({Kind.IMAGE_PAGE})


@dataclass(frozen=True)
class Evidence:
    """One reason a candidate scored the way it did.

    `weight` may be negative: evidence that argues *against* this being a
    watermark is as important to surface as evidence for it.
    """

    label: str
    weight: float = 0.0

    def __str__(self) -> str:
        sign = "+" if self.weight > 0 else ("-" if self.weight < 0 else " ")
        return f"{sign} {self.label}"


@dataclass
class Candidate:
    """A suspected watermark.

    `payload` is opaque to everything except the remover registered for
    `kind`; it carries whatever that remover needs to do its work.
    """

    detector: str
    kind: Kind
    description: str
    pages: list[int] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    #: Set directly to bypass evidence-based scoring (used by phrase hits,
    #: where the user's explicit request is the confidence).
    forced_confidence: float | None = None

    @property
    def confidence(self) -> float:
        if self.forced_confidence is not None:
            return _clamp(self.forced_confidence)
        return _clamp(0.5 + sum(e.weight for e in self.evidence))

    @property
    def actionable(self) -> bool:
        return self.kind not in INFO_ONLY

    def add(self, label: str, weight: float = 0.0) -> None:
        self.evidence.append(Evidence(label, weight))

    def page_summary(self) -> str:
        """Render affected pages as 1-based, collapsing runs: '1-19, 25'."""
        if not self.pages:
            return "-"
        nums = sorted({p + 1 for p in self.pages})
        runs: list[tuple[int, int]] = []
        for n in nums:
            if runs and n == runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], n)
            else:
                runs.append((n, n))
        return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "kind": self.kind.value,
            "description": self.description,
            "pages": [p + 1 for p in sorted(set(self.pages))],
            "page_summary": self.page_summary(),
            "confidence": round(self.confidence, 3),
            "actionable": self.actionable,
            "evidence": [{"label": e.label, "weight": e.weight} for e in self.evidence],
        }


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))
