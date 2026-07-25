#!/usr/bin/env python3
"""A digital sign-off on an undeclared PDK must be disclosed, not silent.

MEASURED (spm x ihp-sg13g2, plugin v1.5.85, image vibeic-eda:0.2.29):
`L19_CONSTRAINTS_PDK.json fields.pdk_target = "sky130"` while
`reports/orchestrator/phase3_one_shot.json pdk = "ihp-sg13g2"`. The entire
backend signed off against IHP SG13G2 and reported DRC 0 / LVS match /
antenna 0 / STA met, and no artifact disclosed that the spec never targets
that PDK. The analog track already refuses this (#496
`flow_compliance_check._pdk_substitution_disclosed`), but that function scans
`analog_dir` for `*.sp` decks and returns None when there is no analog
directory, so a pure digital run was never covered.

BIDIRECTIONAL:
  NEGATIVE — an undisclosed substitution MUST FAIL (rc=1). This is the
             measured defect; without the check it is silent.
  POSITIVE — a disclosed substitution, a waived one, an exact match, a
             declared SECONDARY target, and the two not-applicable cases MUST
             all pass/skip, so the gate cannot be a blanket "any mismatch
             fails" that would false-block honest runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import digital_pdk_substitution_disclosure_check as chk  # noqa: E402


def _mk(tmp_path: Path, *, declared, resolved,
        disclosure: str | None = None, waiver: bool = False) -> Path:
    """Build a minimal project with only the fields the gate reads."""
    proj = tmp_path / "proj"
    if declared is not None:
        d = proj / "phase1" / "generated_docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"fields": {"pdk_target": declared}}))
    if resolved is not None:
        r = proj / "reports" / "orchestrator"
        r.mkdir(parents=True, exist_ok=True)
        (r / "phase3_one_shot.json").write_text(
            json.dumps({"pdk": resolved, "verdict": "PASS"}))
    # A representative sign-off SDC so clock evidence is populated.
    s = proj / "phase3" / "stage3" / "pnr"
    s.mkdir(parents=True, exist_ok=True)
    (s / "constraint.sdc").write_text(
        "# generated\ncreate_clock -name clk -period 10.0 [get_ports clk]\n")
    if disclosure is not None:
        rep = proj / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "final_summary.md").write_text(
            "# summary\n" + disclosure + "\n")
    if waiver:
        (proj / "waivers.json").write_text(json.dumps(
            {"waivers": [{"rule": "PDK_MISMATCH",
                          "rationale": "PDK-portability experiment; "
                                       "constraints re-derived for the "
                                       "substituted library."}]}))
    return proj


# ── NEGATIVE — the measured defect must FAIL ───────────────────────────────
def test_undisclosed_substitution_FAILS(tmp_path):
    proj = _mk(tmp_path, declared="sky130", resolved="ihp-sg13g2")
    rep = chk.check(proj)
    assert rep["verdict"] == "FAIL", rep
    assert "ihp-sg13g2" in rep["reason"] and "sky130" in rep["reason"]
    # the constraint with no spec basis must be named in the evidence
    assert "period 10.0" in rep["clock_evidence"]["create_clock"]
    assert chk.main([str(proj)]) == 1


def test_disclosure_naming_only_ONE_pdk_does_not_count(tmp_path):
    """Half a disclosure is not a disclosure — it must still FAIL."""
    proj = _mk(tmp_path, declared="sky130", resolved="ihp-sg13g2",
               disclosure="pdk_substitution: ihp-sg13g2")
    assert chk.check(proj)["verdict"] == "FAIL"


def test_pdk_substitution_none_cannot_game_the_gate(tmp_path):
    proj = _mk(tmp_path, declared="sky130", resolved="ihp-sg13g2",
               disclosure="pdk_substitution: none")
    assert chk.check(proj)["verdict"] == "FAIL"


# ── POSITIVE — honest runs must NOT be blocked ─────────────────────────────
def test_honest_disclosure_naming_BOTH_pdks_passes(tmp_path):
    proj = _mk(tmp_path, declared="sky130", resolved="ihp-sg13g2",
               disclosure="pdk_substitution: ran on ihp-sg13g2, declared "
                          "target is sky130 (portability experiment)")
    rep = chk.check(proj)
    assert rep["verdict"] == "PASS_WITH_DISCLOSURE", rep
    assert chk.main([str(proj)]) == 0


def test_documented_waiver_passes(tmp_path):
    proj = _mk(tmp_path, declared="sky130", resolved="ihp-sg13g2", waiver=True)
    assert chk.check(proj)["verdict"] == "PASS_WITH_DISCLOSURE"


@pytest.mark.parametrize("declared,resolved", [
    ("sky130", "sky130A"),                       # variant of the target
    ("sky130A", "sky130A"),                      # exact
    ("open-source (SKY130 primary, GF180MCU secondary)", "gf180mcuD"),
    ("open-source (SKY130 primary, GF180MCU secondary)", "sky130A"),
])
def test_declared_target_or_variant_is_not_a_substitution(
        tmp_path, declared, resolved):
    """No false positives: a declared primary OR secondary target passes."""
    proj = _mk(tmp_path, declared=declared, resolved=resolved)
    rep = chk.check(proj)
    assert rep["verdict"] == "PASS", rep


@pytest.mark.parametrize("declared,resolved,why", [
    (None, "ihp-sg13g2", "no L19 target to compare against"),
    ("sky130", None, "phase 3 did not run"),
    ("N/A", "ihp-sg13g2", "target explicitly not-applicable"),
])
def test_not_applicable_cases_SKIP_never_silently_pass(
        tmp_path, declared, resolved, why):
    proj = _mk(tmp_path, declared=declared, resolved=resolved)
    rep = chk.check(proj)
    assert rep["verdict"] == "SKIP", (why, rep)
    assert chk.main([str(proj)]) == 0


# ── the token matcher itself ───────────────────────────────────────────────
@pytest.mark.parametrize("a,b,match", [
    ("ihp-sg13g2", "sky130", False),
    ("gf180mcuD", "sky130", False),
    ("sky130A", "sky130", True),
    ("gf180mcuD", "GF180MCU secondary", True),
    ("nangate45", "sky130", False),
])
def test_family_matching_is_pdk_agnostic(a, b, match):
    assert chk._families_match(a, b) is match
