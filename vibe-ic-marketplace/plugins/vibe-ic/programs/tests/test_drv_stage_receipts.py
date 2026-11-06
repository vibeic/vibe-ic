"""DRV sign-off standard section 1: the flow PRODUCES the stage receipts.

`drv_capture_plan._stages` reads `reports/phase3/drv_stages/<stage>.json`.
Before this, no stage wrote one, so every real run FAILed "required stage
absent".  These tests drive the producer the way the flow does:

* `librelane_contract.run_chain` with a stand-in `docker` that executes the
  shipped probe (`drv_stage_probe.tcl`) in a real Tcl interpreter against a
  stand-in OpenROAD / OpenSTA command set (only the tool's writes are fake);
* the plan reader over the receipts that produced, including the run-instance
  binding (a receipt from another run is refused);
* the SPECIALNETS zero-wiring geometry proof (R-0928-DRV-IC).
"""
from __future__ import annotations

import json
import shutil
import stat
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import librelane_contract as ll  # noqa: E402

TCLSH = shutil.which("tclsh")

#: A stand-in `docker` for `python3 -m librelane.steps run`: it runs the
#: step's command sequence in tclsh after sourcing the init file the real tool
#: would source ($HOME/.openroad, or $HOME/.sta for the sign-off STA binary).
#: The stage commands are stand-ins that record their calls; the probe is the
#: shipped file, executed.
_FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(argv) + "\n")
if "librelane.steps" not in argv:
    sys.exit(0)
out = argv[argv.index("-o") + 1]
os.makedirs(out, exist_ok=True)
step = argv[argv.index("--id") + 1]
home = next((a[5:] for a in argv if a.startswith("HOME=")), None)
cfg = json.load(open(argv[argv.index("-c") + 1]))
fanout = cfg.get("FAKE_SDC_FANOUT", 4)
sta = step == "OpenROAD.STAPostPNR"
tcl = []
if not sta:
    tcl.append("namespace eval ::ord {}")
tcl.append(f"set ::env(SAVE_SDC) {{{out}/top.sdc}}")
tcl.append(f"set ::fo {fanout}")
tcl.append(f"set ::warmup {int(bool(cfg.get('FAKE_REPORT_WARMUP')))}")
tcl.append(r"""
set ::redirect ""
proc write_sdc {args} {
    set f [open [lindex $args end] w]
    puts $f "create_clock -name clk -period 24 \[get_ports clk\]"
    puts $f "set_max_fanout $::fo \[current_design\]"
    puts $f "set_max_transition 3 \[current_design\]"
    puts $f "set_max_capacitance 0.2 \[current_design\]"
    close $f
}
proc emit {text} {
    if {$::redirect eq ""} { puts $text } else {
        set f [open $::redirect a]; puts $f $text; close $f }
}
proc report_check_types {args} {
    if {$::warmup} {
        sta::redirect_file_begin /dev/null
        sta::redirect_file_end
    }
    set redirect 0
    foreach symbol {> >>} {
        set at [lsearch -exact $args $symbol]
        if {$at >= 0} {
            set path [lindex $args [expr {$at + 1}]]
            if {$symbol eq ">"} { sta::redirect_file_begin $path } else {
                sta::redirect_file_append_begin $path
            }
            set redirect 1
        }
    }
    if {"-violators" in $args} {
        emit "max fanout\n\nPin u1/Z\nmax fanout $::fo\nfanout 5\n-----------\nSlack -1 (VIOLATED)"
    } else {
        # every pin with a fanout limit: an IO pad (library default 1, the
        # worst slack) and a core driver under the SDC's limit
        emit "max fanout\n\nPin u_pad/Y\nmax fanout 1\nfanout 3\n-----------\nSlack -2 (VIOLATED)\n\nPin u1/Z\nmax fanout $::fo\nfanout 2\n-----------\nSlack 2 (MET)"
    }
    if {$redirect} { sta::redirect_file_end }
}
proc get_pins {args} { set name [lindex $args end]; if {[string first / $name] >= 0} { return $name }; return {} }
proc get_cells {args} { return [lindex [split [lindex $args end] /] 0] }
namespace eval ::sta {}
proc ::sta::redirect_file_append_begin {path} {
    if {$::redirect ne ""} { error UTL-0102 }
    set ::redirect $path
}
proc ::sta::redirect_file_end {} { set ::redirect "" }
proc ::sta::redirect_file_begin {path} {
    if {$::redirect ne ""} { error UTL-0102 }
    close [open $path w]; set ::redirect $path
}
proc ::sta::max_fanout_check_limit {} { return 1 }   ;# the worst pin: the pad
proc ::sta::max_slew_violation_count {} { return 0 }
proc ::sta::max_capacitance_violation_count {} { return 0 }
proc ::sta::max_fanout_violation_count {} { return 1 }
proc record {command args} {
    set probe [file join [file dirname $::env(SAVE_SDC)] vibeic_drv_stage]
    set f [open [file join [file dirname $::env(SAVE_SDC)] calls.log] a]
    puts $f [list $command $args snapshot_before=[llength [glob -nocomplain $probe/*.pre.sdc]]]
    close $f
}
proc repair_design {args} { record repair_design {*}$args; return repaired }
proc clock_tree_synthesis {args} { record clock_tree_synthesis {*}$args }
proc all_clocks {} { return clk }
proc get_property {obj prop} {
    if {$prop eq "is_propagated"} { return $::propagated }
    if {$prop eq "ref_name"} { return [expr {$obj eq "u_pad" ? "padcell" : "bufcell"}] }
    return $obj
}
set ::propagated 0
proc set_propagated_clock {clocks} { set ::propagated 1 }
proc unset_propagated_clock {clocks} { set ::propagated 0 }
proc estimate_parasitics {args} {}
if {[namespace exists ::ord]} { proc ::ord::get_db_block {} { return blk } }
proc blk {method} { return {net0} }
proc net0 {method} {
    switch $method {
        getSigType { return CLOCK }
        getName { return clknet_0 }
        getITerms { return {itd it1 it2} }
        getBTerms { return {} }
    }
}
proc iterm {self method} {
    switch $method {
        isOutputSignal { return [expr {$self eq "itd"}] }
        isInputSignal { return [expr {$self ne "itd"}] }
        getInst { return inst_$self }
        getMTerm { return mterm_$self }
    }
}
foreach it {itd it1 it2} {
    proc $it {method} "return \[iterm $it \$method\]"
    proc inst_$it {method} "return buf_$it"
    proc mterm_$it {method} "return Z"
}
""")
if home:
    tcl.append(f"source {{{os.path.join(home, '.sta' if sta else '.openroad')}}}")
