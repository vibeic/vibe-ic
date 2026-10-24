"""Native A11--A16 execution adapters, with real product parsers and helpers."""
import hashlib
import json
import sys
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
    assert calls[-1][2]["host"] is True


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


def _op_study_state(project):
    import analog_bound_measurements as measurements
    bdir, _ = physical._paths(project, "unit")
    template = put(project / "continuations/op-study/template.sp",
        f'.include "{bdir / "unit.sp"}"\nv1 a 0 1.8\nX1 a b 0 unit\n'
        'i_load b 0 0.0005\n.end\n')
    source = put(project / "input/source.md", "Nominal output load is 0.5 mA.\n")
    bindings = {"analysis": {"kind": "OP"}, "source": {
        "path": str(source), "sha256": physical._sha(source)}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(b)", "unit": "V"},
        "iq": {"analysis": "OP", "expression": "-i(v1)*1e6", "unit": "uA"}}}
    binding_path = put(template.parent / "bindings.json", bindings)
    destination = template.parent / "native-pre"
    def run(program, argv, **kwargs):
        log = put(destination / "native.log", "MEAS vout=1.19532\nMEAS iq=30.1455\n")
        return {"returncode": 0, "log": str(log), "log_sha256": physical._sha(log),
                "argv": ["ngspice", *argv]}
    record = measurements.run_measurements(project, bdir / "unit.sp", template,
                                           bindings, destination, run)
    record["native_inputs"]["bindings"] = {"path": str(binding_path), "sha256": physical._sha(binding_path)}
    result = put(destination / "result.json", record)
    state = _pre_state(project)
    state["metrics"]["native_measurement_studies"] = [{"status": "PASS", "result": str(result),
        "bindings_path": str(binding_path), "measurements": record["measurements"]}]
    return state, record


def test_a14_reuses_explicit_op_study_as_distinct_pre_without_rerunning_it(project):
    state, original = _op_study_state(project)
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == {"vout": 1.19532, "iq": 30.1455}
    assert record["source"] == "A07 native measurement study"
    assert record["bindings"] == original["bindings"]
    assert record["native_inputs"]["testbench"] == original["native_inputs"]["testbench"]


@pytest.mark.parametrize("damage", ["testbench", "bindings", "log", "source", "values"])
def test_a14_stale_op_study_never_falls_back_to_old_canonical_conditions(project, damage):
    state, original = _op_study_state(project)
    if damage in ("testbench", "bindings"):
        path = Path(original["native_inputs"][damage]["path"])
    elif damage == "source":
        path = Path(original["bindings"]["source"]["path"])
    elif damage == "log":
        path = Path(original["executions"][0]["log"])
    else:
        path = Path(state["metrics"]["native_measurement_studies"][0]["result"])
        original["measurements"]["vout"] = 0.1
        put(path, original)
        path = None
    if path:
        path.write_text(path.read_text() + "\nchanged input bytes\n")
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == {}
    assert "OP measurement study" in record["detail"]


def test_a14_op_study_without_consumed_include_hashes_never_reuses_old_values(project):
    state, original = _op_study_state(project)
    original["native_inputs"] = {role: view for role, view in original["native_inputs"].items()
                                  if not role.startswith("include:")}
    put(Path(state["metrics"]["native_measurement_studies"][0]["result"]), original)
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == {}
    assert "consumed model/include" in record["detail"]


def test_a14_op_study_native_failure_wins_over_partial_measurement_status(project):
    state, original = _op_study_state(project)
    log = Path(original["executions"][0]["log"])
    log.write_text(log.read_text() + ";;RESIDUAL_FAIL invalid native solution\n")
    original["executions"][0]["log_sha256"] = physical._sha(log)
    put(Path(state["metrics"]["native_measurement_studies"][0]["result"]), original)
    state["metrics"]["native_measurement_studies"][0]["status"] = "FAIL"
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == {}
    assert record.get("status") == "FAIL"


