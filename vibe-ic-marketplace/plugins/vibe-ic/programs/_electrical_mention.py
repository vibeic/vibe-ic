"""One definition of "this text mentions an electrical quantity".

Shared by the L1 emitter (`phase1_doc_one_shot_runner`) and the gate
(`l1_electrical_specs_typed_depth_check`) so the two can never drift.
That matters because the gate's job is to falsify the emitter's claim
`no_electrical_specs_in_input`: if each side carried its own private
notion of "electrical mention", a disagreement would be a bug in the
comparison rather than a finding about the document.

THE RULE THIS MODULE ENFORCES
-----------------------------
    A unit or unit-like symbol counts only when it stands as its own
    token. A token that abuts prose is not a unit.

Both halves of that sentence were violated before this module existed,
and both violations produced confident, wrong output:

  * ``VOL`` matched inside the word "Volume", because the symbol
    alternation carried a leading ``\\b`` and no trailing one. Every
    citation of a multi-volume standard therefore read as an
    output-low-voltage specification.
  * ``2v`` matched inside the tool name "sv2v", and ``256.v`` inside
    the file name "sha256.v", because the quantity branch carried no
    left boundary. Any identifier ending in digits followed by a `v`
    read as a voltage.
  * ``\\b(?:Typ\\.|Min\\.|Max\\.)\\b`` could never match at all: ``\\b``
    after a literal ``.`` demands a word character next, which a
    sentence or a table cell never provides. The rule was dead, so the
    tabular Min/Typ/Max shape it was written for went undetected. It
    is repaired here as a CORROBORATED header rule (two of the three
    markers on one line) rather than a bare one, because "max." on its
    own is ordinary English prose ("max. bandwidth") and reviving it
    unqualified would have manufactured the same class of false
    positive it was meant to find.

Chip-AGNOSTIC: the vocabulary is the standard electrical-symbol and
SI-unit set. No vendor, SKU, design or document literal participates.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# (a) A canonical electrical PARAMETER symbol, delimited on BOTH sides.
#     The trailing boundary is the whole point: without it every prefix
#     match ("Vol" in "Volume", "Vil" in "Village") is a symbol.
#
#     The five SUPPLY-RAIL names are deliberately NOT in this class --
#     see (a2). A parameter symbol (IDD, VTH, VOH, ...) has no use
#     outside an electrical specification, so naming it IS mentioning
#     one. A rail name does: it is the ordinary identifier of a net and
#     a pin, and it appears in the connectivity/floorplan section of
#     every digital design that has never stated an electrical spec.
_SYMBOL = (
    r"\b(?:IDD|IDDQ|VTH|VOH|VOL|VIH|VIL|VBG|VREF)\b"
)

# (b) A quantity: a number immediately followed by a unit, where
#     NEITHER may run into a surrounding word. The left lookbehind
#     rejects the digits of an identifier ("sv2v", "sha256.v",
#     "v2.0"); the trailing \b rejects a unit that is really the first
#     letters of a longer word. At most one space may separate the
#     number from its unit -- a number and a unit at opposite ends of
#     an aligned table column are two different columns, not a
#     measurement ("0        UA" is a frame type, not 0 microamps).
_QUANTITY = (
    r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?[ \t]?(?:mV|V|mA|μA|uA|kΩ|Ω)\b"
)

# (c) A Min/Typ/Max table header. Corroborated: a second marker must
#     appear on the same line. One marker alone is prose.
_MINTYPMAX = (
    r"\b(?:Typ|Min|Max)\.(?![A-Za-z])"
    r"(?=[^\n]*\b(?:Typ|Min|Max)\.(?![A-Za-z]))"
)

# (a2) A SUPPLY-RAIL name -- CORROBORATED, exactly the discipline (c)
#     already applies to a lone Min./Typ./Max. marker.
#
#     A rail name ALONE is a net name, not a specification. The line
#
#         | 電源 | `VDD` / `VSS`(NangateOpenCellLibrary 標準) |
#
#     names the two rails of a standard-cell library in a floorplan
#     table. Read as an electrical-spec mention it made the L1 emitter
#     publish `no_electrical_specs_in_input: false` beside
#     `electrical_specs: []` -- "the input HAS electrical specs and I
#     did not type them" about a document that states none. The Tier-2
#     substance gate then counted the empty list as scaffolding.
#
#     A rail name WITH a value is a specification, so the rail counts
#     when its own line also carries a quantity or a Min/Typ/Max header
#     ("VDD 1.8 V", "| VDD | 1.62 | 1.80 | 1.98 | V |"). The lookahead
#     only needs to search RIGHTWARD: when the value precedes the rail
#     ("1.8 V supply on VDD") the (b) quantity branch already matches
#     that same line on its own, and detection here is per-line.
#     The corroborators are the (b) quantity, the (c) Min/Typ/Max
#     header, and a UNIT STANDING ALONE IN ITS OWN TABLE CELL. The
#     third is needed because the canonical supply row puts the unit in
#     a column of its own --
#
#         | VDD | 1.62 | 1.80 | 1.98 | V | core supply |
#
#     -- which (b) deliberately does NOT match (its own comment: a
#     number and a unit at opposite ends of an aligned table column are
#     two different columns). Without this third corroborator the fix
#     would lose the most common electrical-spec shape there is.
#
#     A bare number is deliberately NOT a corroborator: "VDD strap on
#     metal4" and "VDD pitch 2.5um" are floorplan facts, and admitting
#     any digit would re-open the same false-positive door from the
#     other side.
_UNIT_CELL = r"\|\s*(?:mV|V|mA|μA|uA|kΩ|Ω)\s*(?:\||$)"

_RAIL = (
    r"\b(?:VDD|VDDA|VSS|VSSA|VDDIO)\b"
    r"(?=[^\n]*(?:" + _QUANTITY + r"|" + _MINTYPMAX + r"|" + _UNIT_CELL + r"))"
)

ELECTRICAL_MENTION_RE = re.compile(
    _SYMBOL + "|" + _RAIL + "|" + _QUANTITY + "|" + _MINTYPMAX,
    re.IGNORECASE,
)

# (a3) The UNCORROBORATED rail, and the one place it still counts.
#
#     The corroboration in (a2) is scoped to a TABLE ROW, and only to a
#     table row. A table row is a STRUCTURED RECORD: a row whose cells
#     are bare identifiers is a connectivity / pin / floorplan record,
#     and the rail is there as the name of a net. PROSE that names a
#     rail is making a statement ABOUT it -- "VDD must be stable before
#     the reset is released" is a power-sequencing requirement, and
#     v1.7.80 (#514) already fixed it as one. Narrowing to table rows
#     keeps that behaviour byte-for-byte and changes only the record
#     shape where the defect was measured.
_RAIL_UNCORROBORATED_RE = re.compile(
    r"\b(?:VDD|VDDA|VSS|VSSA|VDDIO)\b", re.IGNORECASE)

_TABLE_ROW_RE = re.compile(r"[ \t]*\|")


def search_line(line: str):
    """The per-line decision, shared by BOTH consumers.

    The emitter and the gate must reach the same answer on the same line
    (that is why this module exists), so the table-row scoping lives here
    rather than in either caller. Returns a match object or ``None``.
    """
    if not isinstance(line, str) or not line:
        return None
    m = ELECTRICAL_MENTION_RE.search(line)
    if m is not None:
        return m
    if _TABLE_ROW_RE.match(line):
        return None          # a bare rail name in a structured record
    return _RAIL_UNCORROBORATED_RE.search(line)


def scan_electrical_mentions(text: str,
                             limit: int = 50) -> List[Tuple[int, str]]:
    """Return ``[(line_number, matched_literal), ...]`` for `text`.

    Line numbers are 1-based so a caller can cite ``<file>:<line>``.
    At most one hit per line is reported (a line either mentions an
    electrical quantity or it does not); at most `limit` hits overall
    so a large document cannot dominate a report.
    """
    out: List[Tuple[int, str]] = []
    if not isinstance(text, str) or not text:
        return out
    for i, line in enumerate(text.splitlines(), start=1):
        m = search_line(line)
        if m is None:
            continue
        out.append((i, m.group(0)))
        if len(out) >= limit:
            break
    return out


def has_electrical_mention(text: str) -> bool:
    """True iff `text` mentions at least one electrical quantity."""
    return bool(scan_electrical_mentions(text, limit=1))
