"""Normal L9 producer citations are consumed by the unchanged source reader."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D
from _qualified_by import basis_refusal


TEXT = ("Module name:\nneutral_control\nInput ports:\n"
        "clk: Clock signal.\nreset: Synchronous active-high reset signal.\n"
        "data_i: 1-bit input data.\nOutput ports:\n"
        "data_o: 1-bit output data.\n")


def _sources(project):
    for rel in ("input/docs/contract.md", "phase1/input_doc/contract.txt"):
        source = project / rel
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(TEXT)


def _produce(project):
    D.gen_l9_integration_spec(project, {"contract.md": TEXT, "contract.txt": TEXT}, {})
    D._post_emit_mirror_clock_resets_to_l9_v1_6_311(project)
    return json.loads((project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())


def test_normal_l9_mirror_and_original_citations_are_real_current_inputs(tmp_path):
    _sources(tmp_path)
    row = _produce(tmp_path)["reset_domains"][0]
    assert (row["sync"], row["polarity"]) == ("synchronous", "active_high")
    for field in ("sync", "polarity"):
        basis = row["semantic_provenance"][field]["basis"]
        assert {entry["file"] for entry in basis} == {
            "input/docs/contract.md", "phase1/input_doc/contract.txt"}
        assert basis_refusal(tmp_path, basis) is None
        assert all(entry["sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
                   for entry in basis)


def test_changed_original_is_rejected_by_unchanged_consumer(tmp_path):
    _sources(tmp_path)
    basis = _produce(tmp_path)["reset_domains"][0]["semantic_provenance"]["sync"]["basis"]
    (tmp_path / "input/docs/contract.md").write_text(TEXT.replace("Synchronous", "Asynchronous"))
    assert basis_refusal(tmp_path, basis) is not None


def test_missing_citation_is_not_admitted_by_existing_consumer(tmp_path):
    _sources(tmp_path)
    basis = _produce(tmp_path)["reset_domains"][0]["semantic_provenance"]["sync"]["basis"]
    for entry in basis:
        if entry["file"] == "phase1/input_doc/contract.txt":
            entry["file"] = "input/docs/contract.txt"
    assert basis_refusal(tmp_path, basis) is not None


def test_late_reset_emitter_uses_the_same_real_input_paths(tmp_path):
    _sources(tmp_path)
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "ports": [{"name": "reset", "direction": "input", "width": 1}]}))
    D._post_emit_mirror_clock_resets_to_l9_v1_6_311(tmp_path)
    row = json.loads((docs / "L9_INTEGRATION_SPEC.json").read_text())["reset_domains"][0]
    assert basis_refusal(tmp_path, row["semantic_provenance"]["sync"]["basis"]) is None
    assert {entry["file"] for entry in row["semantic_provenance"]["sync"]["basis"]} == {
        "input/docs/contract.md", "phase1/input_doc/contract.txt"}
