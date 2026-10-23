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

import drv_capture_plan as plan  # noqa: E402
import drv_signoff_judge as drv  # noqa: E402
import drv_stage_receipts as receipts  # noqa: E402
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


def test_a_stage_chain_installs_the_probe_for_openroad_and_sta(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    receipts.claim(project)
    folder = _run(project, docker, state, ("OpenROAD.RepairDesignPostGPL", {}))[0]
    home = project / "phase3/librelane/l/.openroad_home"
    probe = receipts.PROBE_TCL.read_text()
    for init in (".openroad", ".sta"):
        assert probe.strip() in (home / init).read_text(), init
    fingerprint = json.loads((folder / "input_fingerprint.json").read_text())
    assert fingerprint["drv_stage_probe"] == receipts.probe_digest()
    # The snapshot is taken in the stage's process BEFORE the command runs.
    calls = (folder / "calls.log").read_text().splitlines()
    assert calls == ["repair_design {-verbose -slew_margin 20} snapshot_before=1"]
    # ...and the wrapped command still returns its own result.
    assert "repaired" in (folder / "fake_tool.log").read_text()


def test_a_chain_without_a_stage_step_gets_no_probe(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    receipts.claim(project)
    folder = _run(project, docker, state, ("OpenROAD.CheckAntennas", {}))[0]
    assert "drv_stage_probe" not in json.loads((folder / "input_fingerprint.json").read_text())
    assert not (project / "phase3/librelane/l/.openroad_home").exists()


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


def test_stage_reports_allow_the_sdc_warmup_before_native_redirection(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    receipts.claim(project)
    folder = _run(project, docker, state,
                  ("OpenROAD.RepairDesignPostGPL", {"FAKE_REPORT_WARMUP": True}))[0]
    assert not list((folder / receipts.PROBE_DIR).glob("*.error"))
    rows, _ = plan._stages(project, False, frozenset({"padcell"}))
    row = next(row for row in rows if row["name"] == "placement_repair")
    assert row["fanout_check_limit"] == 4
    behavior = Path(row["behavior_report"]["path"]).read_text()
    assert "max_fanout violators=1" in behavior
    assert drv._COMMAND in behavior


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


def test_run_chain_writes_receipts_the_plan_reads_from_tool_bytes(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    run_id = receipts.claim(project)
    _run(project, docker, state, ("OpenROAD.RepairDesignPostGPL", {"FAKE_SDC_FANOUT": 10}),
         ("OpenROAD.CTS", {}), ("OpenROAD.STAPostPNR", {}))
    stored = {name: json.loads((project / receipts.RECEIPT_DIR / f"{name}.json").read_text())
              for name in ("placement_repair", "cts", "signoff_sta")}
    assert all(doc["run_id"] == run_id for doc in stored.values())
    for doc in stored.values():
        for key in ("behavior_report", "sdc_snapshot", "command_args"):
            assert drv._sha(Path(doc[key]["path"])) == doc[key]["sha256"], key
        assert "applied" not in doc  # a receipt carries references, never values
    rows, inventory = plan._stages(project, False, frozenset({"padcell"}))
    rows = {row["name"]: row for row in rows}
    assert inventory["synth"]["status"] == "absent"
    assert inventory["post_grt_repair"]["status"] == "absent"
    # The applied value is the tool's pre-command SDC, 10 here, not the 4
    # the design declares: the judge sees a stage broader than declared.
    assert rows["placement_repair"]["applied"] == {"fanout": 10.0, "slew_ns": 3.0,
                                                   "cap_pf": 0.2}
    assert rows["placement_repair"]["fanout_check_limit"] == 10.0
    for name in ("placement_repair", "cts", "signoff_sta"):
        # R-0929-DRV-FANOUT-LIMIT: the worst-slack pin is the pad (limit 1);
        # the applied-limit check reads the core drivers', the IO cells'
        # library value is recorded as their own class.
        assert rows[name]["worst_pin_fanout_check_limit"] == 1.0
        assert rows[name]["io_fanout_limit"] == 1.0
    assert rows["cts"]["fanout_check_limit"] == 4.0
    assert rows["signoff_sta"]["applied"]["fanout"] == 4.0
    assert rows["cts"]["cts_parameters"] == {"root_buf": "clkbuf_16",
                                             "sink_clustering_size": "4",
                                             "sink_clustering_enable": True}
    assert rows["cts"]["clock_driver_fanout"] == [
        {"driver": "buf_itd/Z", "net": "clknet_0", "fanout": 2}]
    behavior = Path(rows["cts"]["behavior_report"]["path"]).read_text()
    assert drv._COMMAND in behavior and "max_fanout violators=1" in behavior


def test_a_receipt_from_another_run_is_refused(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    receipts.claim(project)
    _run(project, docker, state, ("OpenROAD.CTS", {}))
    receipt = project / receipts.RECEIPT_DIR / "cts.json"
    stale = receipt.read_text()
    receipts.claim(project)          # a new run starts: its directory is empty
    assert not receipt.exists()
    archived = list((project / 'reports/phase3/drv_stage_history').glob('fresh-*/cts.json'))
    assert len(archived) == 1 and archived[0].read_text() == stale
    receipt.write_text(stale)        # an old receipt copied back in
    rows, inventory = plan._stages(project, False)
    assert inventory["cts"]["status"] == "recorded by another run"
    assert "cts" not in {row["name"] for row in rows}


def test_no_claim_means_no_receipt(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    _run(project, docker, state, ("OpenROAD.CTS", {}))
    assert not (project / receipts.RECEIPT_DIR / "cts.json").exists()
    assert plan._stages(project, False)[1]["cts"]["status"] == "absent"


def test_step32_rebinds_signoff_and_repair_to_the_final_state(tmp_path, monkeypatch):
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    receipts.claim(project)
    base = _run(project, docker, state, ("Vibeic.PostRouteRepair", {"FAKE_SDC_FANOUT": 4}),
                ("OpenROAD.STAPostPNR", {"FAKE_SDC_FANOUT": 4}), lane="32-base")
    _run(project, docker, state, ("Vibeic.PostRouteRepair", {"FAKE_SDC_FANOUT": 6}),
         ("OpenROAD.STAPostPNR", {"FAKE_SDC_FANOUT": 6}), lane="32-cand01")
    # The last chain to run was the candidate; step 32 kept the base.
    report = {"adopted": "32-base", "adopted_state": str(base[0] / "state_out.json"),
              "final": {"sta_state": str(base[1] / "state_out.json")}}
    receipts.record_step32(project, report)
    rows = {row["name"]: row for row in plan._stages(project, True, frozenset({"padcell"}))[0]}
    assert rows["signoff_sta"]["applied"]["fanout"] == 4.0
    assert rows["signoff_sta"]["fanout_check_limit"] == 4.0
    assert rows["postroute_repair"]["applied"]["fanout"] == 4.0
    doc = json.loads((project / receipts.RECEIPT_DIR / "signoff_sta.json").read_text())
    assert doc["tool_step"]["folder"] == str(base[1].resolve())


def test_a_gated_out_stage_is_recorded_as_not_run_and_fails(tmp_path):
    project = tmp_path / "proj"
    receipts.claim(project)
    receipts.record_not_run(project, "post_grt_repair", "gate false")
    rows = {row["name"]: row for row in plan._stages(project, False)[0]}
    assert rows["post_grt_repair"]["ran"] is False
    bundle = {"stages": list(rows.values())}
    fails: list = []
    # The judge's own stage rule: a stage that did not run is FAIL.
    result = drv.judge({"identity": {}, "frozen": {}, "current": {}, **bundle,
                        "pins": {}, "scenes": []})
    fails = result["failures"]
    assert "post_grt_repair: did not run or lacks DRV behavior report" in fails


# --- synthesis -----------------------------------------------------------------

def test_synth_keeps_the_script_abc_executed(tmp_path):
    project = tmp_path / "proj"
    receipts.claim(project)
    synth = project / "phase2/stage2/synth"
    kept = synth / "_tmp_yosys-abc-Qa3IyE"
    kept.mkdir(parents=True)
    (kept / "abc.script").write_text("echo + buffer -N 4;\nbuffer -N 4;\n")
    log = ("Running ABC script: <abc-temp-dir>/abc.script\n"
           "Running ABC script: _tmp_yosys-abc-Qa3IyE/abc.script\n")
    path = receipts.keep_abc_script(project, synth, log)
    assert path == receipts.abc_script_path(project)
    assert path.read_text() == "echo + buffer -N 4;\nbuffer -N 4;\n"
    assert not kept.exists(), "yosys's kept temp folder is removed"
    netlist = synth / "top_synth.v"
    netlist.write_text("module top; endmodule\n")
    sdc = project / "constraint.sdc"
    sdc.write_text("set_max_fanout 4 [current_design]\n")
    behavior = path.parent / "behavior.rpt"
    behavior.write_text("clocks 1\nclock clk is_propagated=0\n" + drv._COMMAND + "\n"
                        + "".join(f"{k} violators=0\n" for k in drv.KINDS))
    receipts.record_synth(project, abc_script=path, behavior=behavior,
                          netlist=netlist, sdc=sdc)
    row = plan._stages(project, False)[0][0]
    assert row["name"] == "synth" and row["ran"]
    assert row["applied"] == {"fanout": 4.0}
    assert row["synth_abc_buffering"] and row["ideal_clock_excluded"]


def test_synth_flags_come_from_evidence_not_the_receipt(tmp_path):
    project = tmp_path / "proj"
    run_id = receipts.claim(project)
    folder = project / "evidence"
    folder.mkdir(parents=True)
    script = folder / "abc.script"
    script.write_text("strash\n&nf\n&put\n")          # no buffering at all
    behavior = folder / "behavior.rpt"
    behavior.write_text("clocks 1\nclock clk is_propagated=1\n" + drv._COMMAND + "\n")
    (project / receipts.RECEIPT_DIR / "synth.json").write_text(json.dumps({
        "name": "synth", "run_id": run_id, "ran": True,
        "abc_script": {"path": str(script), "sha256": drv._sha(script)},
        "behavior_report": {"path": str(behavior), "sha256": drv._sha(behavior)},
        # prose claims the evidence contradicts
        "synth_abc_buffering": True, "ideal_clock_excluded": True,
        "applied": {"fanout": 4}}))
    row = plan._stages(project, False)[0][0]
    assert row["applied"] == {"fanout": None}
    assert row["synth_abc_buffering"] is False
    assert row["ideal_clock_excluded"] is False


@pytest.mark.parametrize("lost_source", [None, "missing", "changed"])
def test_native_abc_source_and_slew_option_reach_the_stage_consumer(tmp_path, lost_source):
    project = tmp_path / "proj"
    receipts.claim(project)
    synth = project / "phase2/stage2/synth"
    temp = synth / "_tmp_yosys-abc-A1"
    temp.mkdir(parents=True)
    leaf = temp / "AREA_0.abc"
    recipe = "strash\n&get -n\n&nf\n&put\nbuffer -N 10 -S 750.0\n"
    leaf.write_text(recipe)
    wrapper = temp / "abc.script"
    wrapper.write_text(f"echo + source {leaf}\nsource {leaf}\n")
    path = receipts.keep_abc_script(project, synth,
                                    f"Running ABC script: {wrapper}\n")
    assert path.read_text() == f"echo + source {leaf}\nsource {leaf}\n"
    assert not temp.exists()
    netlist = synth / "top_synth.v"
    netlist.write_text("module top; endmodule\n")
    sdc = project / "constraint.sdc"
    sdc.write_text("set_max_fanout 10 [current_design]\n")
    behavior = path.parent / "behavior.rpt"
    behavior.write_text("clocks 1\nclock clk is_propagated=0\n" + drv._COMMAND + "\n"
                        + "".join(f"{k} violators=0\n" for k in drv.KINDS))
    receipt = receipts.record_synth(project, abc_script=path, behavior=behavior,
                                    netlist=netlist, sdc=sdc)
    document = json.loads(receipt.read_text())
    captured = document.get("abc_sources", [])
    if captured:
        copy = Path(captured[0]["script"]["path"])
        assert copy.read_text() == recipe
        if lost_source == "missing":
            copy.unlink()
        elif lost_source == "changed":
            copy.write_text("buffer -N 100 -S 750.0\n")
    row = plan._stages(project, False)[0][0]
    assert row["ran"] is (lost_source is None)
    assert row["applied"]["fanout"] == (10.0 if lost_source is None else None)
    assert row["synth_abc_buffering"] is (lost_source is None)


def test_a_wrapper_without_bound_source_bytes_is_not_a_synthesis_stage(tmp_path):
    project = tmp_path / "proj"
    receipts.claim(project)
    folder = project / "evidence"
    folder.mkdir(parents=True)
    script = folder / "abc.script"
    leaf = folder / "AREA_0.abc"
    leaf.write_text("buffer -N 10 -S 750.0\n")
    script.write_text(f"source {leaf}\n")
    behavior = folder / "behavior.rpt"
    behavior.write_text(drv._COMMAND + "\n")
    netlist = folder / "top.v"
    netlist.write_text("module top; endmodule\n")
    sdc = folder / "constraint.sdc"
    sdc.write_text("set_max_fanout 10 [current_design]\n")
    receipts.record_synth(project, abc_script=script, behavior=behavior,
                          netlist=netlist, sdc=sdc)
    row = plan._stages(project, False)[0][0]
    assert row["ran"] is False
    assert row["applied"]["fanout"] is None
    assert row["synth_abc_buffering"] is False


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


def _derive(tmp_path, special):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from drv_signoff_annotation import derive
    return derive(*_pad_scene(tmp_path, _NETS + "SPECIALNETS 1 ;\n" + special
                              + "END SPECIALNETS\n"))


def test_a_specialnets_port_pad_net_with_no_wiring_is_proven(tmp_path):
    result = _derive(tmp_path, " - p ( PIN p ) ( u PAD ) + USE SIGNAL ;\n")
    assert result["unresolved"] == []
    assert result["resolved"] == [{"pin": "p", "net": "p",
                                   "reason": "port_pad_zero_routed_segments",
                                   "def_sections": ["SPECIALNETS"],
                                   "def_endpoints": ["p", "u/PAD"]}]


@pytest.mark.parametrize("special", [
    " - p ( PIN p ) ( u PAD ) + ROUTED Metal2 10 ( 0 0 ) ( 10 0 ) + USE SIGNAL ;\n",
    " - p ( PIN p ) ( u PAD ) + RECT Metal2 ( 0 0 ) ( 10 10 ) + USE SIGNAL ;\n",
    " - p ( PIN p ) ( u PAD ) + POLYGON Metal2 ( 0 0 ) ( 1 0 ) ( 1 1 ) + USE SIGNAL ;\n",
    " - p ( PIN p ) ( u PAD ) + VIA via1 N ( 0 0 ) + USE SIGNAL ;\n",
    " - p ( PIN p ) ( u PAD ) + SHIELD VDD Metal2 10 ( 0 0 ) ( 10 0 ) ;\n",
    # the pins are not exactly its endpoints
    " - p ( PIN p ) + USE SIGNAL ;\n",
    " - p ( PIN p ) ( u PAD ) ( w A ) + USE SIGNAL ;\n",
    " - p ( PIN p ) ( * PAD ) + USE SIGNAL ;\n",
])
def test_specialnets_wiring_or_other_endpoints_is_not_a_proof(tmp_path, special):
    result = _derive(tmp_path, special)
    assert result["resolved"] == []
    assert [row["pin"] for row in result["unresolved"]] == ["p"]


def test_a_net_routed_in_nets_is_not_proven_by_its_empty_specialnet(tmp_path):
    from drv_signoff_annotation import derive
    body = ("NETS 1 ;\n - p ( PIN p ) ( u PAD ) + ROUTED Metal2 ( 0 0 ) ( 10 0 ) ;\n"
            "END NETS\nSPECIALNETS 1 ;\n - p ( PIN p ) ( u PAD ) + USE SIGNAL ;\n"
            "END SPECIALNETS\n")
    result = derive(*_pad_scene(tmp_path, body))
    assert [row["pin"] for row in result["unresolved"]] == ["p"]


def test_a_copied_run_rebases_report_evidence_with_its_reports_folder(tmp_path):
    """Receipt evidence lives under reports/phase3/; a path recorded on the
    producer host must keep that `reports` component when the copied project
    is evaluated elsewhere (the plan otherwise reads a phase3/ path that
    does not exist and the stage turns absent)."""
    copy = tmp_path / "copy"
    recorded = "/elsewhere/run/spm/reports/phase3/drv_stages/evidence/synth/abc.script"
    assert plan._run_path(copy, recorded) == copy / "reports/phase3/drv_stages/evidence/synth/abc.script"
    step = "/elsewhere/run/spm/phase3/librelane/32-base/04-openroad-stapostpnr/state_out.json"
    assert plan._run_path(copy, step) == copy / "phase3/librelane/32-base/04-openroad-stapostpnr/state_out.json"
    inside = copy / "reports/phase3/x.json"
    assert plan._run_path(copy, str(inside)) == inside


def test_synth_stage_runs_the_census_deck_and_binds_the_receipt(tmp_path):
    project = tmp_path / "proj"
    receipts.claim(project)
    # This fixture is the existing direct Yosys producer, not a native handoff.
    (project / 'phase3').mkdir(parents=True, exist_ok=True)
    (project / 'phase3/librelane_switch.json').write_text(json.dumps({'steps': {'9': 'direct'}}))
    synth = project / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / "_tmp_yosys-abc-A1/").mkdir()
    (synth / "_tmp_yosys-abc-A1/abc.script").write_text("buffer -N 4;\n")
    receipts.keep_abc_script(project, synth,
                             "Running ABC script: _tmp_yosys-abc-A1/abc.script\n")
    netlist = synth / "top_synth.v"
    netlist.write_text("module top; endmodule\n")
    sdc = project / "c.sdc"
    sdc.write_text("create_clock -period 24 [get_ports clk]\nset_max_fanout 4 [current_design]\n")
    decks = []

    def execute(cmd):              # stands in for OpenSTA: writes what it writes
        deck = Path(cmd.split()[-1])
        decks.append(deck.read_text())
        out = Path(deck.read_text().split("synth_census {")[1].split("}")[0])
        out.write_text("clocks 1\nclock clk is_propagated=0\n" + drv._COMMAND + "\n"
                       + "".join(f"{k} violators=0\n" for k in drv.KINDS))
        return 0, "", ""

    receipts.synth_stage(project, netlist=netlist, top="top", liberties=["/l.lib"],
                         sdc=sdc, to_container=str, execute=execute)
    assert "read_sdc {" + str(sdc) + "}" in decks[0] and "link_design {top}" in decks[0]
    row = plan._stages(project, False)[0][0]
    assert row["ran"] and row["applied"] == {"fanout": 4.0}
    assert row["ideal_clock_excluded"] is True
    # A census the tool did not finish is no behaviour evidence.
    receipts.synth_stage(project, netlist=netlist, top="top", liberties=["/l.lib"],
                         sdc=sdc, to_container=str, execute=lambda cmd: (1, "", "err"))
    assert "behavior_report" not in plan._stages(project, False)[0][0]


@pytest.mark.parametrize("tool_rc", [0, 1])
def test_pnr_synth_census_uses_the_supervised_deck(tmp_path, monkeypatch, tool_rc):
    """The PnR consumer reaches the real supervised branch and keeps receipts."""
    from functools import partial
    import phase3_one_shot_runner as runner
    project = tmp_path / "proj"
    receipts.claim(project)
    # This fixture is the existing direct Yosys producer, not a native handoff.
    (project / 'phase3').mkdir(parents=True, exist_ok=True)
    (project / 'phase3/librelane_switch.json').write_text(json.dumps({'steps': {'9': 'direct'}}))
    netlist = runner._pl.synth_dir(project) / "top_synth.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module top; endmodule\n")
    sdc = project / "constraint.sdc"
    sdc.write_text("create_clock -period 24 [get_ports clk]\n"
                   "set_max_fanout 4 [current_design]\n")
    abc = receipts.abc_script_path(project)
    abc.parent.mkdir(parents=True)
    abc.write_text("buffer -N 4;\n")
    seen = []

    def supervised(container, cmd, marker, **kwargs):
        assert container == "captured"
        assert marker == str(abc.parent / "census.tcl") and marker in cmd
        assert kwargs["log_path"] == abc.parent / "census.log"
        deck = Path(marker).read_text()
        assert "read_sdc {" + str(sdc) + "}" in deck
        assert "link_design {top}" in deck
        behavior = Path(deck.split("synth_census {")[1].split("}")[0])
        behavior.write_text("clocks 1\nclock clk is_propagated=0\n" + drv._COMMAND + "\n"
                            + "".join(f"{kind} violators=0\n" for kind in drv.KINDS))
        seen.append((cmd, marker))
        return tool_rc, "captured native census\n", ""

    def raw(*args, **kwargs):
        pytest.fail("synth census bypassed watchdog binding")

    monkeypatch.setattr(runner._dwd, "run_docker_supervised", supervised)
    monkeypatch.setattr(runner, "_docker_exec_raw", raw)
    monkeypatch.setattr(runner, "_local_exec_mode", lambda: False)
    monkeypatch.setattr(runner, "_to_container_path", lambda path, container: str(path))
    monkeypatch.setattr(runner, "_log_invocation", lambda *args, **kwargs: None)
    receipts.synth_stage_supervised(
        project, netlist=netlist, top="top", liberties=["/l.lib"], sdc=sdc,
        to_container=lambda path: runner._to_container_path(str(path), "captured"),
        execute=partial(runner._docker_exec, "captured"))
    assert len(seen) == 1
    assert (abc.parent / "census.log").read_text().startswith(f"rc={tool_rc}\n")
    row = plan._stages(project, False)[0][0]
    if tool_rc == 0:
        assert row["ran"] and row["applied"] == {"fanout": 4.0}
        assert row["ideal_clock_excluded"] is True
    else:
        assert "behavior_report" not in row
        assert not (abc.parent / "behavior.rpt").exists()


def test_ran_is_the_evidence_not_the_receipts_word(tmp_path):
    project = tmp_path / "proj"
    run_id = receipts.claim(project)
    (project / receipts.RECEIPT_DIR / "cts.json").write_text(json.dumps({
        "name": "cts", "run_id": run_id, "ran": True}))      # no evidence at all
    row = {r["name"]: r for r in plan._stages(project, False)[0]}["cts"]
    assert row["ran"] is False


def test_the_receipt_run_id_is_the_run_identity_recorded_at_start(tmp_path):
    import drv_run_identity
    project = tmp_path / "proj"
    recorded = drv_run_identity.record(project)["run_id"]
    assert receipts.claim(project) == recorded


@pytest.mark.parametrize("entry,retained,withdrawn", [
    ("19", {"placement_repair"}, {"cts", "post_grt_repair", "postroute_repair", "signoff_sta"}),
    ("32", {"placement_repair", "cts", "post_grt_repair"}, {"postroute_repair", "signoff_sta"}),
    ("37", {"placement_repair", "cts", "post_grt_repair", "postroute_repair", "signoff_sta"}, set()),
])
def test_default_window_retains_preceding_native_receipts_and_withdraws_affected_stages(
        tmp_path, monkeypatch, entry, retained, withdrawn):
    import types
    import phase3_one_shot_runner as runner
    import drv_run_identity as identity
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    original = identity.start(project)
    _run(project, docker, state,
         ("OpenROAD.RepairDesignPostGPL", {}), ("OpenROAD.CTS", {}),
         ("OpenROAD.RepairDesignPostGRT", {}), ("Vibeic.PostRouteRepair", {}),
         ("OpenROAD.STAPostPNR", {}))
    before = {name: (project / receipts.RECEIPT_DIR / f"{name}.json").read_bytes()
              for name in retained | withdrawn}
    seen = {}

    def at_native_boundary(*args, **kwargs):
        seen["identity"] = identity.load(project)
        for name in retained:
            assert (project / receipts.RECEIPT_DIR / f"{name}.json").read_bytes() == before[name]
            assert receipts.read_receipt(project, name)[1] == "recorded"
        for name in withdrawn:
            assert receipts.read_receipt(project, name)[1] == "absent"
            archives = list((project / "reports/phase3/drv_stage_history").glob(f"*/{name}.json"))
            assert len(archives) == 1 and archives[0].read_bytes() == before[name]
        rows, _ = plan._stages(project, True, frozenset({"padcell"}))
        assert {row["name"] for row in rows} == retained
        raise SystemExit("native boundary reached")

    monkeypatch.setattr(runner, "_phase3_file_manifest", at_native_boundary)
    args = types.SimpleNamespace(entry_step=entry, exit_step=entry, container="")
    with pytest.raises(SystemExit, match="native boundary reached"):
        runner._run_phase3_window(project, "top", object(), args, ["default_backend"])
    assert seen["identity"]["run_id"] == original["run_id"]
    assert seen["identity"]["recorded_at"] == original["recorded_at"]
    assert seen["identity"]["initial_code_identity"]["plugin_tree_sha256"] == original["plugin_tree_sha256"]


def test_default_retry_records_the_new_cts_output_under_the_same_logical_run(tmp_path, monkeypatch):
    import drv_run_identity as identity
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    original = identity.start(project)
    _run(project, docker, state, ("OpenROAD.RepairDesignPostGPL", {}), ("OpenROAD.CTS", {}))
    old, _ = receipts.read_receipt(project, "cts")
    identity.start(project, continue_steps=["19"])
    _run(project, docker, state, ("OpenROAD.CTS", {"FAKE_SDC_FANOUT": 7}))
    new, status = receipts.read_receipt(project, "cts")
    assert status == "recorded" and new["run_id"] == original["run_id"]
    assert new["sdc_snapshot"]["sha256"] != old["sdc_snapshot"]["sha256"]
    rows, _ = plan._stages(project, False, frozenset({"padcell"}))
    assert next(row for row in rows if row["name"] == "cts")["fanout_check_limit"] == 7
    assert next(row for row in rows if row["name"] == "placement_repair")["fanout_check_limit"] == 4


def test_synthesis_retry_archives_an_unpublished_abc_script_before_new_mapping(tmp_path, monkeypatch):
    import drv_run_identity as identity
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    identity.start(project)
    _run(project, docker, state, ("OpenROAD.CTS", {}))
    abc = receipts.abc_script_path(project)
    abc.parent.mkdir(parents=True)
    abc.write_text("buffer -N 4\n")
    identity.start(project, continue_steps=["9"])
    assert not abc.exists()
    old = list((project / "reports/phase3/drv_stage_history").glob("*/evidence/synth/abc.script"))
    assert len(old) == 1 and old[0].read_text() == "buffer -N 4\n"


def test_default_floorplan_continuation_retains_the_script_from_completed_mapping(tmp_path):
    import drv_run_identity as identity
    project, _ = _project(tmp_path)
    original = identity.start(project)
    synth = project / "phase2/stage2/synth"
    script = synth / "_tmp_yosys-abc-unit/abc.script"
    script.parent.mkdir(parents=True)
    script.write_text("buffer -N 4\n")
    kept = receipts.keep_abc_script(project, synth, f"Running ABC script: {script}\n")
    assert kept is not None and receipts.read_receipt(project, "synth")[1] == "absent"
    new = identity.start(project, continue_steps=["15"])
    assert new["run_id"] == original["run_id"]
    assert kept.read_text() == "buffer -N 4\n"
    assert receipts.read_receipt(project, "synth")[1] == "absent"  # census has not run yet


def test_changed_specification_refuses_default_continuation_before_the_native_tool(tmp_path, monkeypatch):
    import types
    import phase3_one_shot_runner as runner
    import drv_run_identity as identity
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    docs = project / identity.SPEC_DOCS
    docs.mkdir(parents=True)
    spec = docs / "L1_DATASHEET.json"
    spec.write_text('{"clock_period_ns": 10}\n')
    identity.start(project)
    _run(project, docker, state, ("OpenROAD.CTS", {}))
    before = (project / identity.RECORD).read_bytes()
    receipt = (project / receipts.RECEIPT_DIR / "cts.json").read_bytes()
    spec.write_text('{"clock_period_ns": 20}\n')
    monkeypatch.setattr(runner, "_phase3_file_manifest", lambda *a:
                        pytest.fail("native continuation began with another specification"))
    args = types.SimpleNamespace(entry_step="32", exit_step="32", container="")
    assert runner._run_phase3_window(project, "top", object(), args, ["default_backend"]) == 2
    assert (project / identity.RECORD).read_bytes() == before
    assert (project / receipts.RECEIPT_DIR / "cts.json").read_bytes() == receipt


def test_an_io_pad_limit_is_never_read_as_the_design_limit(tmp_path, monkeypatch):
    """Without the Liberty's pad_cell fact the pad's 1 and the core's 4 are one
    class that disagrees: no single applied limit, so the judge cannot pass
    the stage on it."""
    docker = _fake_docker(tmp_path, monkeypatch)
    project, state = _project(tmp_path)
    receipts.claim(project)
    _run(project, docker, state, ("OpenROAD.CTS", {}))
    known = {r["name"]: r for r in plan._stages(project, False, frozenset({"padcell"}))[0]}
    unknown = {r["name"]: r for r in plan._stages(project, False)[0]}
    assert known["cts"]["fanout_check_limit"] == 4.0
    assert unknown["cts"]["fanout_check_limit"] is None


def test_the_plan_reads_pad_cells_from_the_linked_liberty(tmp_path):
    lib = tmp_path / "io.lib"
    lib.write_text('library (io) { time_unit : "1ns"; capacitive_load_unit (1, pf); '
                   'cell (padcell) { pad_cell : true; } cell (bufcell) { area : 1; } }')
    assert plan._pad_cells([{"path": str(lib)}]) == frozenset({"padcell"})


def test_io_library_cells_without_pad_cell_are_io_class(tmp_path):
    """Measured on spm's sign-off STA (real run, 0.3.85): the IO library's
    fill/corner/supply cells (limit 1, library default) carry no pad_cell
    attribute.  Read as core, they made the design limit ambiguous (None);
    the scene's PAD_LIBS Liberty makes all of its cells IO class."""
    io = tmp_path / "io.lib"
    io.write_text('library (io) { time_unit : "1ns"; capacitive_load_unit (1, pf); '
                  'cell (padcell) { pad_cell : true; pin (Y) { direction : output; } } '
                  'cell (fillcell) { pin (VDD) { direction : inout; } } }')
    std = tmp_path / "std.lib"
    std.write_text('library (std) { time_unit : "1ns"; capacitive_load_unit (1, pf); '
                   'cell (bufcell) { pin (Z) { direction : output; } } }')
    libs = [{"path": str(io)}, {"path": str(std)}]
    limits = ("max fanout\n\nPin u_fill/VDD\nmax fanout 1\nfanout 1\n-----------\nSlack 0 (MET)\n"
              "\nPin u1/Z\nmax fanout 4\nfanout 2\n-----------\nSlack 2 (MET)\n")
    cells = "pin_cell\tu_fill/VDD\tfillcell\npin_cell\tu1/Z\tbufcell\n"
    assert plan._class_fanout_limits(limits, cells, plan._pad_cells(libs)) == {
        "core": None, "io": None}                       # fill read as core: ambiguous
    assert plan._class_fanout_limits(limits, cells, plan._pad_cells(libs, [io])) == {
        "core": 4.0, "io": 1.0}
    env = {"PAD_LIBS": "/pdk/p/libs.ref/io/lib/io__tt.lib /pdk/p/libs.ref/io/lib/io__ss.lib",
           "CELL_LIBS": "/pdk/p/libs.ref/std/lib/std__tt.lib"}
    assert plan._pad_lib_paths(env, tmp_path, "p", "tt") == [tmp_path / "p/libs.ref/io/lib/io__tt.lib"]


def _cold_native_synthesis(tmp_path, monkeypatch):
    """Actual chain/receipt/handoff; synthesis mapping is a neutral substitute.

    No ABC/EDA/native qualification is claimed by this software fixture.
    Synthesis intentionally precedes the first Phase3 run claim.
    """
    from types import SimpleNamespace
    import synth_handoff_netlist_check as handoff
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    project = (tmp_path / 'cold-project').resolve()
    rtl = project / 'phase2/stage1/rtl/core.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module core(input a, output y); assign y = a; endmodule\n')
    def put(path, document):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document))
        return path
    put(project / 'input/project.json', {'pdk': 'neutral'})
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'core'})
    header = put(project / 'header.json', {'module': 'core'})
    state = put(project / 'initial.json', {'json_h': str(header)})
    config = put(project / 'phase3/librelane/synthesis_resolved.json', {
        'meta': {'step': 'Yosys.Synthesis'}, 'PDK': 'neutral',
        'DESIGN_NAME': 'core', 'VERILOG_FILES': [str(rtl)],
        'SYNTH_ELABORATE_ONLY': False, 'SYNTH_CHECKS_ALLOW_TRISTATE': False,
        'TRISTATE_CELLS': [],
        'SYNTH_TIEHI_CELL': 'TIE_H/Y', 'SYNTH_TIELO_CELL': 'TIE_L/Y'})
    calls = []
    netlist = 'module core(input a, output y);\nBUF_X1 u_buf (.A(a), .Y(y));\nendmodule\n'
    def tool(cmd, **kwargs):
        folder = Path(cmd[cmd.index('-o') + 1])
        calls.append(str(folder))
        shutil.copyfile(config, folder / 'config.json')
        raw = folder / 'core.nl.v'
        raw.write_text(netlist)
        put(folder / 'state_out.json', {'nl': str(raw), 'metrics': {
            'design__instance_unmapped__count': 0, 'synthesis__check_error__count': 0}})
        put(folder / 'reports/stat.json', {'modules': {'\\core': {'num_submodules': 0}}})
        # Produce both CHECK reports with the installed Yosys, on the actual
        # neutral input and mapped output. The mapping/ABC envelope remains a
        # software transport fixture, never a native synthesis qualification.
        import subprocess
        cells = folder / 'neutral_cells.v'
        cells.write_text('module BUF_X1(input A, output Y); assign Y = A; endmodule\n')
        for name, files in (('pre_synth_chk.rpt', [rtl]),
                            ('chk.rpt', [cells, raw])):
            report = folder / 'reports' / name
            script = '; '.join([
                'read_verilog ' + ' '.join('"' + str(f) + '"' for f in files),
                'hierarchy -check -top core', 'proc',
                'tee -o "' + str(report) + '" check'])
            checked = subprocess.run(['yosys', '-Q', '-T', '-p', script],
                                     capture_output=True, text=True)
            assert checked.returncode == 0, checked.stdout + checked.stderr
            assert 'Found and reported 0 problems.' in report.read_text()
        temp = folder / '_tmp_yosys-abc-neutral'
        temp.mkdir()
        recipe = temp / 'mapping.abc'
        recipe.write_text('strash\nbuffer -N 4 -S 3000\n')
        wrapper = temp / 'abc.script'
        wrapper.write_text(f'echo + source {recipe}\nsource {recipe}\n')
        (folder / 'COMMANDS').write_text('yosys SOURCE_CONTROL native-process substitute\n')
        return SimpleNamespace(returncode=0,
            stdout=f'Running ABC script: {wrapper}\n', stderr='')
    monkeypatch.setattr(ll, 'image_capability', lambda *a: None)
    monkeypatch.setattr(ll, 'run_container', tool)
    assert receipts.current_run(project) is None
    folder = ll.run_chain(project, 'candidate', [('Yosys.Synthesis', config, state)],
                          pdk_root='/pdk')[0]
    mapped = project / 'phase2/stage2/synth/core_synth.v'
    mapped.parent.mkdir(parents=True)
    mapped.write_text(netlist)
    put(mapped.parent / 'synth_inputs.json', {'netlist': mapped.name})
    handoff.publish_handoff(project, folder, mapped, 'core')
    assert handoff.bound_handoff(project)['verdict'] == 'PASS'
    sdc = project / 'constraint.sdc'
    sdc.write_text('create_clock -period 24 [get_ports clk]\nset_max_fanout 4 [current_design]\n')
    return project, folder, mapped, sdc, config, state, calls


