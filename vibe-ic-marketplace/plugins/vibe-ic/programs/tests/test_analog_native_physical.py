"""Native A11--A16 execution adapters, with real product parsers and helpers."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _plugin_tree
import analog_native_physical as physical


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if isinstance(data, dict) else data)
    return path


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "project"
    block = project / "phase3/analog/unit"
    put(block / "unit.sp", ".subckt unit a b vss\nX0 a b vss vss nfet w=1u l=1u\n.ends unit\n")
    put(block / "tb_unit.sp", ".include unit.sp\nX1 a b 0 unit\n.control\nop\necho \"MEAS vout=\" $&v(b)\n.endc\n.end\n")
    put(block / "spec.json", {"specs": [{"name": "vout", "min": 1.1, "max": 1.3}]})
    return project


def test_layout_executes_producer_and_requires_actual_outputs(project):
    calls = []
    def run(program, argv, **kwargs):
        calls.append((program, argv, kwargs))
        put(Path(argv[argv.index("--json") + 1]), {"blocks": {"unit": {"result": "OK"}}})
        return {"returncode": 0}
    # A clean return and an OK string alone are not a physical layout.
    result = physical.run_step("A11", project, {"name": "unit"}, {"pdk": "process"}, run)
    assert result["status"] == "FAIL"
    bdir, _ = physical._paths(project, "unit")
    put(bdir / "layout.mag", "magic\ntech process\n<< end >>\n")
    put(bdir / "unit.gds", "native gds fixture")
    result = physical.run_step("A11", project, {"name": "unit"}, {"pdk": "process"}, run)
    assert result["status"] == "PASS"
    assert calls[-1][0] == "analog_a5_layout_emit.py"
    assert calls[-1][1][calls[-1][1].index("--family") + 1] == "process"


def test_layout_environment_gap_is_not_clean(project):
    def run(program, argv, **kwargs):
        put(Path(argv[argv.index("--json") + 1]), {"result": "ENV_UNAVAILABLE", "reason": "missing magic"})
        return {"returncode": 69}
    result = physical.run_step("A11", project, {"name": "unit"}, {}, run)
    assert result["status"] == "NOT_MEASURED"
    assert "magic" in result["detail"]


@pytest.mark.parametrize("violations,lvs,expected", [(7, "match", "FAIL"),
    (0, "mismatch", "FAIL"), (0, "match", "NOT_MEASURED")])
def test_native_pv_runs_producer_preserves_counts_and_missing_erc(project, monkeypatch,
                                                                violations, lvs, expected):
    import analog_a6_native_pv as pv
    import analog_pdk_availability as availability
    bdir, _ = physical._paths(project, "unit")
    put(bdir / "unit.gds", "native fixture")
    monkeypatch.setattr(availability, "resolve_pdk", lambda *a, **k: {"available": True, "drc_deck": "native.drc"})
    calls = []
    def producer(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ran": True, "drc": {"executed": True, "violations": violations,
                "verdict": "FAIL" if violations else "PASS"},
                "lvs": {"executed": True, "verdict": lvs}}
    monkeypatch.setattr(pv, "run_block_pv", producer)
    result = physical._pv(project, "unit", "container", "image", "process", {"drc_engine": "native"})
    assert len(calls) == 1
    assert result["status"] == expected
    assert result["metrics"]["drc"]["violations"] == violations
    if expected == "NOT_MEASURED":
        assert result["metrics"]["erc"]["status"] == "NOT_MEASURED"


def _extraction_project(project, monkeypatch, parasitic=True):
    import _analog_producer_common as pc
    import librelane_contract as lc
    bdir, _ = physical._paths(project, "unit")
    tech = project / "pdk/process/libs.tech/magic/native.tech"
    put(tech, "extract\n style ngspice variants (), (lvs)\nend\n")
    put(bdir / "unit.gds", "native fixture")
    put(bdir / "layout_provenance.json", {"pdk_sources": {"magic_tech": str(tech)},
        "producer": "analog_a5_layout_emit", "result": "OK", "netlist_content_sha256": "bound"})
    monkeypatch.setattr(pc, "layout_netlist_identity", lambda *a: ("MATCH", "same bytes"))
    calls = []
    def resolve(project, image, source, output, **kwargs):
        put(output, json.loads(source.read_text()))
        return output
    def chain(project, image, steps, **kwargs):
        calls.append((steps, kwargs))
        folder = project / "pex_native"
        text = ".subckt unit a b vss\nX0 a b vss vss nfet w=1u l=1u\n"
        if parasitic:
            text += "R0 a b 12.5\nC0 b vss 1.2f\n"
        extracted = put(folder / "unit.rcx.spice", text + ".ends unit\n")
        put(folder / "state_out.json", {"spice_rcx": str(extracted)})
        return [folder]
    monkeypatch.setattr(lc, "resolve_step_config", resolve)
    monkeypatch.setattr(lc, "run_chain", chain)
    return calls


def _pre_state(project, value=1.2):
    bdir, work = physical._paths(project, "unit")
    log = put(project / "reports/A07-unit.log", f"MEAS vout= {value}\n")
    return {"status": "NOT_MEASURED", "metrics": {"vout": value},
            "input_views": {str(path): physical._sha(path) for path in
                            (bdir / "unit.sp", bdir / "tb_unit.sp")},
            "executions": [{"returncode": 0, "log": str(log), "log_sha256": physical._sha(log),
                            "argv": ["ngspice", "-b", str(bdir / "tb_unit.sp")]}]}


def test_a14_reuses_explicit_actual_canonical_inputs_without_legacy_argv(project):
    state = _pre_state(project)
    bdir, _ = physical._paths(project, "unit")
    state["native_inputs"] = {role: {"path": str(path), "sha256": physical._sha(path)}
        for role, path in (("netlist", bdir / "unit.sp"), ("testbench", bdir / "tb_unit.sp"),
                           ("spec", bdir / "spec.json"))}
    state["executions"][0].pop("argv")
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == {"vout": 1.2}
    assert record["source"] == "A07"


@pytest.mark.parametrize("kind", ["alternate_actual_tb", "changed_actual_input", "legacy_no_argv", "legacy_alternate_tb"])
def test_a14_refuses_actual_or_unproved_noncanonical_pre_testbench(project, kind):
    state = _pre_state(project)
    bdir, _ = physical._paths(project, "unit")
    alternate = put(bdir / "nominal.sp", (bdir / "tb_unit.sp").read_text())
    if kind in ("alternate_actual_tb", "changed_actual_input"):
        state["native_inputs"] = {role: {"path": str(path), "sha256": physical._sha(path)}
            for role, path in (("netlist", bdir / "unit.sp"), ("testbench", bdir / "tb_unit.sp"),
                               ("spec", bdir / "spec.json"))}
        if kind == "alternate_actual_tb":
            state["native_inputs"]["testbench"] = {"path": str(alternate), "sha256": physical._sha(alternate)}
        else:
            state["native_inputs"]["netlist"]["sha256"] = "previous native circuit bytes"
    elif kind == "legacy_no_argv":
        state["executions"][0].pop("argv")
    else:
        state["executions"][0]["argv"][-1] = str(alternate)
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == {}
    assert "no completed source-bound" in record["detail"]
    assert "canonical" in record["detail"] or "changed" in record["detail"]


def test_a14_transfers_consumed_native_input_identity_to_resimulation(project, monkeypatch):
    state = _pre_state(project)
    state["native_inputs"] = {"testbench": {"path": "actual-native-deck.sp", "sha256": "measured"}}
    captured = []
    def native(*args):
        captured.append(args[-1])
        return {"status": "NOT_MEASURED", "outputs": []}
    monkeypatch.setattr(physical, "_native_call", native)
    physical.run_step("A14", project, {"name": "unit"},
        {"previous_results": {"A07": {"unit": state}}}, None)
    assert captured[0]["_pre_result"]["native_inputs"] == state["native_inputs"]


@pytest.mark.parametrize("parasitic,expected", [(True, "PASS"), (False, "FAIL")])
def test_a13_runs_native_extraction_without_resim_and_refuses_parasitic_free(project,
        monkeypatch, parasitic, expected):
    import analog_real_corner_sweep as ars
    calls = _extraction_project(project, monkeypatch, parasitic)
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: pytest.fail("A13 must not resimulate"))
    result = physical._extract(project, "unit", "container", "image", "process", {})
    assert result["status"] == expected
    assert calls[0][0][0][0] == "Magic.RCX"
    if parasitic:
        assert result["metrics"]["corners"][0]["depth"] == "RC"


@pytest.mark.parametrize("post,expected", [(1.19, "PASS"), (0.8, "FAIL"), (None, "NOT_MEASURED")])
def test_a14_consumes_extracted_deck_and_native_measurements(project, monkeypatch, post, expected):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    result = physical._extract(project, "unit", "container", "image", "process", {})
    _, work = physical._paths(project, "unit")
    put(work / "A13.json", result)
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    calls = []
    def spice(container, deck, **kwargs):
        calls.append(Path(deck))
        values = {"vout": 1.2} if "_pre" in str(deck) else ({"vout": post} if post is not None else {})
        return True, values, "native ngspice output", {}
    monkeypatch.setattr(ars, "_run_ngspice", spice)
    result = physical._resim(project, "unit", "container", "image", "process", {
        "_pre_result": _pre_state(project)})
    assert result["status"] == expected
    assert len(calls) == 1
    assert all("_post_" in str(path) for path in calls)
    assert "unit_post_" in calls[-1].read_text()
    assert "unit__rcx" in (work / "unit_post_ngspice.sp").read_text()


def test_a14_changed_extracted_bytes_never_simulates(project, monkeypatch):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    result = physical._extract(project, "unit", "container", "image", "process", {})
    _, work = physical._paths(project, "unit")
    put(work / "A13.json", result)
    put(Path(result["outputs"][0]), "changed extraction")
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: pytest.fail("changed PEX must not simulate"))
    result = physical._resim(project, "unit", "container", "image", "process", {
        "_pre_result": _pre_state(project)})
    assert result["status"] == "NOT_MEASURED"
    assert "extracted SPICE changed" in result["detail"]


@pytest.mark.parametrize("pre_kind", ["absent", "changed_source", "interrupted"])
def test_a14_without_completed_current_pre_values_launches_no_native_work(
        project, monkeypatch, pre_kind):
    import analog_real_corner_sweep as ars
    _extraction_project(project, monkeypatch)
    result = physical._extract(project, "unit", "container", "image", "process", {})
    _, work = physical._paths(project, "unit")
    put(work / "A13.json", result)
    cfg = {}
    if pre_kind != "absent":
        cfg["_pre_result"] = _pre_state(project)
        if pre_kind == "changed_source":
            cfg["_pre_result"]["input_views"][str(project / "phase3/analog/unit/unit.sp")] = "old-source"
        else:
            cfg["_pre_result"]["executions"][0]["returncode"] = 143
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: pytest.fail("missing PRE must not launch a native job"))
    result = physical._resim(project, "unit", "container", "image", "process", cfg)
    assert result["status"] == "NOT_MEASURED"
    assert "no completed source-bound" in result["detail"]


def test_a14_reuses_pre_once_and_preserves_all_five_post_extraction_styles(project, monkeypatch):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    result = physical._extract(project, "unit", "container", "image", "process", {})
    one = result["metrics"]["corners"][0]
    styles = ["ngspice()", "ngspice(hrhc)", "ngspice(lrlc)", "ngspice(hrlc)", "ngspice(lrhc)"]
    result["metrics"]["corners"] = [{**one, "style": style} for style in styles]
    _, work = physical._paths(project, "unit")
    put(work / "A13.json", result)
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    resolver, resolves, calls = physical._pre_layout_measurements, [], []
    def pre(*args):
        resolves.append(True)
        return resolver(*args)
    def spice(container, deck, **kwargs):
        calls.append(Path(deck))
        assert "_post_" in str(deck)
        return True, {"vout": 1.19}, "post native result", {}
    monkeypatch.setattr(physical, "_pre_layout_measurements", pre)
    monkeypatch.setattr(ars, "_run_ngspice", spice)
    result = physical._resim(project, "unit", "container", "image", "process", {
        "_pre_result": _pre_state(project)})
    assert result["status"] == "PASS"
    assert len(resolves) == 1 and len(calls) == 5
    assert {row["style"] for row in result["metrics"]["corners"]} == set(styles)
    assert result["metrics"]["pre"]["reused"] is True
    assert not (work / "tb_unit_pre.sp").exists()


def test_a14_accepts_source_bound_existing_nominal_corner_measurement(project):
    bdir, _ = physical._paths(project, "unit")
    log = put(bdir / "sizing_loop/nominal.ngspice.log", "MEAS vout= 1.197\n")
    put(bdir / "corner_results.json", {"_provenance": "real_ngspice", "deck_source": "a3_netlist",
        "netlist_sha256": physical._sha(bdir / "unit.sp"),
        "netlist_testbench_sha256": physical._sha(bdir / "tb_unit.sp"),
        "all_runs": [{"knob": "__noop__", "ok": True, "partial_measurement": False,
                      "ngspice_log": str(log.relative_to(project))}]})
    values, record = physical._pre_layout_measurements(project, "unit", {})
    assert values == {"vout": 1.197}
    assert record["source"] == "corner_results nominal run"


@pytest.mark.parametrize("rc", [130, 137, 143, -9, -15])
def test_native_interruption_without_terminal_result_is_unmeasured(project, rc):
    result = physical.run_step("A14", project, {"name": "unit"}, {},
                              lambda *a, **k: {"returncode": rc, "log": "retained-interruption.log"})
    assert result["status"] == "NOT_MEASURED"
    assert result["executions"][0]["returncode"] == rc


@pytest.mark.parametrize("scored,expected", [(5, "PASS"), (4, "NOT_MEASURED")])
def test_a15_mc_reads_post_layout_not_schematic_and_counts_full_population(project,
                                                                         monkeypatch, scored, expected):
    import analog_mc_yield_run as mc
    _, work = physical._paths(project, "unit")
    post = put(work / "post.sp", ".include unit_post.sp\n.control\nop\n.endc\n")
    post_net = put(work / "unit_post.sp", ".subckt unit a b vss\nR0 a b 12.5\n.ends unit\n")
    put(work / "A14.json", {"status": "PASS", "metrics": {"corners": [
        {"style": "ngspice()", "post_testbench": str(post),
         "post_netlist": str(post_net), "post_netlist_sha256": physical._sha(post_net),
         "post_testbench_sha256": physical._sha(post)}]}})
    calls = []
    def mc_run(study, name, container, pdk, n):
        selected, rank = mc._find_deck(study, name)
        calls.append(selected)
        assert "unit_post.sp" in selected.read_text()
        assert "statistics" in str(study)
        return {"verdict": "PASS", "mc_runs": n, "spec_yield": {
            "vout": {"runs_scored": scored, "yield_pct": 100.0}}}
    monkeypatch.setattr(mc, "run_block", mc_run)
    result = physical._statistics(project, "unit", "container", "image", "process", {"samples": 5})
    assert result["status"] == expected
    assert len(calls) == 1
    assert not (project / "phase3/analog/unit/corner_results.json").exists()


def test_a16_absent_native_mission_and_reports_never_become_pass(project):
    result = physical._reliability(project, "unit", "container", "image", "process", {})
    assert result["status"] == "NOT_MEASURED"
    assert set(result["metrics"]) == {"mission", "thermal", "em", "aging"}
    assert all(r["status"] == "NOT_MEASURED" for r in result["metrics"].values())


@pytest.mark.parametrize("stress,expected", [(0.8, "NOT_MEASURED"), (1.2, "FAIL")])
def test_a16_executes_native_mission_and_retains_violation_over_other_missing_evidence(
        project, monkeypatch, stress, expected):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    deck = put(project / "input/mission.sp", ".control\nop\n.endc\n.end\n")
    put(project / "input/mission_spec.json", {"specs": [{"name": "max_stress", "max": 1.0}]})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    calls = []
    def simulate(container, actual_deck, **kwargs):
        calls.append(actual_deck)
        return True, {"max_stress": stress}, "native measured stress", {}
    monkeypatch.setattr(ars, "_run_ngspice", simulate)
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "deck": "input/mission.sp", "spec": "input/mission_spec.json"})
    assert result["status"] == expected
    assert calls == [str(deck)]
    assert result["metrics"]["mission"]["measurements"]["max_stress"] == stress
    assert "thermal" in result["metrics"]


def test_a12_internal_entry_preserves_terminal_failure_and_execution(project):
    calls = []
    def run(program, argv, **kwargs):
        calls.append((program, argv))
        put(Path(argv[argv.index("--json") + 1]), {
            "status": "FAIL", "detail": "native LVS mismatch", "outputs": [],
            "metrics": {"lvs": {"verdict": "mismatch"}}})
        return {"returncode": 1, "log": "native.log"}
    result = physical.run_step("A12", project, {"name": "unit"}, {"image": "digest"}, run)
    assert result["status"] == "FAIL"
    assert result["executions"][0]["log"] == "native.log"
    assert calls[0][0] == "analog_native_physical.py"
    assert calls[0][1][0] == "pv"


def test_native_pv_default_runs_librelane_drc_and_independent_native_lvs(project, monkeypatch):
    import analog_a6_native_pv as pv
    import analog_a6_librelane_drc as ll
    import analog_pdk_availability as availability
    bdir, _ = physical._paths(project, "unit")
    put(bdir / "unit.gds", "native fixture")
    monkeypatch.setattr(availability, "resolve_pdk", lambda *a, **k: {
        "available": True, "drc_deck": "drc.rule", "lvs_deck": "lvs.rule"})
    calls = []
    def drc(project, name, image, **kwargs):
        calls.append("native-drc")
        put(bdir / "a6_librelane_drc.json", {"result": "BLOCKING", "authority": {
            "blocking": ["rule_x"]}, "engines": {"KLayout.DRC": {"violations": {"rule_x": 3}}}})
        return 1
    def lvs(project, name, resolved, **kwargs):
        calls.append("native-lvs")
        assert "drc_deck" not in resolved
        return {"ran": True, "lvs": {"executed": True, "verdict": "match"}}
    monkeypatch.setattr(ll, "run", drc)
    monkeypatch.setattr(pv, "run_block_pv", lvs)
    result = physical._pv(project, "unit", "container", "image", "process", {})
    assert result["status"] == "FAIL"
    assert calls == ["native-drc", "native-lvs"]
    assert result["metrics"]["drc"]["native"]["engines"]["KLayout.DRC"]["violations"]["rule_x"] == 3


def test_a13_prior_success_cannot_replace_a_new_missing_terminal_result(project):
    _, work = physical._paths(project, "unit")
    put(work / "A13.json", {"status": "PASS", "detail": "old extraction", "outputs": []})
    result = physical.run_step("A13", project, {"name": "unit"}, {},
                              lambda *a, **k: {"returncode": 2})
    assert result["status"] == "NOT_MEASURED"
    assert "without a terminal result" in result["detail"]
    assert json.loads((work / "A13.json").read_text())["status"] == "NOT_MEASURED"


def test_physical_route_names_are_bound_to_shipped_flow_rows():
    # Exercise a real shipped contract, not a duplicated hand-written registry.
    from _hostpaths import require_repo
    contract = require_repo("vibe-ic-marketplace/plugins/vibe-ic/flow/flow109.json")
    rows = json.loads(contract.read_text())["rows"]
    named = {row["id"]: row["name"] for row in rows}
    assert named["A13"] == "Analog parasitic extraction"
    assert named["A14"] == "Analog post-layout performance"
    assert named["A15"] == "Analog post-layout statistics"
