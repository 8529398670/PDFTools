"""Turning PDF show-text operands into matchable text, and back again.

Two jobs, and the second is why this module is core rather than a convenience:

1. Decode show-text operands to Unicode so phrases can be matched.
2. Remember, for every decoded character, exactly which operand bytes
   produced it -- so a matched phrase can be deleted precisely instead of
   nuking the whole text block it happened to share.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple

import pikepdf

#: Replacement for a code we could not decode. Deliberately a character no
#: real phrase contains, so undecodable runs never create false matches.
UNKNOWN = "�"

_SHOW_OPS = {"Tj", "TJ", "'", '"'}

# Glyph names that actually turn up in /Differences arrays in the wild. Names
# outside this table still resolve if they use the uniXXXX conventions below.
_GLYPH_TO_UNICODE: dict[str, str] = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#",
    "dollar": "$", "percent": "%", "ampersand": "&", "quotesingle": "'",
    "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+",
    "comma": ",", "hyphen": "-", "period": ".", "slash": "/",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "colon": ":", "semicolon": ";", "less": "<", "equal": "=",
    "greater": ">", "question": "?", "at": "@",
    "bracketleft": "[", "backslash": "\\", "bracketright": "]",
    "asciicircum": "^", "underscore": "_", "grave": "`",
    "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~",
    "quoteleft": "‘", "quoteright": "’",
    "quotedblleft": "“", "quotedblright": "”",
    "endash": "–", "emdash": "—", "bullet": "•",
    "fi": "fi", "fl": "fl", "ff": "ff", "ffi": "ffi", "ffl": "ffl",
    "dotlessi": "ı", "germandbls": "ß",
    "copyright": "©", "registered": "®", "trademark": "™",
    "degree": "°", "endash_": "–", "nbspace": " ",
}
for _c in range(ord("A"), ord("Z") + 1):
    _GLYPH_TO_UNICODE[chr(_c)] = chr(_c)
    _GLYPH_TO_UNICODE[chr(_c).lower()] = chr(_c).lower()


def glyphname_to_unicode(name: str) -> str | None:
    """Resolve a PostScript glyph name, including the uniXXXX conventions."""
    name = name.lstrip("/")
    if name in _GLYPH_TO_UNICODE:
        return _GLYPH_TO_UNICODE[name]
    # Composite names like /f_i or /a.sc -- take the base.
    if "." in name:
        return glyphname_to_unicode(name.split(".", 1)[0])
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4,6})", name)
    if m:
        return _safe_chr(int(m.group(1), 16))
    m = re.fullmatch(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        return _safe_chr(int(m.group(1), 16))
    if "_" in name:  # ligature spelled out, e.g. /f_i
        parts = [glyphname_to_unicode(p) for p in name.split("_")]
        if all(parts):
            return "".join(p for p in parts if p)
    return None


def _safe_chr(v: int) -> str | None:
    """chr() that refuses the values that make it raise."""
    if 0 <= v < 0x110000:
        # Surrogates are not valid scalar values; treat as undecodable.
        if 0xD800 <= v <= 0xDFFF:
            return None
        return chr(v)
    return None


# --------------------------------------------------------------------------
# ToUnicode CMaps
# --------------------------------------------------------------------------

#: A /ToUnicode bfrange can legally span a huge interval. Expanding one
#: blindly would hang; no real watermark needs more than this.
_MAX_RANGE = 65536

_HEX = re.compile(rb"<([0-9A-Fa-f\s]*)>")


def _hexbytes(blob: bytes) -> bytes:
    h = re.sub(rb"\s", b"", blob)
    if len(h) % 2:
        h += b"0"
    try:
        return bytes.fromhex(h.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return b""


def _utf16be(raw: bytes) -> str:
    try:
        return raw.decode("utf-16-be", "ignore")
    except (UnicodeDecodeError, LookupError):
        return ""


def parse_tounicode(data: bytes) -> dict[int, str]:
    """Parse a /ToUnicode CMap stream into {character code: string}."""
    cmap: dict[int, str] = {}

    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        toks = _HEX.findall(block)
        for src, dst in zip(toks[::2], toks[1::2]):
            code = _hexbytes(src)
            if not code:
                continue
            cmap.setdefault(int.from_bytes(code, "big"), _utf16be(_hexbytes(dst)))

    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        # Two forms: <lo> <hi> <dst>, and <lo> <hi> [<d1> <d2> ...].
        for m in re.finditer(
            rb"<([0-9A-Fa-f\s]+)>\s*<([0-9A-Fa-f\s]+)>\s*(?:<([0-9A-Fa-f\s]*)>|\[(.*?)\])",
            block,
            re.S,
        ):
            lo = int.from_bytes(_hexbytes(m.group(1)), "big")
            hi = int.from_bytes(_hexbytes(m.group(2)), "big")
            if hi < lo or hi - lo > _MAX_RANGE:
                continue  # malformed or absurd; skip rather than explode
            if m.group(3) is not None:
                dst_raw = _hexbytes(m.group(3))
                if not dst_raw:
                    continue
                base = int.from_bytes(dst_raw, "big")
                # Multi-char destinations increment only the final unit.
                prefix = _utf16be(dst_raw[:-2]) if len(dst_raw) > 2 else ""
                last = int.from_bytes(dst_raw[-2:], "big") if len(dst_raw) >= 2 else base
                for i in range(hi - lo + 1):
                    ch = _safe_chr(last + i)
                    if ch is not None:
                        cmap.setdefault(lo + i, prefix + ch)
            else:
                for i, tok in enumerate(_HEX.findall(m.group(4) or b"")):
                    if lo + i <= hi:
                        cmap.setdefault(lo + i, _utf16be(_hexbytes(tok)))

    return {k: v for k, v in cmap.items() if v}


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------


@dataclass
class FontInfo:
    """Everything needed to turn this font's codes into text."""

    name: str
    bytes_per_code: int = 1
    tounicode: dict[int, str] = field(default_factory=dict)
    differences: dict[int, str] = field(default_factory=dict)
    base_is_ascii: bool = True
    #: Glyph advances in thousandths of text space, by code, from /Widths
    #: (simple fonts) or /W (CID fonts). Empty when the font gives none,
    #: such as an unembedded standard 14 font.
    widths: dict[int, float] = field(default_factory=dict)
    #: /DW of a CID font: the advance of any code /W leaves out.
    default_width: float | None = None

    def width(self, code: int) -> float | None:
        if code in self.widths:
            return self.widths[code]
        return self.default_width

    def decode(self, raw: bytes) -> list[tuple[str, int, int, int]]:
        """Decode to [(text, byte offset, byte length, code)] -- one entry
        per code.

        Byte offsets are relative to `raw`, which is what lets a match be
        mapped back to the exact bytes to delete.
        """
        out: list[tuple[str, int, int, int]] = []
        step = self.bytes_per_code
        for off in range(0, len(raw) - step + 1, step):
            code = int.from_bytes(raw[off : off + step], "big")
            out.append((self._char(code), off, step, code))
        return out

    def _char(self, code: int) -> str:
        if code in self.tounicode:
            return self.tounicode[code]
        if code in self.differences:
            ch = glyphname_to_unicode(self.differences[code])
            if ch is not None:
                return ch
        if self.bytes_per_code == 1 and self.base_is_ascii and 32 <= code < 127:
            return chr(code)
        if self.bytes_per_code == 1 and self.base_is_ascii and 160 <= code < 256:
            # WinAnsi agrees with Latin-1 over this range.
            return chr(code)
        return UNKNOWN


