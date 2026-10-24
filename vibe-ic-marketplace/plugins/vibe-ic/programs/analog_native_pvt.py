#!/usr/bin/env python3
"""Consume actual PRE native PVT studies without rerunning or relabeling them."""
from __future__ import annotations

import itertools
import math
from pathlib import Path
import re
import shlex

import analog_a7_post_layout_emit as spice
import analog_bound_measurements as bound
import analog_native_physical as physical
import analog_native_sim as sim
import analog_real_corner_sweep as sweep


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _key(process, temperature, supply, load):
    return (process, float(temperature), round(supply, 12), round(load, 12))


def _conditions(spec):
    """The source's voltage/load extremes and its actual nominal condition."""
    rows = {sweep.normalize_spec_label(row.get("name")) or row.get("name"): row
            for row in spec.get("specs", []) if isinstance(row, dict)}
    result = {}
    scales = {"V": 1, "mV": 1e-3, "uV": 1e-6,
              "A": 1, "mA": 1e-3, "uA": 1e-6, "nA": 1e-9}
    for key, base in (("vin", "V"), ("iout", "A")):
        row = rows.get(key) or {}
        unit = str(row.get("unit", row.get("units", ""))).replace("µ", "u").replace("μ", "u")
        if unit not in scales or not unit.endswith(base) or any(not _number(row.get(edge)) for edge in ("min", "max", "target")):
            raise ValueError(f"source {key} requires finite min/max/target and explicit {base} units")
        values = {edge: row[edge] * scales[unit] for edge in ("min", "max", "target")}
        if values["min"] > values["target"] or values["target"] > values["max"]:
            raise ValueError(f"source {key} nominal is outside its declared range")
        result[key] = values
    points = set(itertools.product((result["vin"]["min"], result["vin"]["max"]),
                                   (result["iout"]["min"], result["iout"]["max"])))
    points.add((result["vin"]["target"], result["iout"]["target"]))
    return result, points


def _net_signature(path):
    """Every electrical card is retained; only process-section tokens vary."""
    lines, processes = [], []
    text = bound.contextual_template(path.read_text(), path.parent)
    for line in spice._joined_lines(text):
        if not line.strip() or line.lstrip().startswith(("*", ";")):
            continue
        tokens = shlex.split(line)
        if tokens[0].casefold() == ".lib" and len(tokens) == 3:
            section = tokens[2].casefold()
            match = re.fullmatch(r"(.*?)(tt|ss|ff)", section)
            if match and (not match[1] or match[1].endswith(("_", ".", "-"))):
                processes.append((tokens[1], section, match[2]))
                tokens[2] = match[1] + "<process>"
            lines.append(tuple([tokens[0].casefold(), tokens[1], tokens[2]]))
        elif tokens[0].casefold() in (".include", ".inc") and len(tokens) == 2:
            lines.append((".include", tokens[1]))
        else:
            lines.append(tuple(token.casefold() for token in tokens))
    if not processes or len({row[2] for row in processes}) != 1:
        raise ValueError("DUT has no single declared TT/SS/FF process selection")
    return lines, processes[0][2], processes


def _circuit_lines(path):
    text = bound.contextual_template(path.read_text(), path.parent)
    text = re.sub(r"(?ims)^\s*\.control\b.*?^\s*\.endc\b[^\n]*", "", text)
    return [shlex.split(line) for line in spice._joined_lines(text)
            if line.strip() and not line.lstrip().startswith(("*", ";"))
            and not re.match(r"(?i)^\s*\.(?:temp|save|op|dc|ac|tran|noise|meas|measure)\b", line)]


