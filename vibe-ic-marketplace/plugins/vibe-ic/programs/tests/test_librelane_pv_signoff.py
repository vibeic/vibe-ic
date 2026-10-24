"""Steps 31 / 37.3 / 37.4 / 37.5ic on LibreLane (lane mig105).

Every LibreLane step here is faked only at the tool boundary (``docker run``):
the fake writes the files LibreLane writes into a step folder
(``state_in.json``, ``state_out.json``, reports) and nothing else.  Image:
none (host tests); the real-tool proof is in the lane report.
"""
import importlib
import importlib.util
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module("librelane_contract")
pv = importlib.import_module("librelane_pv_signoff")
PLUGIN = PROGRAMS / "librelane_plugins" / "librelane_plugin_vibeic"


def _put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def _folder(root, name, step, before, after):
    """A LibreLane step folder as the tool leaves it."""
    folder = root / name
    _put(folder / "config.json", {"meta": {"step": step}})
    _put(folder / "state_in.json", {"metrics": before})
    _put(folder / "state_out.json", {"metrics": after})
    return folder


# ── judge_pv: THE ONE RULE ──────────────────────────────────────────────────
def test_clean_drc_chain_passes(tmp_path):
    folders = [
        _folder(tmp_path, "01-magic-drc", "Magic.DRC", {}, {"magic__drc_error__count": 0}),
        _folder(tmp_path, "02-klayout-drc", "KLayout.DRC", {"magic__drc_error__count": 0},
                {"magic__drc_error__count": 0, "klayout__drc_error__count": 0}),
    ]
    record = pv.judge_pv(folders, ("Magic.DRC", "KLayout.DRC"), tmp_path / "r.json")
    assert record["verdict"] == "PASS"
    assert record["metrics"]["klayout__drc_error__count"]["value"] == 0
    assert json.loads((tmp_path / "r.json").read_text())["verdict"] == "PASS"


def test_a_producer_that_wrote_nothing_is_not_measured_never_zero(tmp_path):
    folders = [
        _folder(tmp_path, "01-magic-drc", "Magic.DRC", {}, {"magic__drc_error__count": 0}),
        # KLayout.DRC skipped its runset (it only warns upstream): no metric.
        _folder(tmp_path, "02-klayout-drc", "KLayout.DRC", {"magic__drc_error__count": 0},
                {"magic__drc_error__count": 0}),
    ]
    record = pv.judge_pv(folders, ("Magic.DRC", "KLayout.DRC"), tmp_path / "r.json")
    assert record["verdict"] == "NOT_MEASURED"
    row = record["metrics"]["klayout__drc_error__count"]
    assert row["status"] == "NOT_MEASURED"
    assert "did not write" in row["reason"]


def test_a_carried_metric_is_not_this_steps_measurement(tmp_path):
    # KLayout.DRC's key already sat in the state it received (an earlier
    # chain's number): the step wrote nothing new, so it measured nothing.
    carried = {"klayout__drc_error__count": 0}
    folders = [_folder(tmp_path, "01-klayout-drc", "KLayout.DRC", carried, dict(carried))]
    record = pv.judge_pv(folders, ("KLayout.DRC",), tmp_path / "r.json")
    assert record["verdict"] == "NOT_MEASURED"
    assert "carried in" in record["metrics"]["klayout__drc_error__count"]["reason"]


def test_a_step_that_did_not_run_is_not_measured(tmp_path):
    record = pv.judge_pv([], ("Netgen.LVS",), tmp_path / "r.json")
    assert record["verdict"] == "NOT_MEASURED"
    assert all(row["status"] == "NOT_MEASURED" for row in record["metrics"].values())
    assert set(record["metrics"]) == set(pv.PRODUCED["Netgen.LVS"])


def test_a_folder_without_state_in_credits_nothing(tmp_path):
    folder = _folder(tmp_path, "01-magic-drc", "Magic.DRC", {}, {"magic__drc_error__count": 0})
    (folder / "state_in.json").unlink()
    record = pv.judge_pv([folder], ("Magic.DRC",), tmp_path / "r.json")
    assert record["verdict"] == "NOT_MEASURED"
    assert "state_in.json" in record["metrics"]["magic__drc_error__count"]["reason"]


@pytest.mark.parametrize("value,status", [(3, "FAIL"), (True, "INVALID"), (-1, "INVALID"),
                                          ("0", "INVALID")])
def test_a_nonzero_or_non_count_fails(tmp_path, value, status):
    folders = [_folder(tmp_path, "01-magic-drc", "Magic.DRC", {},
                       {"magic__drc_error__count": value})]
    record = pv.judge_pv(folders, ("Magic.DRC",), tmp_path / "r.json")
    assert record["verdict"] == "FAIL"
    assert record["metrics"]["magic__drc_error__count"]["status"] == status


def test_fail_outranks_not_measured(tmp_path):
    folders = [_folder(tmp_path, "01-magic-drc", "Magic.DRC", {},
                       {"magic__drc_error__count": 2})]
    record = pv.judge_pv(folders, ("Magic.DRC", "KLayout.DRC"), tmp_path / "r.json")
    assert record["verdict"] == "FAIL"


def test_one_clean_engine_beside_a_dirty_one_is_a_named_disagreement(tmp_path):
    folders = [
        _folder(tmp_path, "01-magic-drc", "Magic.DRC", {}, {"magic__drc_error__count": 15}),
        _folder(tmp_path, "02-klayout-drc", "KLayout.DRC", {"magic__drc_error__count": 15},
                {"magic__drc_error__count": 15, "klayout__drc_error__count": 0}),
    ]
    record = pv.judge_pv(folders, ("Magic.DRC", "KLayout.DRC"), tmp_path / "r.json")
    assert record["verdict"] == "FAIL"
    assert any(r.startswith("LL_DRC_ENGINES_DISAGREE") for r in record["reasons"])


# ── run_half through the real contract, the tool faked at docker run ─────────
def _fake_tool(monkeypatch, writes):
    """Fake ``docker run``: resolution, bridge conversion and step runs."""
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if "--id" in cmd:
            folder = Path(cmd[cmd.index("-o") + 1])
            step = cmd[cmd.index("--id") + 1]
            incoming = json.loads(Path(cmd[cmd.index("-i") + 1]).read_text())
            _put(folder / "state_in.json", incoming)
            out = dict(incoming, metrics=dict(incoming.get("metrics") or {}))
            out["metrics"].update(writes.get(step, {}))
            if step == "Magic.SpiceExtraction":  # the view the step writes
                (folder / "chip.spice").write_text("* extracted")
                out["spice"] = str(folder / "chip.spice")
            _put(folder / "state_out.json", out)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "openroad" in cmd:
            tcl = Path(cmd[-1]).read_text()
            for line in tcl.splitlines():
                for verb in ("write_db", "write_verilog -include_pwr_gnd"):
                    if line.startswith(verb + " "):
                        Path(line[len(verb) + 1:].strip("{}")).write_text("derived")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(contract, "image_capability", lambda *a, **k: {})
    monkeypatch.setattr(contract, "openroad_home", lambda *a, **k: None)
    monkeypatch.setattr(contract.subprocess, "run", run)
    return calls


