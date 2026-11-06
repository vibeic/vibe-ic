"""Native provider measurements do not require stream-admission passports."""
import hashlib
import json
from pathlib import Path

import pytest

import die_finishing_gen as finishing
import foundry_handoff_package_check as package
from test_provider_die_assembly import bond_geometry, bond_assembly


def publish(assembly):
    project, instruction, _gds, operator, seal, destination = assembly
    return finishing.publish_provider_release(
        project, destination, source_project=project,
        instruction=instruction, precheck=operator, finishing=seal)


def test_native_provider_geometry_needs_no_source_admission(bond_assembly):
    project, _instruction, _gds, _operator, _seal, destination = bond_assembly
    result = publish(bond_assembly)
    edge = result["basis"]["bond_pad_edge_distance"]
    assert edge["opening_count"] == 6
    assert edge["distances_um"] == {"left": 20, "bottom": 30, "right": 100, "top": 200}
    assert edge["verdict"] == "MANUAL_REVIEW"
    assert result["basis"]["platform_accepted"] is False
    assert result["basis"]["provider_precheck"]["accepted"] is False
    assert "source_admission" not in result["basis"]["files"]
    assert not (project / "reports/phase3/gds_admission.json").exists()
    assert finishing.read_admitted_release(project, destination)["gds"] == result["gds"]


def test_old_hash_metadata_cannot_refuse_native_provider_results(bond_assembly):
    project, _instruction, _gds, operator, _seal, destination = bond_assembly
    report = json.loads(operator.read_text())
    report["input_unchanged"] = False
    report["input"]["sha256"] = "old-input-metadata"
    report["output"]["sha256"] = "old-output-metadata"
    for step in report["steps"]:
        step["state_out"]["sha256"] = "old-state-metadata"
    operator.write_text(json.dumps(report))
    result = publish(bond_assembly)
    assert result["gds"].is_file()
    assert result["sha256"] == hashlib.sha256(result["gds"].read_bytes()).hexdigest()
    retained = json.loads(destination.read_text())
    retained["basis"]["provider_precheck"]["layout_sha256"] = "old-layout-metadata"
    retained["basis"]["provider_precheck"]["source"]["sha256"] = "old-report-metadata"
    destination.write_text(json.dumps(retained))
    selected = package.selected_provider_precheck(finishing.read_admitted_release(project, destination))
    assert selected["technical_precheck_status"] == "PASS"
    assert selected["status"] == "NOT_SUBMITTED"
    assert selected["accepted"] is False


@pytest.mark.parametrize("case", ["native_failure", "missing_step", "missing_state", "missing_output"])
def test_native_provider_failure_or_missing_result_stays_open(bond_assembly, case):
    _project, _instruction, _gds, operator, _seal, destination = bond_assembly
    report = json.loads(operator.read_text())
    if case == "native_failure":
        report.update(returncode=7, verdict="FAIL")
    elif case == "missing_step":
        report["steps"].pop()
    elif case == "missing_state":
        Path(report["steps"][0]["state_out"]["path"]).unlink()
    else:
        report["output"]["path"] = str(operator.with_name("missing.gds"))
    operator.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="precheck|step|unreadable"):
        publish(bond_assembly)
    assert not destination.exists()


@pytest.mark.parametrize("change", [
    {"encroaching_polygons": 1}, {"state": "NOT_MEASURED"}, {"population_empty": True},
])
def test_original_seal_clearance_requirement_is_preserved(bond_assembly, change):
    _project, _instruction, _gds, _operator, seal, destination = bond_assembly
    report = json.loads(seal.read_text())
    report["seal_ring"]["core_clearance"].update(change)
    seal.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="measured clear seal-ring"):
        publish(bond_assembly)
    assert not destination.exists()


def test_provider_reader_observes_native_failure_after_publication(bond_assembly):
    project, _instruction, _gds, operator, _seal, destination = bond_assembly
    publish(bond_assembly)
    report = json.loads(operator.read_text())
    report.update(returncode=1, verdict="FAIL")
    operator.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="precheck failed"):
        finishing.read_admitted_release(project, destination)


def test_selected_provider_reader_keeps_native_failure(bond_assembly):
    _project, _instruction, _gds, operator, _seal, _destination = bond_assembly
    assembly = publish(bond_assembly)
    report = json.loads(operator.read_text())
    report.update(returncode=1, verdict="FAIL")
    operator.write_text(json.dumps(report))
    Path(assembly["basis"]["files"]["finished_def"]["path"]).unlink()
    result = package.selected_provider_precheck(assembly)
    assert result["technical_precheck_status"] == "FAIL"
    assert result["status"] == "NOT_MEASURED"
    assert result["accepted"] is False


@pytest.mark.parametrize("steps,rc,expected", [(16, 0, "PASS"), (15, 0, "FAIL"), (16, 7, "FAIL")])
def test_operator_adapter_uses_native_completion_without_input_hash_gate(tmp_path, steps, rc, expected):
    from types import SimpleNamespace
    import wafer_space_precheck as adapter
    source = tmp_path / "operator"
    source.mkdir()
    (source / "precheck.py").write_text(
        "from pathlib import Path\nfrom types import SimpleNamespace\n"
        "class PrecheckFlow:\n    Steps = [SimpleNamespace(id=str(i)) for i in range(16)]\n"
        "def main(input_path, output_path, top, directory, assigned_id, cob, slot, threads, workers, run_tag, *rest):\n"
        "    Path(input_path).write_bytes(b'operator updated its working input')\n"
        "    Path(output_path).write_bytes(b'operator output')\n"
        f"    for i in range({steps}):\n"
        "        folder = Path(directory) / 'runs' / run_tag / f'{i + 1:02d}-step'\n"
        "        folder.mkdir(parents=True)\n"
        "        (folder / 'state_out.json').write_text('{}')\n"
        f"    raise SystemExit({rc})\n")
    incoming = tmp_path / "input.gds"
    incoming.write_bytes(b"original working input")
    state = tmp_path / "state.json"
    state.write_text("{}")
    args = SimpleNamespace(official_source=str(source), input=str(incoming),
        output=str(tmp_path / "output.gds"), top="neutral", dir=str(tmp_path),
        id=None, cob=False, slot="1x1", threads=2, workers=1, run_tag="native",
        with_initial_state=str(state), record=str(tmp_path / "result.json"))
    report = adapter.run(args)
    assert report["verdict"] == expected
    assert report["returncode"] == rc
    assert len(report["steps"]) == steps
    assert "input_unchanged" not in report
