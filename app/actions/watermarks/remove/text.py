"""Removing matched text.

Deletion is per glyph, not per text block: a phrase is often drawn in the
same BT..ET block as legitimate content, and dropping the whole block would
take that content with it. The byte offsets recorded while decoding map each
matched character back to the exact operand bytes that produced it, and the
glyphs cut are replaced by a gap of the same width (remove._rewrite), so the
text around them does not move.

When every glyph in a block is matched, only its show-text operators go. The
block's other operators stay: font, spacing, colour and graphics state set
inside BT..ET carry on past ET, and the text after it relies on them.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.actions.watermarks.model import Candidate

if TYPE_CHECKING:
    from app.actions.watermarks.pdfdoc import Document
    from app.actions.watermarks.remove import Edits


def plan(doc: "Document", cand: Candidate, edits: "Edits") -> tuple[bool, str]:
    from app.actions.watermarks.remove import SHOW_OPS, neutralize

    hits = cand.payload.get("hits") or []
    if not hits:
        return False, "no recorded text matches"

    # Which slot indices each (scope, block) loses.
    per_block: dict[tuple[Any, int], set[int]] = defaultdict(set)
    for scope_key, block_idx, start, end in hits:
        scope = doc.scopes.get(scope_key)
        if scope is None or block_idx >= len(scope.blocks):
            continue
        per_block[(scope_key, block_idx)].update(range(start, min(end, len(scope.blocks[block_idx].slots))))

    planned = 0
    for (scope_key, block_idx), slot_indices in per_block.items():
        if not slot_indices:
            continue
        scope = doc.scopes[scope_key]
        block = scope.blocks[block_idx]
        if len(slot_indices) >= len(block.slots):
            for idx in {slot.instr_idx for slot in block.slots}:
                instr = scope.instructions[idx]
                if str(getattr(instr, "operator", "")) in SHOW_OPS:
                    edits.replace_instructions[scope_key][idx] = neutralize(instr)
            planned += 1
            continue
        for si in slot_indices:
            slot = block.slots[si]
            edits.operand_edits[scope_key][
                (slot.instr_idx, slot.operand_idx, slot.array_idx)
            ].append((slot.byte_start, slot.byte_len, slot.advance))
            planned += 1

    if not planned:
        return False, "matches no longer resolve to any glyphs"
    return True, ""
