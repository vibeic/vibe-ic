"""Source -> real package probe -> unchanged L1 -> actionable width consumer.

The source and package are invented neutral inputs, not design RTL. All
consumer controls start from the same genuinely admitted native publication.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import interface_bindings as binding
import l1_pin_bus_width_actionable_check as gate
import phase1_doc_one_shot_runner as docs

FIXTURE = Path(__file__).parent / "fixtures/phase1_local/neutral_bound_type_width/neutral_bound_type_width.md"
TOOL = pytest.mark.skipif(not (os.environ.get("EDA_CONTAINER") and os.environ.get("VIBEIC_EDA_IMAGE")),
                          reason="real existing pinned EDA container required")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_project(tmp_path):
    root = Path(os.environ.get("VIBEIC_INTERFACE_TEST_ROOT", tmp_path))
    root.mkdir(parents=True, exist_ok=True)
    project = Path(tempfile.mkdtemp(prefix="bound-width-", dir=root))
    source = project / "input/docs/interfaces.md"
    source.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE, source)
    package = project / binding.CONTEXT / "types.sv"
    package.parent.mkdir(parents=True)
    package.write_text("package neutral_pkg;\n  typedef struct packed { logic valid; logic [7:0] data; } payload_t;\nendpackage\n")
    extracted = {source.name: source.read_text()}
    l1 = Path(docs.gen_l1_datasheet(project, extracted).path)
    l9 = Path(docs.gen_l9_integration_spec(project, extracted, {}).path)
    contract = binding.input_contract(project, json.loads(l9.read_text()))
    contract["context"] = {
        "image": os.environ["VIBEIC_EDA_IMAGE"], "revision": "neutral-v1",
        "files": {package.relative_to(project).as_posix(): sha(package)},
        "compile_order": [package.relative_to(project).as_posix()],
        "include_dirs": [], "defines": [], "parameters": {}}
    lines = source.read_text().splitlines()
    contract["physical_ports"] = []
    for name, direction, typ, width in [("payload_i", "input", "neutral_pkg::payload_t", 9),
                                         ("ready_o", "output", "logic", 1)]:
        line = next(i for i, text in enumerate(lines, 1) if f"| {name} |" in text)
        contract["physical_ports"].append({"name": name, "direction": direction,
            "type_ref": typ, "width": width,
            "basis": [{"file": "input/docs/interfaces.md", "line": line, "quote": lines[line-1]}]})
    author = project / binding.INPUT
    author.write_text(json.dumps(contract))
    return project, source, extracted, l1, l9, author, package


@TOOL
def test_real_binding_is_actionable_without_overwriting_l1(tmp_path):
    project, source, extracted, l1, l9, author, package = make_project(tmp_path)
    raw = l1.read_bytes()
    assert gate.evaluate(project)["rc"] == 1
    docs.gen_l9_integration_spec(project, extracted, {})
    assert l1.read_bytes() == raw
    before = {str(p.relative_to(project)): sha(p) for p in project.rglob("*") if p.is_file()}
    result = gate.evaluate(project)
    assert result["rc"] == 0, result
    assert result["bus_confirmed"] == 1
    assert l1.read_bytes() == raw
    assert {str(p.relative_to(project)): sha(p) for p in project.rglob("*") if p.is_file()} == before
    print("NEUTRAL_PROJECT=" + str(project))


@TOOL
@pytest.mark.parametrize("mutation", [
    "wrong_published_width", "wrong_alias_width", "wrong_measurement", "missing_proof",
    "stale_context", "stale_source", "stale_author", "missing_author", "missing_ledger",
    "wrong_l1_width", "stale_execution", "stale_measurements_log", "stale_probe",
    "failed_elaboration", "failed_simulation", "out_of_range_index",
    "coordinated_width_forgery"])
def test_current_binding_controls_refuse(tmp_path, mutation):
    project, source, extracted, l1, l9, author, package = make_project(tmp_path)
    if mutation == "out_of_range_index":
        source.write_text(source.read_text().replace("payload_i[8:0]", "payload_i[9:0]"))
        extracted = {source.name: source.read_text()}
        value = json.loads(author.read_text())
        value["input_files"]["input/docs/interfaces.md"] = sha(source)
        author.write_text(json.dumps(value))
    docs.gen_l9_integration_spec(project, extracted, {})
    value = json.loads(l9.read_text())
    proof_path = project / binding.REPORT / "proof.json"
    if mutation == "wrong_published_width":
        for key in binding.PORT_KEYS:
            next(row for row in value[key] if row["name"] == "payload_i")["width"] = 8
    elif mutation == "wrong_alias_width":
        value["ports"][0]["width"] = 8
    elif mutation == "wrong_measurement":
        value["interface_binding_authoring"]["measurement"]["measurements"][0]["width"] = 8
    elif mutation == "missing_proof": proof_path.unlink()
    elif mutation == "stale_context": package.write_text(package.read_text() + "// changed\n")
    elif mutation == "stale_source": source.write_text(source.read_text() + "\nchanged source\n")
    elif mutation == "stale_author": author.write_text(author.read_text() + " ")
    elif mutation == "missing_author": author.unlink()
    elif mutation == "missing_ledger": del value["interface_binding_authoring"]
    elif mutation == "wrong_l1_width":
        raw = json.loads(l1.read_text())
        next(row for row in raw["pin_table"] if row["name"] == "payload_i")["width"] = 16
        l1.write_text(json.dumps(raw))
    elif mutation == "stale_execution":
        path = project / binding.REPORT / "execution.json"
        execution = json.loads(path.read_text()); execution["semantic_proof"]["sha256"] = "0" * 64
        path.write_text(json.dumps(execution))
    elif mutation == "stale_measurements_log":
        path = project / binding.REPORT / "measurements.log"
        path.write_text(path.read_text().replace("|9", "|8"))
    elif mutation == "stale_probe":
        path = project / binding.REPORT / "type_probe.sv"; path.write_text(path.read_text() + "// changed\n")
    elif mutation in ("failed_elaboration", "failed_simulation"):
        path = project / binding.REPORT / "execution.json"
        execution = json.loads(path.read_text())
        execution["elaboration_rc" if mutation == "failed_elaboration" else "simulation_rc"] = 1
        path.write_text(json.dumps(execution))
    elif mutation == "coordinated_width_forgery":
        authored = json.loads(author.read_text()); authored["physical_ports"][0]["width"] = 10
        author.write_text(json.dumps(authored))
        ledger = value["interface_binding_authoring"]
        ledger["input_sha256"] = sha(author); ledger["physical_ports"][0]["width"] = 10
        proof = json.loads(proof_path.read_text())
        proof["author_input_sha256"] = sha(author); proof["measurements"][0]["width"] = 10
        proof_path.write_text(json.dumps(proof))
        ledger["measurement"] = proof; ledger["proof"]["sha256"] = sha(proof_path)
        path = project / binding.REPORT / "execution.json"
        execution = json.loads(path.read_text()); execution["author_input_sha256"] = sha(author)
        execution["semantic_proof"]["sha256"] = sha(proof_path)
        path.write_text(json.dumps(execution))
        for key in binding.PORT_KEYS:
            next(row for row in value[key] if row["name"] == "payload_i")["width"] = 10
    l9.write_text(json.dumps(value))
    result = gate.evaluate(project)
    assert result["rc"] == 1, result


@TOOL
@pytest.mark.parametrize("mutation", ["wrong_width", "unknown_type"])
def test_real_probe_refuses_unmeasured_claim(tmp_path, mutation):
    project, source, extracted, l1, l9, author, package = make_project(tmp_path)
    value = json.loads(author.read_text())
    if mutation == "wrong_width": value["physical_ports"][0]["width"] = 10
    else:
        package.write_text(package.read_text().replace("payload_t", "other_t"))
        value["context"]["files"][package.relative_to(project).as_posix()] = sha(package)
    author.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="fresh measured|tool refused"):
        docs.gen_l9_integration_spec(project, extracted, {})
    assert gate.evaluate(project)["rc"] == 1
