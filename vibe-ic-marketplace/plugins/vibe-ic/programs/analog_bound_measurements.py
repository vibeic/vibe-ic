#!/usr/bin/env python3
"""Run explicit source-bound OP/DC/AC measurements on a delivered DUT.

The supplied testbench owns the stimulus and conditions. This producer only
replaces its analysis controls with the declared analysis/measurements. Its
result covers those measurements, not whole-block or PVT acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import analog_meas_from_spec_gen as generator
import analog_native_sim as sim
import analog_real_corner_sweep as sweep


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def consumed_input_views(project: Path, deck: Path) -> dict:
    """Hash the native deck's selected .lib and transitive include inputs."""
    from analog_mc_yield_run import _statistical_closure
    deck = Path(deck).resolve()
    _text, files = _statistical_closure(Path(project).resolve(), deck, None)
    return {"include:" + row["path"]: {"path": row["path"], "sha256": row["sha256"]}
            for row in files if Path(row["path"]) != deck}


def validate_consumed_inputs(project: Path, native_inputs: dict) -> tuple[bool, str]:
    """Require the complete current closure, never add hashes to old values."""
    if not isinstance(native_inputs, dict) or not isinstance(native_inputs.get("deck"), dict):
        return False, "native measurement lacks its executed deck input"
    view = native_inputs["deck"]
    deck = Path(view.get("path") or "__missing_native_deck__")
    if not deck.is_file() or view.get("sha256") != sha(deck):
        return False, "executed native deck is absent or changed"
    try:
        expected = consumed_input_views(project, deck)
    except (OSError, ValueError) as exc:
        return False, "native model/include closure unavailable: " + str(exc)
    actual = {role: view for role, view in native_inputs.items() if role.startswith("include:")}
    if actual != expected:
        return False, "native model/include closure receipt is absent, stale, or incomplete"
    return True, "current executed model/include closure"


def contextual_template(text: str, directory: Path) -> str:
    """Keep include resolution when the derived deck lives elsewhere."""
    pattern = re.compile(r'''(?im)^(\s*\.(include|inc|lib)\s+)(?:"([^"]+)"|'([^']+)'|(\S+))([^\n]*)$''')
    def replace(match):
        name = next(value for value in match.group(3, 4, 5) if value is not None)
        # An inline `.lib section` is a section declaration, not a filename.
        if match.group(2).casefold() == "lib" and not match.group(6).strip():
            return match.group(0)
        path = Path(name)
        if path.is_absolute() or "$" in name:
            return match.group(0)
        return match.group(1) + '"' + str((directory / path).resolve()) + '"' + match.group(6)
    return pattern.sub(replace, text)


def emit_deck(template: str, bindings: dict, capture_path: Path | None = None) -> str:
    analysis = bindings.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("explicit analysis required")
    kind = str(analysis.get("kind", "")).upper()
    if kind == "OP":
        command = "op"
    elif kind in ("DC", "AC"):
        source = analysis.get("source")
        values = [analysis.get(key) for key in ("start", "stop", "step")]
        if kind == "AC":
            values = [analysis.get(key) for key in ("points", "start_hz", "stop_hz")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise ValueError("explicit finite analysis range required")
        if kind == "DC":
            if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z_]\w*", source) or not values[2] or (values[1] - values[0]) * values[2] <= 0:
                raise ValueError("DC source and directed nonempty sweep required")
            command = "dc " + source + " " + " ".join(format(value, ".17g") for value in values)
        else:
            if values[0] < 1 or int(values[0]) != values[0] or values[1] <= 0 or values[2] < values[1]:
                raise ValueError("AC points and positive frequency bounds required")
            command = f"ac dec {int(values[0])} {values[1]:.17g} {values[2]:.17g}"
    else:
        raise ValueError("only explicit OP/DC/AC analysis is supported")
    measurements = bindings.get("measurements")
    if not isinstance(measurements, dict) or not measurements:
        raise ValueError("nonempty explicit measurement bindings required")
    commands = [command]
    for name, binding in measurements.items():
        emitted, measure_kind = generator.measurement_commands(name, binding)
        if measure_kind != kind:
            raise ValueError("measurement analysis differs from declared analysis")
        commands += emitted
    capture = bindings.get("capture", {})
    if not isinstance(capture, dict):
        raise ValueError("capture must map vector labels to native expressions")
    for name, expression in capture.items():
        emitted, _ = generator.measurement_commands(name, {"analysis": "OP", "expression": expression})
        commands.append(emitted[0])
    if capture:
        if capture_path is None:
            raise ValueError("capture destination required")
        if re.search(r"[\s;'\"]", str(capture_path)):
            raise ValueError("native wrdata capture path must be one unquoted filename token")
        commands += ["set wr_singlescale", "set wr_vecnames",
                     'wrdata ' + str(capture_path) + ' ' + " ".join("bound_" + name for name in capture)]
    # Retain every circuit/model/stimulus line; no inherited transient runs.
    body = re.sub(r"(?ims)^\s*\.control\b.*?^\s*\.endc\b[^\n]*", "", template)
    body = re.sub(r"(?im)^\s*\.(?:op|dc|ac|tran|noise|meas|measure)\b[^\n]*", "", body)
    body = re.sub(r"(?im)^\s*\.end\s*$", "", body)
    # An inherited .save restriction must retain the actual newly bound
    # probes too; otherwise a successful OP has no requested node vectors.
    probes = set()
    expressions = [binding.get("expression", "") for binding in measurements.values()] + list(capture.values())
    for expression in expressions:
        for function, nodes in re.findall(r"(?i)\b(v(?:db|p|m)?|i)\s*\(\s*([^()\s]+)\s*\)", expression):
            probes.update(("i(" + nodes + ")",) if function.casefold() == "i" else
                          ("v(" + node + ")" for node in nodes.split(",")))
    if probes:
        body += "\n.save " + " ".join(sorted(probes)) + "\n"
    return body.rstrip() + "\n.control\n" + "\n".join(commands) + "\n.endc\n.end\n"


