"""The one chokepoint through which a protocol pack may offer a top-module name.

WHY THIS MODULE EXISTS (vibe-ic#831)
------------------------------------
A protocol pack knows what a *reference implementation* of its protocol is
called.  It does not know what *this* design is called.  Before this module,
20 packs wrote ``L9.top_module`` unconditionally, and
``phase2_scaffold_gen.derive_top_module_name`` ranks ``L9.top_module`` ABOVE
``L1.ic_name`` — so any design that merely tripped a protocol detector was
silently renamed to that protocol's reference part, and the replacement is a
valid Verilog identifier, so nothing downstream could tell.

Measured over the 197 tracked ``L9_INTEGRATION_SPEC.json`` documents in this
repository at e3aa9b126: **42** carry a pack's reference name while
``L1.ic_name`` names a different design.  Seven of those are renamed across
protocol families outright:

    ble        Bluetooth Low Energy 5.2   -> PC16550D                 (a UART)
    io_link    IO-Link (IEC 61131-9)      -> PC16550D                 (a UART)
    sas        SAS_Controller             -> AHCI_HBA                 (SATA)
    ddr4       DDR4 SDRAM  JESD79-4       -> DDR3_SDRAM_component     (prev gen)
    ddr5       DDR5 SDRAM  JESD79-5       -> HBM3_stack_on_interposer
    gddr6      GDDR6 SGRAM JESD250        -> HBM3_stack_on_interposer
    qspi_ospi  Quad/Octal SPI JESD251     -> SPI

THE POLARITY (same as vibe-ic#812)
----------------------------------
Enrichment must FILL A GAP, never overwrite a value the input supplied.

The gap is not guessed here — Phase 1 already records where ``top_module``
came from, in the sibling key ``top_module_extraction_strategy``
(``phase1_doc_one_shot_runner``).  Every strategy that produced a name from
the DESIGN's own material — ``rtl_filesystem_scan``,
``staged_rtl_structural_top``, ``doc_module_decl_or_heading``,
``l1_ic_name_fallback`` — is design-supplied and wins.  Exactly one strategy
means "every extractor was exhausted and nothing in the design named a top":
``canonical_chip_top_sentinel``.  That, and only that, is the gap a pack may
fill.

FAIL-SAFE DIRECTION
-------------------
An unrecognised strategy — including a future one this module has never
heard of, and including a hand-authored L9 that records none at all — is
treated as DESIGN-SUPPLIED and the pack stands down.  The failure mode of
"pack declines to name a design it might have named correctly" is a visible,
recoverable one; the failure mode of "pack renames a design that named
itself" is the invisible one this module exists to stop.  A whitelist of
gap-strategies is therefore the only safe shape: an allowlist of names the
pack may overwrite, not a denylist of names it may not.

Chip-AGNOSTIC: no chip / SKU / vendor / benchmark literal participates in the
decision.  The reference name is a caller argument and is never inspected.
"""
from __future__ import annotations

import re
from typing import Any, Optional

__all__ = [
    "GAP_STRATEGIES",
    "PACK_STRATEGY",
    "is_bare_identifier",
    "merge_pack_payload",
    "offer_reference_top_module",
    "reference_top_module_is_authoritative",
]

# The ONLY provenance value that means "Phase 1 found nothing in the design
# that names a top module, and fell back to a structural placeholder".
# See phase1_doc_one_shot_runner: `top_module_extraction_strategy =
# "canonical_chip_top_sentinel"` is assigned in exactly one place, after
# every real extractor has been exhausted and `top_module is None`.
GAP_STRATEGIES = frozenset({"canonical_chip_top_sentinel"})

# Stamped by this module when a pack's reference name IS adopted, so the
# resulting document never claims a provenance that another program earned.
# Pre-#831 the pack overwrote the value and left the previous program's tag
# standing: 15 of the 42 renamed documents above are published carrying
# `top_module_extraction_strategy == "l1_ic_name_fallback"` next to a value
# that demonstrably did not come from `L1.ic_name` (the two disagree inside
# the same document pair).
PACK_STRATEGY = "protocol_pack_reference_design"


def _stated(v: Any) -> bool:
    """True when a document really states a value (not None / "" / blank)."""
    return isinstance(v, str) and bool(v.strip())


