"""Native A11--A16 execution adapters, with real product parsers and helpers."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _plugin_tree
import analog_native_physical as physical
from _hostpaths import require_repo
from test_analog_method_local_startup import psp_runtime, _psp_project


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


def _resim_extraction(project, name, raw):
    """Supply synthetic RC/A13 prerequisites; no PV/extraction qualification."""
    bdir, work = physical._paths(project, name)
    gds = put(bdir / f"{name}.gds", "synthetic layout prerequisite")
    extracted = put(work / "extracted.spice", raw)
    put(work / "A13.json", {"status": "PASS", "metrics": {
        "netlist_sha256": physical._sha(bdir / f"{name}.sp"),
        "layout_sha256": physical._sha(gds), "corners": [{"style": "ngspice()",
        "extracted_netlist": str(extracted), "sha256": physical._sha(extracted)}]}})


def _real_windows(project, name, image, family):
    import analog_native_flow as native
    args = SimpleNamespace(entry_step="A07", exit_step="A07", blocks=name,
                           container="", image=image, transport="LOCAL", pdk=family)
    pre = native.run_window(project, args)["steps"][0]
    assert pre["status"] == "PASS", pre
    args.entry_step = args.exit_step = "A14"
    report = native.run_window(project, args)
    post = next(row for row in report["steps"] if row["step"] == "A14")
    return pre, post


def test_real_a14_local_uses_repo_declared_context_without_optional_init(tmp_path, psp_runtime):
    from declared_pdk_is_the_pdk_used_check import declared_target
    image, _, _ = psp_runtime
    project = tmp_path / "project"
    declaration = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "tests", "fixtures", "m4_native_top", "phase1", "generated_docs", "L19_CONSTRAINTS_PDK.json")
    put(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", declaration.read_text())
    family, _ = declared_target(project)
    bdir = project / "phase3/analog/unit"
    circuit = ".subckt unit a b vss\nR1 a b 1k\nR2 b vss 2k\n.ends unit\n"
    put(bdir / "unit.sp", circuit)
    put(bdir / "tb_unit.sp", "* preserved canonical input\n")
    put(bdir / "spec.json", {"specs": [{"name": "vout", "min": 1.1, "max": 1.3}]})
    put(bdir / "testbench_inputs.json", {"block": "unit", "ports": ["a", "b", "vss"],
        "rails": {"vss": "vss"}, "testbench": {"supply_exprs": ["1.8"],
        "stimulus": ["v_force a 0 {supply}"],
        "control": ["op", "let sensed = v(b)", 'echo "MEAS vout=" $&sensed', "quit"]}})
    put(project / "phase3/analog/analog_block_list.json", {"blocks": [{"name": "unit"}]})
    _resim_extraction(project, "unit", circuit.replace(".ends unit", "Rpex b sense 10\nCpex sense vss 1p\n.ends unit"))
    pre, post = _real_windows(project, "unit", image, family)
    assert post["status"] == "PASS", post
    assert post["metrics"]["pre"]["measurements"]["vout"] == pre["metrics"]["vout"]
    corner = post["metrics"]["corners"][0]
    assert corner["measurements"]["vout"] == pytest.approx(1.2)
    execution = corner["simulation"]["native_execution"]
    assert execution["argv"][0] == "ngspice"
    assert execution["native_init"] is None
    assert execution["native_environment"]["PDK"] == family
    assert (bdir / "tb_unit.sp").read_text() == "* preserved canonical input\n"


@pytest.mark.parametrize("bad_model", [False, True])
def test_real_a14_local_reuses_a07_psp_startup(tmp_path, psp_runtime, bad_model):
    image, family, init = psp_runtime
    project, canonical = _psp_project(tmp_path, family, "declared")
    before = canonical.read_bytes()
    model = "unavailable_model_alpha" if bad_model else "model_alpha"
    raw = (".subckt device_alpha d g vss\nn_active core g vss vss " + model +
           " w=1u l=1u\nRpex d core 2\nCpex core vss 1p\n.ends device_alpha\n")
    _resim_extraction(project, "device_alpha", raw)
    if not bad_model:
        record = physical._paths(project, "device_alpha")[1] / "A13.json"
        extraction = json.loads(record.read_text())
        extraction["metrics"]["corners"].append(
            {**extraction["metrics"]["corners"][0], "style": "ngspice(hrhc)"})
        put(record, extraction)
    pre, post = _real_windows(project, "device_alpha", image, family)
    assert post["status"] == ("FAIL" if bad_model else "PASS"), post
    simulation = post["metrics"]["simulation"] if bad_model else post["metrics"]["corners"][0]["simulation"]
    execution = simulation["native_execution"]
    assert execution["argv"][0] == "ngspice"
    assert execution["native_init"] == pre["executions"][0]["native_init"]
    assert execution["native_environment"] == pre["executions"][0]["native_environment"]
    assert execution["native_init"]["path"] == str(init)
    assert canonical.read_bytes() == before
    if bad_model:
        assert simulation["rc"] != 0
        assert "*" in simulation["failed_analyses"]
    else:
        assert post["metrics"]["corners"][0]["measurements"]["device_current"] > 0
        assert any(view.get("path") == str(init) for view in post["native_inputs"].values())
        executions = [c["simulation"]["native_execution"] for c in post["metrics"]["corners"]]
        assert len(executions) == len({e["log"] for e in executions}) == 2
        assert all(e["log_sha256"] == physical._sha(Path(e["log"])) for e in executions)


@pytest.mark.parametrize("outcome", ["success", "missing_docker", "missing_container"])
def test_a14_requested_container_never_falls_back_to_local(project, monkeypatch, outcome):
    import analog_native_flow as native
    import subprocess
    _extraction_project(project, monkeypatch)
    put(physical._paths(project, "unit")[1] / "A13.json",
        physical._extract(project, "unit", "requested_alpha", "image", "process", {}))
    state = _declared_pre_state(project)
    calls = []

    def execute(argv, **kwargs):
        calls.append(argv)
        if outcome == "missing_docker":
            raise FileNotFoundError(2, "No such file or directory", "docker")
        if outcome == "missing_container":
            return subprocess.CompletedProcess(argv, 1, "", "No such container: requested_alpha")
        if argv[:2] != ["docker", "exec"] or "analog-native" not in argv:
            raise FileNotFoundError(2, "Only the declared native context is available", "docker")
        return subprocess.CompletedProcess(argv, 0,
            "MEAS vout=1.19 rising_min=1.14 falling_peak=1.26\n", "")

    monkeypatch.setattr(native.subprocess, "run", execute)
    monkeypatch.setattr(native, "_local_ngspice_startup",
        lambda *a: pytest.fail("a requested container must never select LOCAL startup"))
    destination = project / "result.json"
    rc = physical.main(["resim", str(project), "--block", "unit", "--container", "requested_alpha",
        "--image", "image", "--pdk", "process", "--settings", json.dumps({"_pre_result": state}),
        "--json", str(destination)])
    result = json.loads(destination.read_text())
    expected = {"success": (0, "PASS"), "missing_docker": (2, "NOT_MEASURED"),
                "missing_container": (2, "NOT_MEASURED")}[outcome]
    assert (rc, result["status"]) == expected, result
    assert len(calls) == (3 if outcome == "success" else 1)
    assert all(argv[:2] == ["docker", "exec"] and "requested_alpha" in argv for argv in calls)
    if outcome != "success":
        assert "requested_alpha" in result["detail"]
        if outcome == "missing_docker":
            assert "NGSPICE_NATIVE_EXECUTION_UNAVAILABLE" in result["detail"]


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


@pytest.mark.parametrize("rc", [130, 137, 143, -9, -15])
def test_layout_interruption_without_measured_failure_is_unmeasured(project, rc):
    result = physical.run_step("A11", project, {"name": "unit"}, {},
                               lambda *a, **k: {"returncode": rc, "stderr": "interrupted"})
    assert result["status"] == "NOT_MEASURED"
    assert result["executions"][0]["returncode"] == rc


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


def test_native_pv_host_resolves_attested_local_pdk_before_gds(project, monkeypatch):
    import analog_pdk_availability as availability
    root = project / "installed"
    (root / "ihp-sg13g2/libs.tech/ngspice").mkdir(parents=True)
    monkeypatch.setattr(availability, "local_pdks_root", lambda: str(root))
    result = physical._pv(project, "unit", "host", "image", "ihp-sg13g2", {})
    assert result["status"] == "NOT_MEASURED"
    assert result["detail"] == "A11 block GDS is absent"


def test_native_pv_host_resolves_explicit_installed_pdk_before_gds(project):
    root = project / "installed"
    (root / "ihp-sg13g2/libs.tech/ngspice").mkdir(parents=True)
    result = physical._pv(project, "unit", "host", "", "ihp-sg13g2",
                          {"pdk_root": str(root)})
    assert result["status"] == "NOT_MEASURED"
    assert result["detail"] == "A11 block GDS is absent"


def test_native_pv_explicit_host_root_selects_foundry_not_staged_models(project, monkeypatch):
    import analog_a6_native_pv as pv
    import analog_native_erc as erc
    root = project / "installed"
    (root / "ihp-sg13g2/libs.tech/ngspice").mkdir(parents=True)
    put(project / "input/pdk/models/native.lib", ".model native nmos level=1\n")
    put(project / "phase3/analog/unit/unit.gds", "native tool fixture")
    seen = []
    monkeypatch.setattr(pv, "run_block_pv", lambda _p, _b, resolved, **kw:
                        seen.append(resolved) or {"drc": {}, "lvs": {}})
    monkeypatch.setattr(erc, "run", lambda *a, **kw:
                        {"status": "NOT_MEASURED", "outputs": []})
    physical._pv(project, "unit", "host", "", "ihp-sg13g2", {"pdk_root": str(root)})
    assert seen[0]["source"] == "container_installed"
    assert seen[0]["pdk_root"] == str(root / "ihp-sg13g2")


@pytest.mark.parametrize("violations,lvs,expected", [(0, "match", "PASS"),
    (3, "match", "FAIL"), (0, "mismatch", "FAIL")])
def test_attested_in_image_pv_passes_actual_local_context(project, monkeypatch,
                                                        violations, lvs, expected):
    import analog_a6_native_pv as pv
    import analog_native_erc as erc
    import analog_pdk_availability as availability
    import librelane_contract as launch
    put(project / "phase3/analog/unit/unit.gds", "native fixture")
    attested = []
    monkeypatch.setattr(launch, "local_image_attestation", lambda image:
                        attested.append(image) or {"image": image, "cid": "bound-runtime"})
    monkeypatch.setattr(availability, "resolve_pdk", lambda *a, **k:
                        {"available": True, "drc_deck": "native.drc", "lvs_deck": "native.lvs"})
    contexts = []
    def verify(*args, **kwargs):
        contexts.append(("pv", kwargs["container"]))
        return {"ran": True, "drc": {"verdict": "FAIL" if violations else "PASS", "violations": violations},
                "lvs": {"verdict": lvs}}
    def electrical(*args, **kwargs):
        contexts.append(("erc", kwargs["container"]))
        return {"status": "PASS", "outputs": []}
    monkeypatch.setattr(pv, "run_block_pv", verify)
    monkeypatch.setattr(erc, "run", electrical)
    result = physical._pv(project, "unit", "", "selected-image", "fixture180", {"drc_engine": "klayout"})
    assert attested == ["selected-image"]
    assert contexts == [("pv", "host")] + ([("erc", "host")] if expected == "PASS" else [])
    assert result["status"] == expected
    assert result["metrics"]["drc"]["violations"] == violations


def test_pv_without_execution_context_refuses_before_native_tools(project, monkeypatch):
    import analog_a6_native_pv as pv
    import analog_native_erc as erc
    import analog_pdk_availability as availability
    import librelane_contract as launch
    put(project / "phase3/analog/unit/unit.gds", "native fixture")
    def absent(image):
        raise launch.Refusal("LL_LOCAL_IMAGE_UNATTESTED", "no bound runtime")
    monkeypatch.setattr(launch, "local_image_attestation", absent)
    monkeypatch.setattr(availability, "resolve_pdk", lambda *a, **k: {"available": True})
    calls = []
    monkeypatch.setattr(pv, "run_block_pv", lambda *a, **k: calls.append("pv") or
                        {"drc": {"verdict": "PASS"}, "lvs": {"verdict": "match"}})
    monkeypatch.setattr(erc, "run", lambda *a, **k: calls.append("erc") or {"status": "PASS", "outputs": []})
    result = physical._pv(project, "unit", "", "", "fixture180", {"drc_engine": "klayout"})
    assert result["status"] == "NOT_MEASURED"
    assert "LL_LOCAL_IMAGE_UNATTESTED" in result["detail"]
    assert calls == []


def test_named_pv_container_preserves_explicit_execution_context(project, monkeypatch):
    import analog_a6_native_pv as pv
    import analog_native_erc as erc
    import analog_pdk_availability as availability
    import librelane_contract as launch
    put(project / "phase3/analog/unit/unit.gds", "native fixture")
    def unexpected(*args):
        raise AssertionError("named-container route requested local attestation")
    monkeypatch.setattr(launch, "local_image_attestation", unexpected)
    monkeypatch.setattr(availability, "resolve_pdk", lambda *a, **k: {"available": True})
    contexts = []
    monkeypatch.setattr(pv, "run_block_pv", lambda *a, **k: contexts.append(k["container"]) or
                        {"drc": {"verdict": "PASS"}, "lvs": {"verdict": "match"}})
    monkeypatch.setattr(erc, "run", lambda *a, **k: contexts.append(k["container"]) or
                        {"status": "PASS", "outputs": []})
    assert physical._pv(project, "unit", "selected-container", "", "fixture180", {})["status"] == "PASS"
    assert contexts == ["selected-container", "selected-container"]


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
        put(folder / "extraction_full/unit.res.ext", "")
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
    assert all(not Path(c["post_testbench"]).is_absolute() and
               not Path(c["post_netlist"]).is_absolute()
               for c in result["metrics"]["corners"])
    assert all(c["missing"] == ["dropout", "psrr"] for c in result["metrics"]["corners"])
    assert legacy.read_bytes() == before
    assert all(c["native_measurement_study"]["native_inputs"]["bindings"]["sha256"] ==
               original["native_inputs"]["bindings"]["sha256"] for c in result["metrics"]["corners"])
    assert all(not Path(c["native_measurement_study"]["native_inputs"]["bindings"]["path"]).is_absolute()
               for c in result["metrics"]["corners"])
    dependency_paths = {view["path"] for view in result["native_inputs"].values()}
    assert str(Path(original["native_inputs"]["testbench"]["path"]).relative_to(project)) in dependency_paths
    assert str(Path(original["native_inputs"]["bindings"]["path"]).relative_to(project)) in dependency_paths
    assert str(Path(original["executions"][0]["log"]).relative_to(project)) in dependency_paths
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


def _declared_pre_state(project, source="sidecar"):
    import analog_native_sim as sim
    bdir, _ = physical._paths(project, "unit")
    nested = put(bdir / "load_detail.sp", "* declared load model\n")
    put(bdir / "load.sp", '.include "' + str(nested) + '"\n')
    declaration = bdir / "testbench_inputs.json" if source == "sidecar" else project / "declared/inputs.json"
    put(declaration, {"block": "unit", "ports": ["a", "b", "vss"],
        "rails": {"vss": "vss"}, "testbench": {"supply_exprs": ["1.8"],
        "stimulus": ["v1 a 0 {supply}"], "cards": [".include load.sp", "i_load b 0 PULSE(0 1m 2n 1p 1p 4n 10n)"],
        "control": ["op", "let sensed = v(b)", 'echo "MEAS vout=" $&sensed',
            "tran 1p 10n", "meas tran rising_min MIN v(b) FROM=2n TO=5n",
            "meas tran falling_peak MAX v(b) FROM=6n TO=9n"]}})
    config = {} if source == "sidecar" else {"blocks": {"unit": {
        "testbench_inputs": str(declaration.relative_to(project))}}}
    if config:
        put(project / "input/analog_flow.json", config)
    def run(program, argv, **kwargs):
        log = put(Path(argv[argv.index("-o") + 1]), "MEAS vout=1.2 rising_min=1.15 falling_peak=1.25\n")
        capture = put(log.parent / "capture.log", "ngspice batch mode\n")
        return {"returncode": 0, "log": str(capture), "log_sha256": physical._sha(capture),
                "outputs": {str(log): physical._sha(log)},
                "argv": ["ngspice", *argv]}
    return sim.run_step("A07", project, {"name": "unit"}, {"config": config}, run)


@pytest.mark.parametrize("source", ["config", "sidecar"])
def test_a14_reuses_declared_pre_and_substitutes_pex_without_new_pre_run(project, monkeypatch, source):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    extraction = physical._extract(project, "unit", "container", "image", "process", {})
    _, work = physical._paths(project, "unit")
    put(work / "A13.json", extraction)
    state = _declared_pre_state(project, source)
    assert state["status"] == "PASS"
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    calls = []
    def spice(container, deck, **kwargs):
        calls.append(Path(deck))
        assert "v1 a 0 1.8" in calls[-1].read_text()
        assert "unit_post_" in calls[-1].read_text()
        assert "PULSE(0 1m 2n 1p 1p 4n 10n)" in calls[-1].read_text()
        assert "meas tran rising_min MIN v(b) FROM=2n TO=5n" in calls[-1].read_text()
        assert "meas tran falling_peak MAX v(b) FROM=6n TO=9n" in calls[-1].read_text()
        return True, {"vout": 1.19, "rising_min": 1.14, "falling_peak": 1.26}, "MEAS vout=1.19 rising_min=1.14 falling_peak=1.26\n", {}
    monkeypatch.setattr(ars, "_run_ngspice", spice)
    result = physical._resim(project, "unit", "container", "image", "process", {"_pre_result": state})
    assert result["status"] == "PASS"
    assert len(calls) == 1
    assert result["metrics"]["pre"]["measurements"] == {"vout": 1.2, "rising_min": 1.15, "falling_peak": 1.25}
    assert result["metrics"]["corners"][0]["measurements"] == {"vout": 1.19, "rising_min": 1.14, "falling_peak": 1.26}


@pytest.mark.parametrize("changed", ["declaration", "deck", "spec", "removed", "different_selection", "include", "nested_include"])
def test_a14_rejects_stale_declared_pre_without_simulation(project, monkeypatch, changed):
    import analog_real_corner_sweep as ars
    state = _declared_pre_state(project)
    bdir, _ = physical._paths(project, "unit")
    declaration = bdir / "testbench_inputs.json"
    if changed == "removed":
        declaration.unlink()
    elif changed == "different_selection":
        other = put(project / "other.json", json.loads(declaration.read_text()))
        put(project / "input/analog_flow.json", {"blocks": {"unit": {"testbench_inputs": str(other)}}})
    elif changed in ("include", "nested_include"):
        path = bdir / ("load.sp" if changed == "include" else "load_detail.sp")
        path.write_text(path.read_text() + "* changed dependency\n")
    else:
        path = declaration if changed == "declaration" else Path(state["native_inputs"]["testbench"]["path"]) if changed == "deck" else bdir / "spec.json"
        path.write_text(path.read_text() + "\n")
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: pytest.fail("stale PRE must not run"))
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == {}
    assert "no completed source-bound" in record["detail"]


@pytest.mark.parametrize("changed", ["declaration", "pre_log", "include", "nested_include"])
def test_a14_declared_pre_change_during_post_keeps_unmeasured(project, monkeypatch, changed):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    extraction = physical._extract(project, "unit", "container", "image", "process", {})
    bdir, work = physical._paths(project, "unit")
    put(work / "A13.json", extraction)
    state = _declared_pre_state(project)
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    def spice(*args, **kwargs):
        path = {"declaration": bdir / "testbench_inputs.json",
                "pre_log": Path(state["executions"][0]["stdout_path"]),
                "include": bdir / "load.sp", "nested_include": bdir / "load_detail.sp"}[changed]
        path.write_text(path.read_text() + "\n")
        return True, {"vout": 1.19, "rising_min": 1.14, "falling_peak": 1.26}, "MEAS vout=1.19\n", {}
    monkeypatch.setattr(ars, "_run_ngspice", spice)
    result = physical._resim(project, "unit", "container", "image", "process", {"_pre_result": state})
    assert result["status"] == "NOT_MEASURED"
    assert "changed during POST" in result["detail"]


@pytest.mark.parametrize("changed", [None, "bytes", "digest", "missing"])
def test_a14_reuses_real_a07_output_stream_only_while_current(project, changed):
    import shutil
    import analog_native_flow as native
    import analog_native_sim as sim
    if not shutil.which("ngspice"):
        pytest.skip("native ngspice is required for the A07 to A14 stream control")
    bdir, _ = physical._paths(project, "unit")
    put(bdir / "unit.sp", ".subckt unit a b vss\nr1 a b 1k\nr2 b vss 1k\n.ends unit\n")
    put(bdir / "spec.json", {"specs": [{"name": "vout", "min": 0.9, "max": 1.1}]})
    put(bdir / "testbench_inputs.json", {"block": "unit", "ports": ["a", "b", "vss"],
        "rails": {"vss": "vss"},
        "testbench": {"supply_exprs": ["2"], "stimulus": ["v1 a 0 {supply}"],
        "control": ["op", "let sensed = v(b)", 'echo "MEAS vout=" $&sensed', "quit"]}})
    destination = project / "native-capture"
    destination.mkdir()
    state = sim.run_step("A07", project, {"name": "unit"}, {"config": {}},
                         native.NativeCommands(project, destination, ""))
    assert state["status"] == "PASS", state
    execution = state["executions"][0]
    output = Path(execution["stdout_path"])
    assert output != Path(execution["log"])
    assert "MEAS vout=" in output.read_text()
    assert "MEAS vout=" not in Path(execution["log"]).read_text()
    if changed == "bytes":
        output.write_text(output.read_text() + "\n")
    elif changed == "digest":
        execution["outputs"].pop(str(output))
    elif changed == "missing":
        output.unlink()
    values, record = physical._pre_layout_measurements(project, "unit", {"_pre_result": state})
    assert values == ({} if changed else {"vout": pytest.approx(1.0)})
    if changed is None:
        assert record["reused"] is True
        assert record["log"] == str(output)
        assert record["log_sha256"] == execution["outputs"][str(output)]


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
    put(bdir / "spec.json", {"specs": [{"name": "custom_level", "min": 1.1, "max": 1.3,
        "unit": "V", "measurement": {"analysis": "OP", "expression": "v(b)"}}]})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: (True, {"vout": 1.2}, "native measured outputs", {}))
    result = physical._resim(project, "unit", "container", "image", "process", {
        "_pre_result": _pre_state(project)})
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["corners"][0]["missing"] == ["custom_level"]


@pytest.mark.parametrize("source_specs", [
    [{"name": "Vin", "min": 1.6, "max": 2.0},
     {"name": "Iout", "min": 0.1, "max": 1.0}],
    [{"name": "temperature_c", "min": -40, "max": 125}],
    [{"name": "load_capacitance", "min": 1e-12, "max": 1e-9}],
    [{"name": "input_slew", "min": 1e-9, "max": 5e-9}],
], ids=["supply-load", "temperature", "load-capacitance", "input-slew"])
def test_a14_source_conditions_without_output_role_never_launch_native(
        project, monkeypatch, source_specs):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    _extraction_project(project, monkeypatch)
    extraction = physical._extract(project, "unit", "container", "image", "process", {})
    bdir, work = physical._paths(project, "unit")
    put(work / "A13.json", extraction)
    put(bdir / "spec.json", {"specs": source_specs})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    native_calls = []
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k:
        native_calls.append((a, k)) or (True, {}, "native source conditions", {}))

    result = physical._resim(project, "unit", "container", "image", "process", {
        "_pre_result": _pre_state(project)})

    assert native_calls == []
    assert result["status"] == "NOT_MEASURED"
    assert result["detail"] == "post-layout acceptance has no declared numeric spec bounds"


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


def _transferred_post_statistics_inputs(project, damage=None):
    """Stage exact A14 bytes under a new root, retaining its old path strings."""
    _, work = physical._paths(project, "unit")
    study = work / "measurement_studies/ngspice/receipt-id/study-0"
    post_net = put(study / "unit_post_ngspice.sp",
                   ".subckt unit a b vss\nR0 a b 12.5\n.ends unit\n")
    deck = put(study / "measurements.sp",
               ".include unit_post_ngspice.sp\n.control\nop\n.endc\n")
    old_root = project.parent / "transferred-away-project"
    relative_deck = deck.relative_to(project)
    relative_net = post_net.relative_to(project)
    recorded_deck = old_root / relative_deck
    recorded_net = old_root / relative_net
    if damage == "missing":
        deck.unlink()
    elif damage == "changed":
        deck.write_text(deck.read_text() + "* changed after A14\n")
    elif damage == "foreign":
        recorded_deck = project.parent / "foreign-receipt/measurements.sp"
    put(work / "A14.json", {"status": "PASS", "metrics": {"corners": [{
        "style": "ngspice()", "post_testbench": str(recorded_deck),
        "post_netlist": str(recorded_net), "post_netlist_sha256": physical._sha(post_net),
        "post_testbench_sha256": hashlib.sha256(
            ".include unit_post_ngspice.sp\n.control\nop\n.endc\n".encode()).hexdigest()}]}})


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


@pytest.mark.parametrize("damage,expected", [
    (None, "PASS"), ("missing", "NOT_MEASURED"),
    ("changed", "NOT_MEASURED"), ("foreign", "NOT_MEASURED")])
def test_a15_rebinds_only_exact_hash_bound_transferred_a14_paths(
        project, monkeypatch, damage, expected):
    import analog_mc_yield_run as mc
    _transferred_post_statistics_inputs(project, damage)
    calls = []
    monkeypatch.setattr(mc, "run_block", lambda *a: calls.append(a) or {
        "verdict": "PASS", "mc_runs": 2,
        "spec_yield": {"vout": {"runs_scored": 2, "yield_pct": 100.0}}})
    result = physical._statistics(project, "unit", "container", "image", "process", {"samples": 2})
    assert result["status"] == expected
    assert len(calls) == (1 if expected == "PASS" else 0)


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


def test_a16_op_convergence_uses_only_fixed_stock_ngspice_controls(project, monkeypatch):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    deck = put(project / "input/mission.sp",
               "* untouched mission\n.control\nop\necho MEAS max_stress=0.8\n.endc\n.end\n")
    put(project / "input/mission_spec.json",
        {"specs": [{"name": "max_stress", "max": 1.0}]})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    seen = {}
    def simulate(container, actual_deck, **kwargs):
        seen["path"] = Path(actual_deck)
        seen["text"] = kwargs["deck_text"]
        return True, {"max_stress": 0.8}, "native measured stress", {"rc": 0}
    monkeypatch.setattr(ars, "_run_ngspice", simulate)
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "deck": "input/mission.sp", "spec": "input/mission_spec.json",
        "op_convergence": True,
        "_features": {"requires_thermal": False, "requires_ir": False,
                      "requires_em": False, "requires_aging": False}})
    mission = result["metrics"]["mission"]
    assert result["status"] == "PASS"
    assert mission["op_convergence"]["options"] == {
        "itl1": 500, "gminsteps": 100, "srcsteps": 100}
    assert ".options itl1=500 gminsteps=100 srcsteps=100" in seen["text"]
    assert "reltol" not in seen["text"] and "abstol" not in seen["text"]
    assert seen["path"] != deck
    assert deck.read_text() == "* untouched mission\n.control\nop\necho MEAS max_stress=0.8\n.endc\n.end\n"
    assert result["native_inputs"]["mission_execution_deck"]["sha256"] == physical._sha(seen["path"])


@pytest.mark.parametrize("deck", [
    ".control\ntran 1n 10n\nop\n.endc\n.end\n",
    ".options itl1=9\n.control\nop\n.endc\n.end\n",
])
def test_a16_op_convergence_refuses_non_op_or_preconfigured_deck(deck):
    with pytest.raises(ValueError):
        physical._a16_op_convergence_deck(deck)


def test_a16_op_nonconvergence_is_a_consumed_mission_failure(project, monkeypatch):
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    put(project / "input/mission.sp", ".control\nop\n.endc\n.end\n")
    put(project / "input/mission_spec.json",
        {"specs": [{"name": "max_stress", "max": 1.0}]})
    monkeypatch.setattr(dr, "resolve_host_root", lambda *a: str(project))
    monkeypatch.setattr(ars, "_container_path", lambda c, root, p: str(p))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **k: (
        False, {}, "singular matrix", {"rc": 1, "failed_analyses": ["*"]}))
    result = physical._reliability(project, "unit", "container", "image", "process", {
        "deck": "input/mission.sp", "spec": "input/mission_spec.json",
        "op_convergence": True,
        "_features": {"requires_thermal": False, "requires_ir": False,
                      "requires_em": False, "requires_aging": False}})
    assert result["status"] == "FAIL"
    assert result["metrics"]["mission"]["status"] == "FAIL"
    assert result["metrics"]["mission"]["simulation"]["rc"] == 1
    assert result["metrics"]["mission"]["missing"] == ["max_stress"]


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


def test_layout_forwards_selected_block_row_width(project):
    calls = []
    def run(program, argv, **kwargs):
        calls.append(argv)
        return {'returncode': 1}
    physical.run_step('A11', project, {'name': 'unit'},
        {'config': {'steps': {'A11': {'blocks': {'unit': {'max_row_width_um': 400}}}}}}, run)
    argv = calls[0]
    assert argv[argv.index('--max-row-width-um') + 1] == '400'


def test_refused_structural_lvs_does_not_run_erc_or_report_acceptance(project, monkeypatch):
    import analog_pdk_availability as availability
    import analog_a6_native_pv as pv
    import analog_native_erc as erc
    bdir, _ = physical._paths(project, 'unit')
    put(bdir / 'unit.gds', 'native fixture')
    monkeypatch.setattr(availability, 'resolve_pdk', lambda *a, **k: {'available': True})
    monkeypatch.setattr(pv, 'run_block_pv', lambda *a, **k: {
        'ran': False, 'drc': None, 'lvs': {'executed': False, 'verdict': 'refused',
                                         'detail': 'structural source changed'}})
    def no_erc(*args, **kwargs):
        raise AssertionError('unqualified LVS advanced to ERC')
    monkeypatch.setattr(erc, 'run', no_erc)
    result = physical._pv(project, 'unit', 'host', 'image', 'process', {'drc_engine': 'native'})
    assert result['status'] == 'NOT_MEASURED'
    assert result['detail'] == 'structural source changed'


def test_a13_joins_a_resistor_body_to_its_substrate_and_keeps_the_native_output(project, monkeypatch):
    import librelane_contract as lc
    _extraction_project(project, monkeypatch)
    native = ".subckt unit a b vss\nX0 a b vss vss nfet w=1u l=1u\nC0 a a_1_2# 1f\nC1 b vss 2f\n.ends unit\n"
    record = 'device rsubckt rmodel 1 2 3 4 w=1 l=1 "vss" "a_1_2#" 200 0 "a" 1 0 "b" 1 0\n'
    chain = lc.run_chain
    def extract(*args, **kwargs):
        folder = chain(*args, **kwargs)[0]
        put(folder / "unit.rcx.spice", native)
        put(folder / "extraction_full/unit.res.ext", record)
        return [folder]
    monkeypatch.setattr(lc, "run_chain", extract)
    corner = physical._extract(project, "unit", "container", "image", "process", {"styles": ["s"]})["metrics"]["corners"][0]
    bound = Path(corner["extracted_netlist"]).read_text()
    assert "a_1_2#" not in bound and "C0 a vss 1f" in bound
    assert Path(corner["native_netlist"]).read_text() == native
    assert corner["native_sha256"] == physical._sha(Path(corner["native_netlist"]))
    assert corner["sha256"] == physical._sha(Path(corner["extracted_netlist"]))
    assert corner["resistor_bodies"] == [{"body": "a_1_2#", "substrate": "vss",
        "capacitors": [{"capacitor": "C0", "other_node": "a", "value": "1f"}]}]


def test_a13_refuses_an_extraction_without_device_records(project, monkeypatch):
    import librelane_contract as lc
    _extraction_project(project, monkeypatch)
    chain = lc.run_chain
    def extract(*args, **kwargs):
        folder = chain(*args, **kwargs)[0]
        (folder / "extraction_full/unit.res.ext").unlink()
        return [folder]
    monkeypatch.setattr(lc, "run_chain", extract)
    result = physical._extract(project, "unit", "container", "image", "process", {"styles": ["s"]})
    assert result["status"] == "FAIL" and "RCX_DEVICE_RECORD_MISSING" in result["detail"]