def test_a14_op_study_conditions_flow_into_all_post_styles_and_a15(project, monkeypatch):
    import analog_native_flow as flow
    import analog_real_corner_sweep as ars
    import analog_mc_yield_run as mc
    import _designs_root as dr
    state, original = _op_study_state(project)
    bdir, work = physical._paths(project, "unit")
    put(bdir / "spec.json", {"specs": [{"name": "vout", "min": 1.1, "max": 1.3},
        {"name": "iq", "max": 50}, {"name": "dropout", "max": 0.5},
        {"name": "psrr", "min": 40}]})
    _extraction_project(project, monkeypatch)
    extraction = physical._extract(project, "unit", "container", "image", "process", {})
    styles = ["ngspice()", "ngspice(hrhc)", "ngspice(lrhc)", "ngspice(hrlc)", "ngspice(lrlc)"]
    extraction["metrics"]["corners"] = [{**extraction["metrics"]["corners"][0], "style": s} for s in styles]
    put(work / "A13.json", extraction)
    legacy = put(work / "tb_unit_post_ngspice.sp", "legacy 1k-load study stays intact\n")
    before = legacy.read_bytes()
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: pytest.fail("do not rerun PRE or old canonical TB"))
    calls = []
    def runner(project, destination, container, image):
        def run(program, argv, **kwargs):
            text = Path(argv[-1]).read_text()
            calls.append((argv, text))
            assert "i_load b 0 0.0005" in text
            log = put(destination / "native.log", "MEAS vout=1.19\nMEAS iq=31.0\n")
            return {"returncode": 0, "log": str(log), "log_sha256": physical._sha(log)}
        return run
    monkeypatch.setattr(flow, "NativeCommands", runner)
    result = physical._resim(project, "unit", "container", "image", "process", {"_pre_result": state})
    assert result["status"] == "NOT_MEASURED"
    assert len(calls) == 5
    assert result["metrics"]["pre"]["measurements"] == {"vout": 1.19532, "iq": 30.1455}
    assert [c["style"] for c in result["metrics"]["corners"]] == styles
    assert all(c["missing"] == ["dropout", "psrr"] for c in result["metrics"]["corners"])
    assert legacy.read_bytes() == before
    assert all(c["native_measurement_study"]["native_inputs"]["bindings"] ==
               original["native_inputs"]["bindings"] for c in result["metrics"]["corners"])
    assert all(physical._current_native_views({role: view}) for role, view in result["native_inputs"].items())
    dependency_paths = {view["path"] for view in result["native_inputs"].values()}
    assert original["native_inputs"]["testbench"]["path"] in dependency_paths
    assert original["native_inputs"]["bindings"]["path"] in dependency_paths
    assert original["executions"][0]["log"] in dependency_paths
    put(work / "A14.json", result)
    statistical_decks = []
    def statistical(study, name, container, pdk, samples):
        deck, _rank = mc._find_deck(study, name)
        text = deck.read_text()
        assert "i_load b 0 0.0005" in text and "bound_iq" in text
        statistical_decks.append(deck)
        return {"verdict": "NOT_MEASURED", "mc_runs": samples, "spec_yield": {
            key: {"runs_scored": samples, "yield_pct": 100.0} for key in ("vout", "iq")}}
    monkeypatch.setattr(mc, "run_block", statistical)
    statistics = physical._statistics(project, "unit", "container", "image", "process", {"samples": 2})
    assert statistics["status"] == "NOT_MEASURED" and len(statistical_decks) == 5
    assert all(row["source_coverage"]["missing"] == ["dropout", "psrr"]
               for row in statistics["metrics"]["corners"])
    binding_path = Path(original["native_inputs"]["bindings"]["path"])
    binding_path.write_text(binding_path.read_text() + "\n")
    statistical_decks.clear()
    changed = physical._statistics(project, "unit", "container", "image", "process", {"samples": 2})
    assert changed["status"] == "NOT_MEASURED" and statistical_decks == []


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


@pytest.mark.parametrize("override,expected", [(2, 2), (11, 11), (None, 100)])
def test_a15_explicit_execution_sample_count_overrides_config_without_mutating_it(
        project, monkeypatch, override, expected):
    config = {"A15": {"samples": 100}}
    captured = []
    def native(*args):
        captured.append(args[-1])
        return {"status": "NOT_MEASURED", "outputs": []}
    monkeypatch.setattr(physical, "_native_call", native)
    physical.run_step("A15", project, {"name": "unit"},
        {"config": config, "post_mc_samples": override}, None)
    assert captured[0]["samples"] == expected
    assert config == {"A15": {"samples": 100}}


