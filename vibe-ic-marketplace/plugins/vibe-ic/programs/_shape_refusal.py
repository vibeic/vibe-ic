#!/usr/bin/env python3
"""_shape_refusal.py — the ONE definition of "this field is PRESENT and is NOT
the shape this consumer reads", and of the refusal that NAMES WHAT ARRIVED.

WHY THIS MODULE EXISTS  (vibe-ic#991)
=====================================
The shape it exists to remove is one line:

    x if isinstance(x, list) else []

On data that arrived from OUTSIDE the program it maps EVERY unexpected shape
onto the empty list — and the empty list is exactly what an input with nothing
to declare produces. A downstream count or verdict then reads that zero as
"nothing to report" rather than "I could not read this", and the two states
share one output.

MEASURED, not asserted. Four sites in this tree produced BYTE-IDENTICAL output
for a field that was ABSENT and for the same field carrying real content in an
unreadable shape:

  l14_protocol_versioning_contract_check  `[PASS]` rc 0 for both, same report
  l17_channel_catalog_consumer_contract   `pass: true`, `channels_declared: 0`
  analog_sigma_delta_gain_floor_check     a real `FAIL` rc 1 became `[SKIP]` rc 0
  ip_catalog_query                        a declared dependency silently dropped

WHAT A REFUSAL OWES THE READER
==============================
"No `versions` list" sends a reader nowhere. "`versions` is a JSON object
carrying 2 key(s): ['gen-a', 'gen-b']" sends them to where the content actually
is. So every description here names, in this order:

  * the FIELD, by the name the input uses;
  * the JSON TYPE that arrived, in the words a reader of the file would use;
  * WHAT IS IN IT — an object's keys, a string's length and head, a scalar's
    value — because that is the sentence that tells someone whether the content
    is present-and-misfiled or genuinely absent;
  * how many entries were consequently NOT examined, so no count downstream can
    read as a denominator it never had.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
=========================================
It does NOT teach any consumer a second accepted schema. The defect is the
handling of an unexpected shape, not the shape: a consumer taught to also read
the object form would make the NEXT unexpected shape silent again, one level
further in. It classifies and it describes; the caller decides the verdict,
because the right verdict differs per gate and only the gate knows its own
exit-code contract.

ABSENT IS NOT MALFORMED, AND NEITHER IS A DECLARED EMPTY LIST OR AN EXPLICIT
NULL. `read_list` returns NO mismatch for a key that is not there, none for
`[]`, and none for `null` — all three are ways of saying "there is nothing
here", and in this repo's own corpus they are the common case (122 of 197
shipped L14 docs declare `EXTRACTION_FOUND_NOTHING` with empty rows). A module
that refused those would replace a silent pass with a wall of false findings,
which is how the four-gate blanket refusal recorded in
`gate_zero_denominator_refuses_check` flipped 182/159/94/42 of 182 tracked run
dirs and had to be reverted.

`null` IS THE ONE JUDGEMENT CALL HERE, and it is stated rather than buried: a
producer that writes `"versions": null` is declaring emptiness, not handing
over content in the wrong container, so there is nothing for a reader to go and
find. Every call site this module currently serves previously coerced falsy
values to `[]` anyway, so treating `null` as absent also keeps every published
artefact in this tree byte-identical — MEASURED across the L14 (197), L17 (107)
and analog spec (6) corpora, in which the count of explicit nulls in a consumed
list field is ZERO.

chip-AGNOSTIC: pure JSON-shape description. No design, PDK, vendor, SKU or
process token appears here, and none can — nothing in this file reads a value's
CONTENT except to quote a bounded prefix back to the reader.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "json_type_name", "describe", "read_list", "read_list_from",
    "sentence", "not_examined",
]

# What a reader of the file would call each type — the words the INPUT format
# uses, not Python's. A reader looking at JSON is not helped by "dict".
_JSON_TYPE_NAMES = {
    dict: "object", list: "array", str: "string", bool: "boolean",
    int: "number", float: "number", type(None): "null",
}

#: How much of a stringly-typed field to quote back. Long enough to recognise
#: the content, short enough that a refusal stays one readable line.
_STR_HEAD = 60
#: How many object keys to name before eliding. Naming them is the whole point
#: of the refusal, so this is generous; the elision only guards a pathological
#: input from producing an unreadable finding.
_MAX_KEYS = 24


def json_type_name(value: Any) -> str:
    """What a reader of the input file would call this value's type."""
    # bool before int: `isinstance(True, int)` is True and "number" would be a
    # wrong sentence about a boolean.
    if isinstance(value, bool):
        return "boolean"
    return _JSON_TYPE_NAMES.get(type(value), type(value).__name__)


