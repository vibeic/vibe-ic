#!/usr/bin/env python3
"""Tests for sdc_validator_check.py — gate that validates SDC contents.

Wave 83 — coverage for previously untested wired program.

Cases:
  1. POSITIVE_PASS — fpga/*.sdc with all three required clauses → exit 0.
  2. POSITIVE_FAIL — missing set_input_delay → exit 1 with the issue listed.
  3. SKIP_NO_SDC — fpga/ exists but no .sdc files → exit 2 (NOT CHECKED).
  4. SKIP_NO_FPGA_DIR — no fpga/ at all → exit 2 (NOT CHECKED).

Cases 3 and 4 asserted exit 0 until the exit-code contract was applied: a
run that reads no file has not PASSED anything, and at exit 0 the compliance
report recorded it as an ordinary PASS with no `__VACUOUS_HINT__`.
  5. EDGE_MULTIPLE_FILES_ALL_PASS — two .sdc files all valid → PASS with count.
  6. EDGE_MULTIPLE_FILES_ONE_BROKEN — one OK, one broken → FAIL.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "sdc_validator_check.py"


_GOOD_SDC = """\
create_clock -name clk -period 20 [get_ports CLOCK_50]
set_input_delay  -clock clk 2 [get_ports KEY[0]]
set_output_delay -clock clk 2 [get_ports LEDR[0]]
"""


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _seed_sdc(project: Path, name: str, body: str) -> None:
    fpga = project / "phase2" / "stage1" / "fpga"
    fpga.mkdir(parents=True, exist_ok=True)
    (fpga / name).write_text(body)


def test_positive_pass_all_clauses(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "tb.sdc", _GOOD_SDC)
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] sdc_validator_check" in cp.stdout
    assert "1 SDC" in cp.stdout


def test_positive_fail_missing_input_delay(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    body = _GOOD_SDC.replace("set_input_delay  -clock clk 2 [get_ports KEY[0]]\n",
                              "")
    _seed_sdc(project, "tb.sdc", body)
    cp = _run([str(project)])
    assert cp.returncode == 1
    assert "[FAIL]" in cp.stdout
    assert "set_input_delay" in cp.stdout


def test_skip_no_sdc_files(tmp_path):
    project = tmp_path / "proj"
    (project / "phase2" / "stage1" / "fpga").mkdir(parents=True)
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout


def test_skip_no_fpga_dir(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout


def test_edge_multiple_files_all_pass(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "a.sdc", _GOOD_SDC)
    _seed_sdc(project, "b.sdc", _GOOD_SDC)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[PASS]" in cp.stdout
    assert "2 SDC" in cp.stdout


def test_edge_multiple_files_one_broken(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "good.sdc", _GOOD_SDC)
    _seed_sdc(project, "bad.sdc",
               "# missing every required clause\n# just a comment\n")
    cp = _run([str(project)])
    assert cp.returncode == 1
    # The bad file's name should appear in the listed issues.
    assert "bad.sdc" in cp.stdout
    assert "[FAIL]" in cp.stdout


# ===========================================================================
# L8 CROSS-CHECK — the check the flow has DECLARED since Wave 82
#
# flow/phase1_phase2_phase3.yaml step 8 comment:
#     "`sdc_validator_check` cross-checks the SDC against L8_TIMING_WAVEFORM
#      constraints; complements sdc_syntax_check which only validates SDC
#      syntax."
# and its gate command passes
#     --l8 phase1/generated_docs/L8_TIMING_WAVEFORM.json.
# Before this change `args.l8` appeared NOWHERE in the function body — the
# argument existed only so argparse would not reject the gate command — so
# the entire PASS/FAIL surface was three literal substring tests and an SDC
# could constrain a clock at ANY period and still PASS.
#
# MEASURED on ~/campaign_pr427/spm/converge_ihp-sg13g2 (main @ v1.7.36):
#   phase2/stage2/constraints/spm.sdc: create_clock -name clk -period 10.0
#   L8_TIMING_WAVEFORM.json: clocks=[clk 10.0 ns] and
#                            clock_domains=[clk 100 MHz / 10.0 ns,
#                                           clk 125 MHz /  8.0 ns]
#   -> two contradictory periods under one clock name, and the program
#      reported `[PASS] sdc_validator_check: 2 SDC file(s) OK`, rc=0.
# ===========================================================================
import json  # noqa: E402


def _write_l8(project: Path, doc: dict) -> Path:
    gen = project / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    p = gen / "L8_TIMING_WAVEFORM.json"
    p.write_text(json.dumps(doc, indent=1))
    return p


_SDC_10NS = """\
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay  2 -clock clk [all_inputs]
set_output_delay 2 -clock clk [all_outputs]
"""

#: The reference run's L8 shape, values generalised — no chip literals.
_L8_CONTRADICTORY = {
    "schema_version": "1",
    "doc_class": "timing_waveform",
    "timing_windows": [],
    "timing_constants": [],
    "waveforms": [],
    "clock_domains": [
        {"name": "clk", "freq_mhz": 100.0, "period_ns": 10.0,
         "role": "primary", "domain_kind": "primary", "source_pin": "clk"},
        {"name": "clk", "freq_mhz": 125.0, "period_ns": 8.0,
         "role": "extracted_from_doc_freq_mention", "derived_from": "clk",
         "domain_kind": "primary", "source_pin": "clk"},
    ],
    "clocks": [
        {"name": "clk", "type": "input", "freq_mhz": 100.0,
         "period_ns": 10.0, "role": "primary", "domain_kind": "primary"},
    ],
}


def test_l8_contradictory_periods_fail(tmp_path):
    """The reference-run reproducer: one clock name carrying two different
    periods makes the SDC unverifiable and must FAIL."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, _L8_CONTRADICTORY)
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "conflicting periods" in cp.stdout
    assert "8 ns" in cp.stdout and "10 ns" in cp.stdout


