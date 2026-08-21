#!/usr/bin/env python3
"""One code-literal reader for the extractor AND the detector (#499).

WHY THIS MODULE EXISTS — ``l4_regmap_enumerated_values_typed_check``
derives how many code -> meaning bindings a register field OWES from the
field's own documentation text: it scans that text with a regex for
value-shaped, radix-explicit literals (``2'b01``, ``7'h03``, ``0x3``)
and requires the layer to carry one binding per distinct literal.  The
Phase-1 encoding lifter that is supposed to PRODUCE those bindings had
its own, narrower notion of what a code looks like — it handled
``<binary> = <mnem>``, ``| <binary> | <mnem> |`` and ``<decimal> =
<mnem>`` but not the Verilog-literal form at all.

The result measured on a real design (#499): a field whose description
reads *"Always set to 2'b01 to indicate vectored interrupt handling"*
was reported by the gate as declaring one code literal and carrying zero
bindings.  Both components read the same bytes; the detector was
strictly stronger than the extractor, so the layer could never satisfy
the gate no matter how complete the input was.

Two regexes over the same bytes drift.  This repo has shipped that
failure before (#497), so the fix is not a second regex in the lifter —
it is ONE reader, imported by both sides:

  * ``CODE_LITERAL_RE`` — what counts as a code literal.
  * ``FIELD_TEXT_KEYS`` / ``field_text`` — WHICH bytes of a field are
    its own documentation.  The gate derives its requirement from these
    keys; if the lifter walked a different key set the two would
    disagree about what the field even says.
  * ``declared_codes`` — the distinct literals a field declares, in
    document order.  The gate's ``required`` count and the lifter's
    emit set are now the same list by construction.

``parse_code_literal`` / ``to_binary_pattern`` are the numeric half:
they turn a literal as a document writes it into (declared width,
value), refusing anything whose value is not fully determined
(``4'bxx``, ``2'b0z``).  A literal that does not state a value cannot
become a binding, and this module will not invent one.

Chip-AGNOSTIC: Verilog / C radix syntax is IEEE-1364 / IEEE-1800, not a
chip-class literal.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# A literal code binding as vendor docs write it. Value-shaped and
# radix-explicit so ordinary prose numbers are not mistaken for codes.
#
# Moved here verbatim from l4_regmap_enumerated_values_typed_check in
# v1.7.72 (#499). The gate keeps its `_CODE_LITERAL_RE` name as an
# import alias so anything pinned to that name still resolves — but
# there is now exactly one pattern, not two.
CODE_LITERAL_RE = re.compile(
    r"""(?:
        \b\d+'[bBhHdDoO][0-9a-fA-FxXzZ_]+      # 2'b01, 4'hF
      | \b0[xX][0-9a-fA-F]+\b                   # 0x3
      | \b0[bB][01_]+\b                         # 0b01
      | (?<![\w'])[01]{2,8}(?=\s*(?:=|:|->|=>|—|--)\s*\S)  # 00 = idle
    )""",
    re.VERBOSE,
)

# Free-text keys carrying a register field's own documentation. The gate
# derives its required enum cardinality from these — the design's own
# input — so the lifter must read exactly the same keys or the two
# components disagree about what the field says.
FIELD_TEXT_KEYS: Tuple[str, ...] = (
    "description", "meaning", "notes", "note", "comment",
    "detail", "details", "evidence", "doc",
)

# `<size>'<radix><digits>` — the Verilog sized-literal form.
_SIZED_RE = re.compile(
    r"^(?P<size>\d+)'(?P<radix>[bBhHdDoO])(?P<digits>[0-9a-fA-FxXzZ_]+)$")
_HEX_RE = re.compile(r"^0[xX](?P<digits>[0-9a-fA-F]+)$")
_BIN_RE = re.compile(r"^0[bB](?P<digits>[01_]+)$")
_BARE_BIN_RE = re.compile(r"^[01]{2,8}$")

_RADIX_BASE = {"b": 2, "h": 16, "d": 10, "o": 8}
_RADIX_BITS_PER_DIGIT = {"b": 1, "h": 4, "o": 3}


def field_text(field: Dict[str, Any]) -> str:
    """A register field's own documentation text.

    Identical resolution on both sides of the gate/lifter boundary —
    that identity is the point of the function.
    """
    if not isinstance(field, dict):
        return ""
    parts: List[str] = []
    for k in FIELD_TEXT_KEYS:
        v = field.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, str) and vv.strip():
                    parts.append(vv)
    return " ".join(parts)


def declared_codes(field: Dict[str, Any]) -> List[str]:
    """Distinct code literals the FIELD ITSELF declares, in document
    order.

    Derived from the design's own input text, never from a hardcoded
    expectation, so a consumer can never demand a code the input does
    not state.
    """
    text = field_text(field)
    if not text:
        return []
    seen: List[str] = []
    for m in CODE_LITERAL_RE.findall(text):
        tok = str(m).strip()
        if tok and tok not in seen:
            seen.append(tok)
    return seen


def parse_code_literal(tok: str) -> Optional[Tuple[Optional[int], int]]:
    """``"2'b01"`` -> ``(2, 1)``; ``"0x3"`` -> ``(None, 3)``.

    Returns ``(declared_width_or_None, value)``, or ``None`` when the
    token is not a code literal or its value is not fully determined.

    ``declared_width`` is the width the DOCUMENT states — the size
    prefix of a Verilog sized literal, or the digit count of a ``0b`` /
    bare-binary form.  ``None`` means the document stated a value but
    not a width (``0x3``); the caller decides what width to render it
    at.  A literal carrying ``x`` or ``z`` returns ``None`` outright:
    an unknown bit is not a code, and zero-filling it would be an
    invention.
    """
    if not isinstance(tok, str):
        return None
    tok = tok.strip()
    if not tok:
        return None

    m = _SIZED_RE.match(tok)
    if m is not None:
        radix = m.group("radix").lower()
        digits = m.group("digits").replace("_", "")
        if not digits:
            return None
        if any(c in "xXzZ?" for c in digits):
            # Unknown / high-impedance bits — value not determined.
            return None
        try:
            value = int(digits, _RADIX_BASE[radix])
        except (ValueError, KeyError):
            return None
        try:
            size = int(m.group("size"))
        except ValueError:
            return None
        if size <= 0:
            return None
        return size, value

    m = _HEX_RE.match(tok)
    if m is not None:
        try:
            return None, int(m.group("digits"), 16)
        except ValueError:
            return None

    m = _BIN_RE.match(tok)
    if m is not None:
        digits = m.group("digits").replace("_", "")
        if not digits:
            return None
        return len(digits), int(digits, 2)

    if _BARE_BIN_RE.match(tok):
        return len(tok), int(tok, 2)

    return None


def to_binary_pattern(tok: str, width: int) -> Optional[str]:
    """Render ``tok`` as a ``width``-bit binary pattern, or ``None``.

    Refuses — rather than reshaping — in the two cases where rendering
    would assert something the document did not:

      * the literal declares its OWN width and it is not ``width``.  A
        6-bit constant stated about a sub-slice of a 30-bit field is not
        a 30-bit encoding of that field; zero-extending it would claim
        the whole field is zero.
      * the value does not fit in ``width`` bits.
    """
    if not isinstance(width, int) or width <= 0:
        return None
    parsed = parse_code_literal(tok)
    if parsed is None:
        return None
    declared, value = parsed
    if declared is not None and declared != width:
        return None
    if value < 0 or value >= (1 << width):
        return None
    return format(value, f"0{width}b")


def natural_binary_pattern(tok: str) -> Optional[Tuple[int, str]]:
    """``(width, pattern)`` at the literal's OWN declared width.

    Used when a document states a code about a slice narrower than the
    field that contains it: the honest record is the constant as
    written, at the width it was written at, NOT a zero-extension to the
    enclosing field.  Returns ``None`` for width-less forms (``0x3``) —
    those have no natural width to speak of.
    """
    parsed = parse_code_literal(tok)
    if parsed is None:
        return None
    declared, value = parsed
    if declared is None:
        return None
    if value < 0 or value >= (1 << declared):
        return None
    return declared, format(value, f"0{declared}b")


# Sentence segmentation that survives the abbreviations real register
# documentation is written with. A bare `split(".")` cuts "i.e.," in
# half and would hand back a meaning fragment; requiring the next
# sentence to actually begin (whitespace + an opening character) keeps
# the clause intact.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'`(\[])")


def split_sentences(text: str) -> List[str]:
    """Split documentation prose into sentences, conservatively."""
    if not isinstance(text, str) or not text.strip():
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip())
            if s.strip()]
