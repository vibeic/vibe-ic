#!/usr/bin/env python3
"""tests/test_issue_466_468_skill_sections.py — #466B + #468

Bucket-B skill-section captures (prose only, no program code):

  #466B — analog block-list sanity vs the L5 type enumeration:
          a name-only / null-spec block from L1 is presumed SPURIOUS and
          must be confirmed against the L5 enumeration BEFORE A2 sizing;
          multiplicity (×N) comes from the block's OWN enumeration row.
          Section lands in analog-topology-select/SKILL.md, with a shorter
          cross-reference note in analog-spec-extract/SKILL.md.

  #468  — error-flag site recoverable-vs-fatal classification from L3/L5
          prose: continue-serving → '// fsm_error: recoverable'; halt /
          reset-to-clear → fatal; FORBIDDEN to silence the gate without
          quoting the L3/L5 sentence(s). Section lands in rtl-review/SKILL.md
          and spec-to-rtl/SKILL.md.

Each issue gets BOTH:
  * a fixed-path assertion (the new section + its required clauses exist), and
  * a regression guard for the prior correct behavior (the corpus-sweep
    condition): the pre-existing sections/structure are untouched, the
    additions stay chip-AGNOSTIC, and the compliance.yaml files are not broken.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent  # plugins/vibe-ic/
sys.path.insert(0, str(PLUGIN_ROOT))

SKILLS = PLUGIN_ROOT / "skills"
TOPO = SKILLS / "analog-topology-select" / "SKILL.md"
SPEC_EXTRACT = SKILLS / "analog-spec-extract" / "SKILL.md"
RTL_REVIEW = SKILLS / "rtl-review" / "SKILL.md"
SPEC_TO_RTL = SKILLS / "spec-to-rtl" / "SKILL.md"

# Chip / vendor / SKU tokens that must NEVER appear in the new sections as
# detection patterns. Mirrors programs/source_chip_agnostic_check.py intent;
# synthetic-only fixtures here use no real names at all.
FORBIDDEN_CHIP_TOKENS = (
    "spm", "sha256", "subservient", "u_hawaii", "hawaii",
    "tsmc", "sg13g2", "ihp", "caravel", "chipignite",
)


def _read(p: Path) -> str:
    assert p.is_file(), f"missing skill file: {p}"
    return p.read_text()


# ---------------------------------------------------------------------------
# #466B — fixed-path: the sanity section exists with its load-bearing clauses
# ---------------------------------------------------------------------------

def test_466_topology_has_spurious_block_sanity_section():
    text = _read(TOPO)
    # New capture section heading present.
    assert "spurious-block sanity check" in text.lower(), (
        "analog-topology-select missing the #466B spurious-block sanity section"
    )
    low = text.lower()
    # Presumed-spurious + null-spec + product-name-keyword provenance test.
    assert "presumed spurious" in low
    assert "null" in low and "product-name" in low
    # Must require confirm-against-L5 BEFORE spending sizing compute.
    assert "l5 enumeration" in low or "l5 type enumeration" in low
    assert "before" in low and ("sizing" in low or "compute" in low)
    # Multiplicity must come from the block's OWN enumeration row, not a sibling.
    assert "multiplicity" in low
    assert "own" in low and "sibling" in low


def test_466_topology_has_why_not_bucket_a_rationale():
    text = _read(TOPO).lower()
    assert "why_not_bucket_a" in text, (
        "#466B section must carry the why_not_bucket_a rationale"
    )
    # The specific rationale: cannot be safely deny-listed; some chips' blocks
    # genuinely appear only in the datasheet/product name → requires reading L5.
    assert "deny-list" in text or "deny list" in text
    assert "name" in text and "l5" in text


def test_466_spec_extract_has_crossref_note():
    text = _read(SPEC_EXTRACT)
    low = text.lower()
    assert "#466b" in low or "466b" in low, (
        "analog-spec-extract missing the #466B cross-reference note"
    )
    # It is a CROSS-REFERENCE: points back at analog-topology-select, does not
    # re-implement the full procedure / deny-list here.
    assert "analog-topology-select" in low
    assert "spurious" in low
    assert "do not re-implement" in low or "not re-implement" in low


# ---------------------------------------------------------------------------
# #466B — regression guard: prior correct behavior preserved (corpus-sweep)
# ---------------------------------------------------------------------------

def test_466_pre_existing_topology_content_intact():
    """The new section is ADDITIVE — the pre-existing recall-floor / proven
    topologies / ΔΣ capture must all survive untouched."""
    text = _read(TOPO)
    assert "## Proven topologies (GF180, verified via SPICE)" in text
    assert "ΔΣ modulator topology" in text
    assert "_Captured by benchmark-enhancement-capture 2026-05-28._" in text


def test_466_spec_extract_recall_floor_intact():
    """analog-spec-extract's recall-floor doctrine (over-fire flip-side is the
    NEW note) must remain — the spurious-block note complements, not replaces
    the 'catch what the grep misses' residual-judgment rule."""
    text = _read(SPEC_EXTRACT)
    assert "recall floor" in text.lower()
    assert "Catch what the grep misses" in text


# ---------------------------------------------------------------------------
# #468 — fixed-path: the recoverable-vs-fatal section exists with its clauses
# ---------------------------------------------------------------------------

def test_468_rtl_review_has_error_flag_classification_section():
    text = _read(RTL_REVIEW)
    low = text.lower()
    assert "fsm_error_invariant" in text, (
        "rtl-review #468 section must reference the fsm_error_invariant gate"
    )
    assert "recoverable" in low and "fatal" in low
    # recoverable → continue serving + the exact annotation.
    assert "// fsm_error: recoverable" in text
    assert "continue" in low or "continues serving" in low
    # fatal → halt state / reset-to-clear.
    assert "halt" in low
    assert "reset" in low
    # undefined-access path is the trigger described in the issue.
    assert "undefined-access" in low or "undefined access" in low


def test_468_rtl_review_forbidden_silence_without_quote():
    text = _read(RTL_REVIEW).lower()
    assert "forbidden" in text
    # The forbidden act: silencing/waiving the gate without quoting L3/L5.
    assert ("silenc" in text or "waiv" in text)
    assert "quot" in text and ("l3" in text and "l5" in text)


def test_468_rtl_review_has_why_not_bucket_a():
    text = _read(RTL_REVIEW).lower()
    assert "why_not_bucket_a" in text
    # The program already does its half (flagging sites); the semantic judgment
    # lives in protocol prose, not RTL structure.
    assert "flag" in text and ("its half" in text or "half" in text)
    assert "rtl structure" in text or "structure" in text


def test_468_spec_to_rtl_has_matching_section():
    text = _read(SPEC_TO_RTL)
    low = text.lower()
    assert "recoverable" in low and "fatal" in low
    assert "// fsm_error: recoverable" in text
    assert "forbidden" in low
    assert "why_not_bucket_a" in low
    assert "l3" in low and "l5" in low


# ---------------------------------------------------------------------------
# #468 — regression guard: prior correct behavior preserved (corpus-sweep)
# ---------------------------------------------------------------------------

def test_468_rtl_review_program_first_doctrine_intact():
    """rtl-review's program-first wrapper doctrine (run the program FIRST,
    Claude is backstop only) must survive — the new section is ADDITIVE and
    explicitly scopes itself to the residual LLM judgment."""
    text = _read(RTL_REVIEW)
    assert "## Mandatory: run the program FIRST" in text
    assert "rtl_review_aggregate.py" in text
    assert "## Anti-patterns" in text


def test_468_spec_to_rtl_invocation_contract_intact():
    """spec-to-rtl's runner-orchestrated authoring contract must remain — the
    new error-flag section does not displace the blind-rule / WAIVE handoff."""
    text = _read(SPEC_TO_RTL)
    assert "## Invocation contract" in text
    assert "Respect the blind rule" in text
    assert "## Quality bar" in text


# ---------------------------------------------------------------------------
# Cross-cutting: additions are chip-AGNOSTIC + compliance.yaml not broken
# ---------------------------------------------------------------------------

def _new_section_text(full: str, anchor: str) -> str:
    """Return everything from `anchor` to end-of-file (the appended section)."""
    idx = full.find(anchor)
    assert idx != -1, f"anchor {anchor!r} not found"
    return full[idx:]


def test_added_sections_are_chip_agnostic():
    """No chip / vendor / SKU token may appear in any of the four new sections.
    This is the regression guard against keyword-overfit detection logic."""
    checks = [
        (_new_section_text(_read(TOPO), "## Captured by benchmark-enhancement-capture — 2026-06-06")),
        (_new_section_text(_read(SPEC_EXTRACT), "Spurious-block flip-side")),
        (_new_section_text(_read(RTL_REVIEW), "## Error-flag site classification")),
        (_new_section_text(_read(SPEC_TO_RTL), "## Error-flag behavior")),
    ]
    for section in checks:
        low = section.lower()
        for tok in FORBIDDEN_CHIP_TOKENS:
            assert tok not in low, (
                f"chip/vendor/SKU token {tok!r} leaked into a new skill section"
            )


def test_compliance_yaml_files_unbroken():
    """Additive sections must not break the existing compliance.yaml required
    sections. The yamls validate skill OUTPUT (Output/Handoff/Summary/Next),
    not SKILL.md text, so they must remain present + parse-clean."""
    import yaml  # PyYAML is a plugin test dep

    for skill_dir in (
        "analog-topology-select", "analog-spec-extract",
        "rtl-review", "spec-to-rtl",
    ):
        cy = SKILLS / skill_dir / "compliance.yaml"
        assert cy.is_file(), f"missing compliance.yaml for {skill_dir}"
        doc = yaml.safe_load(cy.read_text())
        assert doc.get("skill") == skill_dir
        assert isinstance(doc.get("requirements"), list) and doc["requirements"]
