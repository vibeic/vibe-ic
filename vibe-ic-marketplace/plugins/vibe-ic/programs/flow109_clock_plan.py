"""D34 adapter for the existing special Default clock-plan producer.

This is intentionally not an ``execution_backend_producers`` row.  Native
step 16 is special-cased by the Phase-3 runner: ``emit_clock_plan`` drives the
current OpenROAD measurement, and the unchanged canonical row-16 consumer
runs ``clock_plan_check``.  This adapter only binds that real pair to D34 and
retains its identities; Flow109 and whole-flow acceptance remain unmeasured.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json

SCHEMA = "vibeic.flow109.clock-plan-component.v1"
OUTPUT = "phase3/stage3/cts/clock_plan.json"
NATIVE_STEP = "16"
STEP17_REUSE_ENV = "VIBEIC_FLOW109_STEP17_REUSE_REQUEST"

# Only the reviewed 634 -> 805 Flow109 ownership work may differ while a
# retained Step-17 producer is adopted.  Everything that could have authored
# the old placement remains byte-identical or reuse refuses.
_REUSE_SOURCE_EXCEPTIONS = {
    "flow/FLOW109.md",
    "flow/flow109.json",
    "programs/flow109.py",
    "programs/flow109_clock_plan.py",
    "programs/flow109_final_lec.py",
    "programs/phase3_one_shot_runner.py",
    "programs/tests/test_flow109_clock_plan.py",
    "programs/tests/test_flow109_final_lec.py",
    "programs/tests/test_flow109_mixed_native_window.py",
    "programs/tests/test_flow109_selection.py",
    "programs/tests/test_flow109_window_continuation.py",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operation_sources() -> dict[str, str]:
    paths = (
        Path(__file__),
        HERE / "phase3_one_shot_runner.py",
        HERE / "_physical_current.py",
        HERE / "_path_layout.py",
        HERE / "clock_plan_check.py",
        HERE / "execution_backend_gates.py",
    )
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in paths}


def _inputs(project: Path) -> dict[str, dict[str, object]]:
    import _path_layout as layout

    paths = [project / "phase3/stage3/pnr/floorplan.def",
             project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"]
    paths.extend(layout.clock_plan_input_sdcs(project))
    result = {}
    for path in paths:
        path = Path(path)
        if path.is_file():
            result[str(path.resolve().relative_to(project))] = {
                "sha256": _sha(path), "bytes": path.stat().st_size}
    return result


def _consumer_row() -> dict:
    import execution_backend_gates as gates

    row = gates.canonical_family_row(NATIVE_STEP)
    if (not isinstance(row, dict)
            or row.get("required_outputs") != [OUTPUT]
            or gates.required_commands(row) != [
                "clock_plan_check . --json reports/phase2/gates/clock_plan.json"]):
        raise ValueError("D34_CLOCK_CONSUMER_UNREGISTERED")
    return row


def _step17_reuse_request(project: Path, component_attempt: Path,
                          context: dict) -> Path:
    """Seal an exact retained-placement request; never authorize by presence."""
    runtime = json.loads((project / "reports/orchestrator/runtime_program_tree.json").read_text())
    prior_root = Path(runtime["retained_plugin_root"])
    current_root = HERE.parent
    checked = {}
    for prior in sorted(prior_root.rglob("*")):
        if not prior.is_file() or prior.is_symlink():
            continue
        rel = str(prior.relative_to(prior_root))
        if rel in _REUSE_SOURCE_EXCEPTIONS:
            continue
        current = current_root / rel
        if current.is_symlink() or not current.is_file() or _sha(current) != _sha(prior):
            raise ValueError("D35_RETAINED_SOURCE_CHANGED: " + rel)
        checked[rel] = _sha(current)
    if not checked:
        raise ValueError("D35_RETAINED_SOURCE_CENSUS_EMPTY")

    import step_output_collector as versions
    retained = versions.latest_pass(project, "17")
    backend = project / "reports/phase3/default_steps/17/backend_result.json"
    placed = project / "phase3/stage3/pnr/placed.def"
    handoff = project / "reports/phase3/librelane_placement_handoff.json"
    if (not retained or retained.get("current_inputs") is not True
            or retained.get("canonical_pass") is not True
            or retained.get("status") != "PASS"):
        raise ValueError("D35_RETAINED_CURRENT_PASS_ABSENT")
    for path, reason in ((backend, "BACKEND"), (placed, "PLACED_DEF"),
                         (handoff, "NATIVE_HANDOFF")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("D35_RETAINED_" + reason + "_ABSENT")
    request = component_attempt / "step17_reuse_request.json"
    clock = json.loads((project / OUTPUT).read_text())
    clock_pdk = (clock.get("current") or {}).get("pdk")
    if not isinstance(clock_pdk, str) or not clock_pdk:
        raise ValueError("D35_RETAINED_CLOCK_PDK_ABSENT")
    write_json(request, {
        "schema": "vibeic.flow109.step17-reuse-request.v1",
        "context_sha256": context.get("context_sha256"),
        "source_census_count": len(checked),
        "source_census_sha256": hashlib.sha256(
            json.dumps(checked, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "retained_step_folder": retained.get("folder"),
        "backend_result_sha256": _sha(backend),
        "placed_def_sha256": _sha(placed),
        "native_handoff_sha256": _sha(handoff),
        "pdk": clock_pdk,
    })
    return request


def execute(project, context):
    project = Path(project).resolve()
    component_attempt = project / "reports/flow109/D34" / uuid.uuid4().hex
    component_attempt.mkdir(parents=True, exist_ok=False)
    record = {
        "schema": SCHEMA,
        "step_id": "D34",
        "native_step_id": NATIVE_STEP,
        "component_status": "NOT_MEASURED",
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
        "native_started": False,
        "context_sha256": context.get("context_sha256"),
        "producer": "phase3_one_shot_runner.emit_clock_plan",
        "consumer": "clock_plan_check",
    }
    try:
        if (context.get("requested_step") != "D34"
                or context.get("native_step_id") != "flow109.D34"):
            raise ValueError("D34_CONTEXT_MISMATCH")
        row = _consumer_row()
        sources = operation_sources()
        inputs = _inputs(project)
        floorplan = project / "phase3/stage3/pnr/floorplan.def"
        pdk = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
        sdc_count = sum(path.endswith(".sdc") for path in inputs)
        if not floorplan.is_file():
            raise ValueError("D34_FLOORPLAN_ABSENT")
        if not pdk.is_file():
            raise ValueError("D34_PDK_DECLARATION_ABSENT")
        if not sdc_count:
            raise ValueError("D34_SDC_ABSENT")

        import step_output_collector as versions
        step_attempt = versions.begin_step(project, NATIVE_STEP, inputs)
        output = project / OUTPUT
        before = _sha(output) if output.is_file() else None
        import phase3_one_shot_runner as runner
        notes: list[str] = []
        with versions.active_steps(project, [step_attempt]):
            try:
                produced = runner.emit_clock_plan(
                    project, output, floorplan, floorplan.parent, notes)
                after = _sha(output) if output.is_file() else None
                record["native_started"] = bool(produced and after and after != before)
                record["producer_notes"] = notes
                record["inputs"] = inputs
                record["operation_sources"] = sources

                # Fail closed if current source or any producer input changed
                # across the native producer/consumer boundary.
                if operation_sources() != sources:
                    raise ValueError("D34_OPERATION_SOURCE_CHANGED")
                if _inputs(project) != inputs:
                    raise ValueError("D34_INPUT_CHANGED")

                versions.publish_producer_outputs(project, step_attempt)
                import execution_backend_gates as gates
                gate = gates.evaluate(project, row)
                record["consumer_result"] = gate
                if after:
                    record["outputs"] = {OUTPUT: after}
                    current = json.loads(output.read_text()).get("current", {})
                    record["native_execution"] = current.get("execution")
                else:
                    record["outputs"] = {}

                if gate.get("status") == "FAIL":
                    record.update(component_status="FAIL",
                                  reason="D34_CLOCK_PLAN_CONSUMER_FAILED")
                elif produced and after and gate.get("status") == "PASS":
                    record.update(component_status="PASS",
                                  reason=("D34_CURRENT_CLOCK_PLAN_PRODUCED"
                                          if record["native_started"] else
                                          "D34_CURRENT_CLOCK_PLAN_REUSED"))
                else:
                    record["reason"] = "D34_CLOCK_PLAN_NOT_MEASURED"
                parent_path = os.environ.get("VIBEIC_FLOW109_CONTEXT")
                try:
                    parent = json.loads(Path(parent_path).read_text()) if parent_path else {}
                except (OSError, ValueError, TypeError):
                    parent = {}
                if (record["component_status"] == "PASS"
                        and parent.get("schema") == "vibeic.flow109.execution-window.v1"
                        and parent.get("requested_entry") == "D34"
                        and parent.get("requested_exit") == "D35"
                        and parent.get("dispatch_kind") == "selected_native_sequence"):
                    request = _step17_reuse_request(project, component_attempt, context)
                    record["step17_reuse_request"] = {
                        "path": str(request.relative_to(project)), "sha256": _sha(request)}
                    os.environ[STEP17_REUSE_ENV] = str(request.resolve())
                receipt = {
                    "step_id": NATIVE_STEP,
                    "verdict": record["component_status"],
                    "outputs": record["outputs"],
                    "gate_ledger": gate.get("ledger", []),
                    "canonical_step_result": gate.get("step"),
                }
                receipt_path = project / (
                    "reports/phase3/default_steps/16/backend_result.json")
                write_json(receipt_path, receipt)
                version = versions.finish_step(
                    project, step_attempt,
                    verdict=record["component_status"], result=receipt,
                    canonical_pass=(record["component_status"] == "PASS"))
                record["output_version"] = version["folder"]
                if version["capture_errors"]:
                    raise OSError("D34_OUTPUT_RETENTION_FAILED: " +
                                  "; ".join(version["capture_errors"]))
            except BaseException as exc:
                if not (project / "steps" / step_attempt["folder"] /
                        "outputs.json").is_file():
                    versions.finish_step(
                        project, step_attempt, verdict="NOT_MEASURED",
                        result={"step_id": NATIVE_STEP, "detail": str(exc)})
                raise
    except (OSError, ValueError, TypeError, ImportError) as exc:
        record.update(reason=str(exc).split(":", 1)[0], detail=str(exc))
    write_json(component_attempt / "component.json", record)
    return record
