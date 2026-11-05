"""Read and project the Router's declared input metadata."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml


def input_contract(step: Dict[str, Any], kind: str = "structured") -> Dict[str, Any]:
    """Project the Step 1/2 source alternative declared in the canonical YAML."""
    canonical = step.get("_structured_input_contract")
    if canonical is not None:
        step = dict(step, **canonical)
        step.pop("_structured_input_contract")
    if kind == "structured":
        return step
    alternative = (step.get("input_contracts") or {}).get(kind)
    if not isinstance(alternative, dict):
        return step
    # A source alternative also owns the consumers of that source. Keeping
    # a structured-only gate after replacing its inputs makes it impossible
    # for a complete original-source product to be accepted.
    fields = ("required_inputs", "blocks_on", "gate", "required_outputs")
    overrides = {key: alternative[key] for key in fields if key in alternative}
    return dict(step, _structured_input_contract={key: step.get(key) for key in overrides},
                **overrides)


def load_flow(flow_def: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        import _flow_yaml
        doc = _flow_yaml.load(flow_def, encoding="utf-8")
    except (OSError, yaml.YAMLError) as exc:
        return [], f"flow unreadable: {exc}"
    steps = (doc or {}).get("steps") or []
    if not isinstance(steps, list) or not steps:
        return [], "flow declares no steps"
    return steps, None


def project_input_contract(project: Path, step: Dict[str, Any]) -> Dict[str, Any]:
    import _path_layout
    return input_contract(step, _path_layout.rtl_input(project))


def expand(entry: Dict[str, Any],
           by_id: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(producer, declared-output-spec) pairs this entry requires."""
    src = str(entry["from"])
    if src == "external":
        p = entry.get("path")
        return [("external", p)] if p else []
    if entry.get("outputs") == "all":
        return [(src, spec) for spec in (by_id[src].get("required_outputs") or [])]
    return [(src, entry["path"])]