def _half_project(tmp_path, chain):
    project = tmp_path / "project"
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    for name in ("chip.gds", "chip.def", "chip_pnr.v", "constraint.sdc"):
        (pnr / name).write_text(name)
    (pnr / "chip.def").write_text("DESIGN chip ;\nCOMPONENTS 0 ;\n")
    cfg = project / "cfg"
    views = {"Magic.DRC": (["gds"], []), "KLayout.DRC": (["gds"], []),
             "KLayout.Density": (["gds"], []),
             "Magic.SpiceExtraction": (["gds", "def"], ["spice"]),
             "Netgen.LVS": (["spice", "pnl"], [])}
    configs = {}
    for step in chain:
        configs[step] = _put(cfg / f"{step}.json", {"meta": {"step": step}, "DESIGN_NAME": "chip",
                                                    "TECH_LEFS": {"nom_*": "/pdk/t.lef"}})
        _put(contract.views_path(configs[step]), {"step": step, "inputs": views[step][0],
                                                   "outputs": views[step][1]})
    pdk_root = tmp_path / "pdk"
    (pdk_root / "procA").mkdir(parents=True)
    return project, pnr, configs, pdk_root


def test_drc_half_runs_the_tool_chain_on_the_shipped_gds(tmp_path, monkeypatch):
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.DRC_CHAIN)
    monkeypatch.setattr(pv, "resolve_step_configs", lambda *a, **k: configs)
    calls = _fake_tool(monkeypatch, {"Magic.DRC": {"magic__drc_error__count": 0},
                                     "KLayout.DRC": {"klayout__drc_error__count": 0},
                                     "KLayout.Density": {"klayout__density_error__count": 0}})
    record = pv.run_half(project, "img", pdk_root, "procA", "drc", gds=pnr / "chip.gds",
                         routed_def=pnr / "chip.def", netlist=pnr / "chip_pnr.v",
                         sdc=pnr / "constraint.sdc")
    assert record["verdict"] == "PASS"
    ran = [c[c.index("--id") + 1] for c in calls if "--id" in c]
    assert ran == list(pv.DRC_CHAIN)
    assert record["scope"]["gds_sha256"] == contract.digest(pnr / "chip.gds")
    assert (project / "phase3/librelane/31-drc/01-magic-drc/state_out.json").is_file()
    state = json.loads((project / "phase3/librelane/31-drc-config/bridge/state_in.json").read_text())
    assert state["gds"] == str((pnr / "chip.gds").resolve())


def test_lvs_half_bridges_a_powered_netlist_from_the_routed_database(tmp_path, monkeypatch):
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.LVS_CHAIN)
    monkeypatch.setattr(pv, "resolve_step_configs", lambda *a, **k: configs)
    _fake_tool(monkeypatch, {"Magic.SpiceExtraction": {"magic__illegal_overlap__count": 0},
                             "Netgen.LVS": {k: 0 for k in pv.PRODUCED["Netgen.LVS"]}})
    record = pv.run_half(project, "img", pdk_root, "procA", "lvs", gds=pnr / "chip.gds",
                         routed_def=pnr / "chip.def", netlist=pnr / "chip_pnr.v",
                         sdc=pnr / "constraint.sdc")
    assert record["verdict"] == "PASS"
    bridge = project / "phase3/librelane/31-lvs-config/bridge"
    state = json.loads((bridge / "state_in.json").read_text())
    assert state["pnl"] == str((bridge / "bridge.pnl.v").resolve())
    receipt = json.loads((bridge / "bridge_receipt.json").read_text())
    # the netlist is written from the database the routed DEF was read into
    assert receipt["derived"]["pnl"]["from"] == state["odb"]
    assert receipt["derived"]["odb"]["from"] == str((pnr / "chip.def").resolve())
    assert "write_verilog -include_pwr_gnd" in (bridge / "to_pnl.tcl").read_text()


def test_lvs_half_extracts_gds_with_the_supplied_physical_reference(tmp_path, monkeypatch):
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.LVS_CHAIN)
    supplied = pnr / "current-powered.v"; supplied.write_text("powered current layout")
    seen = {}
    def resolve(*args, **kwargs):
        seen.update(kwargs)
        return configs
    monkeypatch.setattr(pv, "resolve_step_configs", resolve)
    calls = _fake_tool(monkeypatch, {
        "Magic.SpiceExtraction": {"magic__illegal_overlap__count": 0},
        "Netgen.LVS": {k: 0 for k in pv.PRODUCED["Netgen.LVS"]}})
    record = pv.run_half(project, "img", pdk_root, "procA", "lvs",
                         gds=pnr / "chip.gds", routed_def=pnr / "chip.def",
                         netlist=pnr / "chip_pnr.v", sdc=pnr / "constraint.sdc",
                         powered_netlist=supplied, physical_top="physical_chip")
    assert seen["overlay"]["MAGIC_EXT_USE_GDS"][0] is True
    assert seen["overlay"]["MAGIC_EXT_ABSTRACT"][0] is False
    assert seen["overlay"]["DESIGN_NAME"][0] == "physical_chip"
    state = json.loads((project / "phase3/librelane/31-lvs-config/bridge/state_in.json").read_text())
    assert state["pnl"] == str(supplied.resolve())
    assert not any("openroad" in call for call in calls)
    assert record["scope"]["extracted_gds_sha256"] == contract.digest(pnr / "chip.gds")


def test_lvs_half_missing_supplied_reference_refuses_before_native(tmp_path, monkeypatch):
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.LVS_CHAIN)
    monkeypatch.setattr(pv, "resolve_step_configs", lambda *a, **k: configs)
    calls = _fake_tool(monkeypatch, {})
    with pytest.raises(contract.Refusal, match="LL_PV_VIEW_MISSING: pnl"):
        pv.run_half(project, "img", pdk_root, "procA", "lvs", gds=pnr / "chip.gds",
                    routed_def=pnr / "chip.def", netlist=pnr / "chip_pnr.v",
                    sdc=pnr / "constraint.sdc", powered_netlist=pnr / "missing.v")
    assert not any("--id" in call for call in calls)