def _source_control_census(cmd):
    """Write only the current deck's behavior file; the producer owns the deck."""
    deck = Path(cmd.split()[-1])
    target = Path(deck.read_text().split('synth_census {')[1].split('}')[0])
    target.write_text('clocks 1\nclock clk is_propagated=0\n' + drv._COMMAND + '\n'
                      + ''.join(f'{kind} violators=0\n' for kind in drv.KINDS))
    return 0, 'SOURCE_CONTROL census process completed\n', ''


def test_cold_phase2_abc_witness_survives_claim_and_complete_stage_judge(tmp_path, monkeypatch):
    import drv_run_identity as identity
    from test_drv_signoff_judge import (
        _bundle, _install_test_freeze, _synthetic_scene_profile)
    # Reuse the complete judge fixture's explicit software-only scene/image
    # setup here; importing its helpers does not activate its module autouse.
    _synthetic_scene_profile.__wrapped__(tmp_path, monkeypatch)
    project, folder, netlist, sdc, _, _, calls = _cold_native_synthesis(tmp_path, monkeypatch)
    receipt = ll.validate_step_receipt(folder, 'Yosys.Synthesis')
    script = folder / receipts.PROBE_DIR / 'synth/abc.script'
    assert script.is_file(), 'Phase2 deleted its only executed ABC wrapper before a run claim'
    assert receipt['sha256'][str(script.relative_to(folder))] == receipts._sha(script)
    assert not receipts.abc_script_path(project).exists()
    before = {path: path.read_bytes() for path in script.parent.iterdir()}
    identity.start(project, continue_steps=['15'])
    saved = receipts.synth_stage(project, netlist=netlist, top='core', liberties=[],
        sdc=sdc, to_container=str, execute=_source_control_census)
    assert saved is not None and len(calls) == 1
    measured = plan._stages(project, False)[0][0]
    assert measured['ran'] and measured['applied']['fanout'] == 4
    assert measured['synth_abc_buffering'] and measured['ideal_clock_excluded']
    assert {path: path.read_bytes() for path in before} == before
    document = json.loads(saved.read_text())
    assert document['run_id'] == receipts.current_run(project)
    assert document['netlist']['sha256'] == receipts._sha(netlist)
    assert document['census_sdc']['sha256'] == receipts._sha(sdc)
    # The remaining sign-off stages are the existing neutral bundle fixture,
    # not native measurements. Keep them in this project and run without
    # changing any of the cold producer's original inputs or retained files.
    original = {path: path.read_bytes() for path in folder.rglob('*') if path.is_file()}
    original[netlist] = netlist.read_bytes()
    original[netlist.parent / 'synth_inputs.json'] = (netlist.parent / 'synth_inputs.json').read_bytes()
    bundle_root = project
    bundle = _bundle(bundle_root)
    run = plan._run_identity(project)
    bundle['identity'].update({key: run[key] for key in
                              ('run_id', 'run_started_at', 'tree_sha', 'spec_version')})
    assert bundle['identity']['run_id'] == document['run_id']
    bundle['stages'] = [measured if row['name'] == 'synth' else row for row in bundle['stages']]
    _install_test_freeze(bundle, bundle_root, monkeypatch)
    result = drv.judge(bundle)
    (tmp_path / 'cold-abc-judge.observation.json').write_text(json.dumps({
        'scope': 'SOURCE_CONTROL: native-process substitute; no EDA qualification',
        'stage': measured, 'bundle': bundle, 'judge': result}, indent=2) + '\n')
    assert {path: path.read_bytes() for path in original} == original
    assert result['verdict'] == 'PASS', result