def _as_bytes(obj: Any) -> bytes:
    """Best-effort raw bytes out of a pikepdf stream or string object."""
    for attempt in (
        lambda: obj.read_bytes(),
        lambda: bytes(obj),
        lambda: str(obj).encode("latin-1", "replace"),
    ):
        try:
            data = attempt()
        except Exception:
            continue
        if data:
            return data
    return b""


def load_font(name: str, font_obj: Any) -> FontInfo:
    """Build a FontInfo from a /Font resource dictionary."""
    info = FontInfo(name=name)
    if font_obj is None:
        return info

    def get(key: str) -> Any:
        try:
            return font_obj.get(key)
        except Exception:
            return None

    subtype = str(get("/Subtype") or "")
    if subtype == "/Type0":
        # Identity-H/V and the predefined CJK CMaps are all 2-byte. A custom
        # embedded CMap could differ, but 2 is overwhelmingly the right guess.
        info.bytes_per_code = 2
        info.base_is_ascii = False
        _load_cid_widths(info, get("/DescendantFonts"), str(get("/Encoding") or ""))
    elif subtype != "/Type3":
        # Type 3 widths are in the font's own glyph space (its /FontMatrix),
        # not thousandths, so they are left out rather than misread.
        _load_simple_widths(info, get("/FirstChar"), get("/Widths"))

    tu = get("/ToUnicode")
    if tu is not None:
        data = _as_bytes(tu)
        if data:
            info.tounicode = parse_tounicode(data)

    enc = get("/Encoding")
    if enc is not None:
        try:
            diffs = enc.get("/Differences") if hasattr(enc, "get") else None
        except Exception:
            diffs = None
        if diffs is not None:
            current = 0
            for item in diffs:
                try:
                    if isinstance(item, (int, float)):
                        current = int(item)
                    else:
                        info.differences[current] = str(item)
                        current += 1
                except Exception:
                    continue
        base = str(enc) if not hasattr(enc, "get") else str(enc.get("/BaseEncoding") or "")
        if "Identity" in base:
            info.base_is_ascii = False

    return info


