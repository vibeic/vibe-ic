#!/usr/bin/env python3
"""Smoke tests for l8_sta_clock_period_design_owned_check.

EXPLICIT NEGATIVE CONTROL. Every behavioural test asserts BOTH directions:
a deliberately-gutted L8 must FAIL (rc=1) and the well-formed sibling must
PASS (rc=0). A test that cannot fail proves nothing.

All fixtures are SYNTHESIZED neutral data — invented module, port and clock
names, invented frequencies. No real design's files are copied.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "l8_sta_clock_period_design_owned_check.py"

RTL = """module neutral_top (
  input  wire clk_a,
  input  wire rst_na,
  output reg  [7:0] q_a
);
  always @(posedge clk_a or negedge rst_na) begin
    if (!rst_na) q_a <= 8'h00;
    else         q_a <= q_a + 8'h01;
  end
endmodule
"""

L9 = {
    "top_module": "neutral_top",
    "top_module_pins": [
        {"name": "clk_a", "mode": "input", "role": "clock"},
        {"name": "rst_na", "mode": "input", "role": "reset"},
    ],
}

# GUTTED: the layer LOOKS populated — a fully-shaped clock_domains[] entry —
# but every frequency field is null, so the consumer's resolver returns None
# and sdc_gen falls through to its hardcoded default.
GUTTED_L8 = {
    "doc_class": "L8_RTL_CONSTANTS",
    "clock_mhz": None,
    "no_clock_mhz_in_input": True,
    "clock_domains": [
        {"name": "clk_a", "source_pin": "clk_a", "domain_kind": "primary",
         "role": "master", "freq_hz": None, "freq_mhz": None,
         "period_ns": None},
    ],
}

WELLFORMED_L8 = {
    "doc_class": "L8_RTL_CONSTANTS",
    "clock_mhz": None,
    "clock_domains": [
        {"name": "clk_a", "source_pin": "clk_a", "domain_kind": "primary",
         "role": "master", "freq_mhz": 80.0, "period_ns": 12.5,
         "freq_hz": 80000000},
    ],
}


def _run(project: Path):
    proc = subprocess.run(
        [sys.executable, str(GATE), str(project)],
        capture_output=True, text=True, timeout=60)
    return proc.returncode, (proc.stdout + proc.stderr)


def _build(root: Path, l8: dict, *, with_rtl=True, l9=L9,
           staged_sdc: str | None = None,
           backend_sdc: str | None = None) -> Path:
    project = root / "proj"
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8, indent=1))
    if l9 is not None:
        (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9, indent=1))
    if with_rtl:
        r = project / "phase2" / "stage1" / "rtl"
        r.mkdir(parents=True, exist_ok=True)
        (r / "neutral_top.v").write_text(RTL)
    if staged_sdc is not None:
        c = project / "input" / "constraints"
        c.mkdir(parents=True, exist_ok=True)
        (c / "neutral.sdc").write_text(staged_sdc)
    if backend_sdc is not None:
        c = project / "phase2" / "stage2" / "constraints"
        c.mkdir(parents=True, exist_ok=True)
        (c / "neutral_top.sdc").write_text(backend_sdc)
    return project


# --------------------------------------------------------------------------- #
# THE NEGATIVE CONTROL PAIR
# --------------------------------------------------------------------------- #
def test_gutted_l8_fails_and_wellformed_l8_passes(tmp_path):
    """NEGATIVE CONTROL: identical design, only L8's frequency fields differ."""
    gutted = _build(tmp_path / "a", GUTTED_L8)
    rc_bad, out_bad = _run(gutted)
    assert rc_bad == 1, (
        "an L8 whose clock_domains[] carries null freq_hz/freq_mhz/period_ns "
        "MUST FAIL — sdc_gen would fabricate the STA period. "
        f"got rc={rc_bad}\n{out_bad}")
    assert "L8-1" in out_bad
    assert "FABRICATED" in out_bad

    good = _build(tmp_path / "b", WELLFORMED_L8)
    rc_ok, out_ok = _run(good)
    assert rc_ok == 0, (
        f"an L8 owning a real frequency MUST PASS. got rc={rc_ok}\n{out_ok}")
    assert "[PASS]" in out_ok


def test_explicit_clock_mhz_also_passes(tmp_path):
    """Tier-1 resolution (top-level clock_mhz) is equally design-owned."""
    l8 = {"doc_class": "L8_RTL_CONSTANTS", "clock_mhz": 40.0,
          "clock_domains": []}
    project = _build(tmp_path, l8)
    rc, out = _run(project)
    assert rc == 0, f"clock_mhz=40 MUST PASS. got rc={rc}\n{out}"
    assert "L8.clock_mhz" in out


def test_staged_sdc_rescues_but_is_reported_as_an_advisory(tmp_path):
    """Tier-3: the period IS design-owned (the design's own staged SDC), so the
    gate must NOT fail — but it must say L8 does not own it."""
    project = _build(tmp_path, GUTTED_L8,
                     staged_sdc="create_clock -name c_a -period 12.5 "
                                "[get_ports {clk_a}]\n")
    rc, out = _run(project)
    assert rc == 0, (
        "a design-owned staged SDC period must not FAIL. "
        f"got rc={rc}\n{out}")
    assert "staged SDC" in out
    assert "[note]" in out, "the L8-side gap must still be reported"


