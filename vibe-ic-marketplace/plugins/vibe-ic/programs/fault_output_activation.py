"""Recover random-pattern starvation using SAT-generated output activations.

SAT supplies stimulus only. Native Fault re-simulates every supplied vector on
the unchanged complete fault population, starting with zero coverage. Its
``--iterating-upon`` option is deliberately unsuitable: that option trusts
coverage records in its input instead of grading their vectors.

The external .test loader has a fixed executable name, ``atalanta``. Our private
transport adapter only copies generated stimulus into that loader; it does not
claim to run Atalanta or produce coverage. Fault/iverilog owns all detection.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import vibeic_temp as tempfile

import yaml


def canonical_name(value: str) -> str:
    return value.strip().lstrip("\\")


def fault_sets(metadata: dict) -> tuple[set[str], list[set[str]]]:
    """Ignore native Uncovered arrays; some engines duplicate SA0 into SA1."""
    population = {canonical_name(p) for p in metadata["faultPoints"]}
    covered = [{canonical_name(p) for p in metadata[f"sa{v}Covered"]}
               for v in (0, 1)]
    if not population or any(c - population for c in covered):
        raise ValueError("empty fault population or covered site outside population")
    ratio = sum(map(len, covered)) / (2 * len(population))
    if abs(float(metadata["ratio"]) - ratio) > 0.000002:
        raise ValueError("native ratio disagrees with polarity-specific detection sets")
    return population, covered


def activation_targets(metadata: dict, outputs: list[dict]) -> list[tuple[str, int]]:
    population, covered = fault_sets(metadata)
    scalar_outputs = {canonical_name(p["name"]) for p in outputs
                      if p["from"] == p["to"]}
    return [(name, 1 - stuck) for stuck in (0, 1)
            for name in sorted((population - covered[stuck]) & scalar_outputs)]


def stimulus_values(row: dict, ports: list[dict]) -> list[int]:
    vector = row["vector"]
    if len(vector) != len(ports):
        raise ValueError("stimulus port count mismatch")
    values = []
    for number, port in zip(vector, ports):
        if not number or number[0] != "+" or len(number) < 2:
            raise ValueError("expected unsigned Fault BigUInt stimulus")
        if any(type(n) is not int or not 0 <= n < 2**64 for n in number[1:]):
            raise ValueError("invalid BigUInt limb")
        value = sum(n << (64 * i) for i, n in enumerate(number[1:]))
        if value >= 2 ** (abs(port["from"] - port["to"]) + 1):
            raise ValueError("stimulus exceeds declared port width")
        values.append(value)
    return values


def wave_values(wave: dict, ports: list[dict]) -> list[int]:
    values = {}
    for signal in wave["signal"]:
        bits = (signal["data"][0] if signal["wave"].startswith("=")
                else signal["wave"][0])
        if not bits or set(bits) - {"0", "1"}:
            raise ValueError("SAT stimulus contains undefined bits")
        name = canonical_name(signal["name"])
        if name in values:
            raise ValueError("duplicate SAT input")
        values[name] = int(bits, 2)
    return [values[canonical_name(p["name"])] for p in ports]


def emit_transport(work: Path, ports: list[dict], vectors: list[list[int]]) -> int:
    """Only INPUT declarations are needed by Fault's external vector loader."""
    names = [canonical_name(p["name"]) for p in ports]
    if len(set(names)) != len(names):
        raise ValueError("duplicate stimulus port")
    # No syntax-bearing identifiers may enter the generated Tcl/bench files.
    if any(not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$./-]*", n) for n in names):
        raise ValueError("unsupported stimulus identifier")
    widths = [abs(p["from"] - p["to"]) + 1 for p in ports]
    (work / "ports.bench").write_text("".join(
        f"INPUT({name}[{i}])\n" for name, width in zip(names, widths)
        for i in range(width)))
    rows, seen = [], set()
    for vector in vectors:
        if len(vector) != len(ports) or any(
                type(v) is not int or not 0 <= v < 2**w
                for v, w in zip(vector, widths)):
            raise ValueError("invalid stimulus dimensions/value")
        # Fault's .test reader consumes bits least-significant first per port.
        bits = "".join(format(v, f"0{w}b")[::-1]
                       for v, w in zip(vector, widths))
        if bits not in seen:
            seen.add(bits)
            rows.append(f"{len(rows) + 1}: {bits}\n")
    if not rows:
        raise ValueError("empty pattern transport")
    (work / "patterns.test").write_text("".join(rows))
    return len(rows)