def test_a_bridge_that_writes_no_powered_netlist_refuses(tmp_path, monkeypatch):
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.LVS_CHAIN)
    monkeypatch.setattr(pv, "resolve_step_configs", lambda *a, **k: configs)
    _fake_tool(monkeypatch, {})
    monkeypatch.setattr(contract.subprocess, "run",
                        lambda cmd, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    with pytest.raises(contract.Refusal, match="LL_BRIDGE_CONVERSION_FAILED"):
        pv.run_half(project, "img", pdk_root, "procA", "lvs", gds=pnr / "chip.gds",
                    routed_def=pnr / "chip.def", netlist=pnr / "chip_pnr.v",
                    sdc=pnr / "constraint.sdc")


def test_a_missing_shipped_view_refuses_by_name(tmp_path, monkeypatch):
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.DRC_CHAIN)
    monkeypatch.setattr(pv, "resolve_step_configs", lambda *a, **k: configs)
    (pnr / "chip.gds").unlink()
    with pytest.raises(contract.Refusal, match="LL_PV_VIEW_MISSING: gds"):
        pv.run_half(project, "img", pdk_root, "procA", "drc", gds=pnr / "chip.gds",
                    routed_def=pnr / "chip.def", netlist=pnr / "chip_pnr.v",
                    sdc=pnr / "constraint.sdc")


# ── 37.4: rows from judged State, bound by sha ──────────────────────────────
def _judged(tmp_path, project, half="drc", value=0):
    folder = _folder(project / "phase3/librelane/31-drc", "02-klayout-drc", "KLayout.DRC",
                     {}, {"klayout__drc_error__count": value})
    return folder, pv.judge_pv([folder], ("KLayout.DRC",),
                               project / pv.RECORD_REL.format(half=half))


def test_state_metrics_bind_each_value_to_the_state_that_measured_it(tmp_path):
    project = tmp_path / "p"
    folder, _ = _judged(tmp_path, project, value=5)
    rows = pv.state_metrics(project, [project / pv.RECORD_REL.format(half="drc")])
    row = rows["klayout__drc_error__count"]
    assert row["value"] == 5
    assert row["source"] == "phase3/librelane/31-drc/02-klayout-drc/state_out.json"
    assert row["sha256"] == contract.digest(folder / "state_out.json")


def test_a_state_changed_after_judgement_is_not_measured(tmp_path):
    project = tmp_path / "p"
    folder, _ = _judged(tmp_path, project, value=0)
    _put(folder / "state_out.json", {"metrics": {"klayout__drc_error__count": 0, "x": 1}})
    row = pv.state_metrics(project, [project / pv.RECORD_REL.format(half="drc")])[
        "klayout__drc_error__count"]
    assert row["value"] == "NOT_MEASURED"
    assert row["reason"].startswith("LL_STATE_CHANGED")


def _switch(project, mode):
    _put(project / "phase3/librelane_switch.json", {"steps": {"31": mode}})


def test_aggregator_reads_the_tool_state_only_when_step_31_is_on_librelane(tmp_path, monkeypatch):
    agg = importlib.import_module("signoff_metrics_aggregate")
    project = tmp_path / "p"
    from _native_signoff_fixture import producer
    producer(project, monkeypatch, counts={'klayout__drc_error__count': 7},
             inherited={'magic__drc_error__count': 0})
    switch_path = project / 'phase3/librelane_switch.json'
    switch = json.loads(switch_path.read_text())
    switch['steps']['31'] = 'direct'
    _put(switch_path, switch)
    # direct (no switch): the direct rule answers, and this tree has no
    # direct DRC report, so the key is NOT_MEASURED by the direct rule.
    metrics, _ = agg.aggregate(project)
    assert metrics["klayout__drc_error__count"] == "NOT_MEASURED"
    assert "31-drc" not in json.dumps(metrics["__provenance__"]["klayout__drc_error__count"])
    switch['steps']['31'] = 'librelane'
    _put(switch_path, switch)
    metrics, _ = agg.aggregate(project)
    assert metrics["klayout__drc_error__count"] == 7
    prov = metrics["__provenance__"]["klayout__drc_error__count"]
    assert prov["source"] == "phase3/librelane/31-drc/02-klayout-drc/state_out.json"
    # a key of the same chain the tool never wrote stays NOT_MEASURED
    assert metrics["magic__drc_error__count"] == "NOT_MEASURED"
    switch['steps']['31'] = 'dual'
    _put(switch_path, switch)
    metrics, _ = agg.aggregate(project)
    assert metrics["klayout__drc_error__count"] == "NOT_MEASURED"


def test_aggregator_check_refuses_a_record_the_state_no_longer_states(tmp_path, monkeypatch):
    agg = importlib.import_module("signoff_metrics_aggregate")
    project = tmp_path / "p"
    from _native_signoff_fixture import producer
    info = producer(project, monkeypatch)
    folder = info['folders'][1]
    assert agg.main([str(project)]) == 0
    assert agg.main([str(project), "--check"]) == 0
    _put(folder / "state_out.json", {"metrics": {"klayout__drc_error__count": 0, "later": 1}})
    assert agg.main([str(project), "--check"]) == 1


# ── the runner's step-31 switch ─────────────────────────────────────────────
def _row(name, status, detail=""):
    runner = importlib.import_module("phase3_one_shot_runner")
    kwargs = {"reason_class": "not_executed"} if status == "NOT_MEASURED" else {}
    return runner.StepResult(name, status, 0.0, detail, **kwargs)


@pytest.fixture
def runner(monkeypatch):
    module = importlib.import_module("phase3_one_shot_runner")
    monkeypatch.setattr(module, "_vacuous_on_unrouted", lambda *a, **k: None)
    return module


def test_direct_mode_never_touches_the_tool(tmp_path, runner, monkeypatch):
    seen = []
    direct_calls = []
    monkeypatch.setattr(runner, "_step31_librelane",
                        lambda *a, **k: seen.append(a) or _row("drc", "PASS"))
    def direct():
        direct_calls.append('drc')
        return _row('drc', 'NOT_MEASURED', 'SOURCE_FIXTURE_ONLY: no native DRC invocation')
    # Direct mode now owns its producer/current-subject binding. It still
    # never invokes the LibreLane arm; absent native proof remains unmeasured.
    row = runner._step31_dispatch(tmp_path, "chip", None, "drc",
                                  direct)
    assert row.status == 'NOT_MEASURED' and seen == []
    assert direct_calls == ['drc']
    assert json.loads((tmp_path / 'reports/phase3/direct_current_drc.json').read_text())['verdict'] == 'NOT_MEASURED'
    _switch(tmp_path, "direct")
    row = runner._step31_dispatch(tmp_path, "chip", None, "drc", direct)
    assert row.status == 'NOT_MEASURED' and seen == []
    assert direct_calls == ['drc', 'drc']