@pytest.mark.parametrize('changed', ['wrapper', 'source', 'receipt', 'netlist', 'log', 'unreferenced'])
def test_cold_native_abc_witness_cannot_borrow_other_or_changed_evidence(tmp_path, monkeypatch, changed):
    project, folder, netlist, sdc, _, _, _ = _cold_native_synthesis(tmp_path, monkeypatch)
    witness = folder / receipts.PROBE_DIR / 'synth'
    assert (witness / 'abc.script').is_file(), 'executed Phase2 graph was not retained'
    if changed == 'wrapper':
        (witness / 'abc.script').unlink()
    elif changed == 'source':
        (witness / 'abc_source_0.script').write_text('buffer -N 100\n')
    elif changed == 'receipt':
        path = folder / 'vibeic_receipt.json'
        path.write_text(path.read_text() + ' ')
    elif changed == 'netlist':
        netlist.write_text(netlist.read_text() + '// changed handoff bytes\n')
    elif changed == 'log':
        (folder / 'invocation.log').write_text('Running ABC script: unmeasured-other/abc.script\n')
    else:
        # A recipe present in the native folder is not a receipt-bound wrapper.
        (witness / 'abc.script').unlink()
        (folder / 'AREA_0.abc').write_text('buffer -N 4\n')
    receipts.claim(project)
    # A different live claim must not supply a convenient old wrapper either.
    decoy = receipts.abc_script_path(project)
    decoy.parent.mkdir(parents=True)
    decoy.write_text('buffer -N 4\n')
    receipts.synth_stage(project, netlist=netlist, top='core', liberties=[],
        sdc=sdc, to_container=str, execute=_source_control_census)
    measured = plan._stages(project, False)[0][0]
    assert measured['ran'] is False
    assert measured['synth_abc_buffering'] is False
    assert measured['applied']['fanout'] is None