def _load_simple_widths(info: FontInfo, first: Any, widths: Any) -> None:
    if first is None or widths is None:
        return
    try:
        start = int(first)
        for offset, value in enumerate(list(widths)):
            info.widths[start + offset] = float(value)
    except Exception:
        info.widths.clear()


def _load_cid_widths(info: FontInfo, descendants: Any, encoding: str) -> None:
    """/W and /DW of a Type 0 font's descendant. Vertical writing (-V)
    advances down, not across, so it keeps no widths."""
    if encoding.endswith("-V") or descendants is None:
        return
    try:
        cid = list(descendants)[0]
    except Exception:
        return
    try:
        dw = cid.get("/DW")
        info.default_width = float(dw) if dw is not None else 1000.0
        w = cid.get("/W")
        items = list(w) if w is not None else []
    except Exception:
        info.default_width = None
        return
    i = 0
    try:
        while i < len(items):
            first = int(items[i])
            nxt = items[i + 1]
            if isinstance(nxt, pikepdf.Array):
                for offset, value in enumerate(list(nxt)):
                    info.widths[first + offset] = float(value)
                i += 2
            else:
                last, value = int(nxt), float(items[i + 2])
                if last - first <= _MAX_RANGE:
                    for code in range(first, last + 1):
                        info.widths[code] = value
                i += 3
    except Exception:
        return


def load_fonts(resources: Any) -> dict[str, FontInfo]:
    """Load every font in a /Resources dictionary, keyed by resource name."""
    fonts: dict[str, FontInfo] = {}
    if resources is None:
        return fonts
    try:
        fontdict = resources.get("/Font")
    except Exception:
        return fonts
    if fontdict is None:
        return fonts
    try:
        items = list(fontdict.items())
    except Exception:
        return fonts
    for key, val in items:
        name = str(key).lstrip("/")
        try:
            fonts[name] = load_font(name, val)
        except Exception:
            fonts[name] = FontInfo(name=name)
    return fonts


# --------------------------------------------------------------------------
# Decoded text blocks
# --------------------------------------------------------------------------


class Slot(NamedTuple):
    """Where one decoded character came from.

    `array_idx` is -1 for a plain string operand, or the element index when
    the operand is a TJ array.
    """

    instr_idx: int
    operand_idx: int
    array_idx: int
    byte_start: int
    byte_len: int
    #: How far this glyph moves the pen, in a TJ array's units (thousandths
    #: of text space, so a TJ number of -advance takes its place exactly).
    #: None when the font gives no width.
    advance: float | None = None