@pytest.mark.parametrize("override", [True, False, 0, 1, -2, 2.0, "2"])
def test_a15_invalid_execution_sample_count_refuses_before_launch(project, monkeypatch, override):
    captured = []
    monkeypatch.setattr(physical, "_native_call", lambda *a: captured.append(a) or {
        "status": "NOT_MEASURED", "outputs": []})
    result = physical.run_step("A15", project, {"name": "unit"},
        {"config": {"A15": {"samples": 100}}, "post_mc_samples": override}, None)
    assert result["status"] == "NOT_MEASURED"
    assert len(captured) == 0
    assert "post_mc_samples" in result["detail"]


def test_post_mc_execution_override_does_not_change_other_steps(project, monkeypatch):
    captured = []
    monkeypatch.setattr(physical, "_native_call", lambda *a: captured.append(a[-1]) or {
        "status": "NOT_MEASURED", "outputs": []})
    physical.run_step("A12", project, {"name": "unit"},
        {"config": {"A12": {"drc_engine": "native"}}, "post_mc_samples": 2}, None)
    assert captured == [{"drc_engine": "native"}]


def test_a13_forwards_block_extraction_inputs_with_explicit_settings_precedence(project,monkeypatch):
    bdir,_=physical._paths(project,'unit')
    core={'path':'private/core.so','sha256':'a'*64,'target':'/native/tclmagic.so'}
    put(bdir/'extraction_inputs.json',{'magic_core':core,'styles':['source-style']})
    captured=[]
    monkeypatch.setattr(physical,'_native_call',lambda *a:captured.append(a[-1]) or
                        {'status':'NOT_MEASURED','outputs':[]})
    physical.run_step('A13',project,{'name':'unit'},
                      {'config':{'A13':{'styles':['caller-style']}}},None)
    assert captured==[{'magic_core':core,'styles':['caller-style']}]


@pytest.mark.parametrize("step", ["A14", "A15"])
def test_incremental_post_inputs_reach_the_normal_native_dispatch_with_bounded_workers(project, monkeypatch, step):
    bdir, _ = physical._paths(project, "unit")
    declaration = {"kind": "incremental_capture", "manifest": {"path": "post.json", "sha256": "a" * 64},
                   "workers": 8, "samples": 3}
    put(bdir / "post_layout_inputs.json", declaration)
    captured = []
    monkeypatch.setattr(physical, "_native_call", lambda *a: captured.append(a[-1]) or
                        {"status": "NOT_MEASURED", "outputs": []})
    physical.run_step(step, project, {"name": "unit"},
        {"config": {step: {"workers": 4}}, "workers": 2, "cpus": 3}, None)
    assert captured == [{**declaration, "workers": 2, "cpus": 3}]


@pytest.mark.parametrize("operation,status", [("resim", "PASS"), ("resim", "FAIL"),
                                             ("statistics", "PASS"), ("statistics", "FAIL")])
def test_incremental_post_dispatch_preserves_native_verdict_and_actual_operation(project, monkeypatch, operation, status):
    import types
    manifest = {"kind": "incremental_capture_post_layout", "stage": "POST", "project": str(project),
                "block": "unit", "image": "selected-image"}
    path = project / "post.json"
    put(path, manifest)
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": status, "detail": "native result", "outputs": []}
    monkeypatch.setitem(sys.modules, "analog_incremental_post_layout", types.SimpleNamespace(run=run))
    cfg = {"kind": "incremental_capture", "manifest": {"path": str(path), "sha256": physical._sha(path)},
           "workers": 2, "cpus": 3, "samples": 4}
    fn = physical._resim if operation == "resim" else physical._statistics
    result = fn(project, "unit", "selected-container", "selected-image", "pdk", cfg)
    assert result["status"] == status
    assert calls == [((manifest, "selected-container", "selected-image", 2, 3),
                      {"operation": operation, **({"samples": 4} if operation == "statistics" else {})})]
    assert result["native_inputs"]["manifest"]["sha256"] == physical._sha(path)


@pytest.mark.parametrize("field,value", [("project", "/different-project"), ("block", "other-block"),
                                        ("stage", "PRE"), ("image", "different-image")])
def test_incremental_post_cannot_adopt_another_subject_or_pre_stage(project, monkeypatch, field, value):
    import types
    manifest = {"kind": "incremental_capture_post_layout", "stage": "POST", "project": str(project),
                "block": "unit", "image": "selected-image"}
    manifest[field] = value
    path = project / "post.json"
    put(path, manifest)
    calls = []
    monkeypatch.setitem(sys.modules, "analog_incremental_post_layout",
                        types.SimpleNamespace(run=lambda *a, **k: calls.append(a)))
    result = physical._resim(project, "unit", "container", "selected-image", "pdk",
        {"kind": "incremental_capture", "manifest": {"path": str(path), "sha256": physical._sha(path)}})
    assert result["status"] == "NOT_MEASURED"
    assert calls == []