def test_librelane_mode_is_the_tools_verdict(tmp_path, runner, monkeypatch):
    _switch(tmp_path, "librelane")
    monkeypatch.setattr(runner, "_step31_librelane",
                        lambda p, t, k, half, publish: _row(half, "FAIL", f"tool publish={publish}"))
    row = runner._step31_dispatch(tmp_path, "chip", None, "lvs",
                                  lambda: pytest.fail("direct half ran in librelane mode"))
    assert (row.status, row.detail) == ("FAIL", "tool publish=True")


@pytest.mark.parametrize("direct,tool,expected,disagree", [
    ("PASS", "PASS", "PASS", False),
    ("PASS", "FAIL", "FAIL", True),
    ("FAIL", "PASS", "FAIL", True),
    ("PASS", "NOT_MEASURED", "NOT_MEASURED", False),
])
def test_dual_mode_needs_both_halves_clean(tmp_path, runner, monkeypatch,
                                           direct, tool, expected, disagree):
    _switch(tmp_path, "dual")
    published = []
    monkeypatch.setattr(runner, "_step31_librelane",
                        lambda p, t, k, half, publish: published.append(publish)
                        or _row(half, tool, "tool"))
    row = runner._step31_dispatch(tmp_path, "chip", None, "drc", lambda: _row("drc", direct))
    assert row.status == expected
    assert ("LL_PV_ARMS_DISAGREE" in row.detail) is disagree
    assert published == [False]
    assert (row.extras["dual_direct"], row.extras["dual_librelane"]) == (direct, tool)


def _published_half(tmp_path, runner, monkeypatch, half, record, files, *, extraction=True):
    project = tmp_path / "p"
    for path, text in files.items():
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text(text)
    if half == "lvs" and extraction:
        folder = project / "phase3/librelane/31-lvs/01-magic-spiceextraction"
        folder.mkdir(parents=True)
        spice = folder / "layout.spice"
        spice.write_text(".subckt chip a y\nRsignal a y 1\n.ends\n")
        (folder / "feedback.txt").write_text("")
        (folder / "invocation.log").write_text("SOURCE_CONTROL extraction: 0 problems occurred.\n")
        _put(folder / "state_out.json", {"spice": str(spice)})
        record["metrics"]["magic__illegal_overlap__count"] = {
            "step": "Magic.SpiceExtraction", "status": "MEASURED", "value": 0,
            "folder": str(folder)}
    monkeypatch.setattr(contract, "resolve_image", lambda p: "img")
    monkeypatch.setattr(contract, "resolve_pdk_root", lambda *a, **k: tmp_path)
    monkeypatch.setattr(pv, "run_half", lambda *a, **k: _put(
        project / pv.RECORD_REL.format(half=half), record) and record)
    pdk = SimpleNamespace(name="procA")
    if half == "lvs":
        current = importlib.import_module("_physical_current")
        selected = {}
        for key, name in (("gds", "current.gds"), ("def", "current.def"),
                          ("netlist", "current.v")):
            selected[key] = project / name; selected[key].write_text(name)
        monkeypatch.setattr(current, "default_signoff_inputs", lambda p: selected)
        monkeypatch.setattr(runner, "_streamout_top", lambda *a: ("chip", None))
        monkeypatch.setattr(runner, "_stage_padring_io_lefs_for_lvs", lambda *a: [])
        monkeypatch.setattr(runner._lvs_pa, "emit_to_file",
                            lambda source, pdk, output, **kwargs: output.write_text("powered"))
        pdk.cell_lef = "cells.lef"
    return project, runner._step31_librelane(project, "chip", pdk, half, publish=True)


@pytest.mark.parametrize("current_available,provider_release", [(True, False),
                                                               (False, False),
                                                               (True, True)])
def test_librelane_lvs_caller_uses_current_final_and_well_tied_reference(
        tmp_path, runner, monkeypatch, current_available, provider_release):
    current = importlib.import_module("_physical_current")
    pnr = tmp_path / "phase3/stage3/pnr"; pnr.mkdir(parents=True)
    (pnr / "core.gds").write_text("old unadopted stream")
    selected = {}
    for key, name in (("gds", "current-final.gds"), ("def", "filled.def"),
                      ("netlist", "physical.v")):
        selected[key] = tmp_path / name; selected[key].write_text(name)
    monkeypatch.setattr(current, "default_signoff_inputs",
                        lambda p: selected if current_available else None)
    provider_gds = None
    if provider_release:
        import die_finishing_gen
        record = tmp_path / "reports/phase3/provider_die_assembly.json"
        record.parent.mkdir(parents=True); record.write_text("producer release")
        provider_gds = tmp_path / "provider-final.gds"; provider_gds.write_text("provider final")
        def admitted(project, path):
            assert path == record
            return {"gds": provider_gds, "source_project": tmp_path}
        monkeypatch.setattr(die_finishing_gen, "read_admitted_release", admitted)
    monkeypatch.setattr(contract, "resolve_image", lambda p: "img")
    monkeypatch.setattr(contract, "resolve_pdk_root", lambda *a, **k: tmp_path)
    monkeypatch.setattr(runner, "_streamout_top", lambda *a: ("physical_chip", None))
    monkeypatch.setattr(runner, "_stage_padring_io_lefs_for_lvs", lambda *a: [])
    emitted, consumed = {}, {}
    def emit(source, pdk, output, **kwargs):
        emitted.update(source=source, output=output, **kwargs)
        output.write_text("explicit power-aware physical reference")
    def run(*args, **kwargs):
        consumed.update(kwargs)
        return {"verdict": "PASS", "reasons": [], "metrics": {}}
    monkeypatch.setattr(runner._lvs_pa, "emit_to_file", emit)
    monkeypatch.setattr(pv, "run_half", run)
    pdk = SimpleNamespace(name="procA", cell_lef="cells.lef")
    result = runner._step31_librelane(tmp_path, "core", pdk, "lvs", publish=False)
    if not current_available:
        assert result.status == "NOT_MEASURED"
        assert consumed == {} and emitted == {}
    else:
        assert result.status == "PASS"
        assert consumed["gds"] == (provider_gds or selected["gds"])
        assert consumed["routed_def"] == selected["def"]
        assert consumed["netlist"] == emitted["source"] == selected["netlist"]
        assert consumed["physical_top"] == emitted["top"] == "physical_chip"
        assert consumed["powered_netlist"] == emitted["output"]
        assert emitted["rails_as_ports"] is True
        assert emitted["tie_wells_to_rails"] is True


