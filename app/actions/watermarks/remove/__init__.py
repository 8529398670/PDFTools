"""Applying removals.

Every edit is collected into one `Edits` plan before anything is touched,
then applied per content stream. That ordering matters: candidates address
instructions by their original index, so edits must be batched and applied
together rather than one candidate at a time, or the second candidate's
indices would point at the wrong instructions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

import pikepdf
from pikepdf import Array, ContentStreamInstruction, Operator

from app.actions.watermarks.model import Candidate, Kind
from app.actions.watermarks.pdfdoc import Document, objkey

# (start, length, advance): bytes to cut from one string operand, and how far
# those glyphs moved the pen (None when the font gives no widths).
ByteRange = tuple[int, int, Optional[float]]
SlotKey = tuple[int, int, int]  # (instr_idx, operand_idx, array_idx)

SHOW_OPS = {"Tj", "TJ", "'", '"'}


def neutralize(instr: Any) -> list[Any]:
    """What is left of a show-text instruction once its glyphs are all gone:
    everything it did besides painting them. ' moves to the next line first,
    and " also sets word and character spacing, which later text keeps
    using."""
    op = str(getattr(instr, "operator", ""))
    operands = list(getattr(instr, "operands", []) or [])
    if op == "'":
        return [ContentStreamInstruction([], Operator("T*"))]
    if op == '"' and len(operands) >= 2:
        return [
            ContentStreamInstruction([operands[0]], Operator("Tw")),
            ContentStreamInstruction([operands[1]], Operator("Tc")),
            ContentStreamInstruction([], Operator("T*")),
        ]
    return []


@dataclass
class Edits:
    """Everything to change, gathered before anything is changed."""

    drop_instructions: dict[Any, set[int]] = field(
        default_factory=lambda: defaultdict(set))
    #: Instructions replaced by others (an empty list drops one): a text
    #: block whose glyphs all go keeps its state operators this way.
    replace_instructions: dict[Any, dict[int, list[Any]]] = field(
        default_factory=lambda: defaultdict(dict))
    operand_edits: dict[Any, dict[SlotKey, list[ByteRange]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list)))
    drop_resources: dict[Any, set[str]] = field(
        default_factory=lambda: defaultdict(set))
    drop_annots: dict[int, set[int]] = field(
        default_factory=lambda: defaultdict(set))
    drop_ocgs: set[Any] = field(default_factory=set)

    def empty(self) -> bool:
        return not (
            any(self.drop_instructions.values())
            or any(self.replace_instructions.values())
            or any(self.operand_edits.values())
            or any(self.drop_resources.values())
            or any(self.drop_annots.values())
            or self.drop_ocgs
        )


@dataclass
class Report:
    applied: list[Candidate] = field(default_factory=list)
    skipped: list[tuple[Candidate, str]] = field(default_factory=list)
    instructions_removed: int = 0
    glyphs_removed: int = 0
    annots_removed: int = 0
    ocgs_removed: int = 0
    resources_removed: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.instructions_removed or self.glyphs_removed
            or self.annots_removed or self.ocgs_removed
            or self.resources_removed
        )

    def counts(self) -> dict[str, int]:
        return {
            "operators": self.instructions_removed,
            "glyphs": self.glyphs_removed,
            "annotations": self.annots_removed,
            "layers": self.ocgs_removed,
        }


def plan(doc: Document, candidates: list[Candidate]) -> tuple[Edits, Report]:
    """Turn candidates into a single coordinated edit plan."""
    from app.actions.watermarks.remove import annots as annots_mod
    from app.actions.watermarks.remove import ocg as ocg_mod
    from app.actions.watermarks.remove import text as text_mod
    from app.actions.watermarks.remove import xobject as xobject_mod

    handlers = {
        Kind.XOBJECT: xobject_mod.plan,
        Kind.TEXT: text_mod.plan,
        Kind.ANNOT: annots_mod.plan,
        Kind.OCG: ocg_mod.plan,
    }

    edits = Edits()
    report = Report()
    for cand in candidates:
        if not cand.actionable:
            report.skipped.append((cand, "informational only; nothing to remove"))
            continue
        handler = handlers.get(cand.kind)
        if handler is None:
            report.skipped.append((cand, f"no remover for kind {cand.kind.value}"))
            continue
        try:
            ok, why = handler(doc, cand, edits)
        except Exception as exc:  # noqa: BLE001 -- one finding that cannot be planned is skipped
            report.skipped.append((cand, f"failed: {exc}"))
            continue
        if ok:
            report.applied.append(cand)
        else:
            report.skipped.append((cand, why))
    return edits, report


def apply(doc: Document, edits: Edits, report: Report) -> Report:
    """Execute the plan against the document (in memory)."""
    for key, scope in doc.scopes.items():
        drops = edits.drop_instructions.get(key, set())
        replaces = edits.replace_instructions.get(key, {})
        ops = edits.operand_edits.get(key, {})
        if not drops and not ops and not replaces:
            continue

        # Group operand edits by instruction so each is rebuilt once.
        per_instr: dict[int, dict[SlotKey, list[ByteRange]]] = defaultdict(dict)
        for slot, ranges in ops.items():
            per_instr[slot[0]][slot] = ranges

        rebuilt: list[Any] = []
        for idx, instr in enumerate(scope.instructions):
            if idx in drops:
                report.instructions_removed += 1
                continue
            if idx in replaces:
                report.instructions_removed += 1
                report.glyphs_removed += _glyph_count(scope, idx)
                rebuilt.extend(replaces[idx])
                continue
            if idx in per_instr:
                new_instrs, removed = _rewrite(instr, per_instr[idx])
                report.glyphs_removed += removed
                rebuilt.extend(new_instrs if new_instrs is not None else [instr])
            else:
                rebuilt.append(instr)

        scope.instructions = rebuilt
        scope.invalidate()
        scope.dirty = True

    _drop_unused_resources(doc, edits, report)

    for pindex, indices in edits.drop_annots.items():
        report.annots_removed += _drop_annots(doc, pindex, indices)

    if edits.drop_ocgs:
        from app.actions.watermarks.remove import ocg as ocg_mod
        report.ocgs_removed += ocg_mod.execute(doc, edits.drop_ocgs)

    return report


def _glyph_count(scope: Any, idx: int) -> int:
    """How many glyphs one instruction painted. The blocks are still the
    ones decoded before this edit: they are reset only after it."""
    return sum(1 for block in scope.blocks for slot in block.slots if slot.instr_idx == idx)


def _drop_unused_resources(doc: Document, edits: Edits, report: Report) -> None:
    """Take an XObject out of a /Resources dictionary only once no content
    stream using that dictionary still paints it, so a dictionary shared by
    several pages or forms never loses a name something else needs."""
    if not any(edits.drop_resources.values()):
        return
    still_used: dict[Any, set[str]] = defaultdict(set)
    for scope in doc.scopes.values():
        if scope.resources is None:
            continue
        rkey = objkey(scope.resources)
        for instr in scope.instructions:
            if str(getattr(instr, "operator", "")) == "Do":
                operands = list(getattr(instr, "operands", []) or [])
                if operands:
                    still_used[rkey].add(str(operands[0]).lstrip("/"))
    for key, names in edits.drop_resources.items():
        scope = doc.scopes.get(key)
        if scope is None or scope.resources is None:
            continue
        rkey = objkey(scope.resources)
        for name in names:
            if name.lstrip("/") in still_used[rkey]:
                continue
            if _drop_resource(scope.resources, name):
                report.resources_removed += 1


def _pieces(raw: bytes, ranges: list[ByteRange]) -> tuple[list[Any], int, bool]:
    """Split raw around the ranges to cut: the bytes kept and, in place of
    each run cut, a TJ number that moves the pen as far as those glyphs did,
    so the text after them stays exactly where it was. Answers (pieces,
    glyphs cut, whether every glyph cut had a width)."""
    cuts = sorted(r for r in ranges if r[0] >= 0 and r[0] + r[1] <= len(raw))
    pieces: list[Any] = []
    pos, removed, exact = 0, 0, True
    gap, in_gap = 0.0, False
    for start, length, advance in cuts:
        if start < pos:
            continue  # overlapping hit, already cut
        if start > pos:
            if in_gap:
                pieces.append(gap)
                gap, in_gap = 0.0, False
            pieces.append(raw[pos:start])
        if advance is None:
            exact = False
        else:
            gap -= advance
        in_gap = True
        removed += 1
        pos = start + length
    if in_gap:
        pieces.append(gap)
    if pos < len(raw):
        pieces.append(raw[pos:])
    return pieces, removed, exact


def _as_operands(pieces: list[Any]) -> list[Any]:
    out: list[Any] = []
    for piece in pieces:
        if isinstance(piece, bytes):
            if piece:
                out.append(pikepdf.String(piece))
        elif piece:
            out.append(round(piece, 3))
    return out


def _rewrite(instr: Any, slots: dict[SlotKey, list[ByteRange]]) -> tuple[list[Any] | None, int]:
    """Rebuild one show-text instruction with matched bytes deleted.

    pikepdf operand lists are not mutable in place, so fresh instructions are
    built. Glyphs cut from a TJ array become a TJ number of the same width,
    and a Tj (or ' or ") with a cut becomes a TJ the same way, so nothing
    after the cut moves. Where the font gives no widths the bytes are simply
    cut, and what follows in the same string shifts left.
    """
    operands = list(getattr(instr, "operands", []) or [])
    operator = getattr(instr, "operator", None)
    if operator is None:
        return None, 0
    op = str(operator)
    total = 0

    arrays: dict[int, dict[int, list[ByteRange]]] = defaultdict(dict)
    plains: dict[int, list[ByteRange]] = {}
    for (_, op_idx, arr_idx), ranges in slots.items():
        if arr_idx >= 0:
            arrays[op_idx][arr_idx] = ranges
        else:
            plains[op_idx] = ranges

    try:
        if op == "TJ":
            for op_idx, elements in arrays.items():
                if op_idx >= len(operands):
                    continue
                rebuilt: list[Any] = []
                for arr_idx, item in enumerate(list(operands[op_idx])):
                    if arr_idx not in elements or isinstance(item, (int, float)):
                        rebuilt.append(item)
                        continue
                    pieces, n, exact = _pieces(bytes(item), elements[arr_idx])
                    total += n
                    if not exact:
                        pieces = [p for p in pieces if isinstance(p, bytes)]
                    rebuilt.extend(_as_operands(pieces))
                operands[op_idx] = Array(rebuilt)
            return [ContentStreamInstruction(operands, Operator("TJ"))], total

        op_idx = 2 if op == '"' else 0
        ranges = plains.get(op_idx)
        if ranges is None or op_idx >= len(operands):
            return None, 0
        pieces, total, exact = _pieces(bytes(operands[op_idx]), ranges)
        if not exact:
            operands[op_idx] = pikepdf.String(b"".join(p for p in pieces if isinstance(p, bytes)))
            return [ContentStreamInstruction(operands, Operator(op))], total
        shown = ContentStreamInstruction([Array(_as_operands(pieces))], Operator("TJ"))
        return neutralize(instr) + [shown], total
    except Exception:  # noqa: BLE001 -- an operand that cannot be rebuilt is kept as it was
        return None, 0


def _drop_resource(resources: Any, name: str) -> bool:
    if resources is None:
        return False
    try:
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return False
        key = name if name.startswith("/") else "/" + name
        if key in xobjects:
            del xobjects[key]
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _drop_annots(doc: Document, pindex: int, indices: set[int]) -> int:
    try:
        page = doc.pdf.pages[pindex]
        annots = page.obj.get("/Annots")
        if annots is None:
            return 0
        items = list(annots)
        kept = [a for i, a in enumerate(items) if i not in indices]
        if kept:
            page.obj["/Annots"] = doc.pdf.make_indirect(Array(kept))
        else:
            del page.obj["/Annots"]
        return len(items) - len(kept)
    except Exception:  # noqa: BLE001
        return 0