@pytest.mark.parametrize('changed', [None, 'legacy', 'source'])
def test_synthesis_cache_requires_original_executed_abc_witness(tmp_path, monkeypatch, changed):
    project, folder, _, _, config, state, calls = _cold_native_synthesis(tmp_path, monkeypatch)
    original = (folder / 'vibeic_receipt.json').read_bytes()
    assert (folder / receipts.PROBE_DIR / 'synth/abc.script').is_file(), 'native graph missing before cache exercise'
    if changed == 'legacy':
        # A pre-fix receipt never bound an executed graph. Do not rehash it.
        shutil.rmtree(folder / receipts.PROBE_DIR)
    elif changed == 'source':
        (folder / receipts.PROBE_DIR / 'synth/abc_source_0.script').write_text('buffer -N 100\n')
    selected = ll.run_chain(project, 'candidate', [('Yosys.Synthesis', config, state)],
                            pdk_root='/pdk')[0]
    assert selected == folder
    assert len(calls) == (1 if changed is None else 2)
    receipt = ll.validate_step_receipt(folder, 'Yosys.Synthesis')
    script = folder / receipts.PROBE_DIR / 'synth/abc.script'
    assert receipt['sha256'][str(script.relative_to(folder))] == receipts._sha(script)
    if changed is not None:
        archived = list(folder.parent.glob('attempts/*/vibeic_receipt.json'))
        assert len(archived) == 1 and archived[0].read_bytes() == original


