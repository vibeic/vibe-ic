"""Finite physical-checklist syntax shared by L5 discovery and its consumer.

This classifies an occurrence, never an entire document. A checklist is
still a physical verification obligation; it does not request a new ESD
circuit in L5. Ambiguous mentions and actual protection circuits stay visible.
"""
from __future__ import annotations

import re

_LABEL = r"\b(?:DRC|LVS|ERC|IR|EM|ESD)\b"
_LIST = re.compile(_LABEL + r"(?:\s*(?:/|,|&|\band\b)\s*" + _LABEL + r"){2,}", re.I)
_PURPOSE = re.compile(
    r"\b(?:verif(?:y|ies|ied|ication)|sign[ -]?off|checks?|"
    r"pending|unmeasured|obligations?)\b", re.I)
_CIRCUIT_CONTEXT = re.compile(
    r"\b(?:protection|clamp|diode|circuits?|blocks?|devices?|networks?|cells?|"
    r"on[ -](?:chip|die)|integrat(?:e|es|ed|ing)|implement(?:s|ed|ing)?)\b", re.I)
_CLAUSE_BOUNDARY = re.compile(
    r"\n[ \t]*\n|\n[ \t]*#{1,6}\s|[!?;]|(?<!\d)\.|\.(?!\d)")


def is_physical_esd_check(text: str, start: int, end: int) -> bool:
    """True only for literal ESD inside a three-label physical check list.

    Require three distinct check labels and a verification purpose within
    the same sentence/clause. No header or neighboring sentence can suppress
    a real ESD declaration. Qualifying circuit words keep the occurrence.
    """
    if text[start:end].casefold() != "esd":
        return False
    # A soft wrap and a decimal point do not terminate a sentence. Blank
    # paragraphs, headings and actual sentence/clause punctuation do.
    boundaries = list(_CLAUSE_BOUNDARY.finditer(text))
    left = max((m.end() for m in boundaries if m.end() <= start), default=0)
    right = min((m.start() for m in boundaries if m.start() >= end), default=len(text))
    clause = text[left:right]
    # Retain the original keyword policy whenever circuit context makes the
    # list ambiguous. This conservative exclusion is clause-wide: adjective
    # placement or a preceding network noun cannot silently erase a circuit.
    if _CIRCUIT_CONTEXT.search(clause):
        return False
    if not _PURPOSE.search(clause):
        return False
    for match in _LIST.finditer(clause):
        if left + match.start() <= start and end <= left + match.end():
            labels = {m.group().upper() for m in re.finditer(_LABEL, match.group(), re.I)}
            return len(labels) >= 3
    return False