#: Typographic characters folded to ASCII so a phrase typed with a straight
#: quote still matches text that used a curly one.
_FOLD = {
    ord("‘"): "'", ord("’"): "'", ord("‚"): "'", ord("‛"): "'",
    ord("“"): '"', ord("”"): '"', ord("„"): '"',
    ord("–"): "-", ord("—"): "-", ord("−"): "-", ord("­"): "-",
    ord(" "): " ", ord(" "): " ", ord(" "): " ", ord(" "): " ",
}


def normalize(text: str) -> str:
    """Fold typographic variants. Length-preserving, so indices stay valid."""
    return text.translate(_FOLD)


def squash(text: str) -> tuple[str, list[int]]:
    """Lowercase and drop whitespace, returning a map back to `text` indices.

    PDFs very often encode word gaps as positioning operators rather than
    space glyphs -- real text from the bundled example decodes as
    ``JournalPre-proofDeID-Aligner``. Matching therefore has to ignore
    whitespace on both sides, or user phrases would silently never match.
    """
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(normalize(text)):
        if ch.isspace():
            continue
        # Lower per character and keep one char, so the mapping stays 1:1
        # (str.lower can lengthen, e.g. 'İ' -> 2 chars).
        low = ch.lower()
        out.append(low[0] if low else ch)
        index.append(i)
    return "".join(out), index