def test_l8_contradiction_reported_even_with_no_sdc_files(tmp_path):
    """L8 self-consistency is a property of L8 alone — a contradictory
    constraint document must not hide behind an empty SDC glob."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    l8 = _write_l8(project, _L8_CONTRADICTORY)
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "conflicting periods" in cp.stdout
    assert "[SKIP]" not in cp.stdout


def test_l8_period_mismatch_against_sdc_fails(tmp_path):
    """The core cross-check: the SDC constrains clk at 10 ns while L8
    declares 5 ns. Nothing compared these two numbers before."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "period_ns": 5.0, "domain_kind": "primary"}]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "disagrees with L8 clock" in cp.stdout
    assert "10 ns" in cp.stdout and "5 ns" in cp.stdout


def test_l8_freq_mhz_only_is_converted_to_a_period(tmp_path):
    """Unit / field-name variance is tolerated rather than failed on:
    freq_mhz=125 -> 8 ns, which disagrees with the SDC's 10 ns."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "freq_mhz": 125.0, "domain_kind": "primary"}]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "8 ns" in cp.stdout


def test_l8_freq_hz_only_is_converted_to_a_period(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "freq_hz": 250000000, "domain_kind": "primary"}]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "4 ns" in cp.stdout


def test_l8_clock_never_constrained_by_any_sdc_fails(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "period_ns": 10.0, "domain_kind": "primary"},
        {"name": "clk_ref", "period_ns": 4.0, "domain_kind": "primary"},
    ]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "clk_ref" in cp.stdout
    assert "no SDC constrains it" in cp.stdout


def test_l8_corrupt_document_is_reported(tmp_path):
    """The gate fires only when the L8 file exists; an L8 that exists but
    cannot be read means the declared cross-check cannot run at all."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    gen = project / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    l8 = gen / "L8_TIMING_WAVEFORM.json"
    l8.write_text("{ this is not json")
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "unreadable" in cp.stdout