def _physical_spec_checkpoint(tmp_path, monkeypatch):
    """Real neutral native transport/handoff and retained producer snapshots.

    The prior complete acceptances are software fixture preconditions; no IC
    or EDA measurement qualification is claimed by this control.
    """
    import drv_run_identity as identity
    import step_output_collector as versions
    import _phase1_producer_identity as p1
    from programs.tests._p1_identity_fixture import stamp_current

    chain = ll.run_chain
    def prepare(project, image, steps, **kwargs):
        docs = project / identity.SPEC_DOCS
        (docs / 'L8_TIMING_WAVEFORM.json').write_text(json.dumps({
            'clock_domains': [{'role': 'primary', 'source_pin': 'clk', 'period_ns': 24}]}))
        (docs / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({
            'fields': {'constraint_declarations': [
                {'token': 'MAX_FANOUT_CONSTRAINT', 'value': '4'}]}}))
        liberty = project / 'cells.lib'
        liberty.write_text('library(neutral) { time_unit : "1ns"; }\n')
        config = steps[0][1]
        data = json.loads(config.read_text())
        data.update(CLOCK_PERIOD=24, MAX_FANOUT_CONSTRAINT=4,
                    LIB={'*': [str(liberty)]})
        config.write_text(json.dumps(data))
        return chain(project, image, steps, **kwargs)
    monkeypatch.setattr(ll, 'run_chain', prepare)
    project, native, netlist, sdc, config, _, calls = _cold_native_synthesis(tmp_path, monkeypatch)
    monkeypatch.setattr(ll, 'run_chain', chain)
    source = project / 'input/docs/spec.md'
    source.parent.mkdir(parents=True)
    source.write_text('Neutral source specification\n')
    stamp_current(project)
    docs = sorted((project / identity.SPEC_DOCS).glob('*.json'))
    rtl = project / 'phase2/stage1/rtl/core.v'
    ownership = {'D1': docs, '7': [sdc], '9': [netlist],
                 '10': [sdc], '13': [netlist], '14': [netlist]}
    def records(_project):
        for sid, paths in ownership.items():
            yield sid, 'neutral-' + sid, 'PASS', 'phase1' if sid == 'D1' else 'phase2', 'stage', [
                {'rel': str(path.relative_to(project)), 'abs': str(path), 'exists': True}
                for path in paths]
    monkeypatch.setattr(versions, '_iter_step_records', records)
    saved = {}
    def complete(sid, status='PASS'):
        inputs = {str(path.relative_to(project)): ll.digest(path) for path in
                  ([source] if sid == 'D1' else [rtl, sdc])}
        attempt = versions.begin_step(project, sid, inputs)
        saved[sid] = versions.finish_step(project, attempt, verdict=status,
            result={'runner': 'neutral-complete-predecessor-fixture',
                    'canonical_consumer': {'status': status}},
            canonical_pass=(status == 'PASS'))
        return saved[sid]
    for sid in ownership:
        complete(sid)
    old = identity.start(project)
    # A normal completed mapping checkpoint exists before the new Floorplan.
    receipts.synth_stage(project, netlist=netlist, top='core', liberties=[],
        sdc=sdc, to_container=str, execute=_source_control_census)
    assert next(row for row in plan._stages(project, True)[0]
                if row['name'] == 'synth')['ran'] is True
    l19 = project / identity.SPEC_DOCS / 'L19_CONSTRAINTS_PDK.json'
    changed = json.loads(l19.read_text())
    changed['_generator'] = {'emitter': 'neutral normal flow derivation'}
    changed['fields']['constraint_declarations'].append(
        {'token': 'PDN_VWIDTH', 'value': '4.2'})
    l19.write_text(json.dumps(changed))
    assert p1.record_derivation(project, l19.name, ll.digest(l19), 'neutral_normal_flow')
    return project, native, old, saved, complete, calls