def test_backend_sdc_that_contradicts_l8_fails(tmp_path):
    """L8-2 NEGATIVE CONTROL: same L8, two different backend SDCs."""
    bad = _build(tmp_path / "bad", WELLFORMED_L8,
                 backend_sdc="create_clock -name c_a -period 20 "
                             "[get_ports {clk_a}]\n")
    rc_bad, out_bad = _run(bad)
    assert rc_bad == 1, (
        "L8 owns 12.5 ns while the backend SDC constrains 20 ns — MUST FAIL. "
        f"got rc={rc_bad}\n{out_bad}")
    assert "L8-2" in out_bad

    good = _build(tmp_path / "good", WELLFORMED_L8,
                  backend_sdc="create_clock -name c_a -period 12.5 "
                              "[get_ports {clk_a}]\n")
    rc_ok, out_ok = _run(good)
    assert rc_ok == 0, (
        f"a matching backend SDC MUST PASS. got rc={rc_ok}\n{out_ok}")


def test_derived_clock_without_divider_fails(tmp_path):
    """L8-3 NEGATIVE CONTROL: derived entry with and without a divider."""
    bad = json.loads(json.dumps(WELLFORMED_L8))
    bad["clock_domains"].append(
        {"name": "clk_div_a", "role": "derived", "source": "clk_a",
         "freq_mhz": None, "period_ns": None, "freq_hz": None,
         "divider": None})
    project_bad = _build(tmp_path / "bad", bad)
    rc_bad, out_bad = _run(project_bad)
    assert rc_bad == 1, (
        f"a derived clock with no divider and no freq MUST FAIL. "
        f"got rc={rc_bad}\n{out_bad}")
    assert "L8-3" in out_bad and "clk_div_a" in out_bad

    good = json.loads(json.dumps(WELLFORMED_L8))
    good["clock_domains"].append(
        {"name": "clk_div_a", "role": "derived", "source": "clk_a",
         "divider": 4, "freq_mhz": 20.0})
    project_good = _build(tmp_path / "good", good)
    rc_ok, out_ok = _run(project_good)
    assert rc_ok == 0, (
        f"a derived clock with a divider MUST PASS. got rc={rc_ok}\n{out_ok}")


def test_conflicting_same_name_frequencies_are_advisory_only(tmp_path):
    """L8-4 must NOT change the exit code — the ambiguity is a phase-1
    extraction artefact, not proof of a wrong period."""
    l8 = json.loads(json.dumps(WELLFORMED_L8))
    l8["clock_domains"].append(
        {"name": "clk_a", "domain_kind": "primary",
         "role": "extracted_from_doc_freq_mention", "freq_mhz": 125.0})
    project = _build(tmp_path, l8)
    rc, out = _run(project)
    assert rc == 0, f"conflicting-name advisory MUST NOT fail. got {rc}\n{out}"
    assert "conflicting frequencies" in out


def test_unclocked_design_skips(tmp_path):
    """A block with no clock at all must SKIP (rc=2), never fail — this is what
    keeps the gate off pure-analog blocks."""
    l8 = {"doc_class": "L8_RTL_CONSTANTS", "clock_mhz": None,
          "clock_domains": []}
    l9 = {"top_module": "neutral_analog_top",
          "top_module_pins": [{"name": "in_a", "mode": "input"},
                              {"name": "out_a", "mode": "output"}]}
    project = _build(tmp_path, l8, with_rtl=False, l9=l9)
    rc, out = _run(project)
    assert rc == 2, f"unclocked design MUST SKIP. got rc={rc}\n{out}"
    assert "SKIP" in out


def test_waiver_discloses_instead_of_hiding(tmp_path):
    project = _build(tmp_path, GUTTED_L8)
    (project / "waivers.json").write_text(json.dumps({
        "l8_sta_clock_period_not_design_owned":
            "This synthesized fixture's inputs deliberately state no operating "
            "frequency; the fabricated STA period is disclosed for review."}))
    rc, out = _run(project)
    assert rc == 0 and "PASS_WITH_WAIVERS" in out, f"rc={rc}\n{out}"
    assert "FABRICATED" in out, "a waiver must disclose, not hide"

    (project / "waivers.json").write_text(json.dumps({
        "l8_sta_clock_period_not_design_owned": "too short"}))
    rc2, _ = _run(project)
    assert rc2 == 1, "a <40-char waiver must not suppress the finding"


def test_gate_reuses_the_consumers_own_resolver():
    """Emitter/checker doctrine: the gate must delegate to sdc_gen's OWN
    _clock_mhz_from_l8_domains and read its OWN _DEFAULT_MHZ, so gate and
    consumer can never drift."""
    sys.path.insert(0, str(PROGRAMS))
    import importlib
    mod = importlib.import_module("l8_sta_clock_period_design_owned_check")
    import sdc_gen
    assert mod._consumer_domains_mhz is sdc_gen._clock_mhz_from_l8_domains
    assert mod._CONSUMER_DEFAULT_MHZ == sdc_gen._DEFAULT_MHZ
    # The gutted fixture is exactly the shape that returns None from the
    # consumer's own resolver.
    assert sdc_gen._clock_mhz_from_l8_domains(GUTTED_L8) is None
    assert sdc_gen._clock_mhz_from_l8_domains(WELLFORMED_L8) == 80.0


def test_json_report_is_written(tmp_path):
    project = _build(tmp_path, GUTTED_L8)
    out_json = tmp_path / "rep.json"
    proc = subprocess.run(
        [sys.executable, str(GATE), str(project), "--json", str(out_json)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    doc = json.loads(out_json.read_text())
    assert doc["verdict"] == "FAIL"
    assert doc["resolved_mhz"] is None
    assert any(f["rule"] == "L8-1" for f in doc["findings"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
