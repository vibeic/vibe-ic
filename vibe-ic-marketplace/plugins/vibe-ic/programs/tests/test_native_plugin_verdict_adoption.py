"""Focused native controls for the blocking GLS and post-route adoption hooks."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "librelane_plugins"))

from librelane.config import Config
from librelane.common import Path as LLPath
from librelane.flows.classic import Classic
from librelane.state import DesignFormat, State
from librelane.steps.step import StepError
from librelane_plugin_vibeic import GateLevelSim
from librelane_plugin_vibeic.postroute_repair import (
    PostRouteRepair, PostRouteRepairAdoption,
)
from _hostpaths import require_repo


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _gls_subject(tmp_path: Path, mode: str):
    folder = tmp_path / "step"
    folder.mkdir()
    netlist = _write(tmp_path / "chip_top.nl.v", "module chip_top; endmodule\n")
    sdf = _write(tmp_path / "chip_top.sdf", "(DELAYFILE (SDFVERSION \"3.0\"))\n")
    stubs = _write(tmp_path / "stubs.v", "")
    outcome = {
        "good": '$display("[TB case_1] PASS"); $finish;',
        "bad_sim": '$display("[TB case_1] FAIL"); $finish;',
        # The calibrated judge sees a complete PASS transcript. The native
        # hook must still reject the process exit status.
        "nonzero": '$display("[TB case_1] PASS"); $fatal(3, "forced nonzero");',
    }.get(mode, '$display("[TB case_1] PASS"); $finish;')
    tb = _write(tmp_path / "tb.v", """
module tb_case;
  chip_top dut();
  initial begin
    $display("SDF INFO: chip_top.sdf:1: Putting delay: 0.001 for index 0");
    %s
  end
