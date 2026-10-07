"""Steps 24, 26 and 26.5ic on LibreLane tool steps (lane mig101).

Every sample below is the tool's own output as measured on the spm copy
(gf180mcuD, vibeic-eda 0.3.79): PSM's IR report and resistance debug print,
LibreLane's per-net metric keys, the tech LEF's layer grammar.  Only an EDA
tool's file writes are faked (a stand-in `docker` that writes what the tool
would, a KLayout runner that writes the verifier's report); the code under
test is the shipped code.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import librelane_contract as ll  # noqa: E402
import librelane_ir_antenna as la  # noqa: E402
ir_rules = la._plugin_module('ir_rules')

# --- measured samples --------------------------------------------------------

#: LibreLane OpenROAD.IRDropReport state metrics (spm, LEF resistance).
MEASURED_METRICS = {
    "design_powergrid__drop__worst__net:VDD__corner:nom_tt_025C_5v00": 0.0072882,
    "design_powergrid__drop__worst__net:VSS__corner:nom_tt_025C_5v00": 0.00824424,
    "design_powergrid__drop__worst__net:VDD": 0.0072882,
    "design_powergrid__drop__worst__net:VSS": 0.00824424,
    "design_powergrid__drop__worst": 0.00824424,
    # LibreLane's legacy key: the FIRST net's drop (re.search), not the worst.
    "ir__drop__worst": 0.00729,
}

#: PSM's `getResistanceMap` debug print, as LibreLane's PDK config drives it.
PSM_MAP_PDK_LAYERS_RC = """\
[DEBUG PSM-resistance] Estimate parasitics resistance for Metal1 = 0
[DEBUG PSM-resistance] Database resistance for Metal1 = 0.09
[DEBUG PSM-resistance] Estimate parasitics resistance for Via1 = 16.844999313354492
[DEBUG PSM-resistance] Estimate parasitics resistance for Metal2 = 0.00010804107788085939
[DEBUG PSM-resistance] Estimate parasitics resistance for Via2 = 16.844999313354492
[DEBUG PSM-resistance] Estimate parasitics resistance for Metal5 = 3.488223266601562e-05
"""
#: ... and with the step config's LAYERS_RC/VIAS_R cleared (the tech LEF).
PSM_MAP_TECH_LEF = """\
[DEBUG PSM-resistance] Estimate parasitics resistance for Metal1 = 0
[DEBUG PSM-resistance] Database resistance for Metal1 = 0.09
[DEBUG PSM-resistance] Estimate parasitics resistance for Via1 = 0
[DEBUG PSM-resistance] Database resistance for Via1 = 4.5
[DEBUG PSM-resistance] Estimate parasitics resistance for Metal2 = 0
[DEBUG PSM-resistance] Database resistance for Metal2 = 0.09
[DEBUG PSM-resistance] Estimate parasitics resistance for Via2 = 0
[DEBUG PSM-resistance] Database resistance for Via2 = 4.5
[DEBUG PSM-resistance] Estimate parasitics resistance for Metal5 = 0
[DEBUG PSM-resistance] Database resistance for Metal5 = 0.06
"""

#: The gf180mcuD tech LEF's shape: a PROPERTYDEFINITIONS `LAYER` line and a
#: multi-line quoted PROPERTY inside a cut layer.
TECH_LEF = """\
PROPERTYDEFINITIONS
  LAYER LEF58_EOLENCLOSURE STRING ;
END PROPERTYDEFINITIONS
LAYER Metal1
  TYPE ROUTING ;
  WIDTH 0.230 ;                      # Mn.1  (n=1)
  RESISTANCE RPERSQ 0.090 ;
END Metal1
LAYER Via1
  TYPE CUT ;
  WIDTH   0.26 ;
  PROPERTY LEF58_EOLENCLOSURE "
    EOLENCLOSURE 0.34 0.06 ;
    LAYER Metal2 ; " ;
  RESISTANCE 4.5 ;
