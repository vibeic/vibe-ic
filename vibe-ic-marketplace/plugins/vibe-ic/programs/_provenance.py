"""ORGANIC #770 — shared provenance / confidence layer for the --strict gates.

50 of 57 false-positives across CVDP round5/6/7 share ONE meta-pattern: under
`--strict` (sole-emit hard-BLOCK) a gate hard-blocks correct, compilable,
spec-faithful RTL on a checklist-item / finding derived from a PROSE-HEURISTIC
(a free natural-language regex) — while the correct RTL either DIRECTLY
CONTRADICTS that item or has no such thing at all. Per-edge regex patches did
not converge (the catch count rose 7→12→16 each round) because every edge was a
different prose surface of the SAME error class.

The structural fix (this module) tags every BLOCK-eligible finding with a
DETERMINISTIC provenance and lets `--strict` block only on **trustworthy**
evidence:

    BLOCK-eligible  ⇔  provenance == STRUCTURAL
                       OR (provenance == PROSE_HEURISTIC AND corroborated_by_rtl)
    ADVISORY (WARN) ⇔  provenance == PROSE_HEURISTIC
                       AND (contradicted_by_rtl OR no_structural_corroboration)

A finding's author-supplied, compilable, spec-faithful RTL is STRONGER evidence
than a free-prose heuristic; a low-confidence prose guess must never veto correct
silicon. Non-`--strict` behaviour is UNCHANGED (those gaps were already WARN).

§4.05 no-leak boundary — the relaxation is STRICTLY limited to the set
`{ PROSE_HEURISTIC AND (contradicted_by_rtl OR no_structural_corroboration) }`.
EVERY structural negative (a port missing from a real markdown table / given-code
header; a measured latency/area mismatch; a register truly multi-driven across
two real always blocks; a real table-row / table-sourced enum-set the TB never
stimulates) is UNTOUCHED — it stays STRUCTURAL → BLOCK-eligible. The
corroboration test is itself deterministic and NO-LEAK BIASED: when evidence is
ambiguous it defaults to corroborated (preserve the block); it downgrades ONLY
when the RTL clearly contradicts the prose item or provably lacks the structure.

chip-AGNOSTIC: this module encodes the provenance VOCABULARY + the block-decision
rule. It contains no chip / vendor / SKU literal; the per-gate wiring supplies the
structural signals (RTL port set, measured facts, real-table membership).
"""
from __future__ import annotations

from typing import Optional

# ── provenance tags ─────────────────────────────────────────────────────────
STRUCTURAL = "STRUCTURAL"
PROSE_HEURISTIC = "PROSE_HEURISTIC"

# ── corroboration verdicts (for a PROSE_HEURISTIC finding vs the RTL) ─────────
CORROBORATED = "corroborated_by_rtl"        # RTL structurally confirms the item
CONTRADICTED = "contradicted_by_rtl"        # RTL structurally refutes the item
NO_CORROBORATION = "no_structural_corroboration"  # no structural backing at all
UNKNOWN = "unknown"                          # no RTL available to judge (ambiguous)


def is_block_eligible(provenance: str,
                      corroboration: Optional[str] = None) -> bool:
    """The single --strict block-decision rule (ORGANIC #770).

    A finding may HARD-BLOCK under sole-emit `--strict` iff it is STRUCTURAL, or
    it is PROSE_HEURISTIC but the RTL CORROBORATES it (or no RTL was available to
    judge — no-leak biased: an unjudgeable prose item keeps its historical
    blocking power rather than being silently waved through). A PROSE_HEURISTIC
    finding the RTL CONTRADICTS or provably does not back is ADVISORY only.

    chip-AGNOSTIC, pure decision function."""
    if provenance == STRUCTURAL:
        return True
    if provenance == PROSE_HEURISTIC:
        # No-leak bias: only DOWNGRADE on a clear contradiction or a proven
        # absence of structural backing. UNKNOWN / None (no RTL to judge) keeps
        # the block — we never relax on absence of evidence.
        if corroboration in (CONTRADICTED, NO_CORROBORATION):
            return False
        return True
    # Unknown provenance string → treat as blocking (fail-closed).
    return True


def advisory_reason(provenance: str, corroboration: Optional[str]) -> str:
    """A short, deterministic human-readable note for a downgraded finding."""
    if corroboration == CONTRADICTED:
        return ("prose-heuristic finding CONTRADICTED by the RTL "
                "(advisory, not a hard block — ORGANIC #770)")
    if corroboration == NO_CORROBORATION:
        return ("prose-heuristic finding with NO structural corroboration "
                "(advisory, not a hard block — ORGANIC #770)")
    return "advisory (ORGANIC #770)"


# ── corroboration helpers (deterministic, no-leak biased) ────────────────────
def corroborate_port_presence(name: str,
                              rtl_port_names_lower: Optional[set]) -> str:
    """A prose-derived PORT NAME vs the RTL's structural port set.

    CORROBORATED — the name is in the RTL port set (the port really exists).
    CONTRADICTED — the RTL port set parsed and the name is ABSENT (a phantom port
                   scraped from prose: `'and'`, an FSM-state localparam, etc.).
    UNKNOWN      — no RTL port set available to judge (keep the block).

    chip-AGNOSTIC; case-insensitive membership only."""
    if rtl_port_names_lower is None:
        return UNKNOWN
    return CORROBORATED if name.lower() in rtl_port_names_lower else CONTRADICTED


def corroborate_direction(want_dir: str, have_dir: Optional[str]) -> str:
    """A prose-derived PORT DIRECTION vs the RTL's structural declaration.

    CORROBORATED — RTL declares the same direction.
    CONTRADICTED — RTL declares the OPPOSITE direction (the RTL refutes the prose
                   heuristic — the author's structural declaration wins).
    UNKNOWN      — the RTL does not declare this port's direction (keep block).

    chip-AGNOSTIC."""
    if not have_dir:
        return UNKNOWN
    return CORROBORATED if want_dir.lower() == have_dir.lower() else CONTRADICTED


def corroborate_structural_feature(rtl_has_feature: Optional[bool]) -> str:
    """A prose-derived BEHAVIORAL requirement (reset / latency / overflow /
    handshake / signedness …) vs whether the RTL structurally exhibits it.

    rtl_has_feature is True  → CORROBORATED (RTL really has the feature; if the
                               TB doesn't exercise it that is a genuine coverage
                               gap and STILL blocks).
    rtl_has_feature is False → CONTRADICTED (RTL provably lacks the structure the
                               prose asserts — e.g. a pure-combinational design
                               that prose calls 'registered'). Advisory only.
    rtl_has_feature is None  → UNKNOWN (no RTL / cannot tell → keep the block).

    chip-AGNOSTIC, no-leak biased on None."""
    if rtl_has_feature is True:
        return CORROBORATED
    if rtl_has_feature is False:
        return CONTRADICTED
    return UNKNOWN