@pytest.mark.parametrize("damage", ["changed", "missing"])
@pytest.mark.parametrize("native_status,expected", [("PASS", "NOT_MEASURED"), ("FAIL", "FAIL")])
def test_incremental_post_changed_plan_removes_pass_but_retains_native_failure(project, monkeypatch, native_status, expected, damage):
    import types
    path = project / "post.json"
    put(path, {"kind": "incremental_capture_post_layout", "stage": "POST", "project": str(project),
               "block": "unit", "image": "selected-image"})
    before = physical._sha(path)
    def run(*args, **kwargs):
        if damage == "missing":
            path.unlink()
        else:
            path.write_text(path.read_text() + "\n")
        return {"status": native_status, "outputs": []}
    monkeypatch.setitem(sys.modules, "analog_incremental_post_layout", types.SimpleNamespace(run=run))
    result = physical._resim(project, "unit", "container", "selected-image", "pdk",
        {"kind": "incremental_capture", "manifest": {"path": str(path), "sha256": before}})
    assert result["status"] == expected
    assert result["manifest_changed_during_execution"] is True
    assert result["native_inputs"]["manifest"]["sha256"] == before


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


@pytest.mark.parametrize('damage',[None,'hash','target','local','drift','receipt-drift'])
def test_a13_selected_core_uses_readonly_mount_and_current_source_bytes(project,monkeypatch,damage):
    import librelane_contract as lc
    calls=_extraction_project(project,monkeypatch)
    core=put(project/'private/tclmagic.so','native private core fixture')
    receipt=put(core.parent/'build.json',{'compiled_core':physical._sha(core)})
    target='/native/lib/magic/tcl/tclmagic.so'
    selection={'path':str(core),'sha256':physical._sha(core),'target':target,
               'build_receipt':str(receipt)}
    monkeypatch.setattr(lc,'_provider_for_image',lambda *a:None)
    monkeypatch.setattr(lc,'_provider_route',lambda *a:damage=='local')
    monkeypatch.setattr(lc,'run_container',lambda *a,**k:SimpleNamespace(
        returncode=0,stdout='/native/lib\n',stderr=''))
    if damage=='hash':selection['sha256']='0'*64
    if damage=='target':selection['target']='/wrong/lib/magic/tcl/tclmagic.so'
    if damage in ('drift','receipt-drift'):
        chain=lc.run_chain
        def drifting(*args,**kwargs):
            result=chain(*args,**kwargs)
            (core if damage=='drift' else receipt).write_text('changed during native extraction')
            return result
        monkeypatch.setattr(lc,'run_chain',drifting)
    result=physical._extract(project,'unit','container','image','process',{'magic_core':selection})
    assert result['status']==('PASS' if damage is None else 'NOT_MEASURED')
    if damage in ('hash','target','local'):assert not calls
    else:
        assert calls[0][1]['mounts']==[(core,target)]
        assert result['native_inputs'][str(core)]['sha256']==selection['sha256']
        assert str(receipt) in result['native_inputs']


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


@pytest.mark.parametrize("post,expected,missing", [
    ({"vout": 1.2}, "NOT_MEASURED", ["dropout", "iq", "psrr"]),
    ({"vout": 1.5}, "FAIL", ["dropout", "iq", "psrr"]),
    ({"vout": 1.2, "dropout": 0.3, "iq": 20, "psrr": 50}, "PASS", []),
])
def test_a14_requires_source_performance_outputs_without_treating_input_conditions_as_outputs(
        project, monkeypatch, post, expected, missing):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    extraction = physical._extract(project, "unit", "container", "image", "process", {})
    bdir, work = physical._paths(project, "unit")
    put(work / "A13.json", extraction)
    put(bdir / "spec.json", {"specs": [
        {"name": "Vout", "min": 1.1, "max": 1.3},
        {"name": "Dropout", "max": 0.5}, {"name": "Iq", "max": 50},
        {"name": "PSRR", "min": 40}, {"name": "Vin", "min": 1.6, "max": 2.0},
        {"name": "Iout", "min": 0.1, "max": 1.0}]})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: (True, post, "native measured outputs", {}))
    result = physical._resim(project, "unit", "container", "image", "process", {
        "_pre_result": _pre_state(project)})
    assert result["status"] == expected
    corner = result["metrics"]["corners"][0]
    assert sorted(corner["missing"]) == missing
    assert "vin" not in corner["missing"] and "iout" not in corner["missing"]
    assert corner["violations"] == (["vout"] if expected == "FAIL" else [])


