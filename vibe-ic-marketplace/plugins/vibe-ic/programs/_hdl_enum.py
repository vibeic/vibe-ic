#!/usr/bin/env python3
"""`typedef enum` harvester for staged HDL design inputs (#499).

WHY THIS MODULE EXISTS — Phase 1's document ingester had no branch for
``.sv`` / ``.v``, so a design that stages an HDL package as its stated
parameter / CSR ground truth had that document converted to the empty
string.  With the converter branch added, the package arrives as plain
text and the declarations inside it have to be READ, not just present:
a ten-member state enum sitting in a blob of text does not populate
``L6.fsm_states`` by itself.

WHAT IT WILL AND WILL NOT DO — a ``typedef enum`` is a language
construct, not a design-specific pattern, and this module treats it as
one:

  * A file with no ``typedef enum`` yields nothing.  There is no
    fallback that guesses at enum-shaped prose.
  * An enum whose members carry no explicit values yields member NAMES
    with ``value = None``.  Positional indices are NOT synthesised:
    SystemVerilog's implicit numbering is a language default, not
    something the document said, and an encoding the document did not
    state must not appear as if it had.
  * A member whose literal contains ``x`` / ``z`` yields
    ``value = None`` — an unknown bit is not an encoding.

Role routing (``enum_role``) is by the TYPE name's own vocabulary —
``*state*`` / ``*fsm*`` declares a state type, ``*opcode*`` /
``*instr*`` / ``*cmd*`` declares a command type.  That vocabulary is
HDL/architecture convention, shared across every RISC / bus / peripheral
design; no chip, vendor or SKU literal participates.  A type whose name
declares nothing gets ``enum_role = None`` and is carried without being
routed anywhere.

Chip-AGNOSTIC.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _code_literal import parse_code_literal  # noqa: E402

# HDL source extensions this harvester understands. Mirrors the
# `extract_one` dispatch so the two cannot disagree about what counts as
# a staged HDL document.
HDL_SUFFIXES = frozenset({".sv", ".v", ".svh", ".vh"})

# `typedef enum <base-type>? { <body> } <type_name>;`
#
# The body is non-greedy up to the first `}` — SystemVerilog enum bodies
# cannot nest braces, so this is exact rather than heuristic.
_TYPEDEF_ENUM_RE = re.compile(
    r"\btypedef\s+enum\b(?P<base>[^{;]*)\{(?P<body>[^{}]*)\}\s*"
    r"(?P<type_name>[A-Za-z_]\w*)\s*;",
    re.DOTALL,
)

# `logic [3:0]` / `logic[1:0]` / `bit [7:0]` — the packed-range form the
# declared width comes from. A base type with no range (`logic`) is one
# bit; `integer` / `int` state no packed range and get width None.
_PACKED_RANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
_ONE_BIT_BASE_RE = re.compile(r"\b(?:logic|bit|reg)\b")

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

_MEMBER_RE = re.compile(
    r"^(?P<name>[A-Za-z_]\w*)\s*(?:=\s*(?P<literal>.+))?$", re.DOTALL)

# Type-name vocabulary that declares what an enum IS. HDL convention,
# not chip identity — matched on whole identifier SEGMENTS so a
# substring can never route an unrelated type. `wb_instr_type_e` is an
# instruction-class encoding, not an opcode table, and a substring match
# on "instr" would have put it in `L3.opcodes`; the segment rule and the
# deliberately narrow vocabulary below both refuse it. A miss leaves the
# status quo, a false route FABRICATES entries a gate would then bless,
# so the asymmetry is resolved towards refusing.
_STATE_TYPE_SEGMENTS = frozenset({"state", "states", "fsm"})
_OPCODE_TYPE_SEGMENTS = frozenset({
    "opcode", "opcodes", "opcds", "opc", "cmd", "cmds", "command",
    "commands",
})

_SEGMENT_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")

ROLE_FSM_STATE = "fsm_state"
ROLE_OPCODE = "opcode"


def type_name_segments(type_name: str) -> List[str]:
    """Lowercase identifier segments of a type name.

    ``ctrl_fsm_e`` -> ``["ctrl", "fsm", "e"]``;
    ``mainFsmState_t`` -> ``["main", "fsm", "state", "t"]``.
    """
    if not isinstance(type_name, str):
        return []
    return [s.lower() for s in _SEGMENT_SPLIT_RE.split(type_name.strip())
            if s]


def classify_enum_role(type_name: str) -> Optional[str]:
    """What a type name declares the enum to be, or ``None``.

    Deliberately conservative: an enum whose name declares nothing is
    not routed.  Guessing a role from member names would put arbitrary
    constants into ``fsm_states`` / ``opcodes``, which is the failure
    mode the layers already have gates against.
    """
    segs = set(type_name_segments(type_name))
    if not segs:
        return None
    if segs & _STATE_TYPE_SEGMENTS:
        return ROLE_FSM_STATE
    if segs & _OPCODE_TYPE_SEGMENTS:
        return ROLE_OPCODE
    return None


def _strip_comments(text: str) -> str:
    return _LINE_COMMENT_RE.sub(
        "", _BLOCK_COMMENT_RE.sub(" ", text))


def _base_width(base: str) -> Optional[int]:
    """Declared width of the enum's base type, or ``None``."""
    if not isinstance(base, str):
        return None
    base = _strip_comments(base)
    m = _PACKED_RANGE_RE.search(base)
    if m is not None:
        try:
            hi, lo = int(m.group(1)), int(m.group(2))
        except ValueError:
            return None
        return abs(hi - lo) + 1
    if _ONE_BIT_BASE_RE.search(base):
        return 1
    return None