@dataclass
class DecodedBlock:
    """One BT..ET block: its text, and where each character came from."""

    text: str
    slots: list[Slot]
    start_instr: int
    end_instr: int
    font_names: list[str] = field(default_factory=list)
    #: What each slot decoded to, in order (joined, they are text).
    chars_of: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._squashed, self._map = squash(self.text)
        # Which slot each character of text came from. One code can decode
        # to several characters (a ligature's "fi"), so text and slots only
        # line up through this.
        self._char_slot: list[int] = []
        for index, slot in enumerate(self.slots):
            self._char_slot.extend([index] * len(self.chars_of[index]) if self.chars_of else [index])
        if len(self._char_slot) != len(self.text):
            self._char_slot = list(range(len(self.text)))

    def slot_span(self, start: int, end: int) -> tuple[int, int]:
        """The slots that drew text[start:end]: a ligature drawn as one
        glyph is taken whole when any of its characters is matched."""
        if end <= start or start >= len(self._char_slot):
            return (0, 0)
        return (self._char_slot[start], self._char_slot[min(end, len(self._char_slot)) - 1] + 1)

    @property
    def squashed(self) -> str:
        return self._squashed

    def search(self, needle: str, boundary: bool = False) -> list[tuple[int, int]]:
        """Find a literal phrase, whitespace- and case-insensitively.

        With `boundary`, reject hits whose immediate neighbours are letters,
        so a short phrase like "SAMPLE" does not fire on "samples". This has
        to work on the squashed string rather than via \b, because many PDFs
        carry no space glyphs at all for \b to anchor to.

        Returns ranges as indices into `text` (slot_span turns them into
        slots).
        """
        key, _ = squash(needle)
        if not key:
            return []
        hits = []
        for m in re.finditer(re.escape(key), self._squashed):
            if boundary and not self._at_boundary(m.start(), m.end()):
                continue
            hits.append((m.start(), m.end()))
        return self._spans(hits)

    def _at_boundary(self, start: int, end: int) -> bool:
        before = self._squashed[start - 1] if start > 0 else ""
        after = self._squashed[end] if end < len(self._squashed) else ""
        return not (before.isalpha() or after.isalpha())

    def search_regex(self, pattern: str) -> list[tuple[int, int]]:
        """Find a regex. Matched against the raw text, not the squashed form,
        so patterns can rely on normal spacing where the PDF has it."""
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []
        return [(m.start(), m.end()) for m in rx.finditer(normalize(self.text)) if m.end() > m.start()]

    def _spans(self, pairs: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
        spans = []
        for s, e in pairs:
            if e <= s or e > len(self._map):
                continue
            spans.append((self._map[s], self._map[e - 1] + 1))
        return spans



def decode_blocks(instructions: list[Any], fonts: dict[str, FontInfo]) -> list[DecodedBlock]:
    """Split a content stream into BT..ET blocks and decode each one.

    Text is concatenated across show-text operators *and* across TJ array
    elements, so kerning-split runs like ``[(W)-3(ater)5(mark)] TJ`` read as
    ``Watermark``.
    """
    blocks: list[DecodedBlock] = []
    chars: list[str] = []
    slots: list[Slot] = []
    used_fonts: list[str] = []
    current: FontInfo | None = None
    start = -1
    # Text state, which outlives BT..ET: font size, character and word
    # spacing. A form starts from zeros, which is what most set anyway.
    size, tc, tw = 0.0, 0.0, 0.0

    def advance(font: FontInfo, code: int) -> float | None:
        width = font.width(code)
        if width is None or not size:
            return None
        spacing = tc + (tw if font.bytes_per_code == 1 and code == 32 else 0.0)
        return width + spacing * 1000.0 / size

    def flush(end_idx: int) -> None:
        nonlocal chars, slots, used_fonts, start
        if start >= 0 and chars:
            blocks.append(
                DecodedBlock(
                    text="".join(chars),
                    slots=list(slots),
                    chars_of=list(chars),
                    start_instr=start,
                    end_instr=end_idx,
                    font_names=list(dict.fromkeys(used_fonts)),
                )
            )
        chars, slots, used_fonts, start = [], [], [], -1

    for idx, instr in enumerate(instructions):
        op = str(getattr(instr, "operator", ""))
        operands = list(getattr(instr, "operands", []) or [])

        if op == "BT":
            flush(idx)
            start = idx
            continue
        if op == "ET":
            flush(idx)
            continue
        if op == "Tf":
            if operands:
                fname = str(operands[0]).lstrip("/")
                current = fonts.get(fname) or FontInfo(name=fname, bytes_per_code=1)
                used_fonts.append(fname)
                if len(operands) > 1:
                    size = _float(operands[1], size)
            continue
        if op == "Tc" and operands:
            tc = _float(operands[0], tc)
            continue
        if op == "Tw" and operands:
            tw = _float(operands[0], tw)
            continue
        if op == '"' and len(operands) >= 2:
            # " sets word then character spacing before it shows its string.
            tw, tc = _float(operands[0], tw), _float(operands[1], tc)
        if op not in _SHOW_OPS:
            continue
        if start < 0:
            # Show-text outside BT/ET is malformed but occurs; treat the
            # operator itself as a one-instruction block.
            start = idx

        font = current or FontInfo(name="?", bytes_per_code=1)

        if op == "TJ":
            array = operands[0] if operands else []
            try:
                elements = list(array)
            except TypeError:
                elements = []
            for a_idx, el in enumerate(elements):
                raw = _string_bytes(el)
                if raw is None:
                    continue
                for ch, off, ln, code in font.decode(raw):
                    chars.append(ch)
                    slots.append(Slot(idx, 0, a_idx, off, ln, advance(font, code)))
        else:
            # Tj and ' take the string first; " takes (aw, ac, string).
            op_idx = 2 if op == '"' else 0
            raw = _string_bytes(operands[op_idx]) if len(operands) > op_idx else None
            if raw is None:
                continue
            for ch, off, ln, code in font.decode(raw):
                chars.append(ch)
                slots.append(Slot(idx, op_idx, -1, off, ln, advance(font, code)))

    flush(len(instructions))
    return blocks


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_bytes(obj: Any) -> bytes | None:
    """Raw bytes of a string operand, or None if it isn't a string."""
    if isinstance(obj, (int, float)):
        return None
    if isinstance(obj, bytes):
        return obj
    try:
        return bytes(obj)
    except Exception:
        return None
