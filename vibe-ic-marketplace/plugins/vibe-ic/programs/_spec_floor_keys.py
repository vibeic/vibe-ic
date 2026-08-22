"""_spec_floor_keys.py — ONE source of truth for the L-doc key names that the
class-template ``spec_floor:`` rules read.  (re #495, "Stage 0")

WHY THIS MODULE EXISTS
----------------------
A ``spec_floor:`` rule is a two-sided contract: the class template names a
minimum, and a gate reads a key out of the generated L-doc to measure against
it.  Nothing in the repo tied the READ side to the WRITE side, so the two
drifted: several floors read a key spelling that **no producer in the tree has
ever written**, which makes the rule measure the schema instead of the design.
Corpus census over the 201 tracked doc-sets (every directory carrying an
``L1_DATASHEET.json``) at the time this module landed:

    floor rule                     key the gate read   corpus  key the producer writes
    L11_calibration_tables_min     L11.tables            0/201  L11.calibration_tables
    L12_sequences_min              L12.sequences        11/201  L12.behavioral_sequences (22/201)
    L9_top_level_port_count_min    L9.ports (legacy)    31/201  L9.top_ports  (CANONICAL per #490)
    L3_crc_poly_allowed            L3.crc.poly           0/201  L3.crc.poly_hex (14/201),
                                                                L3.crc_parameters.polynomial_hex (11/201)

Each of those is a pure SPELLING mismatch — the producer emits the same concept
under another name.  Collecting the accepted spellings here means the next
producer rename has exactly one place to be reflected, instead of N gates
silently going blind one at a time.

ORDERING RULE (why this repair provably cannot regress)
-------------------------------------------------------
Every tuple below preserves the INCUMBENT key order of the gate that used it,
verbatim, and APPENDS the newly-recognised producer spellings.  Selection is
FIRST-NON-EMPTY — never "longest", never a union.  Consequences:

  * a doc-set whose incumbent key already carries content is read exactly as
    before (same key, same count) — appending an alias cannot change it;
  * a doc-set whose incumbent key is absent or empty, and which carries the
    producer key, goes from a hard 0 to its real count;
  * no count can be inflated by summing spellings of the same list, and no
    alias can be used to pick the largest of several mirrored lists.

The "non-empty" part is load-bearing rather than cosmetic: the incumbent
readers returned on the first key merely PRESENT, so an empty ``ports: []``
would shadow a populated ``top_ports`` and defeat the whole repair.

chip-AGNOSTIC: these are schema key spellings, not vendor / SKU / IC names.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

__all__ = [
    "L3_CRC_CONTAINER_KEYS",
    "L3_CRC_POLY_FIELD_KEYS",
    "L9_TOP_PORT_NESTED_PARENT_KEYS",
    "L9_TOP_PORT_NESTED_SUB_KEYS",
    "L9_TOP_PORT_ROOT_KEYS",
    "L11_CALIBRATION_TABLE_KEYS",
    "L12_SEQUENCE_KEYS",
    "first_nonempty",
    "first_crc_poly",
]


# --- L3: CRC polynomial ------------------------------------------------------
# Incumbent containers: crc / crc8 / crc_config.  Appended: crc_parameters,
# which the doc-extraction producers emit for framed protocols.
L3_CRC_CONTAINER_KEYS: Tuple[str, ...] = (
    "crc", "crc8", "crc_config", "crc_parameters",
)
# Incumbent fields: poly / polynomial.  Appended: the *_hex spellings the
# producers actually write (``poly_hex`` inside ``crc``; ``polynomial_hex``
# inside ``crc_parameters``).
L3_CRC_POLY_FIELD_KEYS: Tuple[str, ...] = (
    "poly", "polynomial", "poly_hex", "polynomial_hex",
)

# --- L9: top-level port list -------------------------------------------------
# Nested orchestrator locations, unchanged.
L9_TOP_PORT_NESTED_PARENT_KEYS: Tuple[str, ...] = (
    "dtop_top_level", "dtop", "top_level",
)
L9_TOP_PORT_NESTED_SUB_KEYS: Tuple[str, ...] = ("ports", "top_level_ports")
# Root-level keys.  Incumbent: top_level_ports / ports / dtop_ports.
# Appended: top_ports (the CANONICAL spelling per #490 — the emitter writes
# ``ports`` / ``top_ports`` / ``top_module_pins`` as mirrors of one list, and
# every other consumer in the tree reads ``top_ports`` first) and the
# ``top_module_pins`` mirror.
L9_TOP_PORT_ROOT_KEYS: Tuple[str, ...] = (
    "top_level_ports", "ports", "dtop_ports", "top_ports", "top_module_pins",
)

# --- L11: calibration tables -------------------------------------------------
# Incumbent: tables (never written into L11 by any producer — the protocol
# synths write ``tables`` into L15, a different layer).  Appended:
# calibration_tables, which the L11 emitter writes.
L11_CALIBRATION_TABLE_KEYS: Tuple[str, ...] = ("tables", "calibration_tables")

# --- L12: behavioural sequences ----------------------------------------------
# Incumbent: sequences (written by a handful of protocol synths).  Appended:
# behavioral_sequences, which the mainline L12 emitter writes and which is
# also the doc's own ``doc_class``.
L12_SEQUENCE_KEYS: Tuple[str, ...] = ("sequences", "behavioral_sequences")


def first_nonempty(
    doc: Optional[Dict[str, Any]],
    keys: Sequence[str],
    kinds: Iterable[type] = (list, dict),
) -> Tuple[Optional[str], Any]:
    """Return ``(key, value)`` for the first key in ``keys`` whose value is a
    NON-EMPTY container of one of ``kinds``; ``(None, None)`` when none is.

    ``kinds`` lets a caller that can only consume one shape (L12 counts a list
    of sequence dicts) skip a differently-shaped value instead of letting it
    shadow a later alias that IS consumable.
    """
    if not isinstance(doc, dict):
        return None, None
    kinds = tuple(kinds)
    for k in keys:
        v = doc.get(k)
        if isinstance(v, kinds) and len(v) > 0:
            return k, v
    return None, None


def first_crc_poly(container: Optional[Dict[str, Any]]) -> Optional[str]:
    """First truthy CRC-polynomial field inside ``container``, lower-cased.

    ``None`` when the container is not a dict or carries no truthy polynomial
    under any accepted spelling (producers legitimately emit
    ``polynomial_hex: null`` when the source document did not state one).
    """
    if not isinstance(container, dict):
        return None
    for f in L3_CRC_POLY_FIELD_KEYS:
        v = container.get(f)
        if v:
            return str(v).lower()
    return None
