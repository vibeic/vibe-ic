#!/usr/bin/env python3
"""Tests for cts_quality_check.py — Step 19 CTS substance gate.

Pins the anti-fabrication hardening: the old gate flipped PASS the moment
post_cts.def + clock_tree.rpt FILES appeared, with zero content check.
This checker must:
  * PASS on a real TritonCTS report + placed post_cts.def (good substance);
  * FAIL on the runner's vacuous "(CTS not invoked)" fallback stub;
  * FAIL when zero clock buffers were inserted (the real backend failure);
  * FAIL on a report carrying no skew/latency/depth number (vacuous);
  * FAIL on report-vs-DEF buffer-count inconsistency;
  * FAIL on an UNPLACED instance;
  * enforce skew <= target ONLY when the artefact states a target, never
    fabricating one;
  * FAIL honestly on missing / empty / garbage artefacts (never vacuous PASS).

Fixtures mirror the real corpus shape, e.g.
benchmark_clean/subservient_v0125_fresh/phase3/stage3/cts/clock_tree.rpt and
.../pnr/post_cts.def.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "cts_quality_check.py"

_spec = importlib.util.spec_from_file_location("cts_quality_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# fixture builders
# ----------------------------------------------------------------------
def _cts_dir(project: Path) -> Path:
    d = project / "phase3" / "stage3" / "cts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pnr_dir(project: Path) -> Path:
    d = project / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    return d


# A realistic TritonCTS report (trimmed from the real corpus). created=145
# clock buffers, path depth 3-3, max level 7.
_GOOD_RPT = """# Auto-extracted CTS report (OpenROAD-derived) — v1.6.36
# Source: phase3/stage3/pnr/openroad.log

