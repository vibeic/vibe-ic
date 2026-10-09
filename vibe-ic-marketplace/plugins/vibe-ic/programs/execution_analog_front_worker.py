"""Passive worker for the existing ordinary analog A1-A5/A9 producers.

The parent Controller owns request authority, frozen inputs, selection and
adoption. This process only stages those inputs, calls the existing runner
producer/gate path in block order, and records the current output bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

PROGRAMS = Path(__file__).resolve().parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
import execution_modes as em
import execution_adapters_analog as analog
import analog_one_shot_runner as runner

STEP_NAMES = {
    "A1": "A1_spec_extract", "A2": "A2_topology_select",
    "A3": "A3_netlist_gen", "A4": "A4_corner_sweep",
    "A5": "A5_layout", "A9": "A9_hw_verify",
}


def _copy_inputs(inputs: Path, project: Path) -> None:
    project.mkdir(parents=True, exist_ok=False)
    for source in sorted(inputs.rglob("*")):
        if source.is_symlink():
            raise em.Refusal("FRONT_INPUT_SYMLINK", str(source))
        if not source.is_file() or source.name == "issued-manifest.json":
            continue
        relative = source.relative_to(inputs)
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o644)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def execute(step: str, inputs: Path, outputs: Path) -> dict:
    if step not in STEP_NAMES:
        raise em.Refusal("FRONT_STEP_UNSUPPORTED", step)
    inputs, outputs = inputs.resolve(), outputs.resolve()
    if outputs.exists() and any(outputs.iterdir()):
        raise em.Refusal("FRONT_OUTPUTS_NOT_EMPTY", str(outputs))
    outputs.mkdir(parents=True, exist_ok=True)
    project = outputs / "project"
    _copy_inputs(inputs, project)
    declaration = analog.declaration_path(project)
    blocks = analog._blocks(project, declaration)
    declared = json.loads(declaration.read_text())
    declared_rows = declared.get("blocks") if isinstance(declared, dict) else declared
    block_rows, results = [], []
    binding = json.loads(os.environ["VIBEIC_EXECUTION_BINDING"])
    if binding.get("step_id") != step:
        raise em.Refusal("FRONT_STEP_BINDING_MISMATCH", step)
    params = binding.get("objective", {}).get("parameters", {})
    args = argparse.Namespace(container=params.get("container"), pdk=params.get("pdk"))
    for block_name in blocks:
        block = next(row for row in declared_rows if row.get("name") == block_name)
        result = runner.step_for_block(project, block, STEP_NAMES[step], args=args)
        row = {"block": block_name, "status": result.status,
               "detail": str(result.detail), "reason_class": result.reason_class,
               "producer": (getattr(result, "extras", None) or {}).get("producer"),
               "output_files": list(result.output_files)}
        block_rows.append(row)
        results.append(result)

    cosim = None
    if step == "A9":
        # A9's existing chip-level producer runs once after every per-block
        # producer, exactly as the ordinary runner does.
        cosim = runner._a9_cosim(project, args)

    source_outputs: dict[str, str] = {}
    for row in block_rows:
        block_root = project / "phase3/analog" / row["block"]
        for name in row["output_files"]:
            path = project / name
            if (path.is_symlink() or not path.is_file() or
                    not path.resolve().is_relative_to(project.resolve())):
                continue
            relative = str(path.relative_to(project))
            # Every per-block output is explicitly attributed to its declared
            # block; another block can never fill this row's output slot.
            if not path.resolve().is_relative_to(block_root.resolve()):
                continue
            source_outputs[relative] = _hash(path)
    if cosim and isinstance(cosim.get("results"), str):
        candidate = Path(cosim["results"])
        if candidate.is_file() and not candidate.is_symlink() and candidate.resolve().is_relative_to(project.resolve()):
            source_outputs[str(candidate.relative_to(project))] = _hash(candidate)

    # Copy only current products named by this run's StepResults or its A9
    # chip-level producer. The controller later imports these exact paths.
    output_hashes = {}
    for relative, expected in sorted(source_outputs.items()):
        source = project / relative
        target = outputs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if _hash(source) != expected or _hash(target) != expected:
            raise em.Refusal("FRONT_OUTPUT_COPY_MISMATCH", relative)
        output_hashes[relative] = expected

    statuses = [result.status for result in results]
    measured_fail = "FAIL" in statuses or bool(cosim and cosim.get("tier") == "PRODUCER_ERROR")
    block_paths = {row["block"]: [name for name in output_hashes
                                  if f"/analog/{row['block']}/" in "/" + name]
                   for row in block_rows}
    complete = bool(blocks) and all(block_paths.values())
    if step == "A9":
        complete = complete and bool(cosim and cosim.get("tier") == "RESULTS_WRITTEN")
    if measured_fail:
        verdict = "FAIL"
    elif complete and all(value == "PASS" for value in statuses):
        verdict = "PASS"
    else:
        verdict = "NOT_MEASURED"
    detail = "; ".join(f"{row['block']}:{row['status']}:{row['detail']}" for row in block_rows)
    receipt = dict(schema=1, binding=binding,
        step_id=step, blocks=list(blocks), rows=block_rows, outputs=output_hashes,
        block_outputs=block_paths, verdict=verdict, detail=detail, a9_cosim=cosim,
        producer_pid=os.getpid(), source_project=str(project))
    temp = outputs / ".front-producer.json.tmp"
    temp.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(temp, outputs / "front-producer.json")
    print(json.dumps({"step_id": step, "verdict": verdict,
                      "blocks": list(blocks), "outputs": output_hashes}, sort_keys=True))
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", required=True, choices=tuple(STEP_NAMES))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        execute(args.step, args.inputs, args.outputs)
        return 0
    except (em.Refusal, OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