def test_default_floorplan_rebuild_accepts_only_downstream_declared_spec_change(tmp_path, monkeypatch):
    import drv_run_identity as identity
    project, native, old, saved, _, calls = _physical_spec_checkpoint(tmp_path, monkeypatch)
    abc = receipts.abc_script_path(project)
    before = {path: path.read_bytes() for path in [abc, native / 'vibeic_receipt.json',
        project / 'steps' / saved['D1']['folder'] / 'outputs.json',
        project / 'steps' / saved['D1']['folder'] / 'L19_CONSTRAINTS_PDK.json']}
    new = identity.start(project, continue_steps=['15', '15.5ic', '16', '17', '19'])
    assert new['run_id'] == old['run_id']
    assert new['initial_spec_version'] == old['spec_version']
    assert new['spec_version'] == identity.spec_version(project) != old['spec_version']
    assert new['initial_code_identity']['plugin_tree_sha256'] == old['plugin_tree_sha256']
    assert {path: path.read_bytes() for path in before} == before
    # A second normal physical decision must retain the same original D1
    # basis and prove the preceding accepted spec through its derivation chain.
    import _phase1_producer_identity as p1
    l19 = project / identity.SPEC_DOCS / 'L19_CONSTRAINTS_PDK.json'
    changed = json.loads(l19.read_text())
    changed['fields']['constraint_declarations'][-1]['value'] = '4.8'
    l19.write_text(json.dumps(changed))
    assert p1.record_derivation(project, l19.name, ll.digest(l19), 'neutral_normal_flow')
    again = identity.start(project, continue_steps=['15', '15.5ic', '16', '17', '19'])
    assert again['run_id'] == old['run_id']
    assert again['initial_spec_version'] == old['spec_version']
    assert again['spec_version'] == identity.spec_version(project) != new['spec_version']
    assert {path: path.read_bytes() for path in before} == before
    assert len(calls) == 1, 'continuation must not rerun RTL or synthesis'


