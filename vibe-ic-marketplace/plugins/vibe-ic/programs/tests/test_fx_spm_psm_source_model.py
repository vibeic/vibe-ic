"""FX_SPM_DEF review fix: a padless block's promoted supply pins must not
become PSM's voltage sources.

`define_pdn_grid -pins` (N7) makes the strap layers of a core-only block its
supply pins. OpenROAD PSM, with no -vsrc file, sources from every BPin shape
(`IRSolver::generateSourceNodes`), so every strap became an ideal supply.
MEASURED on the same spm x gf180mcuD layout (image 0.3.83):

    pins as sources      Metal4 strap current 0 A, EM peak 1.66e-4 A,
                         IR VDD/VSS 0.591 / 0.864 mV, no PSM-0073
    pins PSM_DISCONNECT  Metal4 7.72e-4 A, IR 2.11 / 4.46 mV, PSM-0073 back
    BTerms deleted       identical to PSM_DISCONNECT

Every PSM session (static IR/EM, transient IR, the pre-route EM presweep) is
driven here under tclsh, with a database stand-in whose `analyze_power_grid`
counts what PSM would take as sources: BPins of supply nets without a true
PSM_DISCONNECT property (`BPinNode::shouldConnect`). Only file writes of the
tool are faked.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / "tests"))

import _psm_source_model as SM  # noqa: E402
import dynamic_ir_vectored_emit as DYN  # noqa: E402
from _ppa import pdn_em_presweep as PES  # noqa: E402
from _tcl_walk import walk as _walk  # noqa: E402




# The database: VDD/VSS each carry one SPECIAL BTerm (the promoted pins); a
# second supply VAUX carries an ORDINARY BTerm (a declared port, not a
# promoted strap), which must stay a source; a signal net carries one too. `analyze_power_grid` reports how many
# supply BPins PSM would still source from.
_DB = r"""
namespace eval ord {}
namespace eval odb {}
rename unknown _tcl_unknown
proc unknown {args} { return "" }
rename exit _tcl_exit
proc exit {args} { puts TCL_DONE; _tcl_exit 0 }
set ::pv [dict create]
set ::psm_fail 0
set ::supply_bpins {bp_v1 bp_v2 bp_g1 bp_a1}
proc ord::get_db_block {} { return blk }
proc blk {m args} {
  switch -- $m {
    getInsts { return $::insts }
    getNets { return {net_vdd net_vss net_sig net_aux} }
    default { return "" }
  }
}
proc net_vdd {m args} { switch -- $m { getSigType {return POWER} getBTerms {return bt_v} getName {return VDD} default {return ""} } }
proc net_vss {m args} { switch -- $m { getSigType {return GROUND} getBTerms {return bt_g} getName {return VSS} default {return ""} } }
proc net_sig {m args} { switch -- $m { getSigType {return SIGNAL} getBTerms {return bt_s} default {return ""} } }
proc bt_v {m args} { switch -- $m { isSpecial {return 1} getBPins {return {bp_v1 bp_v2}} default {return ""} } }
proc bt_g {m args} { switch -- $m { isSpecial {return 1} getBPins {return {bp_g1}} default {return ""} } }
proc net_aux {m args} { switch -- $m { getSigType {return POWER} getBTerms {return bt_a} getName {return VAUX} default {return ""} } }
proc bt_a {m args} { switch -- $m { isSpecial {return 0} getBPins {return {bp_a1}} default {return ""} } }
proc bt_s {m args} { switch -- $m { isSpecial {return 0} getBPins {return {bp_s1}} default {return ""} } }
proc inst_core {m args} { switch -- $m { getMaster {return m_core} isPlaced {return 1} isDoNotTouch {return 0} default {return ""} } }
proc inst_pad {m args} { switch -- $m { getMaster {return m_pad} isPlaced {return 1} isDoNotTouch {return 0} default {return ""} } }
proc m_core {m args} { switch -- $m { isPad {return 0} default {return ""} } }
proc m_pad {m args} { switch -- $m { isPad {return 1} default {return ""} } }
proc propcall {p m args} { if {$m eq "setValue"} { dict set ::pv $p [lindex $args 0] } }
proc odb::dbBoolProperty_create {obj name v} {
  set p "prop_${obj}_$name"; dict set ::pv $p $v
  interp alias {} $p {} propcall $p
  return $p
}
proc odb::dbBoolProperty_find {obj name} {
  set p "prop_${obj}_$name"
  if {[dict exists $::pv $p]} { return $p }
  return NULL
}
proc odb::dbProperty_destroy {p} { dict unset ::pv $p; interp alias {} $p {} }
proc analyze_power_grid {args} {
  set n 0
  foreach bp $::supply_bpins {
    set p "prop_${bp}_PSM_DISCONNECT"
    if {!([dict exists $::pv $p] && [dict get $::pv $p])} { incr n }
  }
  puts "PSM_SOLVE sources=$n"
  if {$::psm_fail} { error "psm failed" }
}
"""


def _run(tcl: str, insts, tmp_path: Path, tail: str = "") -> str:
    script = (_DB + f"set ::insts {{{' '.join(insts)}}}\n" + tcl + "\n" + tail
              + "\nputs TCL_DONE\n")
    tmp_path.mkdir(parents=True, exist_ok=True)
    out, err, route = _walk(script, "", tmp_path)
    assert "TCL_DONE" in out, f"Tcl did not finish via {route}:\n{out}\n{err}"
    return out


def _solves(out: str):
    return [ln.split("=", 1)[1] for ln in out.splitlines()
            if ln.startswith("PSM_SOLVE sources=")]


# ---- static IR / EM (step 24/25, the runner's own session) ----------------









# ---- transient IR (step 24 dynamic tier) ----------------------------------

def test_transient_ir_sources_from_no_promoted_pin(tmp_path):
    lib = tmp_path / "sc.lib"
    lib.write_text("library (sc) { }\n")
    tcl = DYN._build_transient_tcl(
        tmp_path / "d.def", tmp_path / "t.lef", tmp_path / "c.lef", lib, [],
        None, ["VDD", "VSS"], 24.0, 10, None, {}, "Metal")
    out = _run(tcl, ["inst_core"], tmp_path / "t")
    assert _solves(out) and set(_solves(out)) == {"1"}, out
    out = _run(tcl, ["inst_pad"], tmp_path / "d")
    assert set(_solves(out)) == {"4"}, out


# ---- pre-route EM presweep (inside the PnR session) -----------------------

def _presweep_tcl() -> str:
    tcl = PES.session_tcl(sweep_dir="__SWEEP__", python="python3",
                          nets={"VDD": 5.0, "VSS": 0.0}, corner=None,
                          declared_pads=[], stage_marker="PNR_STAGE:")
    return tcl.replace("set _pes_dir {__SWEEP__}",
                       "set _pes_dir [file join [file dirname [info script]] pes]"
                       "\nfile mkdir $_pes_dir")


def test_presweep_measures_without_pin_sources_and_restores_the_pins(tmp_path):
    tcl = _presweep_tcl()
    procs = tcl[:tcl.index("set _pes_k 0")]
    out = _run(procs, ["inst_core"], tmp_path / "ok",
               "_vibeic_pes_measure 0 {}\nputs \"PROPS_LEFT [dict size $::pv]\"")
    assert _solves(out) and set(_solves(out)) == {"1"}, out
    # this session writes the DEF later: no mark may survive the measurement
    assert "PROPS_LEFT 0" in out


def test_presweep_restores_the_pins_when_psm_fails(tmp_path):
    tcl = _presweep_tcl()
    procs = tcl[:tcl.index("set _pes_k 0")]
    out = _run(procs, ["inst_core"], tmp_path / "fail",
               "set ::psm_fail 1\n"
               "set rc [catch {_vibeic_pes_measure 0 {}} e]\n"
               "puts \"MEASURE_RC $rc $e\"\n"
               "puts \"PROPS_LEFT [dict size $::pv]\"")
    assert "MEASURE_RC 1 psm failed" in out
    assert "PROPS_LEFT 0" in out


def test_presweep_labels_its_source_model(tmp_path):
    tcl = _presweep_tcl()
    head = tcl[:tcl.index("set _pes_k 0")]
    start = tcl.index("  set _pes_vsrc [dict create]")
    stop = tcl.index("\n", tcl.index("source_model.txt w]", start))
    block = tcl[start:stop]
    out = _run(head + block, ["inst_core"], tmp_path / "p",
               "puts \"MODEL $_pes_model\"\nputs \"PROPS_LEFT [dict size $::pv]\"")
    assert "MODEL psm_generated_bumps_promoted_pins_excluded" in out
    assert "PROPS_LEFT 0" in out
    out = _run(head + block, ["inst_pad"], tmp_path / "q",
               "puts \"MODEL $_pes_model\"")
    assert "MODEL psm_default_bterms_undeclared_pads" in out


# ---- the parser the records use ------------------------------------------

def test_describe_reads_the_sessions_own_line():
    assert SM.read("no marker here") is None
    assert "no PSM_SOURCE_MODEL line" in SM.describe("")["model"]
    d = SM.describe("PSM_SOURCE_MODEL: promoted_supply_pins_excluded=0 "
                    "placed_pads=4\n")
    assert d["model"].startswith("PSM default sources: the design's supply BTerms")
