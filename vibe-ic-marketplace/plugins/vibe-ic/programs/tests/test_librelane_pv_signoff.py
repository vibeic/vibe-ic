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
from _finished_gds_fixture import publish_finished_gds

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
        if cmd[1:3] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0,
                stdout='["/dockerstartup/scripts/ui_startup.sh"]', stderr="")
        if "--id" in cmd:
            folder = Path(cmd[cmd.index("-o") + 1])
            step = cmd[cmd.index("--id") + 1]
            incoming = json.loads(Path(cmd[cmd.index("-i") + 1]).read_text())
            _put(folder / "config.json", json.loads(Path(cmd[cmd.index("-c") + 1]).read_text()))
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
    # The actual Tcl reads the routed DEF into the database used for the powered netlist.
    assert f"read_def {{{(pnr / 'chip.def').resolve()}}}" in (bridge / "def_to_odb.tcl").read_text()
    assert f"read_db {{{state['odb']}}}" in (bridge / "to_pnl.tcl").read_text()
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
    assert record["scope"]["gds"] == str((pnr / "chip.gds").resolve())


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
                        lambda cmd, **k: SimpleNamespace(returncode=0,
                            stdout="null" if cmd[1:3] == ["image", "inspect"] else "", stderr=""))
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


# ── the runner's step-31 switch ─────────────────────────────────────────────


_DECK_LYRDB = ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<report-database>\n"
               " <generator>drc: script='/pdk/procA/libs.tech/klayout/tech/drc/procA.drc'"
               "</generator>\n <top-cell>chip</top-cell>\n <categories>\n </categories>\n"
               " <cells>\n  <cell>\n   <name>chip</name>\n  </cell>\n </cells>\n"
               " <items>\n </items>\n</report-database>\n")


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


@pytest.mark.parametrize("step", ["Vibeic.FinishingXOR", "Vibeic.DatabaseUnit"])
def test_the_stream_checks_need_the_stream_and_nothing_else(tmp_path, step):
    gds = tmp_path / "chip.gds"
    gds.write_bytes(b"stream")
    contract._check_state({"gds": str(gds), "metrics": {}}, step_id=step)
    with pytest.raises(contract.Refusal, match="LL_STATE_MISSING"):
        contract._check_state({"metrics": {}}, step_id=step)


# ── 37.3: the receipt of a LibreLane-promoted stream ────────────────────────


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
