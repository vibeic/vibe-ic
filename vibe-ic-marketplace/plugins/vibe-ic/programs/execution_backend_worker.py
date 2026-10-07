"""Real source-owned backend component for the common execution controller."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import execution_modes as em
from execution_adapters_backend import ROWS
from execution_backend_gates import evaluate, states
from execution_backend_producers import produce
from execution_backend_snapshot import sha


def _copy_input_tree(inputs: Path, project: Path) -> None:
    source = inputs / "project"
    if source.is_dir():
        shutil.copytree(source, project)
    else:
        # The controller's input binding is authoritative; JSON is a valid
        # canonical input (netlist metadata, route declarations, manifests),
        # so do not silently drop it in the compatibility layout.
        shutil.copytree(inputs, project)


def resolve_contract(project: Path, patterns) -> tuple[dict, list[str]]:
    found, missing = {}, []
    for raw in patterns:
        alternatives = [part.strip() for part in str(raw).split(" OR ")]
        paths = sorted({p for pattern in alternatives for p in project.glob(pattern)
                        if p.is_file() and not p.is_symlink() and p.stat().st_size})
        if not paths:
            missing.append(str(raw))
        for path in paths:
            found[str(path.relative_to(project))] = sha(path)
    return found, missing


def resolve_input_contract(project: Path, declarations) -> list[str]:
    missing = []
    for declaration in declarations or ():
        if not isinstance(declaration, dict) or not declaration.get("path"):
            continue
        patterns = [part.strip() for part in str(declaration["path"]).split(" OR ")]
        # A declared path is substantive only when it resolves to a regular,
        # non-empty file.  Preserve OR semantics: one non-empty alternate is
        # sufficient, while a zero-byte placeholder is still missing.
        present = any(
            p.is_file() and not p.is_symlink() and p.stat().st_size > 0
            for pattern in patterns for p in project.glob(pattern))
        if not present:
            missing.append(str(declaration["path"]))
    return missing


def _binding(inputs: Path) -> dict:
    raw = os.environ.get("VIBEIC_EXECUTION_BINDING")
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    files = {str(p.relative_to(inputs)): sha(p) for p in inputs.rglob("*")
             if p.is_file() and not p.is_symlink()}
    return {"inputs": files}


def execute(inputs: Path, outputs: Path, *, step_id: str, params: dict) -> dict:
    inputs, outputs = Path(inputs), Path(outputs)
    outputs.mkdir(parents=True, exist_ok=True)
    project = outputs / "project"
    _copy_input_tree(inputs, project)
    binding = _binding(inputs)
    row = ROWS[str(step_id)]["canonical_row"]
    input_contract = params.get("input_contract", row.get("required_inputs", ()))
    missing_inputs = resolve_input_contract(project, input_contract)
    producer = {"verdict": "NOT_MEASURED", "detail": "producer did not run"}
    gate_result = {"status": "NOT_MEASURED", "ledger": []}
    if missing_inputs:
        producer = {"verdict": "NOT_MEASURED", "detail":
                    "REQUIRED_INPUT_ABSENT: " + "; ".join(missing_inputs)}
    else:
        try:
            params = dict(params, step_id=str(step_id), project=project)
            producer = produce(project, params)
            if not isinstance(producer, dict):
                producer = {"verdict": "NOT_MEASURED", "detail": "producer returned no result"}
        except BaseException as exc:
            producer = {"verdict": "NOT_MEASURED", "detail": f"{type(exc).__name__}: {exc}",
                        "canonical_receipts": [{
                            "schema": "vibeic/backend-producer-receipt/1",
                            "producer": "execution_backend_producers.produce",
                            "step_id": str(step_id), "verdict": "NOT_MEASURED",
                            "detail": f"{type(exc).__name__}: {exc}"}]}
    # A producer exception must not erase a measured FAIL, and a consumer
    # exception must not prevent the canonical gate from being represented in
    # the digest-bound result.  Both remain source-only until native receipts.
    if missing_inputs:
        gate_result = {"status": "NOT_MEASURED", "ledger": [{
            "gate": gate, "rc": None, "verdict": "NOT_MEASURED",
            "reason": "REQUIRED_INPUT_ABSENT"} for gate in binding.get("required_gates", ())]}
    else:
        try:
            gate_result = evaluate(project, row)
        except BaseException as exc:
            gate_result = {"status": "NOT_MEASURED", "ledger": [{
                "gate": "backend_consumer", "verdict": "NOT_MEASURED",
                "reason": f"{type(exc).__name__}: {exc}"}]}
    files, missing = resolve_contract(project, row.get("required_outputs", ()))
    # Publish only exact current producer/gate bytes; no placeholder output is
    # created for a missing canonical contract.
    for name in files:
        source = project / name
        target = outputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    producer_verdict = producer.get("verdict", "NOT_MEASURED")
    gate_status = gate_result.get("status", "NOT_MEASURED")
    gate_states = states(binding, gate_result, producer.get("verdict", "NOT_MEASURED"))
    native_receipts = producer.get("native_receipts") or []
    canonical_receipts = producer.get("canonical_receipts") or []
    verdict = ("FAIL" if producer_verdict == "FAIL" or gate_status == "FAIL" else
               "PASS" if producer_verdict == "PASS" and gate_status == "PASS" and
               canonical_receipts and not missing and not missing_inputs else "NOT_MEASURED")
    result = {
        "schema": "vibeic/backend-result/2", "step_id": str(step_id),
        "source_sha": binding.get("source_sha"), "binding": binding,
        "producer_verdict": producer_verdict, "gates": gate_states,
        "gate_ledger": gate_result.get("ledger", []), "outputs": files,
        "missing_outputs": missing, "native_receipts": native_receipts,
        "canonical_receipts": canonical_receipts,
        "verdict": verdict, "detail": producer.get("detail", ""),
        "input_contract": input_contract, "missing_inputs": missing_inputs,
    }
    (outputs / "backend_result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", type=Path)
    ap.add_argument("outputs", type=Path)
    ap.add_argument("--step-id", required=True)
    ap.add_argument("--params-json", default="{}")
    args = ap.parse_args(argv)
    try:
        params = json.loads(args.params_json)
        execute(args.inputs, args.outputs, step_id=args.step_id, params=params)
        return 0
    except Exception as exc:
        args.outputs.mkdir(parents=True, exist_ok=True)
        (args.outputs / "backend_result.json").write_text(json.dumps({
            "schema": "vibeic/backend-result/2", "step_id": args.step_id,
            "verdict": "NOT_MEASURED", "reason": f"{type(exc).__name__}: {exc}",
            "native_receipts": []}, sort_keys=True) + "\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