# A module name has to survive `phase2_scaffold_gen._sanitize_id` unchanged to
# be a name rather than a summary of one.  That mattered concretely: the
# RS-485 pack offered
#     "RS485_transceiver (external chip) + UART_with_DE/RE#_direction_control (on-chip)"
# and `derive_top_module_name` strips a trailing parenthesised suffix with a
# GREEDY `\s*\(.*\)\s*$`, which matches from the FIRST "(" to the LAST ")" —
# so the emitted identifier was `RS485_transceiver`, naming only the EXTERNAL
# chip and silently discarding the on-chip half the sentence exists to state.
# Prose is welcome under `reference_design`; it is not a top-module name.
_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_bare_identifier(name: Any) -> bool:
    """True when ``name`` is already a Verilog identifier, needing no repair.

    Deliberately NOT "can be coerced into one".  Coercion is what made the
    RS-485 truncation invisible: a mangled name and a real one are
    byte-identically valid Verilog once sanitised, so nothing downstream can
    tell them apart.
    """
    return _stated(name) and bool(_BARE_IDENTIFIER.match(name.strip()))


def reference_top_module_is_authoritative(l9: Any) -> bool:
    """Would a pack's reference name be adopted as ``top_module`` for this L9?

    Split out from the writer so a gate or a test can ask the question
    without mutating anything.
    """
    if not isinstance(l9, dict):
        return True
    if not _stated(l9.get("top_module")):
        # The document names no top module at all.  Nothing to overwrite,
        # and the alternative is `derive_top_module_name` falling to the
        # anonymous "dut" — so filling is strictly better AND lossless.
        return True
    strategy = l9.get("top_module_extraction_strategy")
    if not _stated(strategy):
        # A value with no recorded provenance.  Fail safe: treat as
        # design-supplied.  (Runner-produced L9s always record one; the
        # documents that do not are hand- or AI-authored, i.e. exactly the
        # inputs whose stated name most deserves to survive.)
        return False
    return strategy.strip() in GAP_STRATEGIES


def offer_reference_top_module(
    l9: dict,
    reference_name: str,
    *,
    reference_key: str = "reference_design",
) -> Optional[str]:
    """Offer a protocol's reference-implementation name to an L9 document.

    Always records ``reference_name`` under ``reference_key`` — the pack's
    knowledge is real and stays available as documentation.  Adopts it as
    ``top_module`` ONLY when BOTH (a) the design supplied no name of its own
    and (b) the reference name is already a bare Verilog identifier; stamps
    :data:`PACK_STRATEGY` when it does, so the value and its provenance can
    never disagree.

    Returns the adopted name, or ``None`` when the design's own name stood
    (or when the reference name is prose rather than an identifier).
    """
    if not isinstance(l9, dict):
        raise TypeError("offer_reference_top_module expects an L9 dict")
    if not _stated(reference_name):
        raise ValueError(
            "offer_reference_top_module: reference_name must be a non-empty "
            "string; a pack that has no reference design must not call this")

    name = reference_name.strip()
    # Documentation, unconditionally.  This is the descriptive key #831 asks
    # for: it carries the pack's real knowledge without being read as this
    # design's identity by any consumer of `top_module`.
    l9[reference_key] = name

    if not reference_top_module_is_authoritative(l9):
        return None
    if not is_bare_identifier(name):
        # Prose. It stays as documentation under `reference_key`; adopting it
        # would hand `derive_top_module_name` a sentence to truncate.
        return None

    l9["top_module"] = name
    l9["top_module_extraction_strategy"] = PACK_STRATEGY
    return name


def merge_pack_payload(doc: dict, payload: Any) -> Optional[str]:
    """``doc.update(payload)`` with ``top_module`` routed through the offer.

    The three packs that force-merge a whole canonical L-doc set (eSPI, MDIO,
    USB-PD) carry ``top_module`` as one key of a bulk template.  A plain
    ``dict.update`` makes that key authoritative for exactly the same reason
    a direct assignment did — so the bulk merge has to go through the same
    chokepoint, or the guard is only checking the spelling of the write.

    Returns whatever :func:`offer_reference_top_module` returned, or ``None``
    when the payload carried no ``top_module``.
    """
    if not isinstance(doc, dict):
        raise TypeError("merge_pack_payload expects a document dict")
    if not isinstance(payload, dict):
        return None
    rest = {k: v for k, v in payload.items() if k != "top_module"}
    doc.update(rest)
    ref = payload.get("top_module")
    if not _stated(ref):
        return None
    return offer_reference_top_module(doc, ref)