_DECK_LYRDB = ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<report-database>\n"
               " <generator>drc: script='/pdk/procA/libs.tech/klayout/tech/drc/procA.drc'"
               "</generator>\n <top-cell>chip</top-cell>\n <categories>\n </categories>\n"
               " <cells>\n  <cell>\n   <name>chip</name>\n  </cell>\n </cells>\n"
               " <items>\n </items>\n</report-database>\n")


def test_librelane_drc_publishes_the_deck_report_where_the_gates_read(tmp_path, runner,
                                                                    monkeypatch):
    folder = "phase3/librelane/31-drc/02-klayout-drc"
    record = {"verdict": "PASS", "reasons": [], "metrics": {
        "klayout__drc_error__count": {"step": "KLayout.DRC", "status": "MEASURED", "value": 0,
                                      "folder": str(tmp_path / "p" / folder)}}}
    project, row = _published_half(tmp_path, runner, monkeypatch, "drc", record,
                                   {f"{folder}/reports/drc.klayout.lyrdb": _DECK_LYRDB,
                                    f"{folder}/invocation.log": 'SOURCE_FIXTURE_ONLY KLayout publication transport\n'})
    assert row.status == "PASS"
    assert (project / "reports/phase3/drc_signoff.rpt").read_text() == _DECK_LYRDB
    assert (project / "phase3/reports/drc.rpt").read_text() == _DECK_LYRDB


def test_a_report_that_is_not_a_deck_report_is_not_published(tmp_path, runner, monkeypatch):
    folder = "phase3/librelane/31-drc/02-klayout-drc"
    record = {"verdict": "PASS", "reasons": [], "metrics": {
        "klayout__drc_error__count": {"step": "KLayout.DRC", "status": "MEASURED", "value": 0,
                                      "folder": str(tmp_path / "p" / folder)}}}
    project, row = _published_half(tmp_path, runner, monkeypatch, "drc", record,
                                   {f"{folder}/reports/drc.klayout.lyrdb": "not a report"})
    assert not (project / "reports/phase3/drc_signoff.rpt").exists()
    assert "published" not in row.extras


def test_librelane_lvs_publishes_netgens_report_and_a_verdict_the_aggregator_reads(
        tmp_path, runner, monkeypatch):
    agg = importlib.import_module("signoff_metrics_aggregate")
    folder = "phase3/librelane/31-lvs/02-netgen-lvs"
    record = {"verdict": "PASS", "reasons": [], "metrics": {
        key: {"step": "Netgen.LVS", "status": "MEASURED", "value": 0,
              "folder": str(tmp_path / "p" / folder)} for key in pv.PRODUCED["Netgen.LVS"]}}
    project, row = _published_half(
        tmp_path, runner, monkeypatch, "lvs", record,
        {f"{folder}/reports/lvs.netgen.rpt": "Final result: Circuits match uniquely.\n"})
    assert row.status == "PASS"
    assert "match uniquely" in (project / "reports/phase3/lvs.rpt").read_text()
    verdict = json.loads((project / "reports/phase3/lvs_verdict.json").read_text())
    assert verdict["finding"].startswith("LVS_MATCH")
    assert verdict["compare_performed"] is True
    cell = agg._lvs_from_runner_verdict(project, "design__lvs_error__count", "x")
    assert cell.value == 0



def test_lvs_publication_refuses_missing_extraction_evidence(tmp_path, runner, monkeypatch):
    folder = "phase3/librelane/31-lvs/02-netgen-lvs"
    record = {"verdict": "PASS", "reasons": [], "metrics": {
        "design__lvs_error__count": {"step": "Netgen.LVS", "status": "MEASURED", "value": 0,
                                    "folder": str(tmp_path / "p" / folder)}}}
    project, row = _published_half(tmp_path, runner, monkeypatch, "lvs", record,
        {f"{folder}/reports/lvs.netgen.rpt": "Final result: Circuits match uniquely.\n"},
        extraction=False)
    assert row.status == "FAIL" and "current Magic extraction feedback" in row.detail
    assert not (project / "reports/phase3/lvs_verdict.json").exists()


def test_a_librelane_lvs_mismatch_is_not_published_as_a_match(tmp_path, runner, monkeypatch):
    folder = "phase3/librelane/31-lvs/02-netgen-lvs"
    record = {"verdict": "FAIL", "reasons": ["design__lvs_error__count=176 (Netgen.LVS)"],
              "metrics": {"design__lvs_error__count": {
                  "step": "Netgen.LVS", "status": "FAIL", "value": 176,
                  "folder": str(tmp_path / "p" / folder)}}}
    project, row = _published_half(
        tmp_path, runner, monkeypatch, "lvs", record,
        {f"{folder}/reports/lvs.netgen.rpt": "Netlists do not match.\n"})
    assert row.status == "FAIL"
    verdict = json.loads((project / "reports/phase3/lvs_verdict.json").read_text())
    assert (verdict["status"], verdict["finding"]) == ("FAIL", "LVS_LIBRELANE_FAIL")


def test_step_drc_and_step_lvs_route_through_the_switch(tmp_path, runner, monkeypatch):
    _switch(tmp_path, "librelane")
    monkeypatch.setattr(runner, "_step31_librelane",
                        lambda p, t, k, half, publish: _row(half, "PASS", "tool"))
    assert runner.step_drc(tmp_path, "chip", None, "c").detail == "tool"
    assert runner.step_lvs(tmp_path, "chip", None, "c").detail == "tool"


def test_the_dual_arm_reenters_the_direct_body(tmp_path, runner, monkeypatch):
    _switch(tmp_path, "dual")
    monkeypatch.setattr(runner, "_step31_librelane",
                        lambda p, t, k, half, publish: _row(half, "PASS", "tool"))
    pdk = SimpleNamespace(name="procA", drc_deck=None, calibre_drc=None)
    direct = runner.step_drc(tmp_path, "chip", pdk, "c", _direct=True)
    row = runner.step_drc(tmp_path, "chip", pdk, "c")
    assert (row.extras["dual_direct"], row.extras["dual_librelane"]) == (direct.status, "PASS")
    assert row.status == direct.status  # a clean tool half never lifts the direct verdict
    assert direct.detail in row.detail


def test_an_incomplete_pnr_skips_lvs_on_every_mode(tmp_path, runner, monkeypatch):
    _switch(tmp_path, "librelane")
    monkeypatch.setattr(runner, "_step31_librelane",
                        lambda *a, **k: pytest.fail("the tool ran after a dead pnr"))
    row = runner.step_lvs(tmp_path, "chip", None, "c", upstream_pnr=_row("pnr", "FAIL"))
    assert row.status == "NOT_MEASURED"
    assert "upstream pnr step is FAIL" in row.detail