def test_a14_keeps_unclassified_custom_output_limit(project, monkeypatch):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    extraction = physical._extract(project, "unit", "container", "image", "process", {})
    bdir, work = physical._paths(project, "unit")
    put(work / "A13.json", extraction)
    put(bdir / "spec.json", {"specs": [{"name": "custom_level", "min": 1.1, "max": 1.3}]})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: (True, {"vout": 1.2}, "native measured outputs", {}))
    result = physical._resim(project, "unit", "container", "image", "process", {
        "_pre_result": _pre_state(project)})
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["corners"][0]["missing"] == ["custom_level"]


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


def _post_statistics_inputs(project):
    _, work = physical._paths(project, "unit")
    post = put(work / "post.sp", ".include unit_post.sp\n.control\nop\n.endc\n")
    post_net = put(work / "unit_post.sp", ".subckt unit a b vss\nR0 a b 12.5\n.ends unit\n")
    put(work / "A14.json", {"status": "PASS", "metrics": {"corners": [
        {"style": "ngspice()", "post_testbench": str(post),
         "post_netlist": str(post_net), "post_netlist_sha256": physical._sha(post_net),
         "post_testbench_sha256": physical._sha(post)}]}})


@pytest.mark.parametrize("scored,expected", [(5, "PASS"), (4, "NOT_MEASURED")])
def test_a15_mc_reads_post_layout_not_schematic_and_counts_full_population(project,
                                                                         monkeypatch, scored, expected):
    import analog_mc_yield_run as mc
    _post_statistics_inputs(project)
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


def test_a15_repeated_execution_preserves_previous_native_population(project, monkeypatch):
    import analog_mc_yield_run as mc
    _post_statistics_inputs(project)
    populations = []
    def execute(study, name, container, pdk, count):
        marker = put(study / "native-population.txt", str(count))
        populations.append(marker)
        return {"verdict": "PASS", "mc_runs": count, "spec_yield": {
            "vout": {"runs_scored": count, "yield_pct": 100.0}}}
    monkeypatch.setattr(mc, "run_block", execute)
    first = physical._statistics(project, "unit", "container", "image", "process", {"samples": 2})
    second = physical._statistics(project, "unit", "container", "image", "process", {"samples": 5})
    assert first["status"] == second["status"] == "PASS"
    assert populations[0] != populations[1]
    assert [path.read_text() for path in populations] == ["2", "5"]
    assert first["metrics"]["corners"][0]["study"] != second["metrics"]["corners"][0]["study"]


def test_a15_independent_styles_run_in_parallel_with_one_native_thread_each(project, monkeypatch):
    import threading
    import analog_mc_yield_run as mc
    _post_statistics_inputs(project)
    _, work = physical._paths(project, "unit")
    state = json.loads((work / "A14.json").read_text())
    state["metrics"]["corners"].append({**state["metrics"]["corners"][0], "style": "alternate"})
    put(work / "A14.json", state)
    barrier = threading.Barrier(2)
    def execute(study, name, container, pdk, count):
        deck, _ = mc._find_deck(study, name)
        assert "set num_threads=1" in deck.read_text()
        barrier.wait(timeout=5)
        return {"verdict": "PASS", "mc_runs": count, "spec_yield": {
            "vout": {"runs_scored": count, "yield_pct": 100.0}}}
    monkeypatch.setattr(mc, "run_block", execute)
    result = physical._statistics(project, "unit", "container", "image", "process", {"samples": 2, "workers": 2})
    assert result["status"] == "PASS"
    assert result["metrics"]["workers"] == 2 and len(result["metrics"]["corners"]) == 2


def test_a15_focused_style_selection_reports_unmeasured_styles(project, monkeypatch):
    import analog_mc_yield_run as mc
    _post_statistics_inputs(project)
    _, work = physical._paths(project, "unit")
    state = json.loads((work / "A14.json").read_text())
    state["metrics"]["corners"].append({**state["metrics"]["corners"][0], "style": "alternate"})
    put(work / "A14.json", state)
    monkeypatch.setattr(mc, "run_block", lambda *a, **k: {"verdict": "PASS", "mc_runs": 2,
        "spec_yield": {"vout": {"runs_scored": 2, "yield_pct": 100.0}}})
    result = physical._statistics(project, "unit", "container", "image", "process",
                                 {"samples": 2, "styles": ["ngspice()"]})
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["unmeasured_styles"] == ["alternate"]
    assert len(result["metrics"]["corners"]) == 1


