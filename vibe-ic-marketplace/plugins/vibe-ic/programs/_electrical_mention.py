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

# (a) A canonical electrical symbol, delimited on BOTH sides. The
#     trailing boundary is the whole point: without it every prefix
#     match ("Vol" in "Volume", "Vil" in "Village") is a symbol.
_SYMBOL = (
    r"\b(?:VDD|VDDA|VSS|VSSA|VDDIO|IDD|IDDQ|VTH|VOH|VOL|VIH|VIL|VBG|VREF)\b"
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

ELECTRICAL_MENTION_RE = re.compile(
    _SYMBOL + "|" + _QUANTITY + "|" + _MINTYPMAX,
    re.IGNORECASE,
)


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
        m = ELECTRICAL_MENTION_RE.search(line)
        if m is None:
            continue
        out.append((i, m.group(0)))
        if len(out) >= limit:
            break
    return out


def has_electrical_mention(text: str) -> bool:
    """True iff `text` mentions at least one electrical quantity."""
    return bool(scan_electrical_mentions(text, limit=1))
