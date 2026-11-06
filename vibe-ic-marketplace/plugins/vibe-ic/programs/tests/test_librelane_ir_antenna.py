"""Steps 24, 26 and 26.5ic on LibreLane tool steps (lane mig101).

Retained controls read native per-net metrics and transient reports through
the production plugin readers. Contract controls substitute the Docker edge
and preserve native commands, initialization and output State.
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
sys.path.insert(0, str(ll.PLUGIN_ROOT / 'librelane_plugin_vibeic'))
import ir_rules  # noqa: E402
from transient import transient_findings  # noqa: E402

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


# --- the contract: plugin steps and OpenROAD init lines ----------------------------

def test_the_init_file_carries_caller_lines(tmp_path):
    assert ll.openroad_home(tmp_path / "none", {"openroad_aliases": {}}) is None
    home = ll.openroad_home(tmp_path / "h", {"openroad_aliases": {}}, ["set_debug_level PSM resistance 2"])
    assert "set_debug_level PSM resistance 2" in (home / ".openroad").read_text()


_FAKE_DOCKER = r'''#!/usr/bin/env python3
"""Stand-in `docker`: writes what `librelane.steps run` writes, logs argv."""
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(argv) + "\n")
if argv[:2] == ["image", "inspect"]:
    print("[]")
    sys.exit(0)
if "librelane.steps" in argv:
    out = argv[argv.index("-o") + 1]
    os.makedirs(out, exist_ok=True)
    state = json.load(open(argv[argv.index("-i") + 1]))
    state["metrics"] = {"x": 1}
    json.dump(state, open(os.path.join(out, "state_out.json"), "w"))
    print("neutral native step completed")
'''


def _fake_docker(tmp_path, monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    docker = tmp_path / "bin" / "docker"
    docker.parent.mkdir()
    docker.write_text(_FAKE_DOCKER.replace("#!/usr/bin/env python3", "#!" + sys.executable))
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
    home = project / "phase3/librelane/l/.openroad_home"
    assert "set_debug_level PSM resistance 2" in (home / ".openroad").read_text()
    assert f"HOME={home.resolve()}" in argv
    assert (folder / "state_out.json").is_file()


def test_a_chain_without_init_lines_uses_native_environment(tmp_path, monkeypatch):
    docker, log = _fake_docker(tmp_path, monkeypatch)
    project, state, config = _chain_inputs(tmp_path)
    config.write_text(json.dumps({"meta": {"step": "OpenROAD.CheckAntennas"}}))
    folder = ll.run_chain(project, "img", [("OpenROAD.CheckAntennas", config, state)],
                          docker=str(docker), lane="l", pdk_root='/pdk')[0]
    assert not (project / "phase3/librelane/l/.openroad_home").exists()
    assert (folder / "state_out.json").is_file()
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
    doc = transient_findings((_FIX / "transient_decap_1e-9.rpt").read_text(),
                             ["VDD", "VSS"], 5.0, 24.0, "sdc_create_clock")
    assert doc["scaled_static_bound"] is True
    assert doc["capacitance_model"].startswith("on-die-cap")
    asked = transient_findings((_FIX / "transient_decap_1e-9.rpt").read_text(),
                               ["VDD", "VSS"], 5.0, 24.0, "sdc_create_clock",
                               decap_f=1e-9)
    assert asked["verdict"] == "NOT_MEASURED" and "1e-21" in asked["reason"]


def test_a_net_the_solve_did_not_answer_is_not_measured():
    doc = transient_findings((_FIX / "transient_quasi_static.rpt").read_text(),
                             ["VDD", "VSS", "VDDIO"], 5.0, 24.0, "sdc_create_clock")
    assert doc["verdict"] == "NOT_MEASURED" and "VDDIO" in doc["reason"]


@pytest.mark.parametrize('owner', ['IRDropChecker', 'TransientIR'])
def test_native_ir_plugins_consume_normalized_lib_without_legacy_override(tmp_path, monkeypatch, owner):
    """Exercise each original plugin run and native Liberty reader; no IR solve."""
    import importlib
    from decimal import Decimal
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(ll.PLUGIN_ROOT))
    plugin = importlib.import_module('librelane_plugin_vibeic.ir_drop')
    from librelane.common import Toolbox
    from librelane.steps.openroad import OpenROADStep
    library = tmp_path / 'neutral.lib'
    library.write_text('library(neutral) { default_operating_conditions : typical; '
                       'operating_conditions(typical) { voltage : 5.0; temperature : 25; } }\n')
    sdc = tmp_path / 'neutral.sdc'
    sdc.write_text('create_clock -period 24 [get_ports clk]\n')
    spef = tmp_path / 'neutral.spef'
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    mapping = {'nom_*': [str(library)]}
    cfg = {'LIB': mapping, 'DEFAULT_CORNER': 'nom_tt_025C_5v00',
           'VDD_NETS': ['VDD'], 'GND_NETS': ['VSS'], 'VIBEIC_IR_BUDGET_PCT': Decimal('10'),
           'PNR_SDC_FILE': str(sdc), 'VIBEIC_DECAP_CAP': None}
    toolbox = Toolbox(str(tmp_path / 'toolbox'))
    step = object.__new__(getattr(plugin, owner))
    step.config = cfg
    step.toolbox = toolbox
    step.step_dir = str(tmp_path)
    step.err = lambda *_args: None
    step.extract_env = lambda kwargs: (kwargs, {})
    state = plugin.State({plugin.DesignFormat.SPEF: {'nom_*': str(spef)},
                          plugin.DesignFormat.SDC: str(sdc)}, metrics=MEASURED_METRICS)
    process_calls = []

    def neutral_openroad(_step, _state, **kwargs):
        process_calls.append(kwargs['env'])
        (tmp_path / 'transient_ir.rpt').write_bytes((_FIX / 'transient_quasi_static.rpt').read_bytes())
        return {}, {}

    monkeypatch.setattr(OpenROADStep, 'run', neutral_openroad)
    _, measured = step.run(state)
    if owner == 'IRDropChecker':
        assert measured['vibeic__ir__analysed_net__count'] == 2
        assert measured['vibeic__ir__drop__worst__pct'] > 0
    else:
        assert measured['vibeic__ir_dynamic__drop__worst'] > 0
        assert process_calls[0]['LIB_VOLTAGE'] == '5.0'
        assert process_calls[0]['CURRENT_SPEF_DEFAULT_CORNER'] == str(spef)
    # LIB is authoritative even when the old spelling contains a usable view.
    for invalid in ({}, None):
        step.config = {**cfg, 'LIB': invalid, 'CELL_LIBS': mapping}
        calls = len(process_calls)
        with pytest.raises((plugin.StepError, TypeError, AttributeError)):
            step.run(state)
        assert len(process_calls) == calls
    step.config = {key: value for key, value in cfg.items() if key != 'LIB'}
    step.config['CELL_LIBS'] = mapping
    assert step.run(state)[1] == measured
    (tmp_path / 'IR_LIB_OBSERVATION.json').write_text(json.dumps({
        'owner': owner, 'modern_key': 'LIB', 'legacy_fallback': True,
        'empty_and_null_did_not_fallback': True, 'metrics': measured,
        'neutral_native_solve_only': True}, default=str, indent=2) + '\n')