def _content_phrase(value: Any) -> str:
    """WHAT IS IN IT — the half of the refusal that sends a reader somewhere.

    An object names its keys; a string states its length and quotes its head; a
    scalar states its value. Never "it is not a list", which is what the caller
    already knew.
    """
    if isinstance(value, dict):
        keys = [str(k) for k in value]
        shown = keys[:_MAX_KEYS]
        more = f" (+{len(keys) - len(shown)} more)" if len(keys) > len(shown) \
            else ""
        if not keys:
            return "an object with no keys"
        return (f"an object carrying {len(keys)} key(s): "
                f"{sorted(shown)}{more}")
    if isinstance(value, str):
        head = value[:_STR_HEAD]
        tail = "…" if len(value) > _STR_HEAD else ""
        return f"a {len(value)}-character string beginning {head + tail!r}"
    if isinstance(value, bool):
        return f"the boolean {str(value).lower()}"
    if value is None:
        return "JSON null"
    if isinstance(value, (int, float)):
        return f"the number {value}"
    return f"a {type(value).__name__}"


def _entries_not_examined(value: Any) -> Optional[int]:
    """How many entries the coercion would have discarded, when that number is
    knowable. `None` when the value has no meaningful entry count, so a caller
    can say "unknown" rather than print a zero it did not measure."""
    if isinstance(value, (dict, str, tuple, set)):
        return len(value)
    return None


def describe(value: Any, field: str, expected: str = "array") -> Dict[str, Any]:
    """A STATED description of a value that is not the shape a consumer reads.

    Returns a plain dict so it can be embedded verbatim in a JSON report; the
    prose form is `sentence()`.
    """
    n = _entries_not_examined(value)
    return {
        "field": field,
        "expected": expected,
        "json_type": json_type_name(value),
        "content": _content_phrase(value),
        "keys": (sorted(str(k) for k in value)[:_MAX_KEYS]
                 if isinstance(value, dict) else []),
        "entries_not_examined": n,
    }


def read_list(value: Any, field: str, present: bool = True
              ) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    """`(items, mismatch)` for a field a consumer wants to read as a list.

    `mismatch` is ``None`` when the field is ABSENT (``present=False``) or is
    already a list — INCLUDING the empty list. Those are real zeros and this
    module never manufactures a finding out of one. Otherwise `mismatch` is the
    `describe()` record, and `items` is empty so a caller that ignores the
    second value behaves exactly as it did before this module existed.
    """
    if not present or value is None:
        return [], None
    if isinstance(value, list):
        return value, None
    return [], describe(value, field)


def read_list_from(container: Any, key: str, field: Optional[str] = None
                   ) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    """`read_list` for the common `container[key]` case, with ABSENT decided by
    membership rather than by a falsy value.

    A container that is not an object yields no mismatch: THAT is the caller's
    own outer shape problem and reporting it here would name the wrong field.
    """
    name = field or key
    if not isinstance(container, dict) or key not in container:
        return [], None
    return read_list(container[key], name)


def sentence(mismatch: Dict[str, Any], where: str = "") -> str:
    """The refusal, in one sentence that names what arrived.

    `where` is an optional location a reader can open — a file name, a document
    label, an index. Stated when given; never invented.
    """
    at = f" in {where}" if where else ""
    n = mismatch.get("entries_not_examined")
    lost = (f" {n} entr{'y' if n == 1 else 'ies'} present in it "
            f"{'was' if n == 1 else 'were'} therefore NOT examined."
            if isinstance(n, int) and n > 0 else
            " Nothing in it was examined.")
    return (
        f"`{mismatch['field']}`{at} is PRESENT and is not the shape this "
        f"consumer reads: expected a JSON {mismatch['expected']}, found "
        f"{mismatch['content']}.{lost} This is a REFUSAL to read the field, "
        f"NOT a reading of zero — an absent `{mismatch['field']}` and this one "
        f"must not produce the same result. Remedy: emit `{mismatch['field']}` "
        f"as a JSON {mismatch['expected']}, or state that the producer no "
        f"longer emits it."
    )


def not_examined(mismatches: List[Dict[str, Any]]) -> Optional[int]:
    """Total entries discarded across several refusals, or ``None`` when any
    one of them is uncountable — so a denominator is never reported as a
    number that was partly guessed."""
    if not mismatches:
        return 0
    total = 0
    for m in mismatches:
        n = m.get("entries_not_examined")
        if not isinstance(n, int):
            return None
        total += n
    return total
