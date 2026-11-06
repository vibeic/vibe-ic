"""Run native fixture commands with the existing design input facts."""

import json
from pathlib import Path

import yaml





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
