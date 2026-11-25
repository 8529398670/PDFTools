"""Removing optional-content (layer) watermarks.

Two halves: unregister the layer from /OCProperties, and strip the
BDC...EMC marked-content ranges guarded by it so the drawing inside actually
goes away rather than becoming unconditionally visible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pikepdf import Array

from app.actions.watermarks.model import Candidate
from app.actions.watermarks.pdfdoc import get_key, objkey

if TYPE_CHECKING:
    from app.actions.watermarks.pdfdoc import Document
    from app.actions.watermarks.remove import Edits


def plan(doc: "Document", cand: Candidate, edits: "Edits") -> tuple[bool, str]:
    target = cand.payload.get("target")
    if target is None:
        return False, "no recorded layer"
    edits.drop_ocgs.add(target)

    # Strip the guarded content ranges.
    planned = 0
    for key, scope in doc.scopes.items():
        props = get_key(scope.resources, "/Properties")
        for start, end in _guarded_ranges(scope.instructions, props, target):
            for idx in range(start, end + 1):
                edits.drop_instructions[key].add(idx)
            planned += 1
    return True, "" if planned else "layer unregistered; no guarded content found"


def _guarded_ranges(
    instructions: list[Any], props: Any, target: Any
) -> list[tuple[int, int]]:
    """Find /OC BDC ... EMC spans belonging to `target`, honouring nesting."""
    ranges: list[tuple[int, int]] = []
    depth = 0
    start = -1
    for idx, instr in enumerate(instructions):
        op = str(getattr(instr, "operator", ""))
        if op in ("BDC", "BMC"):
            if start >= 0:
                depth += 1
                continue
            operands = list(getattr(instr, "operands", []) or [])
            if op == "BDC" and len(operands) >= 2 and str(operands[0]) == "/OC":
                if _refers_to(operands[1], props, target):
                    start, depth = idx, 0
        elif op == "EMC" and start >= 0:
            if depth == 0:
                ranges.append((start, idx))
                start = -1
            else:
                depth -= 1
    return ranges


def _refers_to(operand: Any, props: Any, target: Any) -> bool:
    """Does this BDC operand name or reference the target OCG?"""
    if objkey(operand) == target:
        return True
    resolved = get_key(props, str(operand)) if props is not None else None
    if resolved is None:
        return False
    if objkey(resolved) == target:
        return True
    # An /OCMD wrapping the group counts too.
    inner = get_key(resolved, "/OCGs")
    if inner is None:
        return False
    if objkey(inner) == target:
        return True
    try:
        return any(objkey(o) == target for o in list(inner))
    except TypeError:
        return False


def execute(doc: "Document", targets: set[Any]) -> int:
    """Unregister layers from /OCProperties."""
    try:
        ocprops = doc.pdf.Root.get("/OCProperties")
    except Exception:
        return 0
    if ocprops is None:
        return 0

    removed = 0
    for container_key in ("/OCGs",):
        groups = ocprops.get(container_key)
        if groups is None:
            continue
        try:
            items = list(groups)
        except TypeError:
            continue
        kept = [o for o in items if objkey(o) not in targets]
        removed += len(items) - len(kept)
        ocprops[container_key] = doc.pdf.make_indirect(Array(kept))

    default = ocprops.get("/D")
    if default is not None:
        for key in ("/ON", "/OFF", "/Order"):
            lst = default.get(key)
            if lst is None:
                continue
            try:
                items = list(lst)
            except TypeError:
                continue
            default[key] = doc.pdf.make_indirect(Array(_without(items, targets)))
    return removed


def _without(items: list[Any], targets: set[Any]) -> list[Any]:
    """items less the target layers. /Order nests arrays (a label, then its
    layers), so those are filtered too."""
    kept: list[Any] = []
    for item in items:
        if isinstance(item, Array):
            kept.append(Array(_without(list(item), targets)))
        elif objkey(item) not in targets:
            kept.append(item)
    return kept
