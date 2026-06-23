#!/usr/bin/env python3
"""Regression for ORGANIC-20260606 #458 — cdc_crossing_check must PASS a
legitimate single-clock design (zero clock-domain crossings).

Bug (v0.2.90): the checker FAILed every legit single-clock design.
design_one_shot_runner emits, for a single-clock RTL scan:

    reports/phase2/cdc/crossing.json = {
        "verdict": "PASS",
        "evidence": "... single clock domain ['clk'] — no clock-domain
                     crossings exist",
        "crossings": [],
        "clocks_found": ["clk"]
    }

…but the checker ERRORed "No crossing analysis keywords found". Two root
causes:
  (a) the keyword regex only matched the singular literal `\\bcrossing\\b`
      etc.; a zero-crossing report legitimately phrases its substance with
      the plural ("no clock-domain crossings exist") and carries a JSON
      `"crossings"` key — neither matched the singular form.
  (b) the two accept-paths both missed: the keyword path found nothing, and
      the canonical-substance path required len(crossings) > 0. A
      single-clock design has an EMPTY crossings list, so BOTH paths failed.

Fix:
  - broaden the keyword regex to the plural / JSON-key form `\\bcrossings?\\b`
    (applied only to human-readable tool-report text, NOT to the canonical
    JSON whose bare empty-list key must not masquerade as analysis);
  - add a THIRD accept-path: a canonical crossing.json with verdict=PASS AND
    (clocks_found <= 1) OR (crossings == [] backed by single-clock evidence
    wording) is itself the correct substance — a single-clock design has no
    crossings to analyse.

CORPUS-SWEEP guard (preserved): a MULTI-clock report that lists real
crossings but carries no analysis content must STILL FAIL — the third path
is gated on the single-clock condition and the broadened keyword regex is
kept off the canonical JSON, so an empty-list/structural dump cannot fake a
PASS.

chip-AGNOSTIC: fixtures use synthetic generic names only (clk / clk_a /
clk_b / data_*). No chip/vendor/SKU names appear in detection or fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cdc_crossing_check as ccc  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_canonical(project: Path, payload: dict) -> None:
    cdc_dir = project / "reports" / "phase2" / "cdc"
    cdc_dir.mkdir(parents=True, exist_ok=True)
    (cdc_dir / "crossing.json").write_text(json.dumps(payload))


# ---------------------------------------------------------------------------
# FIXED PATH — the bug: single-clock canonical PASS must now PASS
# ---------------------------------------------------------------------------
def test_single_clock_canonical_pass(tmp_path):
    """The exact runner-emitted single-clock report from the issue."""
    _write_canonical(tmp_path, {
        "verdict": "PASS",
        "evidence": ("clock-edge scan of 3 RTL file(s): single clock domain "
                     "['clk'] — no clock-domain crossings exist"),
        "crossings": [],
        "clocks_found": ["clk"],
        "rtl_files_scanned": ["top.v", "core.v", "io.v"],
    })

    result = ccc.audit_cdc(tmp_path)

    assert result.passed is True
    assert result.summary["single_clock_pass"] is True
    # No CROSSING_ANALYSIS ERROR finding should remain.
    assert not any(
        f.rule == "CDC_CROSSING_ANALYSIS" and f.severity == "ERROR"
        for f in result.findings
    )


def test_single_clock_cli_exit_zero(tmp_path):
    """CLI returns 0 for a legit single-clock design (was 1 pre-fix)."""
    _write_canonical(tmp_path, {
        "verdict": "PASS",
        "evidence": ("single clock domain ['clk'] — no clock-domain "
                     "crossings exist"),
        "crossings": [],
        "clocks_found": ["clk"],
    })
    rc = ccc.main([str(tmp_path)])
    assert rc == 0


def test_explicit_single_via_clocks_found_only(tmp_path):
    """clocks_found<=1 alone (path a) accepts even without evidence prose."""
    _write_canonical(tmp_path, {
        "verdict": "PASS",
        "evidence": "scan complete",
        "crossings": [],
        "clocks_found": ["clk"],
    })
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is True
    assert result.summary["single_clock_pass"] is True


def test_zero_clock_combinational_pass(tmp_path):
    """A pure-combinational design (zero clocks) is also single-domain."""
    _write_canonical(tmp_path, {
        "verdict": "PASS",
        "evidence": ("single clock domain ['(none)'] — no clock-domain "
                     "crossings exist"),
        "crossings": [],
        "clocks_found": [],
    })
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is True
    assert result.summary["single_clock_pass"] is True


def test_empty_crossings_with_evidence_no_clocks_field(tmp_path):
    """Path (b): empty crossings + single-clock evidence wording, even if
    `clocks_found` is absent, is accepted."""
    _write_canonical(tmp_path, {
        "verdict": "PASS",
        "evidence": "single clock domain — no clock-domain crossings exist",
        "crossings": [],
    })
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is True
    assert result.summary["single_clock_pass"] is True


# ---------------------------------------------------------------------------
# Broadened keyword regex matches plural prose in a human-readable report
# ---------------------------------------------------------------------------
def test_plural_prose_in_rpt_matches(tmp_path):
    """A tool .rpt that uses the plural "crossings" in analysis prose now
    matches the broadened keyword regex (singular-only form missed it)."""
    rpt = tmp_path / "cdc_analysis.rpt"
    rpt.write_text(
        "Clock domain: clk_a -> clk_b\n"
        "2 clock-domain crossings analysed; synchronizers verified\n"
    )
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is True
    assert result.summary["has_crossing"] is True


# ---------------------------------------------------------------------------
# CORPUS-SWEEP GUARD — prior correct FAIL behavior must be preserved
# ---------------------------------------------------------------------------
def test_guard_multiclock_real_crossings_no_analysis_rpt_fails(tmp_path):
    """The EXACT issue corpus-sweep: a multi-clock report that lists real
    crossings (structurally) but carries NO analysis content must STILL
    FAIL. The dump avoids the prose word "crossing(s)" / synchronizer
    keywords, so neither the keyword path nor any accept-path fires."""
    rpt = tmp_path / "cdc_dump.rpt"
    rpt.write_text(
        "Domains: clk_main, clk_aux\n"
        "Path table:\n"
        "  data_a : clk_main -> clk_aux\n"
        "  data_b : clk_aux -> clk_main\n"
    )
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is False
    assert result.summary["has_crossing"] is False


def test_guard_multiclock_empty_canonical_no_evidence_fails(tmp_path):
    """A canonical PASS that claims >1 clock but lists an empty crossings
    list with NO single-clock evidence must NOT slip through the third
    path (single_clock_pass), and the broadened regex must not be fooled by
    the bare `"crossings"` JSON key on the canonical file."""
    _write_canonical(tmp_path, {
        "verdict": "PASS",
        "evidence": "multi-domain bus bridge present",
        "crossings": [],
        "clocks_found": ["clk_a", "clk_b"],
    })
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is False
    assert result.summary["single_clock_pass"] is False
    assert result.summary["has_crossing"] is False


def test_guard_multiclock_skipped_condition_deferred(tmp_path):
    """SUPERSEDED by ORGANIC #673 (P0). The runner emits SKIPPED-CONDITION
    (not PASS) for a multi-clock design — a DISCLOSED capability gap (a real
    CDC tool is required, #436). The pre-#673 behavior treated it as a hard
    FAIL (`files_found == 0`, "No CDC report found"), which cascade-blocked
    ALL of Phase 3 for any design with >=2 clock domains. Per #673 it is now
    a WAIVED-DEFERRED cap-gap (`cap:cdc`) that PASSES the gate so Phase 3 is
    not blocked. The #458 anti-recycling intent is preserved elsewhere: a
    genuine verdict=FAIL still hard-FAILs, a corrupt JSON is not a disclosed
    skip, and a multi-clock PASS lacking analysis still fails."""
    _write_canonical(tmp_path, {
        "verdict": "SKIPPED-CONDITION",
        "reason": "multi-clock design requires a real CDC tool run",
        "clocks_found": ["clk_a", "clk_b"],
    })
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is True
    assert result.summary["deferred"] is True
    assert result.summary["cap_flag"] == "cap:cdc"


def test_guard_clockref_only_rpt_still_fails(tmp_path):
    """Pre-existing behavior: a .rpt with clock refs but no crossing
    analysis still FAILs (no canonical JSON to rescue it)."""
    rpt = tmp_path / "cdc.rpt"
    rpt.write_text("Clock domain analysis:\nclk_sys frequency = 100 MHz\n")
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is False
    assert result.summary["has_clock_ref"] is True
    assert result.summary["has_crossing"] is False


# ---------------------------------------------------------------------------
# Existing canonical-substance path (multi-clock with real crossings +
# genuine analysis) must still PASS — not weakened by the new path.
# ---------------------------------------------------------------------------
def test_multiclock_real_crossings_with_analysis_pass(tmp_path):
    _write_canonical(tmp_path, {
        "verdict": "PASS",
        "evidence": "two clock domains; synchronizer inserted",
        "crossings": [{"from": "clk_a", "to": "clk_b", "sync": "2ff"}],
        "clocks_found": ["clk_a", "clk_b"],
    })
    result = ccc.audit_cdc(tmp_path)
    assert result.passed is True
    assert result.summary["canonical_substance_pass"] is True
    # It is NOT a single-clock report.
    assert result.summary["single_clock_pass"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