def test_json_report_is_written_on_fail(tmp_path):
    """A FAIL must leave its evidence file behind; the report used to be
    written only on the PASS path."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "period_ns": 5.0, "domain_kind": "primary"}]})
    out = tmp_path / "reports" / "sdc_validator.json"
    cp = _run([str(project), "--l8", str(l8), "--json", str(out)])
    assert cp.returncode == 1
    payload = json.loads(out.read_text())
    assert payload["verdict"] == "FAIL"
    assert payload["issues"], payload


# --- false-red guards: shapes that must NOT be reported ---------------------
def test_l8_clock_matched_by_source_pin_across_differently_named_sdc(tmp_path):
    """A project legitimately ships an FPGA SDC that names the same physical
    clock differently (`-name clk_main [get_ports {clk}]`). Matching by
    target port must keep that green."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "fpga.sdc",
              "create_clock -name clk_main -period 10 [get_ports {clk}]\n"
              "set_input_delay  -clock clk_main -max 4.0 [get_ports {x}]\n"
              "set_output_delay -clock clk_main -max 4.0 [get_ports {p}]\n")
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "period_ns": 10.0, "domain_kind": "primary",
         "source_pin": "clk"}]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 0, cp.stdout
    assert "[PASS]" in cp.stdout


def test_l8_derived_clock_is_not_held_to_create_clock(tmp_path):
    """A generated clock is constrained by create_generated_clock, which is
    derived_clock_sdc_required_check's job — this gate must not double-fail
    it for lacking a create_clock."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "period_ns": 10.0, "domain_kind": "primary"},
        {"name": "clk_div2", "period_ns": 20.0, "domain_kind": "derived",
         "derived_from": "clk"},
    ]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 0, cp.stdout


def test_l8_range_only_record_pins_no_period(tmp_path):
    """A record carrying only a frequency RANGE does not pin a period and
    must not synthesise one (nor a false contradiction)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _SDC_10NS)
    l8 = _write_l8(project, {"clock_domains": [
        {"name": "clk", "period_ns": 10.0, "domain_kind": "primary"},
        {"name": "clk", "freq_low_mhz": 41.7, "high_mhz": 125.0,
         "domain_kind": "primary"},
    ]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 0, cp.stdout


def test_l8_period_tolerance_absorbs_conversion_rounding(tmp_path):
    """133 MHz -> 7.5188 ns; an SDC written as 7.52 ns is the same
    constraint, not a mismatch."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc",
              "create_clock -name clk -period 7.52 [get_ports clk]\n"
              "set_input_delay  2 -clock clk [all_inputs]\n"
              "set_output_delay 2 -clock clk [all_outputs]\n")
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "freq_mhz": 133.0, "domain_kind": "primary"}]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 0, cp.stdout


# --- DIRECTION-1 GUARDS: pass on BOTH the base tree and the fixed tree ------
def test_direction1_no_l8_flag_behaviour_unchanged(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _GOOD_SDC)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[PASS] sdc_validator_check" in cp.stdout


def test_direction1_l8_with_empty_clock_lists_stays_vacuous(tmp_path):
    """Many IC classes emit an L8 whose timing_windows / timing_constants /
    waveforms are all empty and which carries no clock records at all. That
    must remain a plain PASS — an absent declaration is not a violated one."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _GOOD_SDC)
    l8 = _write_l8(project, {"schema_version": "1", "timing_windows": [],
                             "timing_constants": [], "waveforms": [],
                             "clocks": [], "clock_domains": []})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 0, cp.stdout
    assert "[PASS]" in cp.stdout


def test_direction1_missing_l8_file_is_not_an_error(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _GOOD_SDC)
    cp = _run([str(project), "--l8", str(tmp_path / "nope.json")])
    assert cp.returncode == 0, cp.stdout


def test_direction1_three_directive_check_still_blocking(tmp_path):
    """The pre-existing structural test is preserved, not replaced."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc",
              "create_clock -name clk -period 10.0 [get_ports clk]\n")
    l8 = _write_l8(project, {"clocks": [
        {"name": "clk", "period_ns": 10.0, "domain_kind": "primary"}]})
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1
    assert "missing set_input_delay" in cp.stdout
    assert "missing set_output_delay" in cp.stdout


def test_direction1_json_report_on_pass_keeps_its_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "top.sdc", _GOOD_SDC)
    out = tmp_path / "reports" / "sdc_validator.json"
    cp = _run([str(project), "--json", str(out)])
    assert cp.returncode == 0
    payload = json.loads(out.read_text())
    assert payload["verdict"] == "PASS"
    assert payload["issues"] == []
    assert len(payload["sdc_files_checked"]) == 1
