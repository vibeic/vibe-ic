"""Source-bound adapters for the existing analog A1-A5/A9 producer sites.

These rows make the existing ordinary producer and gate path reachable from
the live fixed Controller. Adapter availability describes this source-bound
dispatcher only; it is not a claim that analog tools or hardware are installed.
"""
from __future__ import annotations

import json
import fnmatch
from pathlib import Path
import sys
from typing import Mapping

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_modes as em
import execution_adapters_analog as analog

PROGRAMS = Path(__file__).resolve().parent
WORKER = PROGRAMS / "execution_analog_front_worker.py"
OBSERVE_WORKER = PROGRAMS / "execution_analog_worker.py"
STEP_NAMES = {
    "A1": "A1_spec_extract", "A2": "A2_topology_select",
    "A3": "A3_netlist_gen", "A4": "A4_corner_sweep",
    "A5": "A5_layout", "A9": "A9_hw_verify",
}
FRONT_IDS = tuple(STEP_NAMES)


def _source_files(source_sha: str) -> dict[str, str]:
    from execution_provider_catalog import source_closure, implementation_closure
    interpreter = Path(sys.executable).resolve()
    initial = {
        Path(__file__).resolve(), WORKER.resolve(), OBSERVE_WORKER.resolve(),
        (PROGRAMS / "analog_one_shot_runner.py").resolve(),
        (PROGRAMS / "execution_policy.py").resolve(),
        (PROGRAMS / "execution_modes.py").resolve(),
        (PROGRAMS / "execution_adapters_analog.py").resolve(),
        (PROGRAMS / "execution_provider_catalog.py").resolve(),
        (PROGRAMS / "execution_synthesis_engines.py").resolve(),
        (PROGRAMS / "execution_step_protocol.py").resolve(),
        (PROGRAMS / "execution_source_snapshot.py").resolve(),
        (PROGRAMS / "execution_analog_contracts.py").resolve(),
        (PROGRAMS / "execution_analog_contract.py").resolve(),
        (PROGRAMS / "step_preflight.py").resolve(),
        (PROGRAMS / "_path_layout.py").resolve(),
        (PROGRAMS / "verdict.py").resolve(),
        (PROGRAMS / "_runner_summary.py").resolve(),
        (PROGRAMS / "_analog_a_check_common.py").resolve(),
        (PROGRAMS / "_analog_producer_common.py").resolve(),
        (PROGRAMS / "_progress_run.py").resolve(),
        (PROGRAMS / "_eda_pin.py").resolve(),
        (PROGRAMS / "data/execution_analog_contracts.json").resolve(),
        (PROGRAMS.parent / "flow/phase1_phase2_phase3.yaml").resolve(),
    }
    for step in FRONT_IDS:
        initial.update((PROGRAMS / name).resolve() for name in analog.PRODUCERS[step])
        initial.update((PROGRAMS / (gate["command"].split()[0] + ".py")).resolve()
                       for gate in analog.gate_specs(step))
    initial = {path for path in initial if path.is_file() and not path.is_symlink()}
    closure = set(source_closure(initial))
    # Keep the actual argv[0] executable byte-bound, but do not send the ELF
    # binary through the UTF-8 Python import-closure parser.
    if interpreter.is_file() and not interpreter.is_symlink():
        closure.add(interpreter)
    for path in tuple(initial):
        if path.suffix == ".py" and path.is_file():
            closure.update(implementation_closure(path))
    return {str(path): em.digest(path) for path in sorted(closure)
            if path.is_file() and not path.is_symlink()}