def _template_conditions(net, template, canonical_tb, binding, name):
    netlines = spice._joined_lines(net.read_text())
    pins = next((line.split()[2:] for line in netlines
                 if re.match(r"(?i)^\s*\.subckt\s+" + re.escape(name) + r"\s", line)), [])
    lines = _circuit_lines(template)
    instances = [tokens for tokens in lines if tokens[0].casefold().startswith("x")
                 and tokens[-1].casefold() == name.casefold()]
    if len(instances) != 1 or len(instances[0][1:-1]) != len(pins):
        raise ValueError("PVT template does not contain exactly one unchanged source DUT instance")
    nodes = dict(zip((pin.casefold() for pin in pins), instances[0][1:-1]))
    vin = next((nodes[key] for key in ("vin", "vdd", "supply") if key in nodes), None)
    vout = next((nodes[key] for key in ("vout", "out") if key in nodes), None)
    ground = next((nodes[key] for key in ("vss", "gnd", "ground") if key in nodes), None)
    if ground != "0" or vin is None or vout is None:
        raise ValueError("PVT supply/load connections are not explicit source-DUT pins")
    analysis = binding.get("analysis") or {}
    kind = str(analysis.get("kind", "")).upper()
    def source_value(tokens):
        tail = tokens[3:]
        if tail and tail[0].casefold() == "dc":
            tail = tail[1:]
        if not tail or spice.spice_number(tail[0]) is None:
            raise ValueError("PVT source has no explicit DC value")
        dc, magnitude, phase = spice.spice_number(tail[0]), 0., 0.
        tail = tail[1:]
        if tail:
            if kind != "AC" or len(tail) not in (2, 3) or tail[0].casefold() != "ac" \
                    or spice.spice_number(tail[1]) is None or (len(tail) == 3 and spice.spice_number(tail[2]) is None):
                raise ValueError("PVT source is not an explicit constant with a declared AC stimulus")
            magnitude = spice.spice_number(tail[1])
            phase = spice.spice_number(tail[2]) if len(tail) == 3 else 0.
        return dc, magnitude, phase
    selected, values = {}, {}
    for key, source_kind, node in (("vin", "v", vin), ("iout", "i", vout)):
        sources = [tokens for tokens in lines if tokens[0][0].casefold() == source_kind
                   and len(tokens) >= 4 and tokens[1:3] == [node, ground]]
        if len(sources) != 1:
            raise ValueError(f"PVT {key} requires one explicit independent source at its DUT pin")
        tokens = sources[0]
        selected[key], values[key] = tokens[0].casefold(), source_value(tokens)[0]
    psrr = [row for label, row in binding.get("measurements", {}).items()
            if sweep.normalize_spec_label(row.get("spec_key", label)) == "psrr"]
    if psrr:
        if kind != "AC":
            raise ValueError("PVT PSRR requires an actual AC analysis")
        for tokens in lines:
            if tokens[0][0].casefold() not in ("v", "i"):
                continue
            _dc, magnitude, phase = source_value(tokens)
            if tokens[0].casefold() == selected["vin"]:
                if magnitude != 1 or phase != 0:
                    raise ValueError("PVT -VDB PSRR requires unit AC stimulus at the actual DUT supply")
            elif magnitude != 0:
                raise ValueError("PVT PSRR has another active AC source")
        for row in psrr:
            if re.sub(r"\s+", "", str(row.get("expression", ""))).casefold() != f"-vdb({vout})".casefold():
                raise ValueError("PVT PSRR does not measure rejection at the actual DUT output")
            frequency = row.get("frequency_hz")
            if frequency == "last":
                frequency = analysis.get("stop_hz")
            if not _number(frequency) or frequency <= 0 or not all(_number(analysis.get(edge)) for edge in ("start_hz", "stop_hz")) \
                    or not analysis["start_hz"] <= frequency <= analysis["stop_hz"]:
                raise ValueError("PVT PSRR requires a declared native AC measurement frequency")
    if kind == "DC":
        start, stop, step = (analysis.get(key) for key in ("start", "stop", "step"))
        if any(not _number(value) for value in (start, stop, step)) or not step or (stop - start) * step <= 0:
            raise ValueError("PVT DC endpoint is not a finite directed sweep")
        count = (stop - start) / step
        endpoint = start + math.floor(count + 1e-9) * step
        source = str(analysis.get("source", "")).casefold()
        if source not in selected.values():
            raise ValueError("PVT DC sweep is not the declared supply or load source")
        values[next(key for key, value in selected.items() if value == source)] = endpoint
        if any(row.get("at") != "last" for row in binding.get("measurements", {}).values()):
            raise ValueError("PVT DC observations do not all use the actual final sweep point")
    elif kind not in ("OP", "AC"):
        raise ValueError("PVT contexts require actual OP, endpoint DC or explicit AC measurements")

    def signature(path):
        result = []
        for tokens in _circuit_lines(path):
            command = tokens[0].casefold()
            if command in (".include", ".inc") and len(tokens) == 2:
                # Only the exact corresponding DUT include may vary.
                expected_net = net if path == template else canonical_tb.parent / (name + ".sp")
                tokens = [".include", "<DUT>" if Path(tokens[1]).resolve() == expected_net.resolve() else tokens[1]]
            elif command in selected.values():
                tokens = [*tokens[:3], "<condition>"]
            result.append(tuple(token.casefold() for token in tokens))
        return result
    if signature(template) != signature(canonical_tb):
        raise ValueError("PVT template changes the source circuit beyond supply/load conditions")
    return values