END Via1
LAYER Metal2
  TYPE ROUTING ;
  RESISTANCE RPERSQ 0.090 ;
END Metal2
LAYER Via2
  TYPE CUT ;
  RESISTANCE 4.5 ;
END Via2
LAYER Metal5
  TYPE ROUTING ;
  RESISTANCE RPERSQ 0.060 ;
END Metal5
"""


# --- step 24: the rule ---------------------------------------------------------

def test_the_ir_verdict_reads_the_worst_net_not_the_first():
    doc = ir_rules.ir_findings(MEASURED_METRICS, ["VDD"], ["VSS"], 5.0, 10.0)
    assert doc["worst_net"] == "VSS"
    assert doc["worst_drop_v"] == pytest.approx(0.00824424)
    assert doc["verdict"] == "PASS"


def test_a_declared_net_that_was_not_analysed_fails_by_name():
    metrics = {k: v for k, v in MEASURED_METRICS.items() if "VSS" not in k}
    doc = ir_rules.ir_findings(metrics, ["VDD"], ["VSS"], 5.0, 10.0)
    assert doc["verdict"] == "FAIL"
    assert doc["unanalysed_declared_nets"] == ["VSS"]


@pytest.mark.parametrize("supply,budget", [(None, 10.0), (0.0, 10.0), (5.0, None)])
def test_no_supply_or_no_budget_is_not_measured_never_pass(supply, budget):
    doc = ir_rules.ir_findings(MEASURED_METRICS, ["VDD"], ["VSS"], supply, budget)
    assert doc["verdict"] == "NOT_MEASURED"


def test_a_drop_over_budget_fails():
    doc = ir_rules.ir_findings(MEASURED_METRICS, ["VDD"], ["VSS"], 5.0, 0.1)
    assert doc["verdict"] == "FAIL" and "VSS" in doc["reason"]


# --- step 24: the instruments --------------------------------------------------

def _tool_folder(tmp_path, log: str, metrics=None, env_voltage="5") -> Path:
    folder = tmp_path / "phase3/librelane/24/01-openroad-irdropreport"
    folder.mkdir(parents=True)
    (folder / "openroad-irdropreport.log").write_text(log)
    (folder / "_env.tcl").write_text(f"set ::env(LIB_VOLTAGE) {env_voltage}\n")
    (folder / "state_out.json").write_text(json.dumps({"metrics": metrics or MEASURED_METRICS}))
    return folder


def test_the_tech_lef_reader_skips_property_grammar():
    lef = la.lef_resistance(TECH_LEF)
    assert lef == {"Metal1": {"type": "ROUTING", "value": 0.09},
                   "Via1": {"type": "CUT", "value": 4.5},
                   "Metal2": {"type": "ROUTING", "value": 0.09},
                   "Via2": {"type": "CUT", "value": 4.5},
                   "Metal5": {"type": "ROUTING", "value": 0.06}}


def test_the_resistance_map_is_the_value_psm_solved_with(tmp_path):
    folder = _tool_folder(tmp_path, PSM_MAP_TECH_LEF)
    assert la.resistance_map(folder) == {"Metal1": 0.09, "Via1": 4.5, "Metal2": 0.09,
                                         "Via2": 4.5, "Metal5": 0.06}


def test_the_pdk_layers_rc_model_is_caught(tmp_path):
    folder = _tool_folder(tmp_path, PSM_MAP_PDK_LAYERS_RC)
    rc = la.rc_model(la.resistance_map(folder), la.lef_resistance(TECH_LEF))
    assert rc["verdict"] == "DISAGREE"
    assert set(rc["disagreeing"]) == {"Via1", "Metal2", "Via2", "Metal5"}


def test_the_tech_lef_model_agrees(tmp_path):
    folder = _tool_folder(tmp_path, PSM_MAP_TECH_LEF)
    assert la.rc_model(la.resistance_map(folder), la.lef_resistance(TECH_LEF))["verdict"] == "AGREE"


def test_no_resistance_print_is_not_measured():
    assert la.rc_model({}, la.lef_resistance(TECH_LEF))["verdict"] == "NOT_MEASURED"


def test_arms_on_one_basis_agree_to_print_precision():
    same = la.ir_agreement({"VDD": 0.0072882, "VSS": 0.00824424},
                           {"VDD": 0.0072882, "VSS": 0.00824424})
    assert same["verdict"] == "AGREE"
    # the direct session's own basis (DEF only, no SDC/SPEF) on the same layout
    other = la.ir_agreement({"VDD": 0.0072882, "VSS": 0.00824424},
                            {"VDD": 0.015, "VSS": 0.017})
    assert other["verdict"] == "DISAGREE" and other["disagreeing"] == ["VDD", "VSS"]
    assert la.ir_agreement({"VDD": 0.0072882}, {"VDD": 0.0072882, "VSS": 0.008})["verdict"] == "DISAGREE"
    assert la.ir_agreement({}, {"VDD": 1.0})["verdict"] == "NOT_COMPARABLE"


def test_lib_voltage_is_read_from_the_step_environment(tmp_path):
    assert la.lib_voltage(_tool_folder(tmp_path, "")) == 5.0


# --- step 24: declared voltage sources ------------------------------------------

_PADS = {"u_pad_supply_power": [924.8, 26.0, 999.8, 376.0],
         "u_pad_supply_ground": [1543.5, 26.0, 1618.5, 376.0]}


def _bterm(net, box):
    return {"net": net, "bterm": net, "layer": "Metal5", "box": box}


def test_bterms_on_the_declared_pads_are_the_declared_source_model():
    geometry = {"pads": _PADS, "missing_pads": [], "missing_nets": [],
                "bterms": [_bterm("VDD", [932.3, 28.0, 992.3, 88.0]),
                           _bterm("VSS", [1551.0, 28.0, 1611.0, 88.0])]}
    doc = la.declared_sources(geometry, ["VDD"], ["VSS"])
    assert doc["coincident"] is True
    assert doc["sources"]["VDD"][0]["pad"] == "u_pad_supply_power"
    assert doc["sources"]["VSS"][0]["size"] == pytest.approx(60.0)


def test_a_bterm_off_the_declared_pads_is_not_the_declared_model():
    geometry = {"pads": _PADS, "missing_pads": [], "missing_nets": [],
                "bterms": [_bterm("VDD", [932.3, 28.0, 992.3, 88.0]),
                           _bterm("VDD", [10.0, 10.0, 20.0, 20.0]),
                           _bterm("VSS", [1551.0, 28.0, 1611.0, 88.0])]}
    doc = la.declared_sources(geometry, ["VDD"], ["VSS"])
    assert doc["coincident"] is False
    assert doc["bterms_outside_declared_pads"] == ["VDD:VDD"]


def test_a_declared_pad_hosting_no_supply_terminal_is_refused():
    geometry = {"pads": _PADS, "missing_pads": [], "missing_nets": [],
                "bterms": [_bterm("VDD", [932.3, 28.0, 992.3, 88.0]),
                           _bterm("VSS", [932.4, 30.0, 990.0, 80.0])]}
    with pytest.raises(ll.Refusal, match="LL_VSRC_PAD_TERMINAL_MISSING"):
        la.declared_sources(geometry, ["VDD"], ["VSS"])


def test_a_declared_net_with_no_terminal_on_a_pad_is_refused():
    geometry = {"pads": _PADS, "missing_pads": [], "missing_nets": [],
                "bterms": [_bterm("VDD", [932.3, 28.0, 992.3, 88.0])]}
    with pytest.raises(ll.Refusal, match="LL_VSRC_NET_UNSOURCED"):
        la.declared_sources(geometry, ["VDD"], ["VSS"])


def test_the_vsrc_file_is_psm_grammar(tmp_path):
    files = la.write_vsrc({"VDD": [{"x": 962.3, "y": 58.0, "size": 60.0}]}, {"VDD": 5.0}, tmp_path)
    assert files["VDD"].read_text() == "962.3000,58.0000,60.0000,5\n"


# --- step 24: the judgment -------------------------------------------------------

def _record(tmp_path, log=PSM_MAP_TECH_LEF, metrics=None, deck=None, rc="AGREE"):
    folder = _tool_folder(tmp_path, log, metrics)
    return {"tool_state": str(folder / "state_out.json"), "vdd_nets": ["VDD"],
            "gnd_nets": ["VSS"], "lib_voltage_v": 5.0, "budget_pct": 10.0,
            "rc_model": {"verdict": rc, "disagreeing": [] if rc == "AGREE" else ["Metal2"]},
            "cross_check": deck if deck is not None else {
                "verdict": "MEASURED",
                "per_net_worst_drop_v": {"VDD": 0.0072882, "VSS": 0.00824424}}}


def test_the_tool_path_passes_when_every_instrument_agrees(tmp_path):
    judged = la.judge_ir(_record(tmp_path))
    assert judged["verdict"] == "PASS", judged["reasons"]


def test_arms_that_disagree_fail(tmp_path):
    deck = {"verdict": "MEASURED", "per_net_worst_drop_v": {"VDD": 0.015, "VSS": 0.017}}
    judged = la.judge_ir(_record(tmp_path, deck=deck))
    assert judged["verdict"] == "FAIL"
    assert any(r.startswith("LL_IR_ARMS_DISAGREE") for r in judged["reasons"])


def test_a_resistance_model_off_the_tech_lef_fails(tmp_path):
    judged = la.judge_ir(_record(tmp_path, rc="DISAGREE"))
    assert any(r.startswith("LL_IR_RC_MODEL_INCONSISTENT") for r in judged["reasons"])


def test_an_unreached_supply_terminal_fails(tmp_path):
    log = PSM_MAP_TECH_LEF + "[WARNING PSM-0039] Unconnected instance u1/VDD at location (1, 2).\n"
    judged = la.judge_ir(_record(tmp_path, log=log))
    assert judged["verdict"] == "FAIL"


def test_an_unmeasured_cross_check_is_not_a_pass(tmp_path):
    judged = la.judge_ir(_record(tmp_path, deck={"verdict": "NOT_MEASURED", "reason": "rc=1"}))
    assert judged["verdict"] == "NOT_MEASURED"


# --- step 26: the two kept rules ----------------------------------------------------

def _model(counts, subject):
    return {"counts": counts, "subject_sha256": subject}


def test_both_models_clean_on_the_shipped_layout_pass():
    judged = la.judge_antenna(
        _model({"antenna__violating__nets": 0, "antenna__violating__pins": 0}, "d1"),
        _model({"klayout__antenna_error__count": 0}, "g1"), {"def": "d1", "gds": "g1"})
    assert judged["verdict"] == "PASS"


def test_router_clean_and_deck_not_is_a_disagreement():
    # G-SHIP-ANTENNA's shape: 0/0 from the router, 7 ANT.16_ii_ANT.4 on the GDS.
    judged = la.judge_antenna(
        _model({"antenna__violating__nets": 0, "antenna__violating__pins": 0}, "d1"),
        _model({"klayout__antenna_error__count": 7}, "g1"), {"def": "d1", "gds": "g1"})
    assert judged["verdict"] == "FAIL"
    assert any(r.startswith("LL_ANTENNA_MODELS_DISAGREE") for r in judged["reasons"])


def test_a_count_about_another_layout_is_not_evidence():
    judged = la.judge_antenna(
        _model({"antenna__violating__nets": 0, "antenna__violating__pins": 0}, "pre-promotion"),
        _model({"klayout__antenna_error__count": 0}, "g1"), {"def": "shipped", "gds": "g1"})
    assert judged["verdict"] == "FAIL"
    assert any(r.startswith("LL_ANTENNA_EVIDENCE_STALE") for r in judged["reasons"])


def test_a_missing_model_or_count_is_not_measured():
    router = _model({"antenna__violating__nets": 0, "antenna__violating__pins": 0}, "d1")
    assert la.judge_antenna(router, None, {"def": "d1", "gds": None})["verdict"] == "NOT_MEASURED"
    gds = _model({"klayout__antenna_error__count": None}, "g1")
    assert la.judge_antenna(router, gds, {"def": "d1", "gds": "g1"})["verdict"] == "NOT_MEASURED"


# --- the contract: plugin steps and OpenROAD init lines ----------------------------

def test_the_init_file_carries_caller_lines(tmp_path):
    assert ll.openroad_home(tmp_path / "none", {"openroad_aliases": {}}) is None
    home = ll.openroad_home(tmp_path / "h", {"openroad_aliases": {}}, la.PSM_RESISTANCE_DEBUG)
    assert "set_debug_level PSM resistance 2" in (home / ".openroad").read_text()


_FAKE_DOCKER = r'''#!/usr/bin/env python3
"""Stand-in `docker`: writes what `librelane.steps run` writes, logs argv."""
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(argv) + "\n")
if "librelane.steps" in argv:
    out = argv[argv.index("-o") + 1]
    os.makedirs(out, exist_ok=True)
    state = json.load(open(argv[argv.index("-i") + 1]))
    state["metrics"] = {"x": 1}
    json.dump(state, open(os.path.join(out, "state_out.json"), "w"))
    print("offline step transport completed")
'''


def _fake_docker(tmp_path, monkeypatch):
    docker = tmp_path / "bin" / "docker"
    docker.parent.mkdir()
    docker.write_text(_FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setitem(ll._CAPABILITY, ("img", str(docker)),
                        {"image": "img", "openroad_aliases": {}, "tcl_probe": "MEASURED"})
    return docker, log


def _chain_inputs(tmp_path):
    project = tmp_path / "proj"
    (project / "phase3").mkdir(parents=True)
    view = project / "d.def"
    view.write_text("DESIGN x ;\n")
    state = project / "state_in.json"
    state.write_text(json.dumps({"odb": str(view), "def": str(view), "nl": str(view),
                                 "sdc": str(view), "metrics": {}}))
    config = project / "c.json"
    config.write_text(json.dumps({"meta": {"step": "Vibeic.IRDropChecker"}}))
    return project, state, config


def test_a_step24_plugin_step_carries_its_code_and_init_lines(tmp_path, monkeypatch):
    docker, log = _fake_docker(tmp_path, monkeypatch)
    project, state, config = _chain_inputs(tmp_path)
    run = lambda: ll.run_chain(project, "img", [("Vibeic.IRDropChecker", config, state)],
                               docker=str(docker), lane="l",
                               openroad_init=["set_debug_level PSM resistance 2"], pdk_root='/pdk')
    folder = run()[0]
    argv = json.loads(log.read_text().splitlines()[-1])
    assert f"PYTHONPATH={ll.PLUGIN_ROOT.resolve()}" in argv
    fingerprint = json.loads((folder / "input_fingerprint.json").read_text())
    for name in ("ir_drop.py", "ir_rules.py", "transient.py", "transient_ir.tcl"):
        assert f"librelane_plugins/librelane_plugin_vibeic/{name}" in fingerprint["plugin"], name
    assert "dynamic_ir_vectored_emit.py" in fingerprint["plugin"]
    assert fingerprint["openroad_init"] == ["set_debug_level PSM resistance 2"]
    calls = len(log.read_text().splitlines())
    run()
    assert len(log.read_text().splitlines()) == calls, "unchanged inputs must be reused"


def test_a_chain_without_init_lines_keeps_its_fingerprint(tmp_path, monkeypatch):
    docker, log = _fake_docker(tmp_path, monkeypatch)
    project, state, config = _chain_inputs(tmp_path)
    config.write_text(json.dumps({"meta": {"step": "OpenROAD.CheckAntennas"}}))
    folder = ll.run_chain(project, "img", [("OpenROAD.CheckAntennas", config, state)],
                          docker=str(docker), lane="l", pdk_root='/pdk')[0]
    fingerprint = json.loads((folder / "input_fingerprint.json").read_text())
    assert "plugin" not in fingerprint and "openroad_init" not in fingerprint
    argv = json.loads(log.read_text().splitlines()[-1])
    assert not any(str(a).startswith("PYTHONPATH=") for a in argv)


@pytest.mark.parametrize("step", ["KLayout.Antenna", "KLayout.SealRing"])
def test_a_stream_step_needs_only_the_stream(tmp_path, step):
    gds = tmp_path / "x.gds"
    gds.write_bytes(b"\0")
    ll._check_state({"gds": str(gds)}, step_id=step)
    with pytest.raises(ll.Refusal, match="LL_STATE_MISSING"):
        ll._check_state({}, step_id=step)


# --- step 24: the transient (dynamic) tier ------------------------------------------

_FIX = _PROGRAMS / "tests/fixtures/librelane_irdrop"


def test_the_transient_record_takes_the_worst_net_and_says_it_is_a_bound():
    transient_findings = la.transient_findings
    doc = transient_findings((_FIX / "transient_quasi_static.rpt").read_text(),
                             ["VDD", "VSS"], 5.0, 24.0, "sdc_create_clock")
    assert doc["verdict"] == "MEASURED"
    assert doc["power_net"] == "VSS" and doc["max_dynamic_drop_mv"] == pytest.approx(16.5)
    assert doc["per_net"]["VDD"]["dynamic_drop_v"] == pytest.approx(0.0146)
    assert doc["scaled_static_bound"] is True


def test_a_solve_with_on_die_capacitance_is_labelled_by_the_emitters_rule():
    # The same reader and label rule as dynamic_ir_vectored_emit. T101 pinned
    # the rule as it then was — a printed on-die capacitance made it "genuine"
    # — on this real sample, where the fork read -decap_cap 1e-9 in pF (1e-21 F)
    # and the ratio stayed 2.00, and named it as the defect. F20 changed the
    # rule (the label is earned by a measured reduction against a quasi-static
    # reference) and this sample is now what that rule refuses: read without a
    # declared decap it is the scaled static bound, and read against the 1e-9 F
    # it was asked for it is not a solve of that decap at all.
    transient_findings = la.transient_findings
    doc = transient_findings((_FIX / "transient_decap_1e-9.rpt").read_text(),
                             ["VDD", "VSS"], 5.0, 24.0, "sdc_create_clock")
    assert doc["scaled_static_bound"] is True
    assert doc["capacitance_model"].startswith("on-die-cap")
    asked = transient_findings((_FIX / "transient_decap_1e-9.rpt").read_text(),
                               ["VDD", "VSS"], 5.0, 24.0, "sdc_create_clock",
                               decap_f=1e-9)
    assert asked["verdict"] == "NOT_MEASURED" and "1e-21" in asked["reason"]


def test_a_net_the_solve_did_not_answer_is_not_measured():
    transient_findings = la.transient_findings
    doc = transient_findings((_FIX / "transient_quasi_static.rpt").read_text(),
                             ["VDD", "VSS", "VDDIO"], 5.0, 24.0, "sdc_create_clock")
    assert doc["verdict"] == "NOT_MEASURED" and "VDDIO" in doc["reason"]


def test_a_chain_step_is_found_by_its_name_not_its_slot(tmp_path):
    lane = tmp_path / "phase3/librelane/24"
    (lane / "02-vibeic-irdropchecker").mkdir(parents=True)   # left by an older chain
    (lane / "02-vibeic-transientir").mkdir()
    folder = la.chain_folder(tmp_path, "24", la.IR_STEPS, "Vibeic.TransientIR")
    assert folder.name == "02-vibeic-transientir"


def test_standalone_ir_openroad_and_capability_probe_use_shared_supervisor(
        tmp_path, monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return type("CP", (), {"returncode": 0, "stdout": "True\n",
                                "stderr": ""})()

    monkeypatch.setattr(la, "run_container", run)
    log = tmp_path / "ir" / "openroad.log"
    log.parent.mkdir(parents=True)
    assert la._run_openroad(tmp_path, "img", tmp_path / "x.tcl", log, []) == 0
    assert la.sealring_spans_capable("img")
    assert calls[0][1] == {"supervised": True, "log": log}
    assert calls[1][1] == {"probe_deadline_s": ll.PROBE_DEADLINE_S}


@pytest.mark.parametrize("case", ["active", "non_nominal", "external", "default", "missing", "ambiguous"])
def test_ir_bridge_uses_one_explicit_active_tech_lef(tmp_path, monkeypatch, case):
    project = tmp_path / "project"
    project.mkdir()
    views = [project / name for name in ("route.def", "net.v", "clock.sdc", "route.spef")]
    for view in views:
        view.write_text("offline view\n")
    nominal, active = project / "nominal.tlef", project / "active.tlef"
    if case == "external":
        active = tmp_path / "active.tlef"
    nominal.write_text(TECH_LEF)
    active.write_text(TECH_LEF + "# legal routed via geometry\n")
    if case == "missing":
        active.unlink()
    paths, observed = {}, []

    def configs(_project, _image, _pdk, steps, **kwargs):
        # LibreLane's resolver requires VERILOG_FILES even for a checkpoint
        # solve. This run deliberately has no original RTL source directory.
        verilog = (kwargs.get("overlay") or {}).get("VERILOG_FILES")
        if not verilog or verilog[0] != [str(views[1])]:
            raise ll.Refusal("LL_CONFIG_RESOLUTION_FAILED", "routed netlist was not supplied")
        for step in steps:
            techs = {"nom*": str(nominal), "max*": "untouched-corner.tlef"}
            if case == "ambiguous":
                techs["*"] = str(nominal)
            path = project / (step + ".json")
            path.write_text(json.dumps({"DEFAULT_CORNER": "max_slow" if case == "non_nominal" else "nom_typ", "TECH_LEFS": techs}))
            paths[step] = path
        return paths

    def bridge(_project, _image, config, *_args, **_kwargs):
        observed.append(json.loads(config.read_text()))
        if case == "external":
            assert (active.parent, str(active.parent)) in _kwargs["mounts"]
        raise ll.Refusal("OFFLINE_BRIDGE_OBSERVED", "no native solve in this fixture")

    monkeypatch.setattr(la, "resolve_step_configs", configs)
    monkeypatch.setattr(la, "state_from_direct", bridge)
    expected = {"missing": "LL_IR_TECH_LEF_MISSING",
                "ambiguous": "LL_IR_TECH_LEF_CORNER_UNRESOLVED"}.get(case, "OFFLINE_BRIDGE_OBSERVED")
    kwargs = {} if case == "default" else {"tech_lef": active}
    refusal = None
    try:
        la.run_ir(project, "offline", tmp_path, "neutral-kit", routed_def=views[0],
                  netlist=views[1], sdc=views[2], spef=views[3], budget_pct=10.0,
                  budget_source="fixture", **kwargs)
    except ll.Refusal as exc:
        refusal = exc.code
    assert refusal == expected
    if case in ("missing", "ambiguous"):
        assert not observed
    else:
        selected = nominal if case == "default" else active
        pattern = "max*" if case == "non_nominal" else "nom*"
        assert observed[0]["TECH_LEFS"][pattern] == str(selected)
        for step in la.OPENROAD_IR_STEPS:
            config = json.loads(paths[step].read_text())
            if case == "default":
                assert config["TECH_LEFS"] == {"nom*": str(nominal), "max*": "untouched-corner.tlef"}
            else:
                assert config["TECH_LEFS"] == {pattern: str(active)}
                provenance = json.loads(paths[step].with_suffix(".overrides.json").read_text())
                assert provenance["TECH_LEFS"]["sha256"] == la.digest(active)
                assert provenance["TECH_LEFS"]["previous"] == {"nom*": str(nominal), "max*": "untouched-corner.tlef"}
