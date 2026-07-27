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
declares nothing gets ``enum_role = None``.

ROUTING IS TOTAL (v1.7.74, #507) — name vocabulary alone decided only
two of the twenty-five types one measured package declares, and the
other twenty-three had NO destination and NO record saying so.  Members
of an unrouted type reached the L docs only when prose elsewhere
happened to describe them; that is capture by luck, and a shortfall
produced that way is invisible.  ``route_enum`` therefore returns an
``EnumRouting`` for EVERY declaration, and ``EnumRouting`` refuses to
be constructed without a reason.  "No branch handles this kind" is no
longer expressible as silence — it is expressible only as a written
decision.

The second routing tier is the enum's SHAPE, not its name.  A type
whose members each bind a name to a distinct code in a space far wider
than the set of names is an ADDRESS MAP — that is the shape of a
register map in every CPU / bus / peripheral design, whatever the local
vocabulary happens to call the type.  Name vocabulary is consulted
FIRST so a type the name already decided keeps the destination and the
``extraction_strategy`` stamp it already had.

Chip-AGNOSTIC.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field as _dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# v1.7.74 — for #507. The SHAPE tier's one role. Not a name vocabulary:
# nothing about the type's spelling participates in deciding it.
ROLE_ADDRESS_MAP = "address_map"

# Destinations a routed enum can have. Spelled once here so the runner,
# the coverage gate and the inventory report cannot disagree about what
# a destination is called.
DEST_L3_OPCODES = "L3.opcodes"
DEST_L4_REGISTERS = "L4.registers"
DEST_L6_FSM_STATES = "L6.fsm_states"

_ROLE_DESTINATION = {
    ROLE_OPCODE: DEST_L3_OPCODES,
    ROLE_FSM_STATE: DEST_L6_FSM_STATES,
    ROLE_ADDRESS_MAP: DEST_L4_REGISTERS,
}

# --- the address-map shape ------------------------------------------------
#
# Every threshold below is stated as a property of the CODE SPACE, never
# of a name, and each one exists to refuse a specific non-map shape that
# would otherwise fabricate registers:
#
#   width >= 8      a two- or three-bit code space is a mode / cause /
#                   select encoding.  Calling one of those an address
#                   space would put `PRIV_LVL_M` in the register map.
#   bindings >= 8   a handful of name -> code bindings is as likely a
#                   status / cause table as a map.  This is the honest
#                   floor of the rule and the reason a refusal always
#                   names which condition it failed: a genuine four-
#                   register map is refused here, visibly, rather than
#                   admitted along with every small code table.
#   occupancy       a map picks scattered points out of a space it does
#     <= 1/8        not come close to filling; an encoding enumerates
#                   most or all of its own space.
#   all valued      a member with no literal states no address.  Half a
#                   map is not a map, and SystemVerilog's implicit
#                   numbering is a language default, not a document.
#   distinct        legal SystemVerilog cannot repeat an explicit enum
#                   value, so this can only fire on a mis-parse — and a
#                   mis-parse must not reach L4.
MIN_ADDRESS_SPACE_WIDTH_BITS = 8
MIN_ADDRESS_BINDINGS = 8
MAX_ADDRESS_SPACE_OCCUPANCY = 0.125


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


# --------------------------------------------------------------------------
# v1.7.74 — for #507. Total routing.
# --------------------------------------------------------------------------

def value_bindings(enum: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Members of ``enum`` that state an integer code, in declaration order.

    A member whose literal the parser could not resolve to an integer —
    absent, or carrying an ``x`` / ``z`` bit — states no code and is not
    a binding.
    """
    out: List[Dict[str, Any]] = []
    for mem in (enum or {}).get("members") or []:
        if not isinstance(mem, dict):
            continue
        val = mem.get("value")
        if not isinstance(val, int) or isinstance(val, bool):
            continue
        name = str(mem.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name, "value": val,
                    "literal": mem.get("literal")})
    return out


def address_map_verdict(enum: Dict[str, Any]) -> Tuple[bool, str]:
    """Is ``enum`` shaped like an address map, and why (either way).

    TOTAL: the second element is never empty.  A refusal names the
    condition that failed and the number that failed it, so a design
    whose register map this rule declines can be reviewed against the
    rule instead of disappearing.
    """
    members = (enum or {}).get("members") or []
    n_members = len(members)
    bindings = value_bindings(enum)
    n = len(bindings)
    if n_members == 0:
        return False, "declares no members"
    if n != n_members:
        return (False,
                f"only {n} of {n_members} member(s) state a code — a map "
                f"with holes states no address for the rest")
    width = (enum or {}).get("declared_width")
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        return (False,
                "the declaration states no packed width, so the size of "
                "the code space it selects from is unknown")
    if width < MIN_ADDRESS_SPACE_WIDTH_BITS:
        return (False,
                f"the code space is {width} bit(s) wide (< "
                f"{MIN_ADDRESS_SPACE_WIDTH_BITS}) — that is a mode / "
                f"cause / select encoding, not an address space")
    if n < MIN_ADDRESS_BINDINGS:
        return (False,
                f"{n} name->code binding(s) (< {MIN_ADDRESS_BINDINGS}) — "
                f"too few to tell a register map from a status / cause "
                f"code table")
    values = [b["value"] for b in bindings]
    if len(set(values)) != len(values):
        return (False,
                "two member(s) bind the same code, which legal "
                "SystemVerilog cannot express — the declaration did not "
                "parse as a map")
    occupancy = n / float(1 << width)
    if occupancy > MAX_ADDRESS_SPACE_OCCUPANCY:
        return (False,
                f"{n} binding(s) fill {occupancy:.1%} of a {width}-bit "
                f"code space (> {MAX_ADDRESS_SPACE_OCCUPANCY:.1%}) — a "
                f"space that full is being enumerated, not addressed")
    return (True,
            f"{n} member(s) each bind a name to a distinct code in a "
            f"{width}-bit space they fill {occupancy:.1%} of — the shape "
            f"of a register-map address binding")


def classify_enum_shape(enum: Dict[str, Any]) -> Optional[str]:
    """The role ``enum``'s SHAPE declares, or ``None``.

    Consulted only after the type-name vocabulary has declined, so a
    type the name already routed keeps its existing destination.
    """
    ok, _why = address_map_verdict(enum)
    return ROLE_ADDRESS_MAP if ok else None


@dataclass
class EnumRouting:
    """Where one ``typedef enum`` goes, and why — always both.

    ``__post_init__`` raises when ``reason`` is empty.  That is the
    whole point of the type: #507 measured twenty-three declarations
    with no destination and no record, and a routing table that can be
    silent will be silent again the next time a shape nobody anticipated
    shows up.
    """

    type_name: str
    source_file: str = ""
    destination: Optional[str] = None
    role: Optional[str] = None
    rule: str = ""
    reason: str = ""
    member_count: int = 0
    binding_count: int = 0
    declared_width: Optional[int] = None
    details: Dict[str, Any] = _dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.type_name).strip():
            raise ValueError(
                "EnumRouting.type_name is required: a routing decision "
                "about an unnamed type cannot be reviewed (#507)")
        if not str(self.reason).strip():
            raise ValueError(
                f"routing decision for {self.type_name!r} states no "
                f"reason. A destination of None with no reason is the "
                f"silence #507 exists to remove — say why, even when the "
                f"answer is that no layer consumes this shape.")
        if not str(self.rule).strip():
            raise ValueError(
                f"routing decision for {self.type_name!r} names no rule")

    @property
    def is_routed(self) -> bool:
        return bool(self.destination)

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type_name": self.type_name,
            "source_file": self.source_file,
            "destination": self.destination,
            "role": self.role,
            "rule": self.rule,
            "reason": self.reason,
            "member_count": int(self.member_count),
            "binding_count": int(self.binding_count),
            "declared_width": self.declared_width,
        }
        if self.details:
            d["details"] = self.details
        return d


RULE_TYPE_NAME_VOCABULARY = "type_name_vocabulary"
RULE_ADDRESS_MAP_SHAPE = "address_map_shape_v1_7_74"
RULE_NO_DESTINATION = "no_destination"


def route_enum(enum: Dict[str, Any]) -> EnumRouting:
    """The decision for ONE harvested enum. Never returns ``None``."""
    type_name = str((enum or {}).get("type_name") or "").strip()
    if not type_name:
        raise ValueError("route_enum requires a harvested enum record "
                         "carrying a type_name")
    members = (enum or {}).get("members") or []
    bindings = value_bindings(enum)
    common = {
        "type_name": type_name,
        "source_file": str((enum or {}).get("source_file") or ""),
        "member_count": len(members),
        "binding_count": len(bindings),
        "declared_width": (enum or {}).get("declared_width"),
    }
    # Tier 1 — the type name's own vocabulary. First, so the two types
    # the name already routed keep their destination and their stamp.
    role = (enum or {}).get("enum_role")
    if role in _ROLE_DESTINATION:
        return EnumRouting(
            destination=_ROLE_DESTINATION[role],
            role=role,
            rule=RULE_TYPE_NAME_VOCABULARY,
            reason=(f"the type name declares a {role} type "
                    f"(segments {type_name_segments(type_name)})"),
            **common)
    # Tier 2 — the member set's shape.
    is_map, why = address_map_verdict(enum)
    if is_map:
        return EnumRouting(
            destination=DEST_L4_REGISTERS,
            role=ROLE_ADDRESS_MAP,
            rule=RULE_ADDRESS_MAP_SHAPE,
            reason=why,
            **common)
    return EnumRouting(
        destination=None,
        role=None,
        rule=RULE_NO_DESTINATION,
        reason=(f"the type name declares no role and the member set is "
                f"not an address map: {why}"),
        **common)


def routing_inventory(extracted: Dict[str, str]) -> List[EnumRouting]:
    """One decision per ``typedef enum`` in the staged HDL inputs."""
    return [route_enum(e) for e in harvest_enums(extracted)]


def routing_summary(inventory: List[EnumRouting]) -> Dict[str, Any]:
    """Machine-readable inventory: every decision, grouped by destination."""
    by_dest: Dict[str, int] = {}
    for r in inventory:
        key = r.destination or "(no destination)"
        by_dest[key] = by_dest.get(key, 0) + 1
    return {
        "typedef_enums": len(inventory),
        "routed": sum(1 for r in inventory if r.is_routed),
        "undecided": 0,
        "by_destination": by_dest,
        "decisions": [r.as_dict() for r in inventory],
    }


def address_map_enums(extracted: Dict[str, str]) -> List[Dict[str, Any]]:
    """Harvested enums whose decision sends them to ``L4.registers``.

    Each record is the harvested enum with a ``routing`` key attached, so
    a consumer emitting into L4 carries the reason with the data.
    """
    out: List[Dict[str, Any]] = []
    for enum in harvest_enums(extracted):
        decision = route_enum(enum)
        if decision.destination != DEST_L4_REGISTERS:
            continue
        rec = dict(enum)
        rec["routing"] = decision.as_dict()
        rec["bindings"] = value_bindings(enum)
        out.append(rec)
    return out