if step in ("OpenROAD.RepairDesignPostGPL", "OpenROAD.RepairDesignPostGRT",
            "Vibeic.PostRouteRepair"):
    tcl.append("puts [repair_design -verbose -slew_margin 20]")
elif step == "OpenROAD.CTS":
    tcl.append("clock_tree_synthesis -root_buf clkbuf_16 -sink_clustering_size 4 "
               "-sink_clustering_enable")
    tcl.append("if {$::propagated} { error {probe left the clock propagated} }")
elif sta:
    tcl.append("report_check_types -max_slew -max_capacitance -max_fanout "
               "-violators -corner nom_tt")
tcl.append("write_sdc $::env(SAVE_SDC)")
script = os.path.join(out, "fake_tool.tcl")
open(script, "w").write("\n".join(tcl) + "\n")
run = subprocess.run(["tclsh", script], capture_output=True, text=True)
open(os.path.join(out, "fake_tool.log"), "w").write(run.stdout + run.stderr)
if run.returncode:
    sys.exit(run.returncode)
state = json.load(open(argv[argv.index("-i") + 1]))
state["metrics"] = {}
if step == "OpenROAD.DetailedRouting":
    design = cfg.get("DESIGN_NAME", "neutral")
    odb = os.path.join(out, design + ".odb")
    open(odb, "wb").write(b"routed database subject")
    state["odb"] = odb
    mode = cfg.get("FAKE_DRC_MODE", "canonical")
    if mode == "canonical":
        open(os.path.join(out, design + ".drc"), "wb").write(
            cfg.get("FAKE_DRC_BYTES", "").encode())
    elif mode == "wrong-subject":
        open(os.path.join(out, "other_subject.drc"), "wb").write(b"")
    print("fake DetailedRouting invocation completed")