def validate(outputs: Path, binding: Mapping[str, object]) -> em.Evidence:
    """Re-read worker and gate records, and hash every per-block output."""
    outputs = Path(outputs)
    required_gates = tuple(binding.get("required_gates", ()))
    receipt_path = outputs / "front-producer.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        return em.Evidence(binding, "NOT_MEASURED",
                           {gate: "NOT_MEASURED" for gate in required_gates}, {},
                           detail="FRONT_PRODUCER_RECEIPT_ABSENT")
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        return em.Evidence(binding, "NOT_MEASURED",
                           {gate: "NOT_MEASURED" for gate in required_gates}, {},
                           detail=f"FRONT_PRODUCER_RECEIPT_INVALID:{exc}")
    if receipt.get("binding") != dict(binding) or receipt.get("step_id") != binding.get("step_id"):
        return em.Evidence(binding, "NOT_MEASURED",
                           {gate: "NOT_MEASURED" for gate in required_gates}, {},
                           detail="FRONT_PRODUCER_BINDING_MISMATCH")

    import execution_analog_front_worker as worker
    expected_blocks = tuple(binding.get("objective", {}).get("blocks", ()))
    if (tuple(receipt.get("blocks", ())) != expected_blocks or
            tuple(row.get("block") for row in receipt.get("rows", ())) != expected_blocks):
        return em.Evidence(binding, "NOT_MEASURED",
                           {gate: "NOT_MEASURED" for gate in required_gates}, {},
                           detail="FRONT_BLOCK_POPULATION_MISMATCH")
    observed = {}
    outputs_hashes = {}
    for name, expected in receipt.get("outputs", {}).items():
        try:
            relative = em._relative(name)
        except em.Refusal:
            return em.Evidence(binding, "NOT_MEASURED", observed, outputs_hashes,
                               detail="FRONT_OUTPUT_PATH_UNSAFE:" + str(name))
        path = outputs / relative
        if path.is_symlink() or not path.is_file() or em.digest(path) != expected:
            return em.Evidence(binding, "FAIL" if receipt.get("verdict") == "FAIL"
                               else "NOT_MEASURED", observed, outputs_hashes,
                               detail="FRONT_OUTPUT_CHANGED:" + str(name))
        outputs_hashes[name] = expected

    block_outputs = receipt.get("block_outputs")
    if not isinstance(block_outputs, dict) or set(block_outputs) != set(expected_blocks):
        return em.Evidence(binding, "NOT_MEASURED", {}, outputs_hashes,
                           detail="FRONT_BLOCK_OUTPUT_MAP_INVALID")
    for block in expected_blocks:
        names = block_outputs.get(block)
        if (not isinstance(names, list) or not names or
                any(name not in outputs_hashes or f"/analog/{block}/" not in "/" + name
                    for name in names)):
            return em.Evidence(binding, "FAIL" if receipt.get("verdict") == "FAIL"
                               else "NOT_MEASURED", {}, outputs_hashes,
                               detail="FRONT_BLOCK_OUTPUT_UNBOUND:" + block)

    step = str(binding.get("step_id", ""))
    optional_gates = {
        row["command"].split()[0]: tuple(row.get("condition_files_exist", ()))
        for row in analog.gate_specs(step)
        if row.get("kind") == "optional_program_exit_zero"
    }
    current_inputs = binding.get("inputs", {})
    if not isinstance(current_inputs, Mapping):
        current_inputs = {}
    for gate in required_gates:
        path = outputs / "observed-gates" / f"{gate}.json"
        try:
            record = json.loads(path.read_text())
            argv = record.get("argv", ())
            if (record.get("binding") != dict(binding) or
                    not any(Path(token).name == gate + ".py" for token in argv)):
                raise ValueError("gate record identity mismatch")
            from execution_analog_worker import _gate_status
            report = record.get("report", {})
            status = _gate_status(record.get("rc"), report)
            # This existing checker publishes its typed `passed`/tier schema,
            # not the generic top-level `verdict` field. Accept only its
            # complete non-skipped PASS shape and preserve finding failures.
            summary = report.get("summary", {})
            if (gate == "analog_netlist_pdk_check" and
                    record.get("rc") == 0 and report.get("program") == gate and
                    report.get("passed") is True and
                    summary.get("verdict_tier") == "PASS" and
                    summary.get("skipped") is False and
                    not any(f.get("severity") in ("ERROR", "FAIL")
                            for f in report.get("findings", []) if isinstance(f, dict))):
                status = "PASS"
            # Optional gates remain observed and binding-current. Their
            # canonical condition decides whether their status blocks this
            # row; only a measured FAIL remains blocking when absent.
            conditions = optional_gates.get(gate)
            if conditions and not any(
                    fnmatch.fnmatchcase(str(name), pattern)
                    for pattern in conditions for name in current_inputs):
                status = "FAIL" if status == "FAIL" else "NOT_APPLICABLE"
            observed[gate] = status
            outputs_hashes[f"observed-gates/{gate}.json"] = em.digest(path)
        except (OSError, ValueError, TypeError, KeyError):
            observed[gate] = "NOT_MEASURED"

    # The step producer's measured FAIL dominates missing gates/other blocks.
    measured_fail = receipt.get("verdict") == "FAIL" or "FAIL" in observed.values()
    status = ("FAIL" if measured_fail else "PASS" if receipt.get("verdict") == "PASS"
              and all(observed.get(gate) == "PASS" or
                      (gate in optional_gates and
                       observed.get(gate) == "NOT_APPLICABLE")
                      for gate in required_gates)
              else "NOT_MEASURED")
    return em.Evidence(binding, status, observed, outputs_hashes,
        metrics={"current_artifact_count": float(len(receipt.get("outputs", {})))},
        detail=str(receipt.get("detail", "")),
        provenance={"blocks": list(expected_blocks), "producer_rows": receipt.get("rows", []),
                    "receipt_sha256": em.digest(receipt_path),
                    "gate_record_hashes": {gate: outputs_hashes.get(
                        f"observed-gates/{gate}.json") for gate in required_gates}})


