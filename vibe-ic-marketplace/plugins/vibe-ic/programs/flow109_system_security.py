"""Read native system scenarios, unbounded formal proofs and implementation structure."""
from __future__ import annotations
import json
from pathlib import Path
import re
import uuid

from _atomic_artefact import write_json

SECURITY_IDS = (
    "opentitan_aes.shadowed_controls",
    "opentitan_aes.sparse_fsm_alert",
    "opentitan_aes.lifecycle_escalation",
)
SECURITY_TASKS = {
    SECURITY_IDS[0]: "shadowed_controls",
    SECURITY_IDS[1]: "sparse_fsm_alert",
    SECURITY_IDS[2]: "lifecycle_escalation",
}


class Refusal(RuntimeError):
    def __init__(self, code: str, detail: str, *, status: str = "NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal("FLOW109_SECURITY_INPUT_ABSENT_OR_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise Refusal("FLOW109_SECURITY_INPUT_INVALID", str(path))
    return value


def _bound(project, item, label):
    raw = item.get('path') if isinstance(item, dict) else item
    if not isinstance(raw, str) or not raw:
        raise Refusal('NATIVE_SECURITY_INPUT_ABSENT', label)
    path = Path(raw)
    path = (path if path.is_absolute() else project / path).resolve()
    if not path.is_file():
        raise Refusal('NATIVE_SECURITY_INPUT_ABSENT', label)
    return path, str(path)


def _current_ref(project, ref, label, inputs):
    path, _ = _bound(project, ref, label)
    inputs[str(path)] = str(path)
    return path, _read(path)


def _case_map(record: dict) -> dict[str, dict]:
    rows = record.get("cases")
    if not isinstance(rows, list):
        raise Refusal("D16_NATIVE_RECORD_INVALID", "cases")
    out = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise Refusal("D16_NATIVE_RECORD_INVALID", "case row")
        if row["name"] in out:
            raise Refusal("D16_NATIVE_RECORD_INVALID", "duplicate case")
        out[row["name"]] = row
    return out


def _d16(project: Path, manifest: dict, inputs: dict[str, str]) -> dict:
    _path, record = _current_ref(project, manifest.get("full_stack_record"),
                                 "full_stack_record", inputs)
    if (record.get("program") != "full_stack_functional_tb"
            or record.get("schema") != "vibeic.full_stack_functional.v1"):
        raise Refusal("D16_NATIVE_PRODUCER_MISMATCH", "canonical producer required")
    if record.get("verdict") == "FAIL":
        raise Refusal("D16_MEASURED_FAILURE", str(record.get("reason")), status="FAIL")
    if record.get("verdict") != "PASS":
        raise Refusal("D16_NATIVE_NOT_MEASURED", str(record.get("reason")))
    top = record.get("full_stack_top") or {}
    if not top.get("module") or top.get("refusal"):
        raise Refusal("D16_FULL_STACK_TOP_UNBOUND", str(top.get("refusal")))
    for population in ("sources", "models"):
        rows = record.get(population)
        if not isinstance(rows, list) or not rows:
            raise Refusal("D16_NATIVE_POPULATION_ABSENT", population)
        for item in rows:
            path, _ = _bound(project, item, population)
            inputs[str(path)] = str(path)
    required = manifest.get("required_scenarios")
    if not isinstance(required, list) or not required:
        raise Refusal("D16_REQUIRED_SCENARIOS_EMPTY", "nonempty source-declared population required")
    cases = _case_map(record)
    covered = []
    for item in required:
        if (not isinstance(item, dict) or set(item) != {"id", "case"}
                or not all(isinstance(item.get(k), str) and item[k] for k in ("id", "case"))):
            raise Refusal("D16_REQUIRED_SCENARIO_INVALID", str(item))
        case = cases.get(item["case"])
        disposition = (case or {}).get("step5_disposition") or {}
        accepted = ((case or {}).get("state") == "passed"
                    or (disposition.get("disposition") == "isa_credited"
                        and disposition.get("blocking") is False))
        if not accepted:
            raise Refusal("D16_REQUIRED_SCENARIO_NOT_PASSED", item["id"])
        for key in ("tb", "run_log"):
            rel = case.get(key)
            if rel:
                path, current = _bound(project, rel,
                                       f"{item['id']}.{key}")
                inputs[str(path)] = current
        covered.append({"id": item["id"], "case": item["case"]})
    return {"required_fullchip_scenarios": covered,
            "boot_workload_protocol_errors": 0,
            "blocking_system_scenario_failures": 0,
            "system_signoff_required_scenarios": covered,
            "producer": "full_stack_functional_tb"}


def _formal_result(project: Path, binding: object, obligation: str,
                   inputs: dict[str, str]) -> dict:
    if not isinstance(binding, dict) or set(binding) != {"result", "task"}:
        raise Refusal("D17_FORMAL_BINDING_INVALID", obligation)
    task = binding.get("task")
    if task != SECURITY_TASKS[obligation]:
        raise Refusal("D17_FORMAL_REQUIREMENT_MISMATCH", obligation)
    result_path, result = _current_ref(project, binding.get("result"), obligation, inputs)
    if result.get("program") != "formal_property_run":
        raise Refusal("D17_FORMAL_PRODUCER_MISMATCH", obligation)
    properties = result.get("properties")
    failed_tasks = ([str(row.get("task")) for row in properties
                     if isinstance(row, dict) and row.get("status") == "FAIL"]
                    if isinstance(properties, list) else [])
    if (result.get("verdict") == "FAIL" or int(result.get("failed", 0) or 0) > 0
            or failed_tasks):
        raise Refusal("D17_SECURITY_COUNTEREXAMPLE",
                      ",".join(failed_tasks) or obligation, status="FAIL")
    selected = ([row for row in properties
                 if isinstance(row, dict) and row.get("task") == task]
                if isinstance(properties, list) else [])
    if len(selected) != 1:
        raise Refusal("D17_FORMAL_REQUIREMENT_MISMATCH", obligation)
    selected = selected[0]
    if (result.get("verdict") != "PASS" or result.get("all_proved") is not True
            or selected.get("status") != "PASS"):
        raise Refusal("D17_SECURITY_PROOF_INCOMPLETE", obligation)
    if not result.get("unbounded_proved") or selected.get("bound") != "unbounded":
        raise Refusal("D17_SECURITY_PROOF_BOUNDED_ONLY", obligation)
    for key in ("sby", "evidence"):
        rel = result.get(key)
        if not isinstance(rel, str):
            raise Refusal("D17_FORMAL_EVIDENCE_UNBOUND", f"{obligation}.{key}")
        path = project / rel
        if path.is_symlink() or not path.is_file():
            raise Refusal("D17_FORMAL_EVIDENCE_STALE", f"{obligation}.{key}")
        inputs[str(path.resolve())] = str(path)
    proof_files = (result.get("proof_inputs") or {}).get("files")
    if not isinstance(proof_files, dict) or not proof_files:
        raise Refusal("D17_FORMAL_INPUTS_UNBOUND", obligation)
    assertions = set()
    for name, digest in proof_files.items():
        if (not isinstance(name, str) or Path(name).is_absolute() or Path(name).name != name
               ):
            raise Refusal("D17_FORMAL_INPUTS_UNBOUND", f"{obligation}.{name}")
        path = result_path.parent / name
        if path.is_symlink() or not path.is_file():
            raise Refusal("D17_FORMAL_INPUTS_STALE", f"{obligation}.{name}")
        inputs[str(path.resolve())] = digest
        assertions.update(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*assert\s*\(",
                                     path.read_text(errors="replace")))
    return {"id": obligation, "proof_strength": result.get("proof_strength"),
            "task": task, "property": selected, "assertions": sorted(assertions),
            "property_contract": result.get("property_contract"),
            "property_denominator": result.get("property_denominator"),
            "authored_property_count": result.get("authored_property_count"),
            "unresolved_obligations": result.get("unresolved_obligations")}


def _d17(project: Path, manifest: dict, inputs: dict[str, str]) -> dict:
    # Retained tasks are component evidence, never the requirement denominator.
    required = manifest.get("required_security_requirements")
    proofs = manifest.get("formal_results")
    if required != list(SECURITY_IDS) or not isinstance(proofs, dict) or set(proofs) != set(SECURITY_IDS):
        raise Refusal("D17_SECURITY_DENOMINATOR_INVALID", "retained proof task identity")
    covered = [_formal_result(project, proofs[item], item, inputs) for item in SECURITY_IDS]
    if not manifest.get("property_contract"):
        raise Refusal("D17_PROPERTY_DENOMINATOR_MISSING", "complete document population required")
    _contract_path, contract = _current_ref(project, manifest["property_contract"],
                                             "complete property contract", inputs)
    _proof_path, proof_contract = _current_ref(project, manifest.get("component_contract"),
                                                "retained proof contract", inputs)
    for proof in covered:
        if ((project / str(proof["property_contract"])).resolve() != _proof_path):
            raise Refusal("D17_PROPERTY_DENOMINATOR_UNPROVEN", "retained proof contract changed")
    catalogue, digest = _bound(project, contract.get("catalogue_source"), "security catalogue")
    if not catalogue.is_relative_to((project / "input/docs").resolve()):
        raise Refusal("D17_REQUIREMENT_SOURCE_MISMATCH", "design documents required")
    inputs[str(catalogue)] = digest
    catalogue_ids = set(re.findall(
        r"(?m)^\|\s*([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)\s*\|", catalogue.read_text()))
    requirements = contract.get("required_security_requirements")
    if (not isinstance(requirements, list) or not requirements
            or any(not isinstance(row, dict) or not row.get("id") for row in requirements)):
        raise Refusal("D17_SECURITY_DENOMINATOR_INVALID", "required source population absent")
    ids = [row["id"] for row in requirements]
    if not catalogue_ids or len(set(ids)) != len(ids) or catalogue_ids - set(ids):
        raise Refusal("D17_SOURCE_REQUIREMENT_POPULATION_INCOMPLETE",
                      str(sorted(catalogue_ids - set(ids))))
    population = []
    by_id = {proof["id"]: proof for proof in covered}
    for requirement in requirements:
        citations = requirement.get("sources")
        if not isinstance(citations, list) or not citations:
            raise Refusal("D17_REQUIREMENT_SOURCE_MISMATCH", requirement["id"])
        for source in citations:
            path, digest = _bound(project, source.get("file"), "requirement source")
            start, end = source.get("line_start"), source.get("line_end")
            lines = path.read_text().splitlines()
            if (not path.is_relative_to((project / "input/docs").resolve())
                    or type(start) is not int or type(end) is not int
                    or not 1 <= start <= end <= len(lines)
                    or "\n".join(lines[start - 1:end]) != source.get("excerpt")):
                raise Refusal("D17_REQUIREMENT_SOURCE_MISMATCH", requirement["id"])
            inputs[str(path)] = digest
        binding = requirement.get("proof_binding")
        proof = by_id.get(binding.get("legacy_id")) if isinstance(binding, dict) else None
        proved = (proof is not None and binding.get("task") == proof["task"]
                  and isinstance(binding.get("properties"), list) and binding["properties"]
                  and set(binding["properties"]).issubset(proof["assertions"]))
        population.append({**requirement, "status": "PROVED" if proved else "NOT_MEASURED"})
    unproved = [row for row in population if row["status"] != "PROVED"]
    return {"threat_requirements_coverage": covered,
            "required_security_properties": population,
            "required_requirement_count": len(population),
            "proved_requirement_count": len(population) - len(unproved),
            "unproved_requirement_count": len(unproved),
            "unproved_security_requirements": unproved,
            "security_counterexample_failures": 0,
            "security_metric_targets": {"status": "NOT_MEASURED",
                "reason": "no source-declared quantitative security bounds; physical threats excluded"},
            "limitations": ["retained three-task component evidence is not complete AES security coverage",
                            "no conditional or physical property is waived by this reader"]}


def _implemented_security(netlist_path, top):
    text = netlist_path.read_text(errors="replace")
    if not isinstance(top, str) or not re.search(rf"\bmodule\s+{re.escape(top)}\s*\(", text):
        raise Refusal("D73_ADOPTED_NETLIST_TOP_MISMATCH", str(top))
    required_patterns = {
        SECURITY_IDS[0]: (r"shadow_q", r"committed_q", r"err_(?:update|storage)"),
        SECURITY_IDS[1]: (r"aes_ctrl_cs|sparse", r"alert"),
        SECURITY_IDS[2]: (r"lc_escalate_en", r"alert_fatal"),
    }
    population = []
    for obligation, patterns in required_patterns.items():
        missing = [pattern for pattern in patterns if not re.search(pattern, text)]
        if missing:
            raise Refusal("D73_IMPLEMENTED_SECURITY_POPULATION_MISSING",
                          f"{obligation}: {missing}")
        population.append({"id": obligation, "patterns": list(patterns)})
    header = re.search(rf"\bmodule\s+{re.escape(top)}\s*\((.*?)\);", text, re.S)
    ports = header.group(1) if header else ""
    forbidden = re.findall(r"\b(?:scan|jtag|debug|test_en)[A-Za-z0-9_$]*\b", ports, re.I)
    if forbidden:
        raise Refusal("D73_TEST_DEBUG_ACCESS_EXPOSED", ",".join(sorted(set(forbidden))), status="FAIL")
    return {"final_security_requirements": population,
            "scan_debug_access_violations": 0,
            "final_analog_security_targets": {"status": "NOT_APPLICABLE",
                "reason": "digital AES supported subset"},
            "limitations": ["structural adopted-netlist population plus current D17 proofs only",
                            "physical side-channel and fault-injection signoff NOT_MEASURED"]}


def _d73(project, manifest, inputs):
    coverage = _d17(project, manifest, inputs)
    if coverage['unproved_requirement_count']:
        raise Refusal('D73_SECURITY_PROPERTIES_UNPROVED', str(coverage['unproved_requirement_count']))
    equivalence_path, equivalence = _current_ref(project, manifest.get('equivalence_result'),
                                                'native equivalence result', inputs)
    if equivalence.get('verdict') != 'PASS':
        raise Refusal('D73_EQUIVALENCE_NOT_MEASURED', str(equivalence_path),
                      status='FAIL' if equivalence.get('verdict') == 'FAIL' else 'NOT_MEASURED')
    netlist_path, _ = _bound(project, manifest.get('adopted_netlist'), 'implementation netlist')
    return _implemented_security(netlist_path, manifest.get('top'))


def execute(project, context):
    project = Path(project).resolve()
    row = str(context.get('step_id') or context.get('requested_step') or '')
    methods = {'D16': _d16, 'D17': _d17, 'D73': _d73}
    if row not in methods:
        raise ValueError('Choose native system scenarios, formal security or implemented security')
    inputs = {}
    try:
        metrics = methods[row](project, context, inputs)
        status = 'NOT_MEASURED' if metrics.get('unproved_requirement_count') else 'PASS'
        report = {'component_status': status, 'metrics': metrics, 'input_paths': sorted(inputs)}
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        report = {'component_status': getattr(exc, 'status', 'NOT_MEASURED'), 'reason': str(exc)}
    write_json(project / 'reports/native_tools/system_security' / (row + '.json'), report)
    return report