json.dump(state, open(os.path.join(out, "state_out.json"), "w"))
'''


def _fake_docker(tmp_path, monkeypatch):
    # This fixture substitutes Docker with Tcl stand-ins, not a LOCAL image.
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    docker = tmp_path / "bin" / "docker"
    docker.parent.mkdir()
    docker.write_text(_FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setitem(ll._CAPABILITY, ("img", str(docker)),
                        {"image": "img", "openroad_aliases": {}, "tcl_probe": "MEASURED"})
    return docker


def _project(tmp_path):
    project = tmp_path / "proj"
    (project / "phase3").mkdir(parents=True)
    view = project / "d.def"
    view.write_text("DESIGN x ;\n")
    state = project / "state_in.json"
    state.write_text(json.dumps({"odb": str(view), "def": str(view), "nl": str(view),
                                 "sdc": str(view), "metrics": {}}))
    return project, state


def _config(project, step, **extra):
    path = project / f"{step}.json"
    path.write_text(json.dumps({"meta": {"step": step}, **extra}))
    return path


def _run(project, docker, state, *steps, lane="l"):
    return ll.run_chain(project, "img",
                        [(step, _config(project, step, **extra), state)
                         for step, extra in steps],
                        docker=str(docker), lane=lane, pdk_root=ll.PDK_GUEST_ROOT)


pytestmark = pytest.mark.skipif(TCLSH is None, reason="tclsh absent")






def test_detailed_route_receipt_binds_only_current_subject_drc(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    folder = _run(project, docker, state,
                  ("OpenROAD.DetailedRouting", {"DESIGN_NAME": "neutral"}))[0]
    receipt = ll.validate_step_receipt(folder, "OpenROAD.DetailedRouting")
    report = folder / "neutral.drc"
    assert report.is_file() and report.stat().st_size == 0
    assert receipt["sha256"].get("neutral.drc", "UNBOUND") == ll.digest(report)
    assert not any(name.endswith("other_subject.drc") for name in receipt["sha256"])


@pytest.mark.parametrize("mode", ["missing", "wrong-subject"])
def test_detailed_route_refuses_missing_or_wrong_subject_drc(tmp_path, monkeypatch, mode):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    try:
        _run(project, docker, state, ("OpenROAD.DetailedRouting", {
            "DESIGN_NAME": "neutral", "FAKE_DRC_MODE": mode}))
        observed = "ACCEPTED"
    except ll.Refusal as failure:
        observed = failure.code
    assert observed == "LL_DETAILED_ROUTE_DRC_MISSING"
    folder = project / "phase3/librelane/l/01-openroad-detailedrouting"
    assert not (folder / "vibeic_receipt.json").exists()


def test_detailed_route_receipt_refuses_changed_drc_bytes(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    folder = _run(project, docker, state, ("OpenROAD.DetailedRouting", {
        "DESIGN_NAME": "neutral", "FAKE_DRC_BYTES": "violation type: spacing\n"}))[0]
    report = folder / "neutral.drc"
    report.write_text("violation type: changed subject\n")
    try:
        ll.validate_step_receipt(folder, "OpenROAD.DetailedRouting")
        observed = "ACCEPTED"
    except ll.Refusal as failure:
        observed = failure.code
    assert observed == "LL_STEP_OUTPUT_UNBOUND"




def test_pad_mode_warmup_uses_the_quiet_timing_query(tmp_path):
    import subprocess
    import sdc_environment as sdc
    core = tmp_path / "core.lib"
    io = tmp_path / "io.lib"
    core.write_text('library(core) { time_unit : "1ns"; }')
    io.write_text('library(io) { time_unit : "1ns"; cell(pad) {'
                  ' pin(PAD) { max_transition : 25; } } }')
    record = tmp_path / sdc.IO_PAD_RECORD
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"verdict": "WROTE",
        "io_library_liberty": [str(io)],
        "pad_instances": {"u_pad": {"master": "pad", "terminal": "PAD", "port": "clk"}}}))
    scene = sdc.pad_operating_scene(tmp_path, str(core))
    assert scene["complete_pin_limits"]
    script = tmp_path / "warmup.tcl"
    script.write_text('''namespace eval ::sta {}
set warmups 0
proc worst_slack {args} { incr ::warmups; return 42 }
proc report_worst_slack {args} { error {nested logger redirection} }
proc report_check_types {args} { return native_report }
proc ::sta::max_slew_violation_count {} { return 0 }
proc write_sdc {args} {}
proc get_cells {args} { return u_pad }
proc get_timing_edges {args} { return {} }
''' + scene["tcl"] + '''
puts "RESULT [report_check_types -max_slew]"
puts "WARMUPS $warmups"
''')
    run = subprocess.run([TCLSH, str(script)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "RESULT native_report" in run.stdout
    assert "WARMUPS 1" in run.stdout












# --- synthesis -----------------------------------------------------------------









def test_every_synth_abc_call_keeps_its_script():
    """All four yosys command sites (default read, slang, sv2v, retry) carry
    the flags that make yosys keep and name the script ABC ran."""
    source = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    sites = source.count("abc -liberty {liberty_c}{_abc_timing}{_abc_fanout}")
    assert sites == 4
    assert source.count("abc -liberty {liberty_c}{_abc_timing}{_abc_fanout}{_abc_keep}; ") == 4
    assert '_abc_keep = " -showtmp -nocleanup"' in source


# --- SPECIALNETS zero-wiring proof (R-0928-DRV-IC) ------------------------------

def _pad_scene(tmp_path, def_body):
    from test_drv_signoff_judge import _port_pad_pins, _file
    folder = tmp_path / "scene"
    _file(folder, "annotation.rpt", "Found 1 unannotated drivers.\n p\n"
          "Found 0 partially unannotated drivers.\n")
    lef = _file(tmp_path, "pad.lef", "MACRO pad\n PIN PAD\n USE SIGNAL ;\n END PAD\nEND pad\n")
    lib = _file(tmp_path, "pad.lib", '''library (lib) {
 time_unit : "1ns"; capacitive_load_unit (1, pf);
 cell (pad) { pad_cell : true;
  pin (PAD) { direction : input; timing () { related_pin : "PAD"; } }
 }
}''')
    routed = _file(tmp_path, "route.def", def_body)
    spef = _file(tmp_path, "route.spef", "*D_NET other 0.1\n*END\n")
    return (folder, _port_pad_pins(), [lib], [lef], Path(routed["path"]),
            Path(spef["path"]))


_NETS = "NETS 1 ;\n - n1 ( u A ) ( v Z ) + ROUTED Metal1 ( 0 0 ) ( 1 0 ) ;\nEND NETS\n"
