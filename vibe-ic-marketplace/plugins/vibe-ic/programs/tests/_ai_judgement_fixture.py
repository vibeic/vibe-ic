"""Sign a synthetic project's exact evidence for unrelated flow tests."""

import json
from pathlib import Path

import yaml

import ai_signed_judgement
import _delivery_route


def sign(project: Path, step_id: str) -> None:
    digest = ai_signed_judgement.evidence_sha256(project, step_id)
    assert digest, f"fixture has no Step {step_id} evidence to review"
    receipt = project / "reports/audit/ai_judgements" / f"{step_id}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "schema": ai_signed_judgement.SCHEMA,
        "step_id": step_id,
        "evidence_sha256": digest,
        "verdict": "PASS",
        "signed_by": "synthetic-fixture-reviewer",
        "judgement": "Reviewed the synthetic evidence staged by this test fixture.",
    }) + "\n")


def run_atomic_gate_with_expert_answer(cmd: list[str], run,
                                       project: Path, spec: Path,
                                       prompt: Path, *, prove_unsigned: bool = False,
                                       **kwargs):
    """Keep the original prompt and L9 facts around the native atomic command."""
    source = prompt.read_text()
    doc = yaml.safe_load(spec.read_text()) or {}
    # A `design:` spec carries the prompt as its description; a Shape-C spec
    # (`ic_name` / `L1` / `L9`) carries it as L1's description.
    if "design" in doc:
        assert doc["design"]["name"] == "TopModule"
        key = "design"
    else:
        assert doc["ic_name"] == "TopModule"
        key = "L1"
    doc.setdefault(key, {})["description"] = source
    spec.write_text(yaml.safe_dump(doc, sort_keys=False))
    first = run(cmd, **kwargs)
    l9 = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    assert l9.is_file(), (first.stdout or "") + (first.stderr or "")
    notes = json.loads(l9.read_text()).get("notes") or ""
    assert yaml.safe_load(notes)[key]["description"].strip() == source.strip(), (
        "Phase-1 input lost the fixture's design prompt")
    return first


def run_phase1_with_expert_answer(project: Path, argv: list[str], run,
                                  *, expected_tokens: list[str],
                                  field_path: str = "top_ports",
                                  layer: str = "L9_INTERFACE",
                                  requirement: str = "the design input's named facts appear in final L9",
                                  **kwargs):
    """Run the original Phase-1 command on the existing design fixture."""
    return run(argv, **kwargs)


def consume_phase1_expert_answer(project: Path, argv: list[str], run,
                                 *, expected_tokens: list[str],
                                 field_path: str = "top_ports",
                                 layer: str = "L9_INTERFACE",
                                 requirement: str = "the design input's named facts appear in final L9",
                                 first=None,
                                 **kwargs):
    """Deliver a fixture answer after an already executed Phase-1 first pass."""
    from _path_layout import report_path
    report = report_path(project, "phase1/expert_parse_track.json")
    assert report.is_file(), ((first.stdout or "") + (first.stderr or "")
                              if first else "first pass did not emit a report")
    assert json.loads(report.read_text())["ai_subtrack"]["status"] == "HANDOFF_EMITTED"
    answer = (report.parent / "expert_parse_track_pack"
              / "l_doc_expectations.json")
    assert answer.parent.is_dir(), "first pass did not emit the expert pack"
    answer.write_text(json.dumps({"expectations": [{
        "id": "fixture-declared-layer-fact",
        "layer": layer,
        "field_path": field_path,
        "requirement": requirement,
        "expected_tokens": expected_tokens,
        "evidence": ["the synthetic design input names these facts"],
    }]}))
    sign(project, "D1")
    return run([*argv, "--second-track-only"], **kwargs)
