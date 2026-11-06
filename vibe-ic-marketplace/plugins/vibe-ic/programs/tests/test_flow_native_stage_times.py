import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

import flow_config
import flow_engine


def test_ordinary_synthesis_keeps_native_strategy_without_search(tmp_path, monkeypatch):
    class Config(dict):
        def copy(self, **changes):
            return Config({**self, **changes})

        def to_raw_dict(self):
            return dict(self)

    chain = flow_engine.NativeChain(tmp_path, {"delivery_target": "ip_hardmacro"})
    chain.owner = SimpleNamespace(config=Config(SYNTH_STRATEGY="AREA 0"))
    class State(dict):
        metrics = {}

        def dumps(self):
            return "{}"

    class Synthesis:
        def __init__(self, config, state):
            self.state = state

        def start(self, **kwargs):
            return self.state

    chain.state = State()
    chain.owner.gating_config_vars = {}
    steps = ModuleType("librelane.steps")
    steps.Step = SimpleNamespace(factory=SimpleNamespace(get=lambda name: Synthesis))
    steps.StepError = type("StepError", (Exception,), {})
    steps.StepException = type("StepException", (Exception,), {})
    monkeypatch.setitem(sys.modules, "librelane.steps", steps)
    monkeypatch.setattr(chain, "initialize", lambda: None)
    monkeypatch.setattr(flow_config, "explore_synthesis", lambda *args: "DELAY 4")
    table = flow_engine.read_json(flow_engine.TABLE)
    row = next(row for row in table["steps"] if row["name"] == "synthesis")
    assert "Yosys.Synthesis" in row["tool"]["steps"]
    assert chain.execute(tmp_path, row["tool"]).exit_code == 0
    assert chain.owner.config["SYNTH_STRATEGY"] == "AREA 0"


@pytest.mark.parametrize("missing_corner", [False, True])
@pytest.mark.parametrize("change", ["none", "master", "position", "pin", "port"])
def test_routed_sizing_reads_corners_then_releases_only_signal_wires(tmp_path, missing_corner, change):
    changed = change != "none"
    tclsh = shutil.which("tclsh")
    if tclsh is None:
        pytest.skip("Tcl interpreter is required")
    script = (Path(flow_engine.TABLE).parent.parent / "programs/librelane_plugins/"
              "librelane_plugin_vibeic/postroute_sizing.tcl")
    prefix = r'''
rename source native_source
proc source {args} {}
proc read_current_odb {} {}
proc all_clocks {} {return clk}
proc set_propagated_clock {args} {}
proc set_dont_touch_objects {} {}
proc unset_dont_touch_objects {} {}
proc remove_fillers {} {puts REMOVE_FILL}
namespace eval lln {proc get_corner_names {} {return {min_fast nom_typ max_slow}}}
proc read_spef {args} {puts "SPEF $args"}
proc estimate_parasitics {args} {puts "ESTIMATE $args"}
proc append_if_exists_argument {name key option} {
    upvar 1 $name value
    if {[info exists ::env($key)]} {lappend value $option $::env($key)}
}
proc log_cmd {args} {puts "CALL $args"; set ::edited 1}
proc block {method} {
    switch $method {
        getInsts {return cell}
        getNets {return {signal power ground special}}
    }
}
proc cell {method} {
    switch $method {
        getName {return cell}
        getMaster {return master}
        getLocation {return [expr {$::edited && $::change eq "position" ? "10 0" : "0 0"}]}
        getOrient {return R0}
        getPlacementStatus {return PLACED}
    }
}
proc master {method} {return [expr {$::edited && $::change eq "master" ? "wide" : "small"}]}
proc pin {method} {
    switch $method {
        getInst {return cell}
        getMTerm {return terminal}
    }
}
proc terminal {method} {return [expr {$::edited && $::change eq "pin" ? "B" : "A"}]}
proc port {method} {return [expr {$::edited && $::change eq "port" ? "out_b" : "out_a"}]}
foreach {net type special} {signal SIGNAL 0 power POWER 0 ground GROUND 0 special SIGNAL 1} {
    proc $net {method} [string map [list TYPE $type SPECIAL $special NET $net] {
        switch $method {
            isSpecial {return SPECIAL}
            getSigType {return TYPE}
            getWire {return NET-wire}
            getName {return NET}
            getITerms {return [expr {"NET" eq "signal" ? "pin" : ""}]}
            getBTerms {return [expr {"NET" eq "signal" ? "port" : ""}]}
        }
    }]
}
namespace eval odb {proc dbWire_destroy {wire} {puts "DESTROY $wire"}}
namespace eval utl {proc metric_integer {key value} {puts "METRIC $key $value"}}
proc write_views {} {puts WRITE_VIEWS}
set ::block block
set ::env(SCRIPTS_DIR) unused
set ::env(VIBEIC_PRR_SETUP_MARGIN) 0
set ::env(VIBEIC_PRR_HOLD_MARGIN) 0
set ::env(VIBEIC_PRR_SETUP_MAX_BUFFER_PCT) 5
set ::env(VIBEIC_PRR_HOLD_MAX_BUFFER_PCT) 5
set ::env(VIBEIC_PRR_SETUP_SEQUENCE) default
set ::env(VIBEIC_ROUTED_SPEFS) {min_* min.spef nom_* nom.spef max_* max.spef}
'''
    prefix += f"set ::edited 0\nset ::change {change}\n"
    if missing_corner:
        prefix += "set ::env(VIBEIC_ROUTED_SPEFS) {nom_* nom.spef}\n"
    runner = tmp_path / "run.tcl"
    runner.write_text(prefix + script.read_text())
    result = subprocess.run([tclsh, str(runner)], text=True, capture_output=True)
    if missing_corner:
        assert result.returncode != 0
        assert "No routed SPEF for corner min_fast" in result.stderr
        assert "CALL " not in result.stdout
        assert "WRITE_VIEWS" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert lines[:5] == ["REMOVE_FILL", "SPEF -corner min_fast min.spef",
                             "SPEF -corner nom_typ nom.spef", "SPEF -corner max_slow max.spef",
                             "ESTIMATE -detailed_routing"]
        calls = [line for line in lines if line.startswith("CALL ")]
        assert len(calls) == 4
        assert calls[0] == calls[3] == "CALL repair_design -verbose"
        assert calls[1].startswith("CALL repair_timing -setup ")
        assert calls[2].startswith("CALL repair_timing -hold ")
        assert [line for line in lines if line.startswith("DESTROY ")] == (
            ["DESTROY signal-wire"] if changed else [])
        assert f"METRIC vibeic__postroute__changed {int(changed)}" in lines
        assert lines[-1] == "WRITE_VIEWS"
