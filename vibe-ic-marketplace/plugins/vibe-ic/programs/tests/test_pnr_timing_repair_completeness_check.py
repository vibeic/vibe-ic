"""Tests for pnr_timing_repair_completeness_check.py.

Covers the sta-review captured-note rule: a PnR Tcl that runs ONLY
`repair_timing -hold` (and not set_wire_rc + repair_design +
repair_timing -setup) is the sha256 silicon-DOA anti-pattern.
"""
import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import pnr_timing_repair_completeness_check as mod  # noqa: E402


# ---- canonical good PnR flow (mirrors the phase3 runner template) ----
GOOD_FLOW = """\
read_liberty sky130.lib
read_verilog design.v
link_design top
read_sdc design.sdc

if {[catch {set_wire_rc -signal -layer met1} _swr_sig]} {
  catch {set_wire_rc -layer met1}
}
catch {set_wire_rc -clock -layer met5}
catch {estimate_parasitics -placement}
catch {repair_design}
catch {repair_timing -setup}
catch {detailed_placement}

clock_tree_synthesis -buf_list {sky130_fd_sc_hd__clkbuf_4}
catch {repair_timing -hold}
detailed_placement

global_route
catch {estimate_parasitics -global_routing}
catch {repair_design}
catch {repair_timing -setup}
catch {repair_timing -hold}
detailed_placement
"""

# ---- the silicon-DOA anti-pattern: ONLY hold-repair ----
HOLD_ONLY_FLOW = """\
read_liberty sky130.lib
read_verilog design.v
link_design top
read_sdc design.sdc
global_placement
detailed_placement
clock_tree_synthesis -buf_list {sky130_fd_sc_hd__clkbuf_4}
repair_timing -hold
detailed_placement
global_route
detailed_route
"""