[INFO CTS-0050] Root buffer is sky130_fd_sc_hd__clkbuf_16.
[INFO CTS-0051] Sink buffer is sky130_fd_sc_hd__clkbuf_4.
[INFO CTS-0007] Net "i_clk" found for clock "clk".
[INFO CTS-0010]  Clock net "i_clk" has 1393 sinks.
[INFO CTS-0008] TritonCTS found 1 clock nets.
[INFO CTS-0028]  Total number of sinks: 1393.
[INFO CTS-0035]  Number of sinks covered: 1393.
[INFO CTS-0018]     Created 145 clock buffers.
[INFO CTS-0012]     Minimum number of buffers in the clock path: 3.
[INFO CTS-0013]     Maximum number of buffers in the clock path: 3.
[INFO CTS-0015]     Created 145 clock nets.
[INFO CTS-0017]     Max level of the clock tree: 7.
[INFO CTS-0098] Clock net "i_clk"
[INFO CTS-0099]  Sinks 1497
[INFO CTS-0100]  Leaf buffers 0
[INFO CTS-0101]  Average sink wire length 444.44 um
[INFO CTS-0102]  Path depth 3 - 3
[INFO CTS-0207]  Dummy loads inserted 104
"""


def _def_with_clkbufs(n_clk: int, n_other: int = 10, unplaced: int = 0,
                      declared=None) -> str:
    """Build a minimal DEF with COMPONENTS carrying n_clk clock buffers
    (all PLACED unless `unplaced` says otherwise) + n_other std cells."""
    total = n_clk + n_other + unplaced
    head = (
        'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
        "DESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 416000 416000 ) ;\n"
    )
    decl = declared if declared is not None else total
    lines = [f"COMPONENTS {decl} ;"]
    for i in range(n_clk):
        lines.append(
            f"    - clkbuf_{i}_i_clk sky130_fd_sc_hd__clkbuf_4 "
            f"+ SOURCE TIMING + PLACED ( {1000+i} {2000+i} ) N ;")
    for i in range(n_other):
        lines.append(
            f"    - _cell_{i}_ sky130_fd_sc_hd__inv_1 "
            f"+ PLACED ( {3000+i} {4000+i} ) N ;")
    for i in range(unplaced):
        lines.append(
            f"    - clkbuf_unp_{i} sky130_fd_sc_hd__clkbuf_4 "
            f"+ UNPLACED ;")
    lines.append("END COMPONENTS")
    lines.append("END DESIGN")
    return head + "\n".join(lines) + "\n"


def _run(project: Path):
    out_json = project / "report.json"
    rc = mod.main([str(project), "--json", str(out_json)])
    report = json.loads(out_json.read_text()) if out_json.is_file() else None
    return rc, report


def _rules(rep):
    return {f["rule"] for f in rep["findings"]}


# ----------------------------------------------------------------------
# PASS — real CTS substance
# ----------------------------------------------------------------------
def test_pass_good_report_and_def(tmp_path):
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(_GOOD_RPT)
    # report says 145 buffers; DEF carries 150 placed clk instances -> within
    # the consistency factor.
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    r = _rules(rep)
    assert "CTS_SUBSTANCE_OK" in r
    assert "LATENCY_METRIC_PRESENT" in r
    assert rep["metrics"]["report_created_buffers"] == 145
    assert rep["metrics"]["def_clock_buffers"] == 150
    assert rep["metrics"]["path_depth"] == [3, 3]


def test_pass_with_numeric_skew_within_stated_target(tmp_path):
    rpt = _GOOD_RPT + (
        "[INFO STA] Clock skew  0.0184 ns\n"
        "max allowed skew 0.0500 ns\n"
        "insertion latency 0.220 ns\n"
    )
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(rpt)
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert "SKEW_WITHIN_TARGET" in _rules(rep)
    assert rep["metrics"]["skew_value"] == 0.0184


# ----------------------------------------------------------------------
# FAIL — the real backend failures this gate guards
# ----------------------------------------------------------------------
def test_fail_vacuous_cts_not_invoked_stub(tmp_path):
    # The runner's fallback when OpenROAD CTS produced nothing.
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(
        "# Auto-extracted CTS report (OpenROAD-derived) — v1.6.36\n"
        "# Source: phase3/stage3/pnr/openroad.log\n\n"
        "(OpenROAD CTS not invoked or zero output captured)\n")
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(0, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "CTS_NOT_INVOKED" in _rules(rep)


def test_fail_zero_clock_buffers(tmp_path):
    # Report parses (has metrics) but says 0 buffers AND DEF has none — the
    # clock would ship unbuffered. This is the silent backend failure.
    rpt = _GOOD_RPT.replace("Created 145 clock buffers", "Created 0 clock buffers")
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(rpt)
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(0, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "ZERO_CLOCK_BUFFERS" in _rules(rep)


def test_fail_report_has_no_skew_latency_or_depth(tmp_path):
    # Buffers inserted, but the report carries NO depth/level/skew/latency
    # number at all -> vacuous report.
    rpt = (
        "# Auto-extracted CTS report — v1.6.36\n\n"
        "[INFO CTS-0007] Net \"clk\" found for clock \"clk\".\n"
        "[INFO CTS-0018]     Created 12 clock buffers.\n"
        "[INFO CTS-0015]     Created 12 clock nets.\n"
    )
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(rpt)
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(12, n_other=100))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "NO_LATENCY_OR_SKEW_METRIC" in _rules(rep)


def test_fail_report_vs_def_buffer_count_inconsistent(tmp_path):
    # Report claims 145 buffers but the placed DEF has only 2 -> gross
    # inconsistency (report fabricated relative to the physical DEF).
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(_GOOD_RPT)
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(2, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "BUFFER_COUNT_INCONSISTENT" in _rules(rep)


def test_fail_unplaced_clock_buffer(tmp_path):
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(_GOOD_RPT)
    # 150 placed clk bufs but 3 UNPLACED -> structural failure.
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000, unplaced=3))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "UNPLACED_INSTANCE" in _rules(rep)


def test_fail_skew_exceeds_stated_target(tmp_path):
    rpt = _GOOD_RPT + (
        "[INFO STA] Clock skew  0.0900 ns\n"
        "skew target 0.0500 ns\n"
    )
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(rpt)
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "SKEW_EXCEEDS_TARGET" in _rules(rep)


def test_skew_target_from_clock_plan_enforced(tmp_path):
    # Target lives in clock_plan.json (not the report) and is exceeded.
    rpt = _GOOD_RPT + "[INFO STA] Worst skew = 0.030 ns\n"
    cts = _cts_dir(tmp_path)
    cts.joinpath("clock_tree.rpt").write_text(rpt)
    cts.joinpath("clock_plan.json").write_text(json.dumps(
        {"primary_clock": "clk", "max_skew_ns": 0.010}))
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "SKEW_EXCEEDS_TARGET" in _rules(rep)


# ----------------------------------------------------------------------
# Missing / garbage data -> honest FAIL (never vacuous PASS); SKIP only
# on operational absence of the project dir.
# ----------------------------------------------------------------------
def test_fail_missing_artefacts(tmp_path):
    # project dir exists but neither CTS artefact present
    (tmp_path / "phase3").mkdir()
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "REQUIRED_ARTEFACT_MISSING" in _rules(rep)


def test_fail_missing_def_only(tmp_path):
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(_GOOD_RPT)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "REQUIRED_ARTEFACT_MISSING" in _rules(rep)


def test_fail_empty_report(tmp_path):
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text("")
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "REPORT_EMPTY" in _rules(rep)


def test_fail_garbage_def_no_components(tmp_path):
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(_GOOD_RPT)
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        "not a def file at all\nrandom bytes\n")
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "DEF_NO_COMPONENTS" in _rules(rep)


def test_skip_only_when_project_dir_missing(tmp_path):
    rc = mod.main([str(tmp_path / "does_not_exist")])
    assert rc == 2


# ----------------------------------------------------------------------
# Waiver path
# ----------------------------------------------------------------------
def test_waived_when_missing_and_waiver_present(tmp_path):
    (tmp_path / "phase3").mkdir()
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "cts_quality",
            "ticket": "WAIVE-19",
            "reason": "FPGA-target run; no ASIC CTS",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"


# ----------------------------------------------------------------------
# Boundary: skew exactly at target passes; missing measurement does not
# fabricate one.
# ----------------------------------------------------------------------
def test_pass_skew_exactly_at_target(tmp_path):
    rpt = _GOOD_RPT + (
        "[INFO STA] Clock skew 0.0500 ns\n"
        "skew target 0.0500 ns\n"
    )
    _cts_dir(tmp_path).joinpath("clock_tree.rpt").write_text(rpt)
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert "SKEW_WITHIN_TARGET" in _rules(rep)


def test_target_present_but_no_skew_measurement_does_not_fabricate(tmp_path):
    # clock_plan.json states a target but the report has no numeric skew.
    # The gate must NOT invent a measured value; it passes on the
    # buffer+depth substance and records SKEW_TARGET_NO_MEASUREMENT.
    cts = _cts_dir(tmp_path)
    cts.joinpath("clock_tree.rpt").write_text(_GOOD_RPT)  # no numeric skew
    cts.joinpath("clock_plan.json").write_text(json.dumps(
        {"max_skew_ns": 0.05}))
    _pnr_dir(tmp_path).joinpath("post_cts.def").write_text(
        _def_with_clkbufs(150, n_other=4000))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert "SKEW_TARGET_NO_MEASUREMENT" in _rules(rep)
    assert "SKEW_EXCEEDS_TARGET" not in _rules(rep)
