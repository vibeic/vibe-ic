#!/usr/bin/env python3
"""Prepare, run, or independently collect actual incremental ADC PVT series.

Preparation changes only owned model sections and temperature in private
runtime input views. Collection launches no native jobs. Every corner must
retain a complete source-bound coherent series; scalar/density substitutes
and arithmetic corner estimates are not accepted.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import itertools
import json
import math
from pathlib import Path
import re
import shlex
import sys

import analog_bound_measurements as bound
import analog_incremental_capture as capture
import analog_a7_post_layout_emit as spice
import analog_native_physical as physical
import analog_native_sim as sim
import analog_pdk_deck_context as models
import analog_real_corner_sweep as sweep


def _view(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": bound.sha(path)}


def _current(views):
    return physical._current_native_views(views)


def _net_signature(path):
    """Retain every electrical card while normalizing only its PVT token."""
    lines, processes = [], []
    text = bound.contextual_template(Path(path).read_text(), Path(path).parent)
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
            lines.append((tokens[0].casefold(), tokens[1], tokens[2]))
        elif tokens[0].casefold() in (".include", ".inc") and len(tokens) == 2:
            lines.append((".include", tokens[1]))
        else:
            lines.append(tuple(token.casefold() for token in tokens))
    if not processes or len({row[2] for row in processes}) != 1:
        raise ValueError("DUT has no single declared TT/SS/FF process selection")
    return lines, processes[0][2], processes


def _paths(project, block):
    bdir = Path(project) / "phase3/analog" / block
    return {"netlist": bdir / (block + ".sp"), "testbench": bdir / ("tb_" + block + ".sp"),
            "spec": bdir / "spec.json", "topology": bdir / "topology.json"}


def _template(source, source_net, target_net, temperature):
    text = bound.contextual_template(source.read_text(), source.parent)
    count = 0
    lines = []
    for line in text.splitlines():
        tokens = shlex.split(line) if line.strip() and not line.lstrip().startswith("*") else []
        if tokens and tokens[0].casefold() in (".include", ".inc") and len(tokens) == 2 \
                and Path(tokens[1]).resolve() == source_net.resolve():
            line = ".include " + str(target_net.resolve())
            count += 1
        lines.append(line)
    if count != 1:
        raise ValueError("source testbench must include the exact declared DUT once")
    text, applied = sweep.stamp_temp_card("\n".join(lines) + "\n", temperature)
    if applied.get("temp_c") != temperature:
        raise ValueError("native corner temperature could not be stamped")
    return text


def _coordinates(sections):
    labels = []
    for section in sections:
        match = re.search(r"(?:^|[_\-.])(tt|ss|ff)$", str(section), re.I)
        if not match:
            raise ValueError("process sections must identify actual TT/SS/FF entries")
        labels.append(match[1].casefold())
    if len(sections) != 3 or set(labels) != {"tt", "ss", "ff"}:
        raise ValueError("exactly one actual TT, SS and FF section is required")
    return {section: label for section, label in zip(sections, labels)}


def _reference_ports(spec_path, topology_path, pair):
    required = sim._source_measurement_coverage(Path(spec_path), [])['required']
    if (pair is None or pair == []) and 'vref' not in required:
        return []
    ports = [str(port).casefold() for port in json.loads(Path(topology_path).read_text()).get('ports', [])]
    if (not isinstance(pair, (list, tuple)) or len(pair) != 2
            or not all(isinstance(port, str) and port for port in pair)):
        raise ValueError('explicit positive/negative reference ports are required')
    pair = [port.casefold() for port in pair]
    if pair[0] == pair[1] or any(port not in ports for port in pair):
        raise ValueError('reference ports must be distinct declared DUT ports')
    return pair


def _reference_measurement(point, transcript, reference_ports):
    """Observe the actual native reference pair held by ideal constant sources.

    The initial table alone proves no ramped supply or arbitrary waveform.
    Here its two observed node voltages remain the reference throughout the
    transient because the exact executed deck drives those DUT pins with
    independent constant voltage sources. No cached metric is read.
    """
    views = point["native_inputs"]
    spec_path, net = Path(views["spec"]["path"]), Path(views["netlist"]["path"])
    topology = json.loads(Path(views["topology"]["path"]).read_text())
    ports = [str(port).casefold() for port in topology.get("ports", [])]
    positive, negative = _reference_ports(spec_path, views['topology']['path'], reference_ports)
    declared = [line.split() for line in net.read_text().splitlines() if re.match(r"(?i)^\s*\.subckt\s", line)]
    declared = [tokens for tokens in declared if [port.casefold() for port in tokens[2:]] == ports]
    if len(declared) != 1:
        raise ValueError("reference ports are not the declared DUT subcircuit interface")
    deck = Path(views["deck"]["path"]).read_text()
    top = re.sub(r"(?ims)^\s*\.subckt\b.*?^\s*\.ends\b[^\n]*", "", deck)
    instances = []
    for line in top.splitlines():
        if not re.match(r"(?i)^\s*x\S+\s", line):
            continue
        fields = shlex.split(line)
        split = next((index for index, value in enumerate(fields) if "=" in value), len(fields))
        if fields[split - 1].casefold() == declared[0][1].casefold():
            instances.append(fields[1:split - 1])
    if len(instances) != 1 or len(instances[0]) != len(ports):
        raise ValueError("native reference table is not bound to exactly one instance of the declared DUT")
    nodes = {name: node.casefold() for name, node in zip(ports, instances[0])}
    sources = capture.stimulus.deck_facts(deck)["sources"]
    bindings = {}
    for port in (positive, negative):
        selected = [source for source in sources if source["pos"].casefold() == nodes[port]]
        if len(selected) != 1 or selected[0]["neg"] != "0" or selected[0]["dc_v"] is None \
                or not math.isfinite(selected[0]["dc_v"]):
            raise ValueError("reference stability is not established by explicit ideal constant DC sources")
        bindings[port] = selected[0]
    tables, lines = [], transcript.splitlines()
    for index, line in enumerate(lines):
        if line.strip().casefold() != "initial transient solution":
            continue
        header = next((j for j in range(index + 1, min(index + 10, len(lines)))
                       if re.fullmatch(r"\s*Node\s+Voltage\s*", lines[j], re.I)), None)
        if header is None:
            continue
        found, started = {}, False
        for row in lines[header + 1:]:
            if not row.strip():
                if started:
                    break
                continue
            if re.fullmatch(r"[-\s]+", row):
                continue
            fields = row.replace("=", " ").split()
            if len(fields) != 2:
                break
            started = True
            node = fields[0].casefold()
            if node in (nodes[positive], nodes[negative]):
                if node in found:
                    raise ValueError("native initial reference table has duplicate node values")
                try:
                    value = float(fields[1])
                except ValueError:
                    raise ValueError("native initial reference voltage is not numeric") from None
                if not math.isfinite(value):
                    raise ValueError("native initial reference voltage is not finite")
                found[node] = (value, fields[1])
        if any(nodes[port] not in found for port in bindings):
            raise ValueError("native initial reference table is missing a DUT reference node")
        for port, source in bindings.items():
            if not math.isclose(found[nodes[port]][0], source["dc_v"], rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError("native reference value differs from its executed constant source")
        tables.append(found)
    if not tables:
        raise ValueError("native initial transient reference table is absent")
    raw = [float(Decimal(table[nodes[positive]][1]) - Decimal(table[nodes[negative]][1])) for table in tables]
    if any(value != raw[0] for value in raw):
        raise ValueError("native initial reference tables disagree")
    spec = json.loads(spec_path.read_text())
    rows = [row for row in spec.get("specs", []) if sweep.normalize_spec_label(row.get("name")) == "vref"]
    if len(rows) != 1:
        raise ValueError("one source Vref requirement is required for attribution")
    unit = str(rows[0].get("unit", rows[0].get("units", ""))).replace("µ", "u").replace("μ", "u")
    scale = {"V": 1, "mV": 1e-3, "uV": 1e-6}.get(unit)
    if scale is None:
        raise ValueError("source reference voltage units are unsupported or absent")
    graded = sim.attributed_study_measurements(spec_path,
        {"measurements": {"vref": {"analysis": "OP", "unit": unit}}}, {"vref": raw[0] / scale})
    if len(graded) != 1 or graded[0]["status"] != "PASS":
        raise ValueError("source reference voltage limits/units are incomplete")
    return {**graded[0], "reference_ports": {"positive": positive, "negative": negative},
        "native_difference_v": raw[0], "native_nodes_v": {
        nodes[port]: tables[0][nodes[port]][0] for port in bindings},
        "constant_sources": {port: {key: value[key] for key in ("name", "pos", "neg", "dc_v")}
                             for port, value in bindings.items()},
        "scope": "native initial node observations held for the transient by executed ideal DC reference sources"}


def prepare(project, block, settings_path, destination, model_lib, process_sections, nominal_score=None, image=None,
            reference_ports=None):
    """Materialize nine small input views; this function never runs ngspice."""
    project, destination, model_lib = Path(project).resolve(), Path(destination).resolve(), Path(model_lib).resolve()
    if not re.fullmatch(r"[A-Za-z_][\w.-]*", block):
        raise ValueError("invalid declared block name")
    paths = _paths(project, block)
    settings_path = Path(settings_path).resolve()
    common = json.loads(settings_path.read_text())
    capture.phase_settings(common, 0)
    common.setdefault("threads", 1)
    common.setdefault("openmp_wait_policy", "PASSIVE")
    source_template = Path(common.get("testbench", paths["testbench"]))
    if not source_template.is_absolute():
        source_template = project / source_template
    paths["testbench"] = source_template.resolve()
    # The existing corner builder consumes the canonical delivered pair.
    # An alternate source template is supported by copying it into each view.
    spec = json.loads(paths["spec"].read_text())
    capture.source_enob_min(spec)
    reference_ports = _reference_ports(paths['spec'], paths['topology'], reference_ports)
    capture.prepare_deck(paths["testbench"], spec, json.loads(paths["topology"].read_text()),
                         capture.phase_settings(common, 0), destination / "method-preview")
    process = _coordinates(list(process_sections))
    available = {section.casefold() for section in models.parse_sections(model_lib.read_text())}
    if any(section.casefold() not in available for section in process):
        raise ValueError("requested process section is absent from the actual model library")
    source_signature, source_process, _selected = _net_signature(paths["netlist"])
    if source_process != "tt":
        raise ValueError("nominal source DUT is not bound to its actual TT model section")
    cards = [shlex.split(line) for line in bound.contextual_template(paths["netlist"].read_text(), paths["netlist"].parent).splitlines()
             if line.strip() and not line.lstrip().startswith("*")]
    primary = [tokens for tokens in cards if tokens[0].casefold() == ".lib" and len(tokens) == 3
               and Path(tokens[1]).resolve() == model_lib]
    if len(primary) != 1 or primary[0][2] not in process or process[primary[0][2]] != "tt":
        raise ValueError("model-lib does not identify the actual single TT process card in the source DUT")
    inputs = {role: _view(path) for role, path in paths.items()}
    inputs.update(settings=_view(settings_path), model_lib=_view(model_lib))
    inputs.update({"source:" + role: value for role, value in bound.consumed_input_views(project, paths["testbench"]).items()})
    destination.mkdir(parents=True, exist_ok=False)
    producer_origins = {}
    metadata = destination / 'producer-sources'
    metadata.mkdir()
    for role, source in (('producer', Path(__file__)), ('incremental_producer', Path(capture.__file__))):
        snapshot = metadata / source.name
        snapshot.write_bytes(source.read_bytes())
        inputs[role] = _view(snapshot)
        producer_origins[role] = {'path': str(source.resolve()), 'sha256': inputs[role]['sha256']}
    contexts = []
    for section, (_temp_label, temperature, _offset) in itertools.product(process, sweep.PVT_TEMPS):
        label = section + "_" + str(temperature).replace("-", "m")
        root = destination / label
        root.mkdir()
        reuse = nominal_score is not None and process[section] == "tt" and temperature == 27
        if reuse:
            context_project = project
            context_paths = paths
            effective = common
            score = Path(nominal_score).resolve()
        else:
            context_project = root / "project"
            context_paths = _paths(context_project, block)
            context_paths["netlist"].parent.mkdir(parents=True)
            for role in ("spec", "topology"):
                context_paths[role].symlink_to(paths[role])
            for name in ("input", "phase1"):
                if (project / name).exists():
                    (context_project / name).symlink_to(project / name, target_is_directory=True)
            contextual = bound.contextual_template(paths["netlist"].read_text(), paths["netlist"].parent)
            # The existing corner builder accepts one-token library paths.
            # Contextualization quotes absolute paths; serialize equivalent
            # tokens for that API without changing any electrical card.
            native_lines = []
            for line in contextual.splitlines():
                tokens = shlex.split(line) if line.strip() and not line.lstrip().startswith("*") else []
                if tokens and tokens[0].casefold() == ".lib" and len(tokens) == 3:
                    if re.search(r"\s", tokens[1]):
                        raise ValueError("existing corner builder cannot materialize whitespace-bearing model paths")
                    line = ".lib " + tokens[1] + " " + tokens[2]
                native_lines.append(line)
            context_paths["netlist"].write_text("\n".join(native_lines) + "\n")
            context_paths["testbench"].write_text(_template(paths["testbench"], paths["netlist"], context_paths["netlist"], temperature))
            deck, info = sweep.build_design_deck(context_project, block, str(model_lib), section,
                temp_c=temperature, corner_sections=list(process))
            if deck is None:
                raise ValueError("existing corner materializer refused the source pair: " + str(info))
            start = f"* --- inlined {block}.sp (A3 block netlist) ---\n"
            end = f"\n* --- end {block}.sp ---"
            if deck.count(start) != 1 or deck.count(end) != 1:
                raise ValueError("existing corner materializer did not retain the single delivered DUT")
            derived = deck.split(start, 1)[1].split(end, 1)[0]
            context_paths["netlist"].write_text(derived + "\n")
            signature, actual_process, _libs = _net_signature(context_paths["netlist"])
            if signature != source_signature or actual_process != process[section]:
                raise ValueError("corner materialization changed the source electrical cards/model set")
            effective = {**common, "testbench": str(context_paths["testbench"])}
            score = root / "series/score.json"
        effective_path = root / "common.json"
        physical._write(effective_path, effective)
        contexts.append({"process": section, "process_label": process[section], "temperature_c": temperature,
            "project": str(context_project), "settings": _view(effective_path), "score": str(score),
            "reuse_only": reuse, "native_inputs": {role: _view(path) for role, path in context_paths.items()}})
    if not _current(inputs):
        raise ValueError("source inputs changed during corner preparation")
    return {"kind": "incremental_capture_pvt", "operation": "prepare", "stage": "PRE", "block": block,
            "project": str(project), "status": "PASS", "detail": "nine corner input views prepared; no native series executed",
            "process_sections": list(process), "common_settings": common, "image": image,
            "reference_ports": reference_ports,
            "producer_origins": producer_origins,
            "native_inputs": inputs, "contexts": contexts}


def _validate_manifest(manifest):
    if manifest.get("kind") != "incremental_capture_pvt" or manifest.get("stage") != "PRE":
        raise ValueError("actual PRE incremental PVT input manifest required")
    inputs = manifest.get("native_inputs") or {}
    if not _current(inputs):
        raise ValueError("incremental PVT source inputs are absent or changed")
    declared_paths = _paths(Path(manifest["project"]).resolve(), manifest["block"])
    for role in ("netlist", "spec", "topology"):
        if Path(inputs[role]["path"]).resolve() != declared_paths[role].resolve():
            raise ValueError("PVT manifest project/block does not identify its actual source DUT")
    pair = _reference_ports(inputs['spec']['path'], inputs['topology']['path'], manifest.get('reference_ports'))
    if pair != manifest.get('reference_ports'):
        raise ValueError('PVT reference-port declaration is not the prepared immutable list')
    sections = _coordinates(manifest["process_sections"])
    expected = {(section, temp) for section, (_label, temp, _offset) in itertools.product(sections, sweep.PVT_TEMPS)}
    contexts = manifest.get("contexts")
    if not isinstance(contexts, list) or len(contexts) != len(expected):
        raise ValueError("exactly nine actual process/temperature contexts are required")
    seen = set()
    source_net, source_tb = Path(inputs["netlist"]["path"]), Path(inputs["testbench"]["path"])
    source_signature, _process, _libs = _net_signature(source_net)
    common = manifest["common_settings"]
    original = json.loads(Path(inputs["settings"]["path"]).read_text())
    original.setdefault("threads", 1)
    original.setdefault("openmp_wait_policy", "PASSIVE")
    if common != original:
        raise ValueError("PVT common settings differ from the source nominal method")
    for context in contexts:
        coordinate = (context["process"], context["temperature_c"])
        if coordinate not in expected or coordinate in seen:
            raise ValueError("duplicate or unexpected incremental PVT corner")
        seen.add(coordinate)
        views = context["native_inputs"]
        if not _current(views) or not _current({"settings": context["settings"]}):
            raise ValueError("prepared corner input bytes changed")
        signature, label, _libs = _net_signature(Path(views["netlist"]["path"]))
        if signature != source_signature or label != sections[coordinate[0]]:
            raise ValueError("PVT DUT differs beyond its declared process section")
        for role in ("spec", "topology"):
            if views[role]["sha256"] != inputs[role]["sha256"]:
                raise ValueError("PVT context changed the source specification/topology")
        settings = json.loads(Path(context["settings"]["path"]).read_text())
        if context.get("reuse_only"):
            if coordinate != (next(section for section, label in sections.items() if label == "tt"), 27) \
                    or views != {role: inputs[role] for role in ("netlist", "testbench", "spec", "topology")} or settings != common:
                raise ValueError("only the exact nominal source context may reuse its A07 series")
        else:
            expected_tb = _template(source_tb, source_net, Path(views["netlist"]["path"]), coordinate[1])
            if Path(views["testbench"]["path"]).read_text() != expected_tb \
                    or settings != {**common, "testbench": views["testbench"]["path"]}:
                raise ValueError("PVT stimulus/settings differ beyond declared temperature/model context")
    return contexts


def collect(manifest):
    """Replay actual per-corner native scores; never launch missing conversions."""
    rows, inputs, outputs, failed, incomplete, images = [], dict(manifest.get("native_inputs") or {}), [], False, False, set()
    try:
        contexts = _validate_manifest(manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return physical._result("NOT_MEASURED", str(exc), native_inputs=inputs, metrics={"stage": "PRE"})
    spec_path = Path(inputs["spec"]["path"])
    source_spec = json.loads(spec_path.read_text())
    target = capture.source_enob_min(source_spec)
    required = sim._source_measurement_coverage(spec_path, [])["required"]
    for index, context in enumerate(contexts):
        prefix = f"corner:{index}:"
        inputs.update({prefix + role: view for role, view in context["native_inputs"].items()})
        inputs[prefix + "common_settings"] = context["settings"]
        try:
            reference_rows, reference_gaps, phases = [], [], set()
            score_path = Path(context["score"])
            score = json.loads(score_path.read_text()) if score_path.is_file() else {}
            expected_settings = json.loads(Path(context["settings"]["path"]).read_text())
            points = score.get("points")
            score_missing = not isinstance(points, list) or not points
            if score_missing:
                # A failed first conversion need not have produced a score.
                # Inspect only this exact series' retained point receipts;
                # current native failure must not become missing performance.
                points = [_view(path) for path in sorted(score_path.parent.glob("point-[0-9][0-9][0-9]/result.json"))]
            if not points:
                raise ValueError("corner has no actual native point references")
            outputs.append(str(score_path.parent))
            for entry in points:
                point_path = Path(entry["path"])
                if not point_path.is_file() or entry.get("sha256") != bound.sha(point_path):
                    raise ValueError("native corner point reference changed or is absent")
                point = json.loads(point_path.read_text())
                views = point.get("native_inputs") or {}
                phase = point.get("settings", {}).get("phase_index")
                phases.add(phase)
                if point.get("settings") != capture.phase_settings(expected_settings, phase) \
                        or any(views.get(role, {}).get("sha256") != view["sha256"]
                               for role, view in context["native_inputs"].items()):
                    raise ValueError("native point does not belong to the exact prepared corner/method")
                current, reason = bound.validate_consumed_inputs(Path(context["project"]), views)
                if not current or not _current(views) or not capture.declared_dut_consumed(views):
                    raise ValueError("corner native input closure is not current: " + reason)
                if not point.get("image") or (manifest.get("image") and point["image"] != manifest["image"]):
                    raise ValueError("corner native image differs from the prepared runtime")
                images.add(point["image"])
                inputs.update({prefix + f"point:{phase}:" + role: view for role, view in views.items()})
                if capture.native_execution_failure(point):
                    failed = True
                    raise ValueError("native corner conversion execution failed")
                for execution in point.get("executions") or []:
                    log = Path(execution["log"])
                    if execution.get("log_sha256") != bound.sha(log):
                        raise ValueError("native corner transcript changed")
                    inputs[prefix + f"point:{phase}:log"] = _view(log)
                    temperatures = [float(value) for value in re.findall(
                        r"Doing analysis at TEMP\s*=\s*([-+.\deE]+)", log.read_text(errors="replace"))]
                    if not temperatures or any(not math.isclose(value, context["temperature_c"], rel_tol=0, abs_tol=1e-6)
                                               for value in temperatures):
                        raise ValueError("actual native TEMP differs from its PVT context")
                    if "vref" in required:
                        try:
                            observation = _reference_measurement(point, log.read_text(errors="replace"), manifest['reference_ports'])
                            reference_rows.append({"phase_index": phase, **observation})
                            failed = failed or observation["violation"]
                        except (OSError, ValueError, KeyError, TypeError) as exc:
                            reference_gaps.append({"phase_index": phase, "detail": str(exc)})
            if score_missing:
                raise ValueError("full native corner series/score has not completed")
            replayed = capture.replay_score(score_path)
            outputs += replayed.get("outputs", [])
            status = replayed.get("status", "NOT_MEASURED")
            values = replayed.get("measurements") or {}
            if status == "PASS" and (replayed.get("target_bits") != target or
                    not isinstance(values.get("enob"), (int, float)) or values["enob"] < target):
                raise ValueError("native corner resolution is not graded against the current source minimum")
            measured_outputs = []
            enob = values.get("enob")
            if isinstance(enob, (int, float)) and not isinstance(enob, bool) and math.isfinite(enob):
                measured_outputs.append("enob")
            if "vref" in required:
                complete = (phases == set(range(expected_settings["series_length"])) and
                            len(reference_rows) == len(phases) and not reference_gaps)
                if complete:
                    measured_outputs.append("vref")
                    values["vref"] = reference_rows[0]["value"]
                if any(row["violation"] for row in reference_rows):
                    status = "FAIL"
                elif not complete and status != "FAIL":
                    status = "NOT_MEASURED"
            failed = failed or status == "FAIL"
            incomplete = incomplete or status not in ("PASS", "FAIL") or bool(set(required) - set(measured_outputs))
            rows.append({"process": context["process"], "temperature_c": context["temperature_c"],
                         "status": status, "score": str(score_path), "measurements": values,
                         "resolution_status": replayed.get("status", "NOT_MEASURED"),
                         "measured_outputs": measured_outputs, "reference_observations": reference_rows,
                         "reference_gaps": reference_gaps,
                         "scope": replayed.get("scope"), "detail": replayed.get("detail")})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            incomplete = True
            reference_failed = any(row.get("violation") for row in reference_rows)
            failed = failed or reference_failed
            rows.append({"process": context["process"], "temperature_c": context["temperature_c"],
                         "status": "FAIL" if reference_failed or "native corner conversion execution failed" in str(exc) else "NOT_MEASURED",
                         "reference_observations": reference_rows, "reference_gaps": reference_gaps,
                         "detail": ("source Vref bound violation; " if reference_failed else "") + str(exc)})
    gaps = []
    if not _current(inputs):
        gaps.append("consumed native inputs changed during collection")
    if len(images) > 1:
        gaps.append("PVT series use different native runtime images")
    if gaps:
        incomplete = True
    status = "FAIL" if failed else "NOT_MEASURED" if incomplete else "PASS"
    source_coverage = {key: {"required_contexts": 9,
        "measured_contexts": sum(key in row.get("measured_outputs", []) for row in rows),
        "missing_contexts": [{"process": row["process"], "temperature_c": row["temperature_c"]}
                             for row in rows if key not in row.get("measured_outputs", [])],
        "gaps": [{"process": row["process"], "temperature_c": row["temperature_c"],
                  "detail": row.get("reference_gaps") if key == "vref" else row.get("detail")}
                 for row in rows if key not in row.get("measured_outputs", [])]} for key in required}
    measured = [key for key, coverage in source_coverage.items() if coverage["measured_contexts"] == 9]
    return physical._result(status, "native incremental SNDR/ENOB across actual PVT contexts", sorted(set(outputs)),
        native_inputs=inputs, metrics={"stage": "PRE", "total_corners": 9, "corners_executed": sum(row["status"] in ("PASS", "FAIL") for row in rows),
            "full_pvt_sweep_executed": not incomplete, "design_traceable": not gaps,
            "target_bits": target, "contexts": rows, "gaps": gaps,
            "scope": "process/temperature at the exact selected source operating configuration; deterministic transient SNDR; device noise not added",
            "spec_results": [{"name": key, "status": ("FAIL" if key == "vref" and any(
                    value.get("violation") for value in row.get("reference_observations", [])) else
                    (row.get("resolution_status", "NOT_MEASURED") if key == "enob" else "PASS")
                    if key in row.get("measured_outputs", []) else "NOT_MEASURED"),
                "value": row.get("measurements", {}).get(key), "target": target if key == "enob" else None,
                "process": row["process"], "temperature_c": row["temperature_c"]} for row in rows for key in required],
            "source_context_coverage": source_coverage,
            "source_measurement_coverage": {"required": required, "measured": measured,
                "missing": sorted(set(required) - set(measured))}})


def run(manifest, container, image, workers=1, cpus=1, launch=None):
    """Share one bounded phase-worker/CPU budget across native corner series."""
    contexts = _validate_manifest(manifest)
    threads = manifest["common_settings"].get("threads", 1)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (workers, cpus, threads)) or cpus < threads:
        raise ValueError("positive bounded workers/CPU budget must accommodate native threads")
    candidates = [context for context in contexts if not context.get("reuse_only")]
    width = min(len(candidates), workers, cpus // threads)
    inner = min(workers // max(width, 1), cpus // (max(width, 1) * threads))
    if manifest.get("image") and image != manifest["image"]:
        raise ValueError("requested native image differs from the prepared runtime")
    before = collect(manifest)
    reused = [context for context in contexts if context.get("reuse_only")]
    if before["status"] in ("PASS", "FAIL") or any(row["status"] != "PASS" for row in before.get("metrics", {}).get("contexts", [])
            if any(context["process"] == row["process"] and context["temperature_c"] == row["temperature_c"] for context in reused)):
        return before
    def one(context):
        return (launch or capture.series_main)([context["project"], "--block", manifest["block"],
            "--settings", context["settings"]["path"], "--out", str(Path(context["score"]).parent),
            "--score", context["score"], "--container", container, "--image", image,
            "--workers", str(inner), "--cpus", str(inner * threads)])
    with ThreadPoolExecutor(max_workers=width) as executor:
        codes = list(executor.map(one, candidates))
    result = collect(manifest)
    result.setdefault("metrics", {})["execution_budget"] = {"series_returncodes": codes,
        "corner_workers": width, "phase_workers_per_series": inner,
        "native_threads_per_phase": threads, "total_phase_workers": width * inner,
        "total_cpu_ceiling": width * inner * threads}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("project", type=Path)
    prepare_parser.add_argument("--block", required=True)
    prepare_parser.add_argument("--settings", type=Path, required=True)
    prepare_parser.add_argument("--out", type=Path, required=True)
    prepare_parser.add_argument("--model-lib", type=Path, required=True)
    prepare_parser.add_argument("--process-sections", nargs=3, required=True)
    prepare_parser.add_argument("--reference-ports", nargs=2, metavar=('POSITIVE', 'NEGATIVE'))
    prepare_parser.add_argument("--nominal-score", type=Path)
    prepare_parser.add_argument("--image")
    prepare_parser.add_argument("--json", type=Path, required=True)
    for operation in ("run", "collect"):
        command = commands.add_parser(operation)
        command.add_argument("manifest", type=Path)
        command.add_argument("--json", type=Path, required=True)
        if operation == "run":
            command.add_argument("--container", required=True)
            command.add_argument("--image", required=True)
            command.add_argument("--workers", type=int, default=1)
            command.add_argument("--cpus", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.operation == "prepare":
            report = prepare(args.project, args.block, args.settings, args.out, args.model_lib,
                             args.process_sections, args.nominal_score, args.image, args.reference_ports)
        else:
            manifest = json.loads(args.manifest.read_text())
            report = collect(manifest) if args.operation == "collect" else run(manifest, args.container, args.image, args.workers, args.cpus)
            report.setdefault("native_inputs", {})["pvt_manifest"] = _view(args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = physical._result("NOT_MEASURED", str(exc), metrics={"stage": "PRE"})
    physical._write(args.json, report)
    print(json.dumps({"status": report["status"], "detail": report["detail"], "report": str(args.json)}))
    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