@pytest.mark.parametrize('changed', [
    'entry19', 'entry21', 'snapshot', 'other_doc', 'unknown_token', 'fanout',
    'clock', 'rtl', 'sdc', 'native_config', 'liberty', 'measured_fail',
    'unrecorded_edit', 'invalid_width'])
def test_downstream_spec_rebuild_preserves_upstream_and_unknown_refusals(tmp_path, monkeypatch, changed):
    import drv_run_identity as identity
    import _phase1_producer_identity as p1
    project, native, _, saved, complete, _ = _physical_spec_checkpoint(tmp_path, monkeypatch)
    docs = project / identity.SPEC_DOCS
    l19 = docs / 'L19_CONSTRAINTS_PDK.json'
    value = json.loads(l19.read_text())
    if changed == 'snapshot':
        (project / 'steps' / saved['D1']['folder'] / l19.name).write_text('{}')
    elif changed == 'other_doc':
        (docs / 'L9_INTEGRATION_SPEC.json').write_text('{"top_module":"other"}')
    elif changed == 'unknown_token':
        value['fields']['constraint_declarations'][-1]['token'] = 'UNSUPPORTED_PHYSICAL_KNOB'
    elif changed == 'fanout':
        value['fields']['constraint_declarations'][0]['value'] = '8'
    elif changed == 'clock':
        path = docs / 'L8_TIMING_WAVEFORM.json'
        path.write_text(path.read_text().replace('24', '12'))
    elif changed == 'rtl':
        path = project / 'phase2/stage1/rtl/core.v'
        path.write_text(path.read_text() + '// changed RTL\n')
    elif changed == 'sdc':
        (project / 'constraint.sdc').write_text('create_clock -period 12 [get_ports clk]\n')
    elif changed == 'native_config':
        (native / 'config.json').write_text('{}')
    elif changed == 'liberty':
        (project / 'cells.lib').write_text('library(other) {}')
    elif changed == 'measured_fail':
        complete('13', 'FAIL')
    elif changed == 'unrecorded_edit':
        value['fields']['constraint_declarations'][-1]['value'] = '5.0'
    elif changed == 'invalid_width':
        value['fields']['constraint_declarations'][-1]['value'] = '-4'
    if changed in ('unknown_token', 'fanout', 'unrecorded_edit', 'invalid_width'):
        l19.write_text(json.dumps(value))
        if changed != 'unrecorded_edit':
            assert p1.record_derivation(project, l19.name, ll.digest(l19), 'neutral_normal_flow')
    original = (project / identity.RECORD).read_bytes()
    abc = receipts.abc_script_path(project).read_bytes()
    with pytest.raises(ValueError, match='specification changed'):
        identity.start(project, continue_steps=[changed[5:] if changed.startswith('entry') else '15'])
    assert (project / identity.RECORD).read_bytes() == original
    assert receipts.abc_script_path(project).read_bytes() == abc