def recover(project: Path, *, cut_rel: str, tv_rel: str, coverage_rel: str,
            liberty: str, cell_model: str, clock: str, target: float,
            execute, max_targets: int = 512, mounted_root: str = "/work") -> dict:
    """Run using the caller's container executor; never change canonical files.

    Return paths only after native full-population grading. The calling producer
    decides whether to publish them. A partial SAT campaign can supply useful
    patterns, but never excludes any fault from the subsequent native grading.
    """
    if not 95 <= target <= 100 or max_targets <= 0:
        raise ValueError("recovery requires the unchanged >=95% coverage target")
    project = Path(project).resolve()
    cut, tv, cov = [project / p for p in (cut_rel, tv_rel, coverage_rel)]
    for path in (cut, tv, cov):
        path.resolve().relative_to(project)
    schema = json.loads(tv.read_text())
    original = yaml.safe_load(cov.read_text())
    population, covered = fault_sets(original)
    targets = activation_targets(original, schema["outputs"])
    report = {"method": "SAT output activation then native full-population regrade",
              "original_fault_sites": len(population),
              "original_detected_faults": sum(map(len, covered)),
              "eligible_targets": len(targets), "target_pct": target,
              "verdict": "NOT_RECOVERED", "reuses_coverage": False}
    if not targets:
        return report
    import transition_fault_atpg_run as tdf
    top, prim_in, _prim_out, pairs = tdf.parse_cut_ports(cut.read_text())
    cut_inputs = {canonical_name(n) for n, _ in prim_in}
    cut_inputs.update(canonical_name(pi) for _, pi, _ in pairs)
    inputs = {canonical_name(p["name"]) for p in schema["inputs"]}
    if inputs != cut_inputs - {clock}:
        raise ValueError("stimulus schema must control every cut input except clock")
    base = project / "phase2/stage2/dft/output_activation"
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="attempt_", dir=base))
    shutil.copyfile(tv, work / "original_vectors.json")
    shutil.copyfile(cov, work / "original_coverage.yml")
    ctr = str(work)
    targets = targets[:max_targets]
    report.update(work_dir=str(work), selected_targets=len(targets),
                  input_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (cut, tv, cov)})
    (work / "targets.json").write_text(json.dumps(targets, indent=2))
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", top):
        raise ValueError("unsupported top identifier")
    script = tdf._tdf_pre_flatten_script(liberty, cut_rel, top,
                                        "__vibeic_temp_flat.v") + "check -assert\n"
    script = script.replace("/work/", mounted_root.rstrip("/") + "/")
    script = script.replace(mounted_root.rstrip("/") + "/__vibeic_temp_flat.v", ctr + "/flat.v")
    for i, (name, level) in enumerate(targets):
        if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$./-]*", name):
            raise ValueError("unsupported SAT target identifier")
        script += (f"log OUTPUT_ACTIVATION {i} {name} {level}\n"
                   f"sat -timeout 5 -set \\{name} {level} -show-inputs "
                   f"-dump_json {ctr}/vector_{i:04d}.json {top}\n")
    (work / "run.ys").write_text(script)
    command = f"yosys -Q -T -s {shlex.quote(ctr + '/run.ys')} > {shlex.quote(ctr + '/yosys.log')} 2>&1"
    rc, _out, _err = execute([command])
    report["yosys_rc"] = rc
    if rc:
        report["verdict"] = "UNMEASURED"
        return report
    waves = sorted(work.glob("vector_*.json"))
    report["activation_patterns"] = len(waves)
    if not waves:
        return report
    vectors = [stimulus_values(r, schema["inputs"]) for r in schema["coverageList"]]
    vectors.extend(wave_values(json.loads(p.read_text()), schema["inputs"])
                   for p in waves)
    report["unique_stimuli"] = emit_transport(work, schema["inputs"], vectors)
    adapter = work / "transport"
    adapter.mkdir()
    shim = adapter / "atalanta"
    shim.write_text("#!/bin/sh\n# SAT stimulus transport only; no Atalanta computation.\n"
                    "set -eu\ncp \"$FAULT_SAT_PATTERN_FILE\" \"$2\"\n")
    shim.chmod(0o755)
    report["external_loader"] = "Fault Atalanta-format loader with SAT stimulus transport adapter"
    args = ["fault", "atpg", "--cell-model", cell_model, "--clock", clock,
            "--reset", "__vibeic_no_reset_bypass__", "-g", "Atalanta",
            "-b", ctr + "/ports.bench", "-v", "8", "-r", "8", "-m", str(target),
            "-o", ctr + "/graded.json", "--output-coverage-metadata",
            ctr + "/coverage.yml", mounted_root.rstrip("/") + "/" + cut_rel]
    command = (f"cd {shlex.quote(ctr)} && "
               f"export PATH={shlex.quote(ctr + '/transport')}:$PATH && "
               f"export FAULT_SAT_PATTERN_FILE={shlex.quote(ctr + '/patterns.test')} && "
               + shlex.join(args) + " > fault.log 2>&1")
    rc, _out, _err = execute([command])
    report["fault_rc"] = rc
    if rc or not all((work / p).is_file() for p in ("coverage.yml", "graded.json")):
        report["verdict"] = "UNMEASURED"
        return report
    measured = yaml.safe_load((work / "coverage.yml").read_text())
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest
           for path, digest in report["input_hashes"].items()):
        raise ValueError("an ATPG input changed during recovery")
    new_population, new_covered = fault_sets(measured)
    if new_population != population:
        raise ValueError("Fault changed the original fault population")
    detected = sum(map(len, new_covered))
    percent = 100 * detected / (2 * len(population))
    report.update(detected_faults=detected, total_faults=2 * len(population),
                  coverage_pct=percent, lost_detections=[len(a - b) for a, b in
                                                      zip(covered, new_covered)],
                  coverage_path=str(work / "coverage.yml"),
                  vectors_path=str(work / "graded.json"))
    if percent >= target and not any(report["lost_detections"]):
        report["verdict"] = "RECOVERED"
    (work / "recovery.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