def test_the_direct_bodies_are_still_the_step_functions():
    import inspect
    runner = importlib.import_module("phase3_one_shot_runner")
    assert "offgrid_drc_classify_check" in inspect.getsource(runner.step_drc)
    assert "upstream pnr step is" in inspect.getsource(runner.step_lvs)


# ── the plugin steps' pure parts ────────────────────────────────────────────
def _load_plugin_module(name):
    spec = importlib.util.spec_from_file_location(f"_mig105_{name}", PLUGIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real8(value):
    """Encode a GDSII 8-byte real (excess-64, base 16)."""
    if value == 0:
        return b"\0" * 8
    exponent = 64
    while value >= 1:
        value /= 16.0
        exponent += 1
    while value < 1 / 16.0:
        value *= 16.0
        exponent -= 1
    return bytes([exponent]) + int(value * (1 << 56)).to_bytes(7, "big")


def _gds(path, user, meters, units_first=True):
    def rec(rtype, dtype, payload=b""):
        return struct.pack(">HBB", 4 + len(payload), rtype, dtype) + payload
    units = rec(0x03, 0x05, _real8(user) + _real8(meters))
    body = [rec(0x00, 0x02, b"\x02\x58"), rec(0x01, 0x02, b"\0" * 24),
            rec(0x02, 0x06, b"LIB\0")]
    body += [units, rec(0x05, 0x02, b"\0" * 24)] if units_first else [rec(0x05, 0x02, b"\0" * 24), units]
    path.write_bytes(b"".join(body))
    return path


@pytest.mark.parametrize("meters", [1e-9, 5e-10, 2.5e-10])
def test_database_unit_reader_agrees_with_the_host_gds_reader(tmp_path, meters):
    units = _load_plugin_module("gds_units")
    geometry = importlib.import_module("_gds_geometry")
    path = _gds(tmp_path / "a.gds", 1e-3, meters)
    measured = units.gds_database_unit_um(str(path))
    assert measured == pytest.approx(meters * 1e6, rel=1e-12)
    assert measured == pytest.approx(geometry.read_layout(path).dbu_um, rel=1e-12)


def test_a_units_record_after_the_first_structure_is_not_read(tmp_path):
    units = _load_plugin_module("gds_units")
    assert units.gds_database_unit_um(str(_gds(tmp_path / "b.gds", 1e-3, 1e-9,
                                                units_first=False))) is None


def test_every_finishing_key_the_judge_requires_is_one_the_script_prints():
    script = (PLUGIN / "finishing_xor.drc").read_text()
    for key in pv.PRODUCED["Vibeic.FinishingXOR"]:
        stem = key[len("vibeic__finishing_xor__"):-len("__count")]
        assert (f'"{stem}"' in script or f"__{stem}__count" in script), key
    assert "%OL_METRIC_I vibeic__finishing_xor__defect__count" in script


def test_the_plugin_registers_both_steps_and_fingerprints_the_drc_script():
    init = (PLUGIN / "__init__.py").read_text()
    assert "from .signoff import DatabaseUnit, FinishingXOR" in init
    digests = contract._plugin_digests("Vibeic.FinishingXOR")
    assert "librelane_plugins/librelane_plugin_vibeic/finishing_xor.drc" in digests
    assert contract._plugin_digests("KLayout.DRC") == {}


# ── the tech LEF the route read (via-legalization record) ──────────────────
def _legalized(project, *, status="APPLIED", recorded=None, content="VIA Via1 ;",
               sha=None):
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    tlef = pnr / "active_via_legalized.tlef"
    tlef.write_text(content)
    _put(project / pv.VIA_LEGALIZATION_REL, {
        "status": status,
        "derived_tech_lef": recorded or "/elsewhere/run/phase3/stage3/pnr/active_via_legalized.tlef",
        "derived_sha256": sha or contract.digest(tlef)})
    return tlef


def test_no_record_or_no_remediation_means_the_pdk_tech_lef(tmp_path):
    assert pv.route_tech_lef(tmp_path) is None
    assert pv.tech_lef_overlay(tmp_path) is None
    _legalized(tmp_path, status="NOT_APPLIED")
    assert pv.route_tech_lef(tmp_path) is None


def test_an_applied_remediation_is_the_tech_lef_every_geometry_step_reads(tmp_path):
    tlef = _legalized(tmp_path)
    path, source = pv.route_tech_lef(tmp_path)
    assert path == tlef.resolve()
    assert contract.digest(tlef) in source
    overlay = pv.tech_lef_overlay(tmp_path)
    assert overlay["TECH_LEFS"][0] == {"*": str(tlef.resolve())}


def test_an_applied_remediation_whose_bytes_changed_refuses(tmp_path):
    _legalized(tmp_path, sha="0" * 64)
    with pytest.raises(contract.Refusal, match="LL_ROUTE_TECH_LEF_UNBOUND"):
        pv.route_tech_lef(tmp_path)


def test_an_applied_record_without_its_hash_refuses(tmp_path):
    tlef = _legalized(tmp_path)
    doc = json.loads((tmp_path / pv.VIA_LEGALIZATION_REL).read_text())
    del doc["derived_sha256"]
    _put(tmp_path / pv.VIA_LEGALIZATION_REL, doc)
    with pytest.raises(contract.Refusal, match="LL_ROUTE_TECH_LEF_UNBOUND"):
        pv.route_tech_lef(tmp_path)
    assert tlef.is_file()


def test_step_31_resolves_its_configs_with_the_routes_tech_lef(tmp_path, monkeypatch):
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.DRC_CHAIN)
    tlef = _legalized(project)
    seen = {}

    def resolve(*args, **kwargs):
        seen.update(kwargs)
        return configs
    monkeypatch.setattr(pv, "resolve_step_configs", resolve)
    _fake_tool(monkeypatch, {"Magic.DRC": {"magic__drc_error__count": 0},
                             "KLayout.DRC": {"klayout__drc_error__count": 0},
                             "KLayout.Density": {"klayout__density_error__count": 0}})
    pv.run_half(project, "img", pdk_root, "procA", "drc", gds=pnr / "chip.gds",
                routed_def=pnr / "chip.def", netlist=pnr / "chip_pnr.v",
                sdc=pnr / "constraint.sdc")
    assert seen["overlay"]["TECH_LEFS"][0] == {"*": str(tlef.resolve())}