@pytest.mark.parametrize('native_rc', [0, 1])
def test_retained_backend_synth_census_mounts_staged_pdk(tmp_path, monkeypatch, native_rc):
    """A host-only staged Liberty reaches the native deck without resynthesis."""
    from types import SimpleNamespace
    import execution_backend_producers as backend
    import phase3_one_shot_runner as runner
    project = tmp_path / 'project'
    project.mkdir()
    receipts.claim(project)
    synth = runner._pl.synth_dir(project)
    synth.mkdir(parents=True, exist_ok=True)
    netlist = synth / 'neutral_synth.v'
    netlist.write_text('module neutral(input clk); endmodule\n')
    pnr = project / backend.PNR
    pnr.mkdir(parents=True)
    sdc = pnr / 'constraint.sdc'
    sdc.write_text('create_clock -period 10 [get_ports clk]\n')
    route = pnr / 'routed.def'
    route.write_text('DESIGN neutral ; END DESIGN\n')
    root = tmp_path / 'host-only-pdk'
    root.mkdir()
    liberty = root / 'neutral.lib'
    liberty.write_text('library(neutral) {}\n')
    evidence = receipts.abc_script_path(project).parent
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'census.log').write_text('old missing-Liberty failure\n')
    (evidence / 'behavior.rpt').write_text('old behavior must not become current\n')
    before = {p: p.read_bytes() for p in (netlist, route, sdc)}
    calls = []

    def transport(argv, *, supervised, log):
        calls.append(argv)
        flags = backend._dmem.docker_memory_flags()
        assert flags and argv[2:2 + len(flags)] == flags
        assert supervised is True
        assert log == evidence / 'census.log'
        assert argv[argv.index('test-image') + 1] == '--skip'
        assert 'sta' in argv and not any('yosys' in a for a in argv)
        assert f'{root}:{root}:ro' in argv
        assert f'{project}:{project}' in argv
        deck = Path(argv[-1]).read_text()
        assert f'read_liberty {{{liberty}}}' in deck
        assert f'read_verilog {{{netlist}}}' in deck
        assert f'read_sdc {{{sdc}}}' in deck
        if native_rc == 0:
            (evidence / 'behavior.rpt').write_text('native measurement\n')
        return SimpleNamespace(returncode=native_rc, stdout='', stderr='')

    monkeypatch.setattr(ll, 'run_container', transport)
    monkeypatch.setattr(ll, 'native_tool_command', lambda image, cmd: ('none', cmd))
    receipt = backend._retained_synth_census(
        project, {'top': 'neutral', 'pdk_root': str(root), 'image_id': 'test-image'},
        runner, ll, SimpleNamespace(liberty=liberty))
    result = json.loads(receipt.read_text())
    assert len(calls) == 1
    assert ('behavior_report' in result) == (native_rc == 0)
    assert result['ran'] is False  # no ABC evidence: measurement cannot invent synthesis proof
    assert {p: p.read_bytes() for p in before} == before
    archives = list((project / 'reports/phase3/drv_stage_history').glob('retained-synth-census-*'))
    assert len(archives) == 1
    assert (archives[0] / 'evidence/synth/census.log').read_text() == 'old missing-Liberty failure\n'
    assert (archives[0] / 'evidence/synth/behavior.rpt').read_text() == 'old behavior must not become current\n'


def test_bounded_step32_refreshes_retained_census_before_native_consumer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import execution_backend_producers as backend
    calls = []
    runner = SimpleNamespace(step_postroute_repair_librelane=lambda *_: (
        calls.append('step32') or SimpleNamespace(status='FAIL', detail='real design failure')))
    monkeypatch.setattr(backend, '_parameters', lambda *_: (runner, ll, object(), 'unused'))
    monkeypatch.setattr(backend, '_retained_synth_census', lambda *_: calls.append('retained_census'))
    result = backend.produce_signoff(tmp_path, {
        'step_id': '32', 'top': 'neutral', 'pdk_root': str(tmp_path), 'image_id': 'test-image'})
    assert calls == ['retained_census', 'step32']
    assert result == {'verdict': 'FAIL', 'detail': 'real design failure'}


@pytest.mark.parametrize('damage', ['missing_pre', 'changed_final', 'warning'])
def test_cold_native_handoff_keeps_critical_check_refusals(tmp_path, monkeypatch, damage):
    import synth_handoff_netlist_check as handoff
    import hashlib
    project, folder, mapped, _, _, _, _ = _cold_native_synthesis(tmp_path, monkeypatch)
    if damage == 'missing_pre':
        (folder / 'reports/pre_synth_chk.rpt').unlink()
    else:
        target = folder / 'reports/chk.rpt'
        target.write_text('Warning: Wire core.\\missing is used but has no driver.\n'
                          'Found and reported 1 problems.\n')
        if damage == 'warning':
            # Bind the bad CHECK bytes as if produced by the native transport:
            # matching hashes must not excuse a genuine measured check failure.
            receipt = folder / 'vibeic_receipt.json'
            doc = json.loads(receipt.read_text())
            doc['sha256']['reports/chk.rpt'] = hashlib.sha256(target.read_bytes()).hexdigest()
            receipt.write_text(json.dumps(doc))
    with pytest.raises((ValueError, OSError)):
        handoff.publish_handoff(project, folder, mapped, 'core')