@pytest.mark.parametrize("yield_pct,extra,verdict,expected", [
    (100.0, [], "PASS", "PASS"),
    (100.0, [{"name": "psrr", "min": 40.0}], "PASS", "NOT_MEASURED"),
    (float("nan"), [], "PASS", "NOT_MEASURED"),
    (100.0, [], "FAIL", "FAIL"),
])
def test_a15_scores_source_outputs_not_supply_load_conditions(
        project, monkeypatch, yield_pct, extra, verdict, expected):
    import analog_mc_yield_run as mc
    bdir, _ = physical._paths(project, "unit")
    put(bdir / "spec.json", {"specs": [
        {"name": "vout", "min": 1.1, "max": 1.3},
        {"name": "vin", "min": 1.6, "max": 2.0},
        {"name": "iout", "min": 0.1, "max": 1.0}, *extra]})
    _post_statistics_inputs(project)
    monkeypatch.setattr(mc, "run_block", lambda *a: {
        "verdict": verdict, "mc_runs": 2,
        "spec_yield": {"vout": {"runs_scored": 2, "yield_pct": yield_pct}}})
    result = physical._statistics(project, "unit", "container", "image", "process", {"samples": 2})
    assert result["status"] == expected
    if expected == "PASS":
        assert result["metrics"]["corners"][0]["source_coverage"]["required"] == ["vout"]
    if extra:
        assert "psrr" in result["metrics"]["corners"][0]["source_coverage"]["missing"]


def test_a16_mission_without_declared_limits_does_not_launch(project, monkeypatch):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    put(project / "input/mission.sp", ".control\nop\n.endc\n.end\n")
    calls = []
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    def simulate(*args, **kwargs):
        calls.append(args)
        return True, {"max_stress": 0.8}, "native measured stress", {}
    monkeypatch.setattr(ars, "_run_ngspice", simulate)
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "deck": "input/mission.sp"})
    assert result["status"] == "NOT_MEASURED"
    assert calls == []
    assert "mission.spec" in result.get("missing_inputs", [])


def test_a16_absent_native_mission_and_reports_never_become_pass(project):
    result = physical._reliability(project, "unit", "container", "image", "process", {})
    assert result["status"] == "NOT_MEASURED"
    assert set(result["metrics"]) == {"mission", "thermal", "ir", "em", "aging"}
    assert all(r["status"] == "NOT_MEASURED" for r in result["metrics"].values())


def test_a16_routes_design_applicability_without_hiding_missing_required_evidence(project):
    def run(program, argv, **kwargs):
        assert kwargs['host'] is True
        settings = json.loads(argv[argv.index("--settings") + 1])
        result = physical._reliability(project, "unit", "container", "image", "process", settings)
        put(Path(argv[argv.index("--json") + 1]), result)
        return {"returncode": 2}
    result = physical.run_step("A16", project, {"name": "unit"}, {"features": {
        "requires_thermal": False, "requires_aging": False, "requires_ir": True,
        "requires_em": True}}, run)
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["thermal"]["status"] == "NOT_APPLICABLE"
    assert result["metrics"]["aging"]["status"] == "NOT_APPLICABLE"
    assert result["metrics"]["em"]["status"] == "NOT_MEASURED"
    assert set(result["missing_inputs"]) == {"mission.deck", "mission.spec", "ir.report", "em.report"}


def test_a16_supplied_thermal_violation_survives_unrequested_feature(project):
    put(project / "native_power.json", {"total_power_w": 2.0})
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "_features": {"requires_thermal": False, "requires_aging": False},
        "thermal": {"report": "native_power.json", "arguments": {"die_area_mm2": 1.0}}})
    assert result["status"] == "FAIL"
    assert result["metrics"]["thermal"]["result"]["verdict"] == "FAIL"
    assert result["metrics"]["aging"]["status"] == "NOT_APPLICABLE"


def test_a16_explicit_missing_thermal_report_remains_unmeasured(project):
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "_features": {"requires_thermal": False},
        "thermal": {"report": "requested_but_missing.json"}})
    assert result["metrics"]["thermal"]["status"] == "NOT_MEASURED"
    assert "thermal.report" in result["missing_inputs"]