# ---- missing only the EXPECTED (estimate_parasitics + hold) -> WARN ----
SETUP_NO_HOLD_FLOW = """\
read_verilog design.v
link_design top
set_wire_rc -signal -layer met1
set_wire_rc -clock -layer met5
repair_design
repair_timing -setup
detailed_placement
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_pass_full_flow(tmp_path, capsys):
    """All 3 required commands present (even inside catch{}) -> PASS, exit 0."""
    p = _write(tmp_path, "pnr_good.tcl", GOOD_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["setup_repair_chain_present"] is True
    assert rep["summary"]["hold_repair_present"] is True
    assert rep["summary"]["missing_required"] == []
    assert rep["summary"]["hold_only_antipattern"] is False
    captured = capsys.readouterr()
    assert "PASS:" in captured.out


def test_fail_hold_only_antipattern(tmp_path, capsys):
    """repair_timing -hold but no setup chain -> FAIL, exit 1, antipattern flag."""
    p = _write(tmp_path, "pnr_hold_only.tcl", HOLD_ONLY_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["summary"]["hold_only_antipattern"] is True
    assert rep["summary"]["setup_repair_chain_present"] is False
    # all 3 required are flagged missing
    missing = rep["summary"]["missing_required"]
    assert any("set_wire_rc" in m for m in missing)
    assert any("repair_design" in m for m in missing)
    assert any("repair_timing -setup" in m for m in missing)
    captured = capsys.readouterr()
    assert "hold_only_antipattern" in captured.out


def test_warn_setup_present_but_no_hold(tmp_path):
    """Setup chain present, but missing estimate_parasitics + hold -> WARN, exit 0."""
    p = _write(tmp_path, "pnr_warn.tcl", SETUP_NO_HOLD_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 0  # WARN is non-blocking
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "WARN"
    assert rep["summary"]["setup_repair_chain_present"] is True
    assert rep["summary"]["missing_required"] == []
    # estimate_parasitics + hold are the expected-missing ones
    me = rep["summary"]["missing_expected"]
    assert any("estimate_parasitics" in m for m in me)
    assert any("repair_timing -hold" in m for m in me)


def test_fail_missing_one_required(tmp_path):
    """Has set_wire_rc + repair_design but no repair_timing -setup -> FAIL."""
    flow = (
        "read_verilog d.v\nlink_design top\n"
        "set_wire_rc -signal -layer met1\n"
        "repair_design\n"
        "repair_timing -hold\n"
        "detailed_placement\n"
    )
    p = _write(tmp_path, "pnr_partial.tcl", flow)
    rc = mod.main([str(p)])
    assert rc == 1
    verdict, findings, summary = mod.audit(p)
    assert verdict == "FAIL"
    assert any("repair_timing -setup" in m for m in summary["missing_required"])
    # not a hold-only antipattern because set_wire_rc + repair_design present
    assert summary["hold_only_antipattern"] is False


def test_commented_out_does_not_count(tmp_path):
    """A fully-commented repair_timing -setup line does NOT count as present."""
    flow = (
        "read_verilog d.v\nlink_design top\n"
        "set_wire_rc -signal -layer met1\n"
        "repair_design\n"
        "# repair_timing -setup   ;# TODO turn this back on\n"
        "repair_timing -hold\n"
    )
    p = _write(tmp_path, "pnr_commented.tcl", flow)
    rc = mod.main([str(p)])
    assert rc == 1
    verdict, _, summary = mod.audit(p)
    assert verdict == "FAIL"
    assert any("repair_timing -setup" in m for m in summary["missing_required"])


def test_catch_guarded_counts_as_present(tmp_path):
    """A command wrapped in `catch {...}` still executes -> counts as present."""
    flow = (
        "read_verilog d.v\nlink_design top\n"
        "catch {set_wire_rc -signal -layer met1}\n"
        "catch {repair_design}\n"
        "catch {repair_timing -setup}\n"
    )
    p = _write(tmp_path, "pnr_catch.tcl", flow)
    verdict, _, summary = mod.audit(p)
    assert summary["setup_repair_chain_present"] is True
    assert summary["missing_required"] == []


# ---- honest-FAIL edge cases: missing / empty / garbage input ----

def test_missing_file_is_error_not_pass(tmp_path, capsys):
    rc = mod.main([str(tmp_path / "nope.tcl")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_empty_file_is_error_not_pass(tmp_path, capsys):
    p = _write(tmp_path, "empty.tcl", "   \n  \n")
    rc = mod.main([str(p)])
    assert rc == 2
    assert "empty" in capsys.readouterr().err


def test_non_tcl_garbage_is_error_not_pass(tmp_path, capsys):
    """A file with no OpenROAD anchors must NOT vacuously PASS -> exit 2."""
    p = _write(tmp_path, "readme.txt",
               "This is a project README.\nIt has prose, no Tcl flow.\n")
    rc = mod.main([str(p)])
    assert rc == 2
    assert "no OpenROAD" in capsys.readouterr().err


# ---- DIRECTORY MODE (added when the gate was wired into Step 17) ----
#
# The gate is wired UNCONDITIONALLY on the P&R DIRECTORY, not on a literal
# `pnr.tcl`. Both halves are load-bearing and both are pinned here.

def test_directory_finds_a_differently_named_pnr_script(tmp_path):
    """The published run whose defect this gate exists for names its script
    `pnr_fixed.tcl`. A literal `pnr.tcl` wire would have missed exactly it."""
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr_fixed.tcl").write_text(HOLD_ONLY_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(d), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["summary"]["hold_only_antipattern"] is True
    assert rep["script"].endswith("pnr_fixed.tcl")


def test_directory_takes_the_worst_verdict(tmp_path):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(GOOD_FLOW)
    (d / "pnr_eco.tcl").write_text(HOLD_ONLY_FLOW)
    out = tmp_path / "rep.json"
    rc = mod.main([str(d), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert len(rep["audited"]) == 2
    assert rep["verdict"] == "FAIL"


def test_directory_ignores_non_pnr_tcl_siblings(tmp_path):
    """`sta_one.tcl` / `magic_stream_out.tcl` live in the same directory and
    are not P&R flows; auditing them would be a FAIL for the wrong reason."""
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(GOOD_FLOW)
    (d / "magic_stream_out.tcl").write_text("gds write out.gds\n")
    out = tmp_path / "rep.json"
    rc = mod.main([str(d), "--json", str(out)])
    assert rc == 0
    assert len(json.loads(out.read_text())["audited"]) == 1


def test_directory_with_no_pnr_script_is_the_disclosed_skip_tier(tmp_path):
    """rc=2 is the flow's disclosed-skip tier. It is what lets this gate be
    wired UNCONDITIONALLY instead of behind a `condition_files_exist` on the
    very script whose absence would be interesting."""
    d = tmp_path / "pnr"
    d.mkdir()
    rc = mod.main([str(d)])
    assert rc == 2


def test_missing_directory_is_also_the_skip_tier(tmp_path):
    rc = mod.main([str(tmp_path / "no_such_dir")])
    assert rc == 2