def run_pvt_studies(project: Path, name: str, reference: dict) -> dict:
    """Derive current PRE PVT evidence from an ordinary native-results manifest."""
    project = Path(project).resolve()
    bdir, _work = physical._paths(project, name)
    net, spec, tb = bdir / (name + ".sp"), bdir / "spec.json", bdir / ("tb_" + name + ".sp")
    consumed, outputs, rows, gaps, seen, failed = {}, [], [], [], set(), False
    measured_contexts, psrr_frequency = set(), None
    try:
        if not isinstance(reference, dict) or not reference.get("path"):
            raise ValueError("PVT result requires an actual manifest path and sha256")
        manifest_path = (project / reference["path"]).resolve()
        if not physical._current_native_views({"manifest": {**reference, "path": str(manifest_path)}}):
            raise ValueError("PVT manifest is absent or its referenced hash changed")
        manifest = physical._read(manifest_path)
        base = manifest.get("source_netlist") or {}
        if not net.is_file() or base.get("sha256") != physical._sha(net) or not physical._current_native_views({"base": base}):
            raise ValueError("PVT manifest source base is not the current canonical PRE DUT")
        base_signature, _process, _libs = _net_signature(net)
        domain, conditions = _conditions(physical._read(spec))
        expected = {_key(process, temperature, supply, load)
                    for (process, _offset), (_label, temperature, _delta), (supply, load)
                    in itertools.product(sweep.PVT_PROCESS, sweep.PVT_TEMPS, conditions)}
        consumed = {"manifest": {"path": str(manifest_path), "sha256": physical._sha(manifest_path)},
                    "source_netlist": {"path": str(net), "sha256": physical._sha(net)},
                    "source_spec": {"path": str(spec), "sha256": physical._sha(spec)},
                    "source_testbench": {"path": str(tb), "sha256": physical._sha(tb)}}
        outputs.append(str(manifest_path))
        entries = manifest.get("rows")
        if not isinstance(entries, list) or not entries:
            raise ValueError("PVT manifest has no actual native context records")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return physical._result("NOT_MEASURED", str(exc), native_inputs=consumed, metrics={"stage": "PRE"})

    limits = physical._required_limits(project, name)
    required = sorted(limits)
    coverage = {key: set() for key in required}
    for index, entry in enumerate(entries):
        try:
            path = (project / entry["result"]).resolve()
            record = physical._read(path)
            views = record.get("native_inputs") or {}
            variant = Path(views["netlist"]["path"])
            binding = record["bindings"]
            declared = binding.get("integration_condition") or {}
            if not physical._current_native_views(views):
                raise ValueError("native PVT consumed inputs changed or are absent")
            if variant.resolve() != net.resolve() and (views.get("source_netlist") or {}).get("sha256") != consumed["source_netlist"]["sha256"]:
                raise ValueError("PVT variant lacks its exact canonical source-base input")
            signature, process, selections = _net_signature(variant)
            if signature != base_signature:
                raise ValueError("PVT variant electrical cards/model paths differ beyond declared process selection")
            declared_process = str(declared.get("process", declared.get("mos_corner", ""))).casefold()
            if declared_process not in {process, *(section for _path, section, _process in selections)}:
                raise ValueError("PVT process declaration differs from its actual model section")
            actual = _template_conditions(variant, Path(views["testbench"]["path"]), tb, binding, name)
            temperature = binding["analysis"].get("temperature_c")
            if not _number(temperature) or not _number(declared.get("temp_c")) or temperature != declared["temp_c"]:
                raise ValueError("PVT temperature declarations differ or are absent")
            if any(not _number(declared.get(key)) or not math.isclose(declared[key], actual[field], rel_tol=0, abs_tol=1e-12)
                   for key, field in (("vin_v", "vin"), ("load_a", "iout"))):
                raise ValueError("PVT declared supply/load differs from actual template or DC endpoint")
            key = _key(process, temperature, actual["vin"], actual["iout"])
            if key not in expected:
                raise ValueError("PVT context is outside the source-selected corner/operating matrix")
            prefix = f"context:{index}:"
            consumed[prefix + "result"] = {"path": str(path), "sha256": physical._sha(path)}
            consumed.update({prefix + role: view for role, view in views.items()})
            outputs.append(str(path))
            candidate = {"metrics": {"native_measurement_studies": [{"result": str(path),
                "bindings_path": views.get("bindings", {}).get("path"), "status": record.get("status")}]}}
            measured, state = physical._pre_measurement_study(project, variant, [candidate], physical._native_values, ("OP", "DC", "AC"))
            for j, execution in enumerate(record.get("executions", [])):
                view = {"path": execution.get("log"), "sha256": execution.get("log_sha256")}
                consumed[prefix + f"log:{j}"] = view
                outputs.append(view["path"])
            if state.get("status") == "FAIL":
                failed = True
                rows.append({"context": list(key), "status": "FAIL", "detail": state["detail"], "result": str(path)})
                continue
            if not measured:
                raise ValueError(state.get("detail", "native PVT measurements incomplete"))
            deck_status, deck_detail, _required = sim._validate_deck(variant, Path(views["deck"]["path"]),
                {"required_measurements": list(binding.get("measurements", {}))})
            if deck_status != "PASS":
                raise ValueError("PVT native measurement definitions invalid: " + deck_detail)
            capture = Path(record["capture"]["path"]) if record.get("capture") else Path(views["deck"]["path"]).parent / "curve.dat"
            regenerated = bound.emit_deck(bound.contextual_template(Path(views["testbench"]["path"]).read_text(),
                Path(views["testbench"]["path"]).parent), binding, capture)
            if regenerated != Path(views["deck"]["path"]).read_text():
                raise ValueError("PVT executed deck differs from actual template and measurement bindings")
            consumed.update({prefix + role: view for role, view in state.get("comparison_inputs", {}).items()})
            observations = sim.attributed_study_measurements(spec, binding, measured)
            violation = any(row.get("violation") for row in observations)
            failed = failed or violation
            present = {row["name"] for row in observations if row.get("status") == "PASS"}
            if any((key, output) in measured_contexts for output in present):
                raise ValueError("duplicate PVT output/context cannot substitute for a missing corner/condition")
            if any(row["name"] == "psrr" for row in observations):
                frequencies = {value.get("frequency_hz") if value.get("frequency_hz") != "last" else binding["analysis"].get("stop_hz")
                    for label, value in binding["measurements"].items()
                    if sweep.normalize_spec_label(value.get("spec_key", label)) == "psrr"}
                if len(frequencies) != 1 or (psrr_frequency is not None and psrr_frequency not in frequencies):
                    raise ValueError("PVT PSRR measurement frequency differs between contexts")
                psrr_frequency = next(iter(frequencies))
            seen.add(key)
            measured_contexts.update((key, output) for output in present)
            for row in observations:
                if row.get("status") == "PASS":
                    coverage[row["name"]].add(key)
            rows.append({"context": list(key), "status": "FAIL" if violation else "PASS", "result": str(path),
                         "analysis": binding["analysis"],
                         "source_observations": observations, "measurements": measured,
                         "native_temperatures_c": state["native_temperatures_c"]})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            gaps.append({"row": index, "detail": str(exc)})
    missing_contexts = sorted(expected - seen)
    missing_outputs, measured_outputs, matrix = [], [], {}
    for key in required:
        selected = {context for context in expected if key != "dropout" or
                    math.isclose(context[2], domain["vin"]["min"], rel_tol=0, abs_tol=1e-12)}
        missing = selected - coverage[key]
        matrix[key] = {"required_contexts": len(selected), "measured_contexts": len(coverage[key] & selected),
                       "missing_contexts": [list(context) for context in sorted(missing)]}
        (missing_outputs if missing else measured_outputs).append(key)
    if not physical._current_native_views(consumed):
        gaps.append({"detail": "PVT consumed files changed during reference-only derivation"})
    status = "FAIL" if failed else "NOT_MEASURED" if gaps or missing_contexts or missing_outputs else "PASS"
    return physical._result(status, "current PRE native PVT study measurements" +
        ("; missing source outputs: " + ", ".join(missing_outputs) if missing_outputs else ""),
        sorted({path for path in outputs if path}), native_inputs=consumed,
        metrics={"stage": "PRE", "total_corners": len(expected), "corners_executed": len(seen),
                 "psrr_measurement_frequency_hz": psrr_frequency,
                 "psrr_scope": "rejection only at the declared measurement point; no source-provided/all-frequency band is inferred",
                 "full_pvt_sweep_executed": not missing_contexts and not gaps,
                 "design_traceable": not gaps, "spec_results": [observation for row in rows
                    for observation in row.get("source_observations", [])],
                 "source_measurement_coverage": {"required": required, "measured": measured_outputs,
                                                 "missing": missing_outputs},
                 "source_context_coverage": matrix, "missing_contexts": [list(key) for key in missing_contexts],
                 "gaps": gaps, "contexts": rows})
