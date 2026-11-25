"""Removing a repeated XObject overlay.

Only the `Do` operator is deleted. The surrounding `q`/`Q`/`cm` are left
exactly as they are: `Do` does not modify graphics state, so dropping just
that one operator cannot unbalance the stack or disturb anything else that
shares the block. Deleting the enclosing `q`...`Q` instead would risk
taking neighbouring content's clipping or transform with it.

The XObject itself is left in the file, merely unreferenced; qpdf drops it on
save if nothing else points at it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.actions.watermarks.model import Candidate

if TYPE_CHECKING:
    from app.actions.watermarks.pdfdoc import Document
    from app.actions.watermarks.remove import Edits


def plan(doc: "Document", cand: Candidate, edits: "Edits") -> tuple[bool, str]:
    invocations = cand.payload.get("invocations") or []
    if not invocations:
        return False, "no recorded invocations to remove"

    touched = 0
    for inv in invocations:
        if inv.scope is None or inv.instr_idx < 0:
            continue
        scope = doc.scopes.get(inv.scope)
        if scope is None:
            continue
        # Confirm the instruction really is the Do we recorded, so a stale
        # index can never delete unrelated content.
        if not _is_expected_do(scope.instructions, inv.instr_idx, inv.name):
            continue
        edits.drop_instructions[inv.scope].add(inv.instr_idx)
        edits.drop_resources[inv.scope].add(inv.name)
        touched += 1

    if not touched:
        return False, "could not match any Do operator to remove"
    return True, ""


def _is_expected_do(instructions: list[Any], idx: int, name: str) -> bool:
    if idx >= len(instructions):
        return False
    instr = instructions[idx]
    if str(getattr(instr, "operator", "")) != "Do":
        return False
    operands = list(getattr(instr, "operands", []) or [])
    if not operands:
        return False
    return str(operands[0]).lstrip("/") == name.lstrip("/")
