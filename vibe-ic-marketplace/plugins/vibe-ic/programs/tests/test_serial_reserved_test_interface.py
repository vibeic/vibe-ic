"""D09 producer controls; pending connectivity never grants a native row PASS."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from collections import Counter

import pytest

PROGRAMS = Path(os.environ.get(
    "FLOW109_SOURCE_PROGRAMS", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(PROGRAMS))
import serial_parallel_mul_synth as producer


@pytest.fixture
def reviewed_project():
    value = os.environ.get("FLOW109_D09_REVIEWED_PROJECT")
    if not value:
        pytest.skip("current independently reviewed D01/D09 source required")
    return Path(value)


def _native_project(reviewed_project, tmp_path, spec, rtl):
    import p0_tool_frontend_check as frontend

    project = tmp_path / "model"
    source = project / "phase2/stage1/rtl" / (spec["top"] + ".v")
    source.parent.mkdir(parents=True)
    source.write_text(rtl)
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    shutil.copy2(reviewed_project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
                 docs / "L9_INTEGRATION_SPEC.json")
    native = frontend.check(project)
    assert native["passed"] is True, native
    graph = json.loads((project / frontend.RTL_ELAB_REL).read_text())
    return project, graph


def _hygiene(project, tmp_path):
    result = subprocess.run([
        sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"),
        "--project", str(project), "--json", str(tmp_path / "hygiene.json"), "--strict",
    ], capture_output=True, text=True)
    (tmp_path / "hygiene.stdout").write_text(result.stdout)
    (tmp_path / "hygiene.stderr").write_text(result.stderr)
    return result


def test_current_authority_materializes_original_product_observation(reviewed_project, tmp_path):
    import fault_scan_chain_insert as scan
    import flow109_metric_acceptance as metrics
    import p0_tool_frontend_check as frontend

    binding, problems = scan.load_d09_dft_contract(reviewed_project)
    assert binding is not None and not problems
    spec, reason = producer.extract_serial_parallel_mul_spec(
        reviewed_project, "digital_arithmetic_primitive")
    assert spec is not None, reason
    rtl = producer.emit_rtl(spec)
    project, graph = _native_project(reviewed_project, tmp_path, spec, rtl)
    ports = metrics.dft_port_consistency(binding, graph, spec["top"])
    (tmp_path / "port-consumer.json").write_text(json.dumps(ports, indent=2))
    assert ports["status"] == "PASS", ports
    baseline = (reviewed_project / "phase2/stage1/rtl" / (spec["top"] + ".v")).read_text()
    endpoint = binding["intent"]["test_port_def"]["scan_out"]["public"]
    addition = f"    assign {endpoint} = pr;\n"
    assert rtl.count(addition) == 1
    assert rtl.replace(addition, "")[rtl.index("    reg  ["):] == baseline[baseline.index("    reg  ["):]
    original = json.loads((reviewed_project / frontend.RTL_ELAB_REL).read_text())
    before = original["modules"][spec["top"]]
    after = graph["modules"][spec["top"]]
    added = set(after["cells"]) - set(before["cells"])
    assert len(added) == 1
    observed = after["cells"][added.pop()]
    assert observed["type"] == "$buf"
    assert int(observed["parameters"]["WIDTH"], 2) == 1
    assert observed["port_directions"] == {"A": "input", "Y": "output"}
    assert observed["connections"] == {
        "A": after["netnames"]["pr"]["bits"], "Y": after["ports"][endpoint]["bits"]}
    assert set(before["cells"]).issubset(after["cells"])
    bit_map = {value: value for value in ("0", "1", "x", "z")}
    for name, net in before["netnames"].items():
        actual = after["netnames"][name]
        assert len(net["bits"]) == len(actual["bits"])
        for old, new in zip(net["bits"], actual["bits"]):
            assert bit_map.setdefault(old, new) == new
    assert len(set(bit_map.values())) == len(bit_map)
    for name, cell in before["cells"].items():
        for field in ("type", "parameters", "port_directions"):
            assert after["cells"][name][field] == cell[field]
        assert after["cells"][name]["connections"] == {
            port: [bit_map[bit] for bit in bits]
            for port, bits in cell["connections"].items()}
    for name, port in before["ports"].items():
        assert after["ports"][name] == {
            **port, "bits": [bit_map[bit] for bit in port["bits"]]}
    assert Counter(c["type"] for c in after["cells"].values()) == (
        Counter(c["type"] for c in before["cells"].values()) + Counter({"$buf": 1}))
    for register in ("s", "c", "yr", "pr"):
        assert len(after["netnames"][register]["bits"]) == len(before["netnames"][register]["bits"])
    for module in (before, after):
        functional_driver = [cell for cell in module["cells"].values()
                             if cell["type"] == "$buf" and cell["connections"] == {
                                 "A": module["netnames"]["pr"]["bits"],
                                 "Y": module["ports"][spec["serial_out"]]["bits"]}]
        assert len(functional_driver) == 1
    result = _hygiene(project, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mutation", ("absent", "input"))
def test_actual_native_port_consumer_rejects_missing_or_wrong_direction(
        reviewed_project, tmp_path, mutation):
    import fault_scan_chain_insert as scan
    import flow109_metric_acceptance as metrics

    spec, reason = producer.extract_serial_parallel_mul_spec(
        reviewed_project, "digital_arithmetic_primitive")
    assert spec is not None, reason
    binding, problems = scan.load_d09_dft_contract(reviewed_project)
    assert binding is not None and not problems
    endpoint = binding["intent"]["test_port_def"]["scan_out"]["public"]
    rtl = producer.emit_rtl(spec)
    declaration = f",\n    output wire            {endpoint}"
    assert declaration in rtl
    rtl = rtl.replace(f"    assign {endpoint} = pr;\n", "")
    rtl = rtl.replace(declaration, "" if mutation == "absent" else
                      f",\n    input wire            {endpoint}")
    _project, graph = _native_project(reviewed_project, tmp_path, spec, rtl)
    actual = metrics.dft_port_consistency(binding, graph, spec["top"])
    (tmp_path / "port-consumer.json").write_text(json.dumps(actual, indent=2))
    assert actual["status"] == "FAIL", actual
    assert actual["mismatches"], actual


def test_undriven_functional_output_remains_native_hygiene_failure(reviewed_project, tmp_path):
    spec, reason = producer.extract_serial_parallel_mul_spec(
        reviewed_project, "digital_arithmetic_primitive")
    assert spec is not None, reason
    rtl = producer.emit_rtl(spec)
    assignment = f"    assign {spec['serial_out']} = pr;\n"
    assert assignment in rtl
    project, _graph = _native_project(
        reviewed_project, tmp_path, spec, rtl.replace(assignment, ""))
    result = _hygiene(project, tmp_path)
    assert result.returncode == 1
    assert "undriven-output-port" in result.stdout
    logs = list(tmp_path.glob("native-elaboration-*/native.log"))
    assert logs and any("ERROR: Found" in path.read_text() for path in logs)


@pytest.mark.parametrize("register", ("c[0]", "1'b0"))
def test_arbitrary_or_constant_observation_is_refused(reviewed_project, register):
    import fault_scan_chain_insert as scan

    spec, reason = producer.extract_serial_parallel_mul_spec(
        reviewed_project, "digital_arithmetic_primitive")
    assert spec is not None, reason
    binding, problems = scan.load_d09_dft_contract(reviewed_project)
    assert binding is not None and not problems
    endpoint = binding["intent"]["test_port_def"]["scan_out"]["public"]
    spec["preinsert_test_observation"] = {
        "port": endpoint, "register": register, "purpose": "pre_insertion_observation"}
    with pytest.raises(ValueError, match="unapproved pre-insertion product observation"):
        producer.emit_rtl(spec)


def test_unproven_test_intent_does_not_get_silently_dropped(reviewed_project, tmp_path):
    project = tmp_path / "unproven"
    shutil.copytree(reviewed_project / "phase1/generated_docs", project / "phase1/generated_docs")
    shutil.copytree(reviewed_project / "input/docs", project / "input/docs")
    (project / "plugin_output").mkdir()
    original = json.loads((reviewed_project / "plugin_output/declaration.json").read_text())
    (project / "plugin_output/declaration.json").write_text(json.dumps(original))
    # No publication, producer report or expert receipt is invented/copied.
    spec, reason = producer.extract_serial_parallel_mul_spec(
        project, "digital_arithmetic_primitive")
    assert spec is None
    assert "DFT interface authority is unavailable" in reason


def test_unplanned_functional_template_bytes_remain_exact(reviewed_project):
    spec, reason = producer.extract_serial_parallel_mul_spec(
        reviewed_project, "digital_arithmetic_primitive")
    assert spec is not None, reason
    # Renderer compatibility control only; this does not alter the owner's
    # decision or grant the scan-required product a no-scan disposition.
    spec.pop("reserved_test_ports", None)
    spec.pop("dft_intent_binding", None)
    spec.pop("preinsert_test_observation", None)
    actual = producer.emit_rtl(spec).encode()
    original = reviewed_project / "phase2/stage1/rtl" / (spec["top"] + ".v")
    assert hashlib.sha256(actual).digest() == hashlib.sha256(original.read_bytes()).digest()