# ── step 37: the finishing XOR decides a stream's feasibility ───────────────
def _step37_world(tmp_path, monkeypatch, finishing):
    step37 = importlib.import_module("librelane_step37")
    fill = importlib.import_module("librelane_fill_dfm")
    project = tmp_path / "p"
    tlef = _legalized(project)
    pnr = project / "phase3/stage3/pnr"
    for name in ("routed.def", "chip_pnr.v", "constraint.sdc"):
        (pnr / name).write_text(name)
    seen = {}
    configs = {step: _put(tmp_path / "cfg" / f"{step}.json",
                          {"meta": {"step": step}, "DIE_AREA": [0, 0, 10, 10]})
               for step in step37.STEPS}

    def resolve(*args, **kwargs):
        seen["overlay"] = kwargs.get("overlay")
        return configs
    monkeypatch.setattr(step37, "resolve_step_configs", resolve)
    monkeypatch.setattr(step37, "declaration_config",
                        lambda p: ({"CORE_AREA": [1, 1, 9, 9]}, {"CORE_AREA": "decl"}))
    monkeypatch.setattr(step37, "_routed_state", lambda *a, **k: tmp_path / "bridge.json")
    streams = {}

    def run(project_, image, pdk_root, pdk, steps, state, lane, configs_):
        out = []
        for index, step in enumerate(steps, 1):
            folder = project_ / "phase3/librelane" / lane / f"{index:02d}"
            gds = folder / f"{lane}-{index}.gds"
            gds.parent.mkdir(parents=True, exist_ok=True)
            gds.write_text(lane)
            doc = {"gds": str(gds), "mag_gds": str(folder / "m.gds"),
                   "klayout_gds": str(folder / "k.gds"), "metrics": {}}
            for key in ("mag_gds", "klayout_gds"):
                Path(doc[key]).write_text(key)
            _put(folder / "state_out.json", doc)
            out.append(folder)
        return out
    monkeypatch.setattr(step37, "_run", run)

    def judge(folder, keys, output, limits=None, **k):
        return {"verdict": "PASS", "metrics": {key: {"status": "MEASURED", "value": 0}
                                               for key in keys}}
    monkeypatch.setattr(step37, "judge_step", judge)
    monkeypatch.setattr(step37, "_vibeic_gds_gates",
                        lambda *a, **k: {"substance": {"rc": 0, "sha256": "x"}})
    monkeypatch.setattr(step37, "_measured_drc",
                        lambda *a, **k: {"magic": 0, "klayout": 0, "total": 0, "report": "r"})
    def measured_ratios(project_, image, pdk_root, pdk, gds, config, lane):
        report = project_ / "phase3/librelane" / lane / "density_ratios.json"
        _put(report, {"status": "MEASURED", "layers": {
            "M2.4": {"status": "MEASURED", "ratio": 0.35}}})
        return {"report": str(report), "report_sha256": contract.digest(report),
                "subject": str(gds), "subject_sha256": contract.digest(gds),
                "layers": {"M2.4": {"status": "MEASURED", "ratio": 0.35}}}
    monkeypatch.setattr(fill, "measure_density_ratios", measured_ratios)
    calls = []

    def finishing_xor(project_, image, pdk_root, pdk, *, pre, sealed, final, core,
                      core_source, lane, record):
        arm = lane.split("-", 1)[1]
        calls.append((arm, pre, sealed, final, core))
        return {"verdict": finishing[arm]}
    monkeypatch.setattr(pv, "run_finishing_xor", finishing_xor)
    return step37, project, tlef, seen, calls


def test_a_stream_whose_finishing_touched_the_design_is_not_promoted(tmp_path, monkeypatch):
    step37, project, tlef, seen, calls = _step37_world(
        tmp_path, monkeypatch, {"magic": "FAIL", "klayout": "FAIL"})
    pnr = project / "phase3/stage3/pnr"
    with pytest.raises(contract.Refusal, match="LL_NO_FEASIBLE_STREAM"):
        step37.run(project, "img", tmp_path, "procA", pnr / "routed.def",
                   pnr / "chip_pnr.v", pnr / "constraint.sdc", pnr / "chip.gds")
    feasibility = json.loads((project / "phase3/librelane/37-feasibility.json").read_text())
    assert feasibility["finishing_xor"] == {"magic": "FAIL", "klayout": "FAIL"}
    assert not (pnr / "chip.gds").exists()
    assert seen["overlay"]["TECH_LEFS"][0] == {"*": str(tlef.resolve())}
    # each arm's XOR compares ITS stream, ITS seal-ring output and ITS final GDS
    for arm, pre, sealed, final, core in calls:
        assert Path(pre).name == ("m.gds" if arm == "magic" else "k.gds")
        assert f"37-{arm}-finish" in str(sealed) and f"37-{arm}-finish" in str(final)
        assert core == [1, 1, 9, 9]


def test_only_the_stream_whose_finishing_is_clean_can_be_promoted(tmp_path, monkeypatch):
    step37, project, _, _, _ = _step37_world(
        tmp_path, monkeypatch, {"magic": "FAIL", "klayout": "PASS"})
    pnr = project / "phase3/stage3/pnr"
    result = step37.run(project, "img", tmp_path, "procA", pnr / "routed.def",
                        pnr / "chip_pnr.v", pnr / "constraint.sdc", pnr / "chip.gds")
    assert result["engine"] == "klayout"
    promotion = json.loads((project / "phase3/librelane/37-promotion.json").read_text())
    assert promotion["finishing_xor"] == {"magic": "FAIL", "klayout": "PASS"}


def test_an_undeclared_core_refuses_before_any_stream(tmp_path, monkeypatch):
    step37, project, _, _, calls = _step37_world(
        tmp_path, monkeypatch, {"magic": "PASS", "klayout": "PASS"})
    monkeypatch.setattr(step37, "declaration_config", lambda p: ({}, {}))
    monkeypatch.setattr(step37, "_run", lambda *a, **k: pytest.fail("streamed without a core"))
    pnr = project / "phase3/stage3/pnr"
    with pytest.raises(contract.Refusal, match="LL_FINISHING_CORE_UNDECLARED"):
        step37.run(project, "img", tmp_path, "procA", pnr / "routed.def",
                   pnr / "chip_pnr.v", pnr / "constraint.sdc", pnr / "chip.gds")


@pytest.mark.parametrize("step", ["Vibeic.FinishingXOR", "Vibeic.DatabaseUnit"])
def test_the_stream_checks_need_the_stream_and_nothing_else(tmp_path, step):
    gds = tmp_path / "chip.gds"
    gds.write_bytes(b"stream")
    contract._check_state({"gds": str(gds), "metrics": {}}, step_id=step)
    with pytest.raises(contract.Refusal, match="LL_STATE_MISSING"):
        contract._check_state({"metrics": {}}, step_id=step)