@pytest.mark.parametrize("drop,expected", [(10.0, "NOT_MEASURED"), (100.0, "FAIL")])
def test_a16_routes_native_ir_report_and_explicit_design_budget(project, drop, expected):
    put(project / "native_ir.json", {"worst_ir_drop_mv": drop, "vdd_v": 1.2})
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "ir": {"report": "native_ir.json", "arguments": {"vdd": 1.2, "budget_pct": 5.0}}})
    assert result["status"] == expected
    assert result["metrics"]["ir"]["status"] == ("PASS" if drop == 10.0 else "FAIL")
    assert "ir_report" in result["native_inputs"]


def test_a16_retains_supplied_native_report_and_detects_change_during_check(project, monkeypatch):
    import thermal_screen_check as thermal
    source = put(project / "native_power.json", {"total_power_w": 0.1})
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    evaluate = thermal.main
    def changing_report(argv):
        rc = evaluate(argv)
        put(source, {"total_power_w": 2.0})
        return rc
    monkeypatch.setattr(thermal, "main", changing_report)
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "thermal": {"report": "native_power.json", "arguments": {"die_area_mm2": 1.0}}})
    assert result["metrics"]["thermal"]["status"] == "PASS"
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["input_currentness"]["changed"] == ["thermal_report"]
    assert result["native_inputs"]["thermal_report"]["sha256"] == original


def test_a16_block_declaration_routes_mission_and_keeps_every_attempt(project, monkeypatch):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    put(project / "mission.sp", ".control\nop\necho MEAS max_stress=0.8\n.endc\n.end\n")
    put(project / "limits.json", {"specs": [{"name": "max_stress", "max": 1.0}]})
    put(project / "phase3/analog/unit/reliability_inputs.json", {
        "deck": "mission.sp", "spec": "limits.json"})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: (
        True, {"max_stress": 0.8}, "native stress result", {}))
    def run(program, argv, **kwargs):
        settings = json.loads(argv[argv.index("--settings") + 1])
        result = physical._reliability(project, "unit", "container", "image", "process", settings)
        put(Path(argv[argv.index("--json") + 1]), result)
        return {"returncode": 2}
    first = physical.run_step("A16", project, {"name": "unit"}, {}, run)
    second = physical.run_step("A16", project, {"name": "unit"}, {}, run)
    assert first["metrics"]["mission"]["status"] == "PASS"
    assert first["native_inputs"]["mission_deck"]["path"] == str(project / "mission.sp")
    assert "reliability_inputs" in first["native_inputs"]
    assert first["outputs"][0] != second["outputs"][0]
    assert all(Path(p).is_file() for p in first["outputs"] + second["outputs"])


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


def test_a11_uses_declared_routing_geometry_and_explicit_config_wins(project):
    bdir, _ = physical._paths(project, 'unit')
    put(bdir / 'layout_inputs.json', {'wire_width_um': 0.6, 'pg_via_cuts': 2, 'pg_wire_width_um': 3})
    calls = []
    def run(program, argv, **kwargs):
        calls.append(argv)
        put(Path(argv[argv.index('--json') + 1]), {'result': 'ENV_UNAVAILABLE'})
        return {'returncode': 69}
    physical.run_step('A11', project, {'name': 'unit'}, {}, run)
    assert calls[-1][calls[-1].index('--wire-width-um') + 1] == '0.6'
    assert calls[-1][calls[-1].index('--pg-via-cuts') + 1] == '2'
    assert calls[-1][calls[-1].index('--pg-wire-width-um') + 1] == '3'
    physical.run_step('A11', project, {'name': 'unit'}, {
        'config': {'steps': {'A11': {'wire_width_um': 0.8}}}}, run)
    assert calls[-1][calls[-1].index('--wire-width-um') + 1] == '0.8'


@pytest.mark.parametrize('declared', ['not json', '[]'])
def test_a11_corrupt_layout_inputs_cannot_silently_use_default_geometry(project, declared):
    bdir, _ = physical._paths(project, 'unit')
    put(bdir / 'layout_inputs.json', declared)
    result = physical.run_step('A11', project, {'name': 'unit'}, {},
        lambda *a, **k: pytest.fail('invalid selected geometry must not launch native layout'))
    assert result['status'] == 'NOT_MEASURED'