def run_measurements(project: Path, netlist: Path, template: Path, bindings: dict,
                     destination: Path, run) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    deck = destination / "measurements.sp"
    capture_path = destination / "curve.dat"
    text = contextual_template(template.read_text(), template.parent)
    deck.write_text(emit_deck(text, bindings, capture_path))
    status, detail, required = sim._validate_deck(netlist, deck,
        {"required_measurements": list(bindings.get("measurements", {}))})
    report = {"status": status, "detail": detail, "scope": "explicit native measurement bindings only",
              "native_inputs": {role: {"path": str(path.resolve()), "sha256": sha(path)} for role, path in
                                (("netlist", netlist), ("testbench", template), ("deck", deck))},
              "bindings": bindings, "measurements": {}, "executions": []}
    if status != "PASS":
        return report
    try:
        report["native_inputs"].update(consumed_input_views(project, deck))
    except (OSError, ValueError) as exc:
        report.update(status="NOT_MEASURED", detail="native model/include inputs unavailable: " + str(exc))
        return report
    execution = run("@ngspice", ["-b", str(deck)], cwd=template.parent)
    report["executions"] = [execution]
    text = sim._log_text(execution)
    values = {key.casefold(): value for key, value in sweep.native_meas_rows(text).items()}
    for match in sweep._MEAS_LINE_RE.finditer(text):
        for key, value in sweep._KV_RE.findall(match.group(1)):
            values.setdefault(key.casefold(), float(value))
    missing = [name for name in required if name not in values or not math.isfinite(values[name])]
    interrupted = execution.get("returncode") in (130, 137, 143) or (
        isinstance(execution.get("returncode"), int) and execution["returncode"] < 0)
    failed = any(sweep._scan_analysis_failures(text)) or re.search(
        r"(?im)\bfatal(?: error)?\b|\bsimulation(?:\(s\)|s)?\s+aborted\b|\btimestep too small\b", text)
    status = ("NOT_MEASURED" if interrupted else "FAIL" if execution.get("returncode") != 0 or failed
              else "NOT_MEASURED" if missing else "PASS")
    if bindings.get("capture") and not capture_path.is_file() and status == "PASS":
        status = "NOT_MEASURED"
        missing.append("native curve capture")
    report.update(status=status, detail="native explicit measurements" + ("; absent: " + ", ".join(missing) if missing else ""),
                  measurements=values, missing=missing, outputs=[str(deck), execution.get("log")])
    if capture_path.is_file():
        report["capture"] = {"path": str(capture_path), "sha256": sha(capture_path),
                             "vectors": list(bindings["capture"])}
        report["outputs"].append(str(capture_path))
    changed = []
    for role, view in report["native_inputs"].items():
        path = Path(view["path"])
        if not path.is_file() or sha(path) != view["sha256"]:
            changed.append(role)
    if changed:
        report.update(status="FAIL" if report["status"] == "FAIL" else "NOT_MEASURED",
                      detail=report["detail"] + "; native inputs changed during execution: " + ", ".join(changed),
                      changed_inputs=changed, measurements={})
    current, why = validate_consumed_inputs(project, report["native_inputs"])
    if not current:
        report.update(status="FAIL" if report["status"] == "FAIL" else "NOT_MEASURED",
                      detail=report["detail"] + "; " + why, measurements={})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--testbench", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args(argv)
    from analog_native_flow import NativeCommands
    runner = NativeCommands(args.project, args.out, args.container, args.image)
    binding_bytes = args.bindings.read_bytes()
    binding_digest = hashlib.sha256(binding_bytes).hexdigest()
    report = run_measurements(args.project.resolve(), args.netlist.resolve(), args.testbench.resolve(),
                              json.loads(binding_bytes), args.out.resolve(), runner)
    report["native_inputs"]["bindings"] = {"path": str(args.bindings.resolve()), "sha256": binding_digest}
    if not args.bindings.is_file() or sha(args.bindings) != binding_digest:
        report.update(status="FAIL" if report["status"] == "FAIL" else "NOT_MEASURED",
                      detail=report["detail"] + "; measurement bindings changed during execution",
                      changed_inputs=report.get("changed_inputs", []) + ["bindings"], measurements={})
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "measurements": report["measurements"],
                      "result": str(args.out / "result.json")}))
    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