def register_front_adapters(registry: em.Registry, *, project: Path,
                            source_sha: str,
                            parameters: Mapping[str, object] | None = None) -> None:
    """Register one existing producer chain for each owned canonical row."""
    declaration = analog.declaration_path(project)
    blocks = list(analog._blocks(project, declaration))
    declaration_hash = em.digest(declaration)
    source_files = _source_files(source_sha)
    params = dict(parameters or {})
    pdk = params.get('pdk_name') or params.get('pdk')
    if isinstance(pdk, Mapping):
        pdk = pdk.get('name')
    elif pdk is not None and not isinstance(pdk, str):
        pdk = getattr(pdk, 'name', None)
    caller_params = {'container': params.get('container'), 'pdk': pdk}
    if any(value is not None and not isinstance(value, str)
           for value in caller_params.values()):
        raise em.Refusal('FRONT_CALLER_PARAMETER_INVALID', repr(tuple(caller_params)))
    for step, step_name in STEP_NAMES.items():
        specs = analog.CONTRACTS[step]
        required = tuple(specs["portfolio_policy"]["required_output_contract"])
        objective = dict(metric="current_artifact_count", direction="max",
            step_id=step, blocks=blocks, original_project=str(project.resolve()),
            declaration_sha256=declaration_hash,
            source_manifest_sha256=em._hash(source_files),
            parameters={"producer_step": step_name, **caller_params})
        row_inputs = [item["path"] for item in specs["canonical_row"].get("required_inputs", ())
                      if isinstance(item, dict) and item.get("path")]
        # The ordinary producer reads the prior fixed-step products from its
        # project tree. The isolated worker sees only Context inputs, so bind
        # these current A1/A2 bytes before staging A2/A3.
        if step in ("A2", "A3", "A5", "A9"):
            row_inputs.append("phase3/analog/*/spec.json")
        if step in ("A3", "A5", "A9"):
            row_inputs.append("phase3/analog/*/topology.json")
        if step == "A5":
            row_inputs.append("phase3/analog/*/netlist_provenance.json")
        row_inputs.extend((str(declaration.relative_to(project)),
                           "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
                           "input/pdk/**/*"))
        if step == "A9":
            # These are prior products/current declarations read by the
            # existing cosim and hardware consumers, never A9's own reports.
            row_inputs.extend(("phase1/generated_docs/L22*.json",
                "phase3/analog/*/*.sp", "phase3/analog/*/a7_post_layout.json",
                "phase3/analog/*/pre_vs_post.json", "phase3/analog/*/corner_results.json",
                "phase3/analog/hardmacro/*/*.v", "input/mixed_signal/**/*"))
            row_inputs.extend(pattern
                for gate in analog.gate_specs(step)
                if gate.get("kind") == "optional_program_exit_zero"
                for pattern in gate.get("condition_files_exist", ()))
        gate_names = tuple(gate["command"].split()[0] for gate in analog.gate_specs(step)
                           if gate["kind"] != "advisory_program_exit_zero")
        components = [em.Component("produce-existing-row",
            (str(Path(sys.executable).resolve()), str(WORKER), "--step", step,
             "--inputs", "{inputs}", "--outputs", "{outputs}"), 1800)]
        components.extend(em.Component(gate,
            (str(Path(sys.executable).resolve()), str(OBSERVE_WORKER),
             "--outputs", "{outputs}", "--observe-gate", gate), 180)
            for gate in gate_names)
        registry.register(em.Adapter(
            arm_id="analog-front-" + step.lower(), tool_id="analog-front-worker",
            step_id=step, source_sha=source_sha, source_files=source_files,
            tool_version="existing-runner-producer-chain", engine_families=("vibeic-analog-" + step.lower(),),
            components=tuple(components), validate=validate,
            required_outputs=required, objective=objective,
            applicability="applicable" if blocks else "inapplicable",
            applicability_reason="" if blocks else "declared analog block population is empty",
            qualified=True, available=True,
            qualification_evidence="source-bound existing producer/gate dispatch; native readiness not implied",
            availability_reason="Native/tool availability is classified by current producer and gates",
            cpus=1, ram_mb=1024,
            own_no_tool_reason="Uses the sole existing source producer chain; no competing provider is claimed.",
            output_contract={spec: (spec,) for spec in required},
            input_contract=tuple(dict.fromkeys(row_inputs))))