# ── 37.3: the receipt of a LibreLane-promoted stream ────────────────────────
def _promoted(tmp_path, verdict="PASS", defect=0, pairs=None, bytes_=b"finished stream"):
    import _default_backend_fixtures as retained
    xor = importlib.import_module("gds_xor_check")
    project = tmp_path / "p"
    gds = project / "phase3/stage4/gds/chip.gds"
    gds.parent.mkdir(parents=True)
    gds.write_bytes(bytes_)
    routed = project / "phase3/stage3/pnr/routed.def"
    routed.parent.mkdir(parents=True)
    routed.write_text("DESIGN chip ;\n")
    folder = project / "phase3/librelane/37.3-klayout/01-vibeic-finishingxor"
    metrics = {"vibeic__finishing_xor__defect__count": defect,
               "vibeic__finishing_xor__design_pair__count": 38}
    metrics.update({f"vibeic__finishing_xor__defect__count__pair:{k}": v
                    for k, v in (pairs or {}).items()})
    # This source-only receipt fixture supplies the strict reader's actual
    # State/config/material population, not a bare promoted PASS document.
    before = {'gds': str(gds.resolve()), 'metrics': {}}
    folder, _ = retained.producer(
        project, 'Vibeic.FinishingXOR', before, dict(before, metrics=metrics),
        lane='37.3-klayout/01-vibeic-finishingxor',
        config_folder='37.3-klayout-config', name='chip')
    pre = routed.parent / 'chip.prefinish.gds'
    pre.write_bytes(b'SOURCE_FIXTURE_ONLY unsealed stream')
    config = project / 'phase3/librelane/37.3-klayout-config/Vibeic.FinishingXOR.json'
    cfg = json.loads(config.read_text())
    cfg['VIBEIC_FINISHING_PRE_GDS'] = str(pre)
    _put(config, cfg)
    _put(folder / 'config.json', cfg)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(config=contract.digest(config), config_files={str(pre): contract.digest(pre)})
    _put(folder / 'input_fingerprint.json', fp)
    _put(folder / 'vibeic_receipt.json', {
        'input': fp, 'sha256': {str(p.relative_to(folder)): contract.digest(p)
        for p in folder.rglob('*') if p.is_file() and p.name != 'vibeic_receipt.json'}})
    _put(project / 'reports/phase3/technology_units.json', {'pdk': 'neutral'})
    _put(project / "phase3/librelane/37.3-klayout-finishing-xor.json", {
        "verdict": verdict, "reasons": [] if verdict != "NOT_MEASURED" else ["no core"],
        "metrics": {"vibeic__finishing_xor__defect__count": {
            "status": {"PASS": "MEASURED", "FAIL": "FAIL"}.get(verdict, "NOT_MEASURED"),
            "value": defect, "folder": str(folder)}}})
    _put(project / xor.LIBRELANE_PROMOTION_REL,
         {"selection": "klayout", "canonical_sha256": contract.digest(gds)})
    # librelane_step37.run writes its Magic-vs-KLayout stream XOR before it can
    # promote anything (LL_XOR_NOT_ZERO refuses otherwise); U15 binds 37.3's
    # connectivity to it, so the promoted fixture carries it as the run does.
    _put(project / xor.LIBRELANE_STREAM_XOR_REL, {
        "verdict": "PASS", "metrics": {"design__xor_difference__count": {
            "status": "MEASURED", "value": 0}}})
    return xor, project, gds


def test_a_clean_librelane_finishing_is_the_37_3_receipt(tmp_path):
    xor, project, gds = _promoted(tmp_path)
    assert xor.main([str(project)]) == 0
    receipt = json.loads((project / xor.REPORT_REL).read_text())
    assert receipt["verdict"] == "PASS"
    assert receipt["reference"]["kind"] == "librelane_stream"
    assert receipt["design_layer_differences"] == []
    assert xor.judge_receipt(project, xor.REPORT_REL)[0] == 0


def test_a_finishing_defect_names_its_design_pairs_and_fails(tmp_path):
    xor, project, gds = _promoted(tmp_path, verdict="FAIL", defect=3,
                                  pairs={"36_0": 2, "42_0": 1})
    assert xor.main([str(project)]) == 1
    receipt = json.loads((project / xor.REPORT_REL).read_text())
    assert [(d["layer"], d["datatype"], d["differences"])
            for d in receipt["design_layer_differences"]] == [(36, 0, 2), (42, 0, 1)]
    assert xor.judge_receipt(project, xor.REPORT_REL)[0] == 1


def test_an_unmeasured_finishing_is_not_a_zero(tmp_path):
    xor, project, gds = _promoted(tmp_path, verdict="NOT_MEASURED", defect=None)
    assert xor.main([str(project)]) == 2
    assert xor.judge_receipt(project, xor.REPORT_REL)[0] == 2


def test_other_bytes_than_the_promoted_stream_take_the_direct_comparison(tmp_path):
    xor, project, gds = _promoted(tmp_path)
    gds.write_bytes(b"a later rewrite")
    assert xor.librelane_finishing_receipt(project, contract.digest(gds)) is None


def test_the_drc_script_prints_a_per_pair_defect_metric():
    script = (PLUGIN / "finishing_xor.drc").read_text()
    assert "vibeic__finishing_xor__defect__count__pair:" in script


def test_candidate_pv_preserves_canonical_half_namespace(tmp_path, monkeypatch):
    """Exercise the actual native adapter used by repair, without replacing it."""
    project, pnr, configs, pdk_root = _half_project(tmp_path, pv.DRC_CHAIN)
    monkeypatch.setattr(pv, "resolve_step_configs", lambda *a, **k: configs)
    _fake_tool(monkeypatch, {"Magic.DRC": {"magic__drc_error__count": 0},
                             "KLayout.DRC": {"klayout__drc_error__count": 0},
                             "KLayout.Density": {"klayout__density_error__count": 0}})
    views = dict(gds=pnr / "chip.gds", routed_def=pnr / "chip.def",
                 netlist=pnr / "chip_pnr.v", sdc=pnr / "constraint.sdc")
    canonical = pv.run_half(project, "img", pdk_root, "procA", "drc", **views)
    record_path = project / pv.RECORD_REL.format(half="drc")
    before = record_path.read_bytes()
    candidate_record = project / "reports/candidate/drc.json"
    observed = pv.run_half(project, "img", pdk_root, "procA", "drc", **views,
                           lane_prefix="candidate-finished-pv", record=candidate_record)
    assert canonical["verdict"] == observed["verdict"] == "PASS"
    assert record_path.read_bytes() == before
    assert json.loads(candidate_record.read_text())["scope"] == canonical["scope"]
    folder = project / "phase3/librelane/candidate-finished-pv-drc/01-magic-drc"
    assert (folder / "state_out.json").is_file()
    bridge = project / "phase3/librelane/candidate-finished-pv-drc-config/bridge/state_in.json"
    assert json.loads(bridge.read_text())["gds"] == str(views["gds"].resolve())