endmodule
""" % outcome)
    if mode == "compile_fail":
        netlist.write_text("module chip_top(\n")
    manifest = {
        "compile_flags": "-g2012", "netlist": str(netlist),
        "cases": [{"id": "case_1", "module": "tb_case", "testbench": str(tb)}],
        "models": [], "stubs": str(stubs), "sdf_placeholder": "__SDF__",
        "model_closure": {"files": []}, "not_a_subject": [],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    instance = SimpleNamespace(
        id=GateLevelSim.id,
        config={"VIBEIC_GLS_MANIFEST": str(manifest_path),
                "VIBEIC_GLS_TIMEOUT_S": 30},
        step_dir=str(folder), _run=GateLevelSim._run)
    state = {DesignFormat.NETLIST: str(netlist),
             DesignFormat.SDF: {"corner": str(sdf)}}
    return instance, state, folder


def test_gate_level_sim_good_native_process_passes(tmp_path):
    instance, state, folder = _gls_subject(tmp_path, "good")
    _, metrics = GateLevelSim.run(instance, state)
    assert metrics["vibeic__gls__passed"] == 1
    assert json.loads((folder / "gls_results.json").read_text())["verdict"] == "PASS"


@pytest.mark.parametrize("mode", ["bad_sim", "compile_fail", "nonzero"])
def test_gate_level_sim_bad_native_process_blocks(tmp_path, mode):
    instance, state, folder = _gls_subject(tmp_path, mode)
    with pytest.raises(StepError, match="BLOCKING gate-level simulation"):
        GateLevelSim.run(instance, state)
    result = json.loads((folder / "gls_results.json").read_text())
    assert result["verdict"] == "FAIL"
    if mode in ("compile_fail", "nonzero"):
        assert result["native_exit_failures"]


def _measurement(*, setup=-0.2, hold=0.0, slew=1, cap=0, fanout=0,
                 antenna=0):
    return {
        "unmeasured_corners": [],
        "setup_ws": {"corner": setup}, "hold_ws": {"corner": hold},
        "drv": {"slew": {"corner": slew}, "cap": {"corner": cap},
                "fanout": {"corner": fanout}},
        "antenna_nets": antenna, "antenna_pins": antenna,
    }


_ROUTE_CLEAN = {
    "vibeic__prr__before__unrouted__count": 0,
    "vibeic__prr__after__unrouted__count": 0,
    "vibeic__prr__unrouted__added": 0,
}


def test_postroute_improving_candidate_is_adopted():
    decision, _ = PostRouteRepairAdoption._adoption_decision(
        _measurement(), _measurement(setup=0.1, slew=0), _ROUTE_CLEAN,
        {"action": "RUN"})
    assert decision == "ADOPTED"


@pytest.mark.parametrize("candidate", [
    _measurement(setup=-0.3),
    _measurement(hold=-0.1),
    _measurement(slew=2),
])
def test_postroute_worse_candidate_is_rolled_back(candidate):
    decision, reason = PostRouteRepairAdoption._adoption_decision(
        _measurement(), candidate, _ROUTE_CLEAN, {"action": "RUN"})
    assert decision == "ROLLED_BACK"
    assert "regressed" in reason


def test_postroute_measured_clean_input_is_named_no_repair():
    decision, reason = PostRouteRepairAdoption._adoption_decision(
        _measurement(setup=0.1, slew=0), _measurement(setup=0.1, slew=0), {},
        {"action": "SKIP"})
    assert decision == "NO_REPAIR"
    assert "measured clean" in reason


def _native_metrics(*, setup, hold=0.0, slew=0):
    return {
        "timing__setup__ws__corner:corner": setup,
        "timing__hold__ws__corner:corner": hold,
        "design__max_slew_violation__count__corner:corner": slew,
        "design__max_cap_violation__count__corner:corner": 0,
        "design__max_fanout_violation__count__corner:corner": 0,
        "antenna__violating__nets": 0,
        "antenna__violating__pins": 0,
    }


@pytest.mark.parametrize("candidate_setup,candidate_slew,expected", [
    (0.1, 0, "ADOPTED"),
    (-0.3, 1, "ROLLED_BACK"),
    (None, None, "NO_REPAIR"),
])
def test_native_run_returns_only_the_selected_state(
        tmp_path, candidate_setup, candidate_slew, expected):
    baseline_odb = _write(tmp_path / "baseline.odb", "baseline")
    candidate_odb = _write(tmp_path / "candidate.odb", "candidate")
    clean = expected == "NO_REPAIR"
    baseline_metrics = _native_metrics(
        setup=0.1 if clean else -0.2, slew=0 if clean else 1)
    baseline = State({"odb": LLPath(str(baseline_odb))}, metrics=baseline_metrics)
    input_state = State({"odb": LLPath(str(baseline_odb))})
    candidate_raw = State({"odb": LLPath(str(candidate_odb))}, metrics={
        "vibeic__prr__before__unrouted__count": 0,
        "vibeic__prr__after__unrouted__count": 0,
        "vibeic__prr__unrouted__added": 0,
    })
    candidate = None if clean else State(
        {"odb": LLPath(str(candidate_odb))},
        metrics={**candidate_raw.metrics,
                 **_native_metrics(setup=candidate_setup, slew=candidate_slew)})

    def measure(_state, prefix):
        return baseline if prefix == "baseline" else candidate

    def start_child(*_args):
        assert not clean, "a measured-clean input must not launch a candidate"
        return candidate_raw

    instance = SimpleNamespace(
        id=PostRouteRepairAdoption.id, config={"STA_CORNERS": ["corner"]},
        step_dir=str(tmp_path), _measure=measure, _start_child=start_child,
        _antenna=PostRouteRepairAdoption._antenna,
        _adoption_decision=PostRouteRepairAdoption._adoption_decision,
        _views=PostRouteRepairAdoption._views)
    views, _ = PostRouteRepairAdoption.run(instance, input_state)
    record = json.loads((tmp_path / "postroute_adoption.json").read_text())
    assert record["decision"] == expected
    selected = candidate_odb if expected == "ADOPTED" else baseline_odb
    assert Path(views[DesignFormat.ODB]) == selected


def test_native_flow_inserts_adoption_hook_with_meta_substituting_steps(tmp_path):
    config = _write(tmp_path / "config.yaml", """
meta:
  flow: Classic
  substituting_steps:
    "+OpenROAD.DetailedRouting": "Vibeic.PostRouteRepairAdoption"
""")
    meta = Config.get_meta(str(config))
    assert meta is not None and meta.substituting_steps is not None
    substituted = Classic.Substitute(meta.substituting_steps)
    ids = [step.id for step in substituted.Steps]
    route = ids.index("OpenROAD.DetailedRouting")
    assert ids[route + 1] == "Vibeic.PostRouteRepairAdoption"
    assert PostRouteRepair.id == "Vibeic.PostRouteRepair"


def test_hooks_are_backed_by_the_checked_in_plugin_sources():
    root = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "librelane_plugins", "librelane_plugin_vibeic")
    init = (root / "__init__.py").read_text()
    repair = (root / "postroute_repair.py").read_text()
    assert "sgs.judge_tool_arm" in init
    assert 'id = "Vibeic.PostRouteRepairAdoption"' in repair