def _split_members(body: str) -> List[str]:
    """Split an enum body on top-level commas."""
    out: List[str] = []
    depth = 0
    cur: List[str] = []
    for ch in body:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def parse_typedef_enums(text: str) -> List[Dict[str, Any]]:
    """Every ``typedef enum`` declared in ``text``.

    Each record::

        {"type_name": "ctrl_fsm_e",
         "base_type": "logic [3:0]",
         "declared_width": 4,
         "enum_role": "fsm_state" | "opcode" | None,
         "members": [{"name": "RESET", "literal": None, "value": None},
                     ...]}

    ``literal`` / ``value`` are ``None`` whenever the declaration does
    not state them.  Nothing is filled in.
    """
    if not isinstance(text, str) or not text:
        return []
    if "typedef" not in text or "enum" not in text:
        return []
    clean = _strip_comments(text)
    out: List[Dict[str, Any]] = []
    for m in _TYPEDEF_ENUM_RE.finditer(clean):
        type_name = m.group("type_name")
        base = (m.group("base") or "").strip()
        members: List[Dict[str, Any]] = []
        for raw in _split_members(m.group("body") or ""):
            mm = _MEMBER_RE.match(raw.strip())
            if mm is None:
                continue
            name = mm.group("name")
            literal_raw = mm.group("literal")
            literal = None
            value = None
            if literal_raw is not None:
                literal = " ".join(literal_raw.split()).strip()
                parsed = parse_code_literal(literal)
                if parsed is not None:
                    value = parsed[1]
            members.append({
                "name": name,
                "literal": literal,
                "value": value,
            })
        if not members:
            continue
        out.append({
            "type_name": type_name,
            "base_type": base,
            "declared_width": _base_width(base),
            "enum_role": classify_enum_role(type_name),
            "members": members,
        })
    return out


def harvest_enums(extracted: Dict[str, str]) -> List[Dict[str, Any]]:
    """Walk an ``{filename: text}`` map and return every enum declared in
    its HDL-suffixed entries, each stamped with ``source_file``.

    Non-HDL documents are not scanned: a ``typedef enum`` quoted inside
    a datasheet's prose example is illustration, not a declaration the
    design makes, and the ingester already has prose walkers for the
    shapes documentation actually uses.
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(extracted, dict):
        return out
    for fname, text in extracted.items():
        if not isinstance(fname, str) or not isinstance(text, str):
            continue
        if Path(fname).suffix.lower() not in HDL_SUFFIXES:
            continue
        for enum in parse_typedef_enums(text):
            enum = dict(enum)
            enum["source_file"] = fname
            out.append(enum)
    return out
