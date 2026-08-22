"""What a protocol pack may write into ``L9.top_module``.

A protocol pack encodes one reference document. It knows that document's
part name; it does not know the design in front of it. Every pack that
writes ``L9.top_module`` today writes a literal lifted from its reference
document — ``SPI``, ``PC16550D``, ``HBM3_stack_on_interposer``,
``DDR3_SDRAM_component``, ``AHCI_HBA`` — and it writes it unconditionally.
Measured on the source: 15 packs assign ``d["top_module"] = <literal>``,
2 more route the same assignment through a ``_force`` helper, and 0 use
``setdefault``.

``L9.top_module`` is not a description. ``phase2_scaffold_gen.
derive_top_module_name`` ranks it ABOVE ``L1.ic_name`` and sanitizes the
winner into the design's Verilog top-module identifier, so whatever a pack
puts here becomes the name the RTL, the QSF, and the full-stack testbench
all bind to. A pack literal in this field is the pack naming somebody
else's chip.

WHAT WAS MEASURED
-----------------
Two separate failures, both visible in artefacts committed to this repo.

1. FOREIGN CLAIM. Packs co-fire. A Bluetooth document mentions start bits
   and stop bits, so the UART detector fires alongside the BLE detector;
   the BLE pack has no ``top_module`` write and the UART pack does, so the
   Bluetooth design's top module is ``PC16550D``. Same shape for
   ``io_link`` (``PC16550D``), ``ddr4`` (``DDR3_SDRAM_component``),
   ``ddr5`` and ``gddr6`` (``HBM3_stack_on_interposer``), ``qspi_ospi``
   (``SPI``), ``sas`` (``AHCI_HBA``). In each of those the design's own
   settled ``ic_name`` names a DIFFERENT protocol than the top module does.

2. FALSE PROVENANCE. ``L9.top_module_extraction_strategy`` exists to
   record where the name came from — ``rtl_filesystem_scan`` and friends
   when the design's own input declared it, ``l1_ic_name_fallback`` when
   it was derived from ``L1.ic_name``, ``canonical_chip_top_sentinel``
   when nothing was found at all. Phase 1 stamps it before any pack runs
   and no pack updates it. 31 committed L9 documents therefore carry a
   pack literal while their own provenance field claims the name was
   derived from ``L1.ic_name`` (or that no name was found and ``chip_top``
   was defaulted). The field is not merely unhelpful there; it is wrong,
   and it is wrong in the direction that makes the value look extracted.

THE TWO RULES
-------------
R1  A pack does not overwrite a top module the DESIGN'S OWN input named.
    "Named by the input" is not a new notion invented here — phase 1
    already distinguishes it, in ``top_module_extraction_strategy``, and
    ``DESIGN_OWNED_STRATEGIES`` below is exactly that set. When the
    strategy on disk is one of those, the pack's literal is recorded in
    the descriptive field and ``top_module`` is left alone.

R2  A pack that DOES write the field says so. ``top_module_extraction_
    strategy`` becomes ``protocol_pack_reference_default`` and
    ``protocol_reference_top_module`` records the literal, the pack's own
    ``ic_name``, and the value that was displaced. An artefact then states
    what it is: a name a protocol pack supplied, not a name anybody read
    out of the design.

R2 is what makes the foreign claim REPAIRABLE. `reconcile` runs once at
the tail of the protocol-synth chain, after every pack has had its turn,
and compares the ``ic_name`` recorded WITH the claim against the design's
settled ``ic_name``. Equal means the pack that named the design also named
its top module — that claim stands. Different means a pack that lost the
identity contest still won the identifier, and the displaced value is put
back, along with the provenance it had. The mirror of
``l4_register_map_claim.reconcile_register_map_claims``: whichever overlay
stamped the claim, the published document still has to agree with itself.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
``L9.top_module`` is never removed and never emptied.
``l_doc_structured_field_count_check`` counts a non-empty ``top_module``
as one of the >=3 typed structural fields L9 must carry, so deleting the
key — the obvious-looking way to stop a pack naming the design — turns a
passing L9 into a failing one. The field stays; only what goes into it,
and what the document says about where it came from, changes.

chip-AGNOSTIC: every decision reads the document's own keys. No chip,
vendor, PDK, or benchmark literal participates.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

__all__ = [
    "PACK_DEFAULT_STRATEGY",
    "DESIGN_OWNED_STRATEGIES",
    "REFERENCE_FIELD",
    "apply",
    "decide",
    "reconcile",
]

#: Stamped into ``top_module_extraction_strategy`` by `apply` whenever a
#: pack's reference literal actually lands in ``top_module``.
PACK_DEFAULT_STRATEGY = "protocol_pack_reference_default"

#: The descriptive field. Nothing derives an identifier from it — that is
#: the point of it existing.
REFERENCE_FIELD = "protocol_reference_top_module"

#: The provenance values phase 1 stamps when the DESIGN'S OWN input named
#: the top module: an actual ``module <name>`` declaration found by
#: scanning staged RTL, a declaration or heading in the design's docs, or
#: the top-cell / top-module prose walkers. Every other value phase 1 can
#: stamp (``l1_ic_name_fallback``, ``canonical_chip_top_sentinel``) is by
#: its own docstring a last resort that fires precisely BECAUSE no such
#: declaration was found.
DESIGN_OWNED_STRATEGIES = frozenset({
    "rtl_filesystem_scan",
    "staged_rtl_structural_top",
    "doc_module_decl_or_heading",
    "rtl_top_prose_v1_6_545",
    "doc_prose_top_cell_v1_6_398",
    "doc_prose_top_module_v1_6_409",
})


def _clean(v: Any) -> Optional[str]:
    """The string a field carries, or None for anything unusable."""
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def decide(l9: Dict[str, Any], pack_default: str) -> Tuple[bool, str]:
    """Should this pack's literal become the design's top module?

    Returns ``(write, why)``. Pure — takes and mutates nothing — so the
    decision can be tested without a filesystem and so a caller that wants
    only the reason can ask for it.
    """
    if not isinstance(l9, dict):
        return False, "l9_not_a_mapping"
    if _clean(pack_default) is None:
        return False, "pack_default_empty"
    strategy = _clean(l9.get("top_module_extraction_strategy")) or ""
    current = _clean(l9.get("top_module"))
    if current is not None and strategy in DESIGN_OWNED_STRATEGIES:
        # R1: the design's own input declared this. A reference document
        # does not get to rename it.
        return False, "design_named_its_own_top_module"
    return True, "no_design_declared_top_module"


def apply(l9: Dict[str, Any], pack_default: str,
          pack_ic_name: Optional[str] = None) -> Dict[str, Any]:
    """Record this pack's reference top-module name in ``l9``, in place.

    ``pack_ic_name`` defaults to the ``ic_name`` the document carries at
    call time. Every pack writes its own ``ic_name`` across the L docs
    before it reaches its L9 block, so that default IS this pack's
    ic_name; passing it explicitly is available but not required.

    Returns the record written to `REFERENCE_FIELD` (also useful for
    logging). Always leaves ``top_module`` non-empty when it was non-empty
    before, and never removes the key.
    """
    if not isinstance(l9, dict):
        return {}
    name = _clean(pack_default)
    if name is None:
        return {}
    if pack_ic_name is None:
        pack_ic_name = _clean(l9.get("ic_name"))

    write, why = decide(l9, name)
    record: Dict[str, Any] = {
        "name": name,
        "pack_ic_name": pack_ic_name,
        "applied_to_top_module": bool(write),
        "why": why,
    }
    if write:
        displaced = _clean(l9.get("top_module"))
        displaced_strategy = _clean(
            l9.get("top_module_extraction_strategy"))
        if displaced is not None:
            record["displaced"] = displaced
        if displaced_strategy is not None:
            record["displaced_strategy"] = displaced_strategy
        l9["top_module"] = name
        # R2: the document now says where the name came from. Without
        # this the artefact keeps asserting the pre-pack provenance,
        # which is the false-certificate shape, and `reconcile` below
        # would have nothing to key on.
        l9["top_module_extraction_strategy"] = PACK_DEFAULT_STRATEGY
    l9[REFERENCE_FIELD] = record
    return record


def reconcile(l9: Dict[str, Any],
              settled_ic_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Put back a top module a FOREIGN pack took, at the tail of the chain.

    Runs after every pack. Does nothing unless `apply` actually wrote the
    field (``top_module_extraction_strategy == PACK_DEFAULT_STRATEGY``) —
    a design-declared or phase-1-derived name is not this function's
    business.

    The test is one comparison: does the ``ic_name`` recorded WITH the
    claim still equal the design's settled ``ic_name``? Equal means the
    pack that named the design also named its top module, and the two
    agree. Different means some other pack co-fired, lost the identity
    contest, and kept the identifier anyway — a Bluetooth design named
    ``PC16550D``. In that case the displaced value and the provenance it
    carried are restored.

    ``settled_ic_name`` defaults to ``l9["ic_name"]`` — the value left
    standing after the whole chain ran. A caller with access to L1 should
    pass ``L1.ic_name``, which is the same value by construction and is
    where `phase2_scaffold_gen.derive_top_module_name` looks next.

    Returns the change made, or None when nothing needed changing.
    """
    if not isinstance(l9, dict):
        return None
    strategy = _clean(l9.get("top_module_extraction_strategy"))
    if strategy != PACK_DEFAULT_STRATEGY:
        return None
    record = l9.get(REFERENCE_FIELD)
    if not isinstance(record, dict):
        return None
    if settled_ic_name is None:
        settled_ic_name = _clean(l9.get("ic_name"))
    else:
        settled_ic_name = _clean(settled_ic_name)
    claim_ic_name = _clean(record.get("pack_ic_name"))
    if claim_ic_name is None or settled_ic_name is None:
        # Nothing to compare. Leaving the pack name in place with its
        # honest `protocol_pack_reference_default` stamp is the weaker
        # but truthful outcome; inventing a replacement is not.
        return None
    if claim_ic_name == settled_ic_name:
        return None

    displaced = _clean(record.get("displaced"))
    displaced_strategy = _clean(record.get("displaced_strategy"))
    if displaced is None:
        # The pack's literal is all this document ever had in the field,
        # and `l_doc_structured_field_count_check` counts a non-empty
        # `top_module` toward L9's >=3 typed fields. Removing it to
        # register a complaint would cost the layer a gate. Record the
        # foreign claim and leave the value.
        record["foreign_claim"] = True
        record["settled_ic_name"] = settled_ic_name
        l9[REFERENCE_FIELD] = record
        return {
            "action": "flagged_foreign_claim_no_displaced_value",
            "top_module": _clean(l9.get("top_module")),
            "pack_ic_name": claim_ic_name,
            "settled_ic_name": settled_ic_name,
        }

    l9["top_module"] = displaced
    if displaced_strategy is not None:
        l9["top_module_extraction_strategy"] = displaced_strategy
    else:
        l9.pop("top_module_extraction_strategy", None)
    record["applied_to_top_module"] = False
    record["foreign_claim"] = True
    record["settled_ic_name"] = settled_ic_name
    record["reverted_to"] = displaced
    l9[REFERENCE_FIELD] = record
    return {
        "action": "reverted_foreign_pack_claim",
        "top_module": displaced,
        "was": _clean(record.get("name")),
        "pack_ic_name": claim_ic_name,
        "settled_ic_name": settled_ic_name,
    }
