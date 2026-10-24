#!/usr/bin/env python3
"""Prepare and replay foundry-mismatch incremental ADC chip cohorts.

One seed identifies one chip across its entire coherent conversion series.
Preparation does not run simulations. Native parameter probes must establish
actual mismatch activation before any statistical yield can be accepted.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import _analog_a8_extraction_wrapper as spice
import analog_bound_measurements as bound
import analog_incremental_capture as capture
import analog_incremental_pvt as pvt
import analog_lvs_comparison_prep as calls
import analog_mc_yield_run as mc
import analog_pdk_deck_context as models
import analog_real_corner_sweep as sweep

KIND = "incremental_capture_statistics"
RANDOM = re.compile(r"(?i)\b(?:agauss|gauss|aunif|unif)\s*\(")
ASSIGN = re.compile(r'''\b([A-Za-z_]\w*)\s*=\s*(?:'([^']*)'|"([^"]*)"|([^\s;]+))''')


def _view(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": bound.sha(path)}


def _current(views):
    return bool(views) and all(isinstance(row, dict) and row.get("path") and
        Path(row["path"]).is_file() and row.get("sha256") == bound.sha(row["path"])
        for row in views.values())


def _assignments(line):
    return [(match[1].casefold(), next(value for value in match.group(2, 3, 4) if value is not None))
            for match in ASSIGN.finditer(line)]


def _source_sections(project, net):
    result, files = [], {}
    for _line, tokens in mc._cards(bound.contextual_template(net.read_text(), net.parent)):
        if tokens[0].casefold() != ".lib" or len(tokens) != 3:
            continue
        library = mc._source_path(project, net.parent, tokens[1])
        available = models.parse_sections(library.read_text())
        choices = [section for section in available if section.casefold() in
                   (tokens[2].casefold() + "_mismatch", tokens[2].casefold() + "_mm")]
        if len(choices) != 1:
            raise ValueError("one actual foundry mismatch sibling is required: " + str(library))
        text, closure = mc._statistical_closure(project, library, choices[0])
        if not RANDOM.search(text) or not re.search(r"(?i)\bmm_ok\s*=\s*0\b", text):
            raise ValueError("selected mismatch source lacks a real random distribution and declared mm_ok switch")
        result.append({"library": str(library), "nominal_section": tokens[2], "section": choices[0]})
        files.update({row["path"]: _view(row["path"]) for row in closure})
    if not result:
        raise ValueError("delivered DUT has no explicit foundry model-library selections")
    return result, files


def _model_text(project, source, mapping, enabled):
    """Only relocate source includes and enable foundry-declared switches."""
    lines, edits = [], 0
    for line in Path(source).read_text().splitlines():
        try:
            tokens = shlex.split(line) if line.strip() and not line.lstrip().startswith("*") else []
        except ValueError:
            tokens = []
        if tokens and tokens[0].casefold() in (".include", ".inc", ".lib") \
                and len(tokens) >= (3 if tokens[0].casefold() == ".lib" else 2):
            child = mc._source_path(project, Path(source).parent, tokens[1])
            target = mapping.get(str(child), str(child))
            line = tokens[0] + ' "' + target + '"' + (" " + tokens[2] if tokens[0].casefold() == ".lib" else "")
        if enabled and line.lstrip().startswith(("+", ".param", ".PARAM")):
            line, count = re.subn(r"(?i)(\bmm_ok\s*=\s*)0(?=\s|$)", r"\g<1>1", line)
            edits += count
        lines.append(line)
    return "\n".join(lines) + "\n", edits


def _models(project, files, destination, enabled):
    mapping = {name: str(destination / hashlib.sha256(name.encode()).hexdigest()[:12] / Path(name).name)
               for name in files}
    records, edits = [], 0
    for name in sorted(files):
        path = Path(mapping[name]); path.parent.mkdir(parents=True, exist_ok=True)
        text, count = _model_text(project, name, mapping, enabled)
        path.write_text(text); edits += count
        records.append({"source": files[name], "copy": _view(path), "switch_edits": count})
    if enabled and not edits:
        raise ValueError("no declared foundry mismatch switch was enabled")
    return {"mapping": mapping, "files": records, "enabled": enabled}


def _dut_text(source, sections, mapping):
    choices = {(row["library"], row["nominal_section"]): row["section"] for row in sections}
    lines, changed = [], 0
    for line in bound.contextual_template(source.read_text(), source.parent).splitlines():
        tokens = shlex.split(line) if line.strip() and not line.lstrip().startswith("*") else []
        if tokens and tokens[0].casefold() == ".lib" and len(tokens) == 3:
            key = (str(Path(tokens[1]).resolve()), tokens[2])
            if key not in choices:
                raise ValueError("unbound source model-library selection")
            line = '.lib "' + mapping[key[0]] + '" ' + choices[key]
            changed += 1
        lines.append(line)
    if changed != len(sections):
        raise ValueError("not every source model selection was replaced exactly once")
    return "\n".join(lines) + "\n"


def _fingerprint_bindings(project, net, template, sections, mapping):
    selected = "\n".join(mc._statistical_closure(project, Path(mapping[row["library"]]), row["section"])[0]
                          for row in sections)
    source_calls = {}
    for line in spice.logical_lines(net.read_text()):
        if line.casefold().startswith("x"):
            name, rest = line.split(None, 1); call = calls._split_call(rest)
            if call:
                source_calls.setdefault(call[1].casefold(), []).append(name.casefold())
    declarations = [line.split()[1].casefold() for line in spice.logical_lines(net.read_text())
                    if line.casefold().startswith(".subckt ")]
    if len(declarations) != 1:
        raise ValueError("one declared DUT subcircuit is required for parameter probes")
    instances = []
    for line in spice.logical_lines(template.read_text()):
        if line.casefold().startswith("x"):
            name, rest = line.split(None, 1)
            call = calls._split_call(rest)
            if call and call[1].casefold() == declarations[0]:
                instances.append(name.casefold())
    if len(instances) != 1:
        raise ValueError("exactly one source DUT instance is required for native parameter probes")
    fields = []
    for model, names in sorted(source_calls.items()):
        wrappers = re.findall(r"(?ims)^\s*\.subckt\s+" + re.escape(model) + r"\b[^\n]*\n(.*?)^\s*\.ends\b[^\n]*", selected)
        if not wrappers:
            raise ValueError("source device lacks a selected mismatch wrapper: " + model)
        lines = [line for wrapper in wrappers for line in spice.logical_lines(wrapper)]
        params = [(key, value) for line in lines if line.casefold().startswith(".param") for key, value in _assignments(line)]
        random = {key for key, value in params if RANDOM.search(value)}
        for _ in range(len(params) + 1):
            random.update(key for key, value in params if random.intersection(re.findall(r"[A-Za-z_]\w*", value.casefold())))
        probes = set()
        for line in lines:
            first = line.split()[0]
            if first[0].casefold() not in ("n", "c", "r"):
                continue
            for key, value in _assignments(line):
                if RANDOM.search(value) or random.intersection(re.findall(r"[A-Za-z_]\w*", value.casefold())):
                    probes.add((first.casefold(), key))
        if not probes:
            raise ValueError("no random-fed intrinsic device input parameter can be queried: " + model)
        for name in sorted(names)[:2]:
            for intrinsic, parameter in sorted(probes):
                fields.append({"key": f"fp_{len(fields):04d}", "model": model,
                    "source_instance": name, "parameter": parameter,
                    "expression": f"@{intrinsic[0]}.{instances[0]}.{name}.{intrinsic}[{parameter}]"})
    if not fields:
        raise ValueError("no source device has native random-fed input parameters")
    return fields


def _template(source, source_net, target_net, seed):
    text = pvt._template(source, source_net, target_net, 27)
    if re.search(r"(?im)^\s*\.options?\b[^\n]*\bseed\s*=", text):
        raise ValueError("source testbench already owns an RNG seed")
    first, _, rest = text.partition("\n")
    return first + f"\n.option seed={seed}\n" + rest


def _probe_text(paths, common, fields, phase, root):
    text, _clock, _decl = capture.prepare_deck(paths["testbench"], json.loads(paths["spec"].read_text()),
        json.loads(paths["topology"].read_text()), capture.phase_settings(common, phase), root)
    # Parameter activation is a setup observation, not conversion performance.
    text = re.sub(r"(?im)^tran\s+[^\n]+", "tran 1e-10 1e-9", text)
    text = re.sub(r"(?im)^wrdata\s+[^\n]+", "", text)
    commands = []
    for field in fields:
        commands += [f"let a09_{field['key']} = {field['expression']}",
                     f'echo "{field["key"]}=" $&a09_{field["key"]}']
    text = text.replace("\n.endc", "\n" + "\n".join(commands) + "\n.endc")
    return text


def _probe(project, paths, common, fields, seed, phase, root):
    root.mkdir(parents=True, exist_ok=False)
    deck = root / "activation.sp"; deck.write_text(_probe_text(paths, common, fields, phase, root))
    return {"seed": seed, "phase_index": phase, "project": str(project), "deck": _view(deck),
            "receipt": str(root / "result.json"), "scope": "native realized input parameters only; no operating/performance credit"}


def prepare(project, block, settings, destination, samples, first_seed=1, image=None, reference_ports=None, nominal_score=None):
    project, destination, settings = Path(project).resolve(), Path(destination).resolve(), Path(settings).resolve()
    if not re.fullmatch(r"[A-Za-z_][\w.-]*", block) or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (samples, first_seed)) or samples < 2:
        raise ValueError("a declared block and at least two finite chip seeds are required")
    paths = pvt._paths(project, block); common = json.loads(settings.read_text())
    capture.phase_settings(common, 0)
    if common["series_length"] % 4:
        raise ValueError("cohort phase-control series must have a quarter-phase index")
    common.setdefault("threads", 1); common.setdefault("openmp_wait_policy", "PASSIVE")
    source_tb = Path(common.get("testbench", paths["testbench"]))
    paths["testbench"] = source_tb if source_tb.is_absolute() else project / source_tb
    capture.source_enob_min(json.loads(paths["spec"].read_text()))
    reference_ports = pvt._reference_ports(paths["spec"], paths["topology"], reference_ports)
    source = {role: _view(path) for role, path in paths.items()}; source["settings"] = _view(settings)
    sections, foundry = _source_sections(project, paths["netlist"])
    source.update({"foundry:" + name: view for name, view in foundry.items()})
    destination.mkdir(parents=True, exist_ok=False)
    producer_origins = {}
    for role, path in (("producer", Path(__file__)), ("incremental_producer", Path(capture.__file__))):
        snapshot = destination / "producer-sources" / path.name
        snapshot.parent.mkdir(exist_ok=True)
        snapshot.write_bytes(path.read_bytes())
        source[role] = _view(snapshot)
        producer_origins[role] = _view(path)
    enabled = _models(project, foundry, destination / "models/enabled", True)
    disabled = _models(project, foundry, destination / "models/disabled", False)
    fields = _fingerprint_bindings(project, paths["netlist"], paths["testbench"], sections, enabled["mapping"])
    cohorts, off = [], None
    for seed in range(first_seed, first_seed + samples):
        root = destination / f"chip-{seed:06d}"; study = root / "project"; current = pvt._paths(study, block)
        current["netlist"].parent.mkdir(parents=True)
        for role in ("spec", "topology"):
            current[role].symlink_to(paths[role])
        current["netlist"].write_text(_dut_text(paths["netlist"], sections, enabled["mapping"]))
        current["testbench"].write_text(_template(paths["testbench"], paths["netlist"], current["netlist"], seed))
        method = {**common, "testbench": str(current["testbench"])}
        method_path = root / "common.json"; capture.write_json(method_path, method)
        controls = [_probe(study, current, method, fields, seed, phase, root / f"activation/phase-{phase:03d}")
                    for phase in (0, common["series_length"] // 4)]
        cohorts.append({"seed": seed, "project": str(study), "settings": _view(method_path),
            "native_inputs": {role: _view(path) for role, path in current.items()},
            "score": str(root / "series/score.json"), "probes": controls})
        if off is None:
            off_project = root / "disabled-project"; off_paths = pvt._paths(off_project, block)
            off_paths["netlist"].parent.mkdir(parents=True)
            for role in ("spec", "topology"):
                off_paths[role].symlink_to(paths[role])
            off_paths["netlist"].write_text(_dut_text(paths["netlist"], sections, disabled["mapping"]))
            off_paths["testbench"].write_text(_template(paths["testbench"], paths["netlist"], off_paths["netlist"], seed))
            off = {"native_inputs": {role: _view(path) for role, path in off_paths.items()},
                   "control": _probe(off_project, off_paths, {**common, "testbench": str(off_paths["testbench"])},
                                     fields, seed, 0, root / "activation/disabled")}
    if not _current(source):
        raise ValueError("source inputs changed during cohort preparation")
    return {"kind": KIND, "stage": "PRE", "operation": "prepare", "status": "PASS", "block": block,
        "project": str(project), "destination": str(destination), "requested_samples": samples,
        "first_seed": first_seed, "image": image, "common_settings": common, "native_inputs": source,
        "reference_ports": reference_ports,
        "producer_origins": producer_origins, "nominal_score": _view(nominal_score) if nominal_score else None,
        "sections": sections, "model_copies": [enabled, disabled], "fingerprint_bindings": fields,
        "cohorts": cohorts, "disabled_control": off,
        "detail": "foundry-mismatch chip inputs and native parameter probes prepared; no draw or variation measured"}


def _validate(manifest):
    if manifest.get("kind") != KIND or manifest.get("stage") != "PRE" or not _current(manifest.get("native_inputs") or {}):
        raise ValueError("current source-bound PRE mismatch cohort is required")
    source, common = manifest["native_inputs"], manifest["common_settings"]
    for role in ("producer", "incremental_producer"):
        if not source.get(role) or source[role]["sha256"] != manifest.get("producer_origins", {}).get(role, {}).get("sha256"):
            raise ValueError("immutable preparation producer snapshots are required")
    project, block = Path(manifest["project"]).resolve(), manifest["block"]
    if not isinstance(block, str) or not re.fullmatch(r"[A-Za-z_][\w.-]*", block):
        raise ValueError("declared project/block identity is invalid")
    paths = {role: Path(source[role]["path"]) for role in ("netlist", "testbench", "spec", "topology")}
    declared = pvt._paths(project, block)
    for role in ("netlist", "spec", "topology"):
        if paths[role].resolve() != declared[role].resolve():
            raise ValueError("cohort project/block does not identify its actual source " + role)
    pvt._reference_ports(paths["spec"], paths["topology"], manifest.get("reference_ports"))
    original = json.loads(Path(source["settings"]["path"]).read_text())
    expected_tb = Path(original.get("testbench", declared["testbench"]))
    if not expected_tb.is_absolute():
        expected_tb = project / expected_tb
    if paths["testbench"].resolve() != expected_tb.resolve():
        raise ValueError("cohort source testbench is not the declared default or explicit COMMON template")
    original.setdefault("threads", 1); original.setdefault("openmp_wait_policy", "PASSIVE")
    if common != original:
        raise ValueError("statistical cohort changed the source measurement method")
    sections, foundry = _source_sections(project, paths["netlist"])
    if sections != manifest["sections"]:
        raise ValueError("selected foundry mismatch sections changed")
    copies = manifest["model_copies"]
    if len(copies) != 2 or [row.get("enabled") for row in copies] != [True, False]:
        raise ValueError("explicit enabled and disabled foundry model copies are required")
    for variant in copies:
        if set(variant["mapping"]) != set(foundry) or len(variant["files"]) != len(foundry):
            raise ValueError("foundry model closure was omitted or duplicated")
        seen = set()
        for row in variant["files"]:
            name = row["source"]["path"]
            if name in seen or row["source"] != foundry.get(name) or not _current({"copy": row["copy"]}):
                raise ValueError("foundry source/copy input changed")
            seen.add(name)
            text, edits = _model_text(project, name, variant["mapping"], variant["enabled"])
            if row["copy"]["path"] != variant["mapping"][name] or Path(row["copy"]["path"]).read_text() != text or edits != row["switch_edits"]:
                raise ValueError("model copy differs beyond source relocation and the declared mismatch switch")
    fields = _fingerprint_bindings(project, paths["netlist"], paths["testbench"], sections, copies[0]["mapping"])
    if fields != manifest["fingerprint_bindings"]:
        raise ValueError("native parameter probes differ from actual random-fed model inputs")
    first, count = manifest["first_seed"], manifest["requested_samples"]
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in (first, count)) or count < 2:
        raise ValueError("at least two explicit chip seeds are required")
    cohorts = manifest["cohorts"]
    if [row.get("seed") for row in cohorts] != list(range(first, first + count)):
        raise ValueError("statistical chip seeds are missing, duplicated, or reordered")
    probes = []
    for cohort in cohorts:
        current = pvt._paths(Path(cohort["project"]), block)
        if cohort["native_inputs"] != {role: _view(path) for role, path in current.items()} or not _current({"settings": cohort["settings"]}):
            raise ValueError("prepared chip source inputs changed")
        if any(cohort["native_inputs"][role]["sha256"] != source[role]["sha256"] for role in ("spec", "topology")):
            raise ValueError("chip changed source specification or topology")
        expected = {**common, "testbench": str(current["testbench"])}
        if json.loads(Path(cohort["settings"]["path"]).read_text()) != expected \
                or current["netlist"].read_text() != _dut_text(paths["netlist"], sections, copies[0]["mapping"]) \
                or current["testbench"].read_text() != _template(paths["testbench"], paths["netlist"], current["netlist"], cohort["seed"]):
            raise ValueError("chip differs beyond declared mismatch models and its frozen seed")
        if [row.get("phase_index") for row in cohort["probes"]] != [0, common["series_length"] // 4]:
            raise ValueError("same-chip native phase0/quarter-phase controls are required")
        for probe in cohort["probes"]:
            if probe["seed"] != cohort["seed"] or not _current({"deck": probe["deck"]}) or Path(probe["deck"]["path"]).read_text() != _probe_text(current, expected, fields, probe["phase_index"], Path(probe["deck"]["path"]).parent):
                raise ValueError("native same-chip parameter control changed")
            probes.append((probe, current))
    off = manifest["disabled_control"]
    probe = off["control"]; current = pvt._paths(Path(probe["project"]), block)
    if off["native_inputs"] != {role: _view(path) for role, path in current.items()} \
            or current["netlist"].read_text() != _dut_text(paths["netlist"], sections, copies[1]["mapping"]) \
            or current["testbench"].read_text() != _template(paths["testbench"], paths["netlist"], current["netlist"], first) \
            or probe["seed"] != first or probe["phase_index"] != 0 or not _current({"deck": probe["deck"]}) \
            or Path(probe["deck"]["path"]).read_text() != _probe_text(current, {**common, "testbench": str(current["testbench"])}, fields, 0, Path(probe["deck"]["path"]).parent):
        raise ValueError("native mismatch-disabled control changed")
    return cohorts, [*probes, (probe, current)]


def _native_probe(probe, fields, image):
    path = Path(probe["receipt"])
    if not path.is_file():
        return "NOT_MEASURED", {}, "native parameter control is absent"
    row = json.loads(path.read_text()); execution = row.get("execution") or {}
    log = Path(execution.get("log") or "__missing_parameter_log__")
    if not log.is_file() or execution.get("log_sha256") != bound.sha(log):
        return "NOT_MEASURED", {}, "native parameter transcript is absent or changed"
    text = log.read_text(errors="replace")
    code = execution.get("returncode")
    interrupted = code in (124, 130, 137, 143) or (isinstance(code, int) and code < 0)
    failed = capture.native_failed(text) or (isinstance(code, int) and code != 0 and not interrupted)
    if failed:
        return "FAIL", {}, "native parameter control failed"
    if interrupted:
        return "NOT_MEASURED", {}, "native parameter control was interrupted"
    if code != 0 or isinstance(code, bool):
        return "NOT_MEASURED", {}, "native parameter execution return code is absent"
    views = row.get("native_inputs") or {}
    if row.get("image") != image or views.get("deck") != probe["deck"] or not _current(views) \
            or not bound.validate_consumed_inputs(Path(probe["project"]), views)[0] \
            or probe["deck"]["path"] not in execution.get("argv", []):
        return "NOT_MEASURED", {}, "native parameter control does not bind current inputs/runtime"
    temperatures = [float(value) for value in re.findall(r"Doing analysis at TEMP\s*=\s*([-+.\deE]+)", text)]
    if not temperatures or any(value != 27 for value in temperatures):
        return "NOT_MEASURED", {}, "native parameter control temperature is not27C"
    values = sweep.native_meas_rows(text)
    wanted = [field["key"] for field in fields]
    if any(key not in values or not isinstance(values[key], (int, float)) or not math.isfinite(values[key]) for key in wanted):
        return "NOT_MEASURED", {}, "actual random-fed native device parameters are absent"
    return "PASS", {key: values[key] for key in wanted}, "actual native device input parameters"


def _point_failure(point):
    for execution in point.get("executions") or []:
        code = execution.get("returncode")
        log = Path(execution.get("log") or "__missing_native_chip_log__")
        if log.is_file() and execution.get("log_sha256") == bound.sha(log) and capture.native_failed(log.read_text(errors="replace")):
            return True
        if isinstance(code, int) and code > 0 and code not in (124, 130, 137, 143):
            return True
    return False


def run_probes(manifest, runner, image):
    """Explicit bounded caller entry; prepare/collect never invoke this."""
    _cohorts, probes = _validate(manifest)
    if image != manifest.get("image"):
        raise ValueError("native image differs from cohort runtime")
    results = []
    for probe, current in probes:
        if Path(probe["receipt"]).exists():
            results.append(_native_probe(probe, manifest["fingerprint_bindings"], image)[0]); continue
        directory = Path(probe["receipt"]).parent
        if capture.active_point(directory) or (directory / "running.json").exists():
            results.append("NOT_MEASURED"); continue
        me = Path("/proc") / str(os.getpid()); stat = (me / "stat").read_text()
        argv = [os.fsdecode(item) for item in (me / "cmdline").read_bytes().split(b"\0") if item]
        try:
            claim = os.open(directory / "running.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            results.append("NOT_MEASURED"); continue
        with os.fdopen(claim, "w") as stream:
            json.dump({"pid": os.getpid(), "argv": argv,
                "start_ticks": stat[stat.rfind(")") + 2:].split()[19]}, stream)
            stream.write("\n")
        inputs = {role: _view(path) for role, path in current.items()}
        inputs["deck"] = probe["deck"]
        inputs.update(bound.consumed_input_views(Path(probe["project"]), Path(probe["deck"]["path"])))
        execution = runner("@env", ["OMP_NUM_THREADS=1", "OMP_WAIT_POLICY=PASSIVE", "GOMP_SPINCOUNT=0",
                                    "ngspice", "-b", probe["deck"]["path"]], cwd=current["testbench"].parent)
        capture.write_json(Path(probe["receipt"]), {"operation": "native_parameter_probe", "image": image,
            "native_inputs": inputs, "execution": execution})
        results.append(_native_probe(probe, manifest["fingerprint_bindings"], image)[0])
    return results


def collect(manifest):
    """Replay native per-chip scores and source-bound device activation data."""
    inputs = dict(manifest.get("native_inputs") or {}); rows, gaps, failed = [], [], False
    try:
        cohorts, _probes = _validate(manifest)
        for variant in manifest["model_copies"]:
            inputs.update({"model_copy:" + row["copy"]["path"]: row["copy"] for row in variant["files"]})
        fields = manifest["fingerprint_bindings"]; groups = {field["model"] for field in fields}
        state, disabled, detail = _native_probe(manifest["disabled_control"]["control"], fields, manifest["image"])
        failed |= state == "FAIL"
        if state != "PASS":
            gaps.append("mismatch-disabled control: " + detail)
        for probe, _paths in _probes:
            path = Path(probe["receipt"])
            if path.is_file():
                inputs["probe_receipt:" + str(path)] = _view(path)
                record = json.loads(path.read_text())
                inputs.update({"probe:" + str(path) + ":" + key: view for key, view in (record.get("native_inputs") or {}).items()})
                log = Path((record.get("execution") or {}).get("log") or "__missing_probe_log__")
                if log.is_file():
                    inputs["probe_log:" + str(log)] = _view(log)
        fingerprints = {}
        for cohort in cohorts:
            inputs[f"chip:{cohort['seed']}:settings"] = cohort["settings"]
            inputs.update({f"chip:{cohort['seed']}:" + role: view for role, view in cohort["native_inputs"].items()})
            states = [_native_probe(probe, fields, manifest["image"]) for probe in cohort["probes"]]
            failed |= any(row[0] == "FAIL" for row in states)
            active = all(row[0] == "PASS" for row in states) and states[0][1] == states[1][1]
            if active and disabled:
                active = all(any(states[0][1][field["key"]] != disabled[field["key"]]
                                 for field in fields if field["model"] == model) for model in groups)
            else:
                active = False
            if active:
                fingerprints[cohort["seed"]] = states[0][1]
            else:
                gaps.append(f"seed{cohort['seed']}: actual phase-invariant mismatch activation not proven")
            try:
                score_path = Path(cohort["score"])
                score = json.loads(score_path.read_text()) if score_path.is_file() else {}
                if score_path.is_file():
                    inputs["score:" + str(cohort["seed"])] = _view(score_path)
                common = json.loads(Path(cohort["settings"]["path"]).read_text())
                references = score.get("points") or []
                score_missing = not references
                if score_missing:
                    references = [_view(path) for path in sorted(score_path.parent.glob("point-[0-9][0-9][0-9]/result.json"))]
                phases, reference_rows = set(), []
                for reference in references:
                    point_path = Path(reference["path"])
                    if not point_path.is_file() or reference.get("sha256") != bound.sha(point_path):
                        raise ValueError("native chip point reference changed")
                    point = json.loads(point_path.read_text()); phase = point.get("settings", {}).get("phase_index")
                    if point.get("settings") != capture.phase_settings(common, phase) or point.get("image") != manifest["image"] \
                            or any(point.get("native_inputs", {}).get(role) != view for role, view in cohort["native_inputs"].items()):
                        raise ValueError("native conversion is not this frozen chip/seed/method")
                    phases.add(phase)
                    inputs[f"chip:{cohort['seed']}:point:{phase}"] = _view(point_path)
                    inputs.update({f"chip:{cohort['seed']}:point:{phase}:" + key: view for key, view in point["native_inputs"].items()})
                    if _point_failure(point):
                        failed = True
                        raise ValueError("native chip conversion failed")
                    if any(execution.get("returncode") in (124, 130, 137, 143) or
                           (isinstance(execution.get("returncode"), int) and execution["returncode"] < 0)
                           for execution in point.get("executions") or []):
                        raise ValueError("native chip conversion was interrupted")
                    for execution in point.get("executions") or []:
                        log = Path(execution["log"])
                        if not log.is_file() or execution.get("log_sha256") != bound.sha(log):
                            raise ValueError("native chip transcript changed")
                        inputs[f"chip:{cohort['seed']}:point:{phase}:log"] = _view(log)
                        transcript = log.read_text(errors="replace")
                        temperatures = [float(value) for value in re.findall(r"Doing analysis at TEMP\s*=\s*([-+.\deE]+)", transcript)]
                        if not temperatures or any(value != 27 for value in temperatures):
                            raise ValueError("native chip temperature differs from nominal27C")
                        if manifest["reference_ports"]:
                            reference_rows.append(pvt._reference_measurement(point, transcript, manifest["reference_ports"]))
                if score_missing:
                    raise ValueError("native full chip score is absent or incomplete")
                replay = capture.replay_score(score_path)
                measured = dict(replay.get("measurements") or {})
                reference_pass = None
                if manifest["reference_ports"]:
                    if phases != set(range(common["series_length"])) or len(reference_rows) != len(phases):
                        raise ValueError("native per-phase reference observations are incomplete")
                    reference_pass = not any(row["violation"] for row in reference_rows)
                    measured["vref"] = reference_rows[0]["value"]
                rows.append({"seed": cohort["seed"], "status": replay["status"],
                             "score": str(score_path), "activation_proven": active,
                             "measurements": measured, "reference_pass": reference_pass})
                if replay["status"] not in ("PASS", "FAIL"):
                    gaps.append(f"seed{cohort['seed']}: native full series incomplete")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                gaps.append(f"seed{cohort['seed']}: {exc}")
                rows.append({"seed": cohort["seed"], "status": "NOT_MEASURED", "detail": str(exc), "activation_proven": active})
        if len(fingerprints) == len(cohorts):
            distinct = True
            for model in groups:
                signatures = {tuple(fp[field["key"]] for field in fields if field["model"] == model) for fp in fingerprints.values()}
                if len(signatures) != len(cohorts):
                    distinct = False
                    gaps.append("different seeds did not realize distinct native mismatch parameters: " + model)
        else:
            distinct = False
        if not _current(inputs):
            gaps.append("consumed native source/model/point/probe bytes changed during collection")
        complete = not gaps and len(rows) == manifest["requested_samples"]
        spec_yield = {}
        for metric in ("enob", "vref"):
            scored = [row for row in rows if row["status"] in ("PASS", "FAIL") and
                      isinstance(row.get("measurements", {}).get(metric), (int, float))]
            passed = sum((row["status"] == "PASS" if metric == "enob" else row.get("reference_pass") is True) for row in scored)
            spec_yield[metric] = {"runs_scored": len(scored), "passed": passed,
                                 "yield_pct": 100 * passed / len(scored) if scored else None}
        grade = mc._grade_source_yield(Path(manifest["project"]), manifest["native_inputs"]["spec"]["path"],
                                       spec_yield, manifest["requested_samples"])
        status = "FAIL" if failed or grade["verdict"] == "FAIL" else grade["verdict"] if complete else "NOT_MEASURED"
        yield_pct = grade["mc_yield_pct"] if complete else None
        return {"status": status, "detail": "native incremental per-chip mismatch cohort" + ("; " + "; ".join(gaps) if gaps else ""),
            "native_inputs": inputs, "outputs": sorted({view["path"] for view in inputs.values()}),
            "metrics": {"stage": "PRE", "requested_samples": manifest["requested_samples"],
                "samples_executed": sum(row["status"] in ("PASS", "FAIL") for row in rows), "mc_yield_pct": yield_pct,
                "native_activation_proven": distinct,
                "spec_yield": spec_yield, "mc_source_coverage": grade["mc_source_coverage"],
                "yield_policy": "existing analog_mc_yield_run95percent threshold", "cohorts": rows, "gaps": gaps,
                "scope": "foundry mismatch at nominal27C; actual deterministic transient SNDR; jitter/noise not added"}}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "FAIL" if failed else "NOT_MEASURED", "detail": str(exc), "native_inputs": inputs,
                "metrics": {"stage": "PRE", "cohorts": rows, "gaps": [str(exc)]}}


def _nominal_context(project, views):
    """Actual nominal includes and ordered selected library contexts only."""
    template = Path(views["testbench"]["path"])
    closure = bound.consumed_input_views(project, template)
    if not closure:
        raise ValueError("nominal source model/include closure is empty")
    def signature(text, files):
        # Expanded text retains include order and position; file/section hash
        # multiplicities retain the selected closure without project paths.
        return (hashlib.sha256(text.encode()).hexdigest(), tuple(sorted(
            (str(row.get("section") or "").casefold(), row["sha256"]) for row in files)))
    text, files = mc._statistical_closure(project, template.resolve(), None)
    includes = signature(text, files)
    net = Path(views["netlist"]["path"])
    libraries = []
    for _line, tokens in mc._cards(bound.contextual_template(net.read_text(), net.parent)):
        if tokens[0].casefold() != ".lib" or len(tokens) != 3:
            continue
        library = mc._source_path(project, net.parent, tokens[1])
        # Do not inspect or require unselected mismatch siblings. The MC
        # manifest validates those independently before its cohorts can run.
        text, files = mc._statistical_closure(project, library, tokens[2])
        libraries.append((tokens[2].casefold(), signature(text, files)))
    return closure, (includes, tuple(libraries))


def _nominal_control(manifest):
    reference = manifest.get("nominal_score")
    if not reference or not _current({"nominal_score": reference}):
        raise ValueError("a current source nominal A07 score reference is required before cohort series launch")
    path = Path(reference["path"])
    score = json.loads(path.read_text())
    source = manifest["native_inputs"]
    roles = ("netlist", "testbench", "spec", "topology")
    if not _current({role: source[role] for role in roles}):
        raise ValueError("current nominal source inputs are absent or changed")
    _source_closure, source_context = _nominal_context(Path(manifest["project"]), source)
    for entry in score.get("points") or []:
        point = json.loads(Path(entry["path"]).read_text())
        phase = point.get("settings", {}).get("phase_index")
        views = point.get("native_inputs") or {}
        if point.get("settings") != capture.phase_settings(manifest["common_settings"], phase) \
                or point.get("image") != manifest["image"] \
                or any(views.get(role, {}).get("sha256") != source[role]["sha256"] for role in roles):
            raise ValueError("nominal A07 points do not belong to the current source DUT and measurement method")
        project = Path(point["project"])
        if not _current(views) or not bound.validate_consumed_inputs(project, views)[0] \
                or not capture.declared_dut_consumed(views):
            raise ValueError("nominal A07 actual consumed inputs are absent, stale, or incomplete")
        expected, context = _nominal_context(project, views)
        actual = {role: view for role, view in views.items() if role.startswith("include:")}
        if actual != expected or context != source_context:
            raise ValueError("nominal A07 consumed model/include context differs from the source nominal context")
    replay = capture.replay_score(path)
    if replay.get("status") != "PASS":
        raise ValueError("native nominal A07 raw replay must PASS before cohort series launch")
    return reference


def run(manifest, container, image, workers=1, cpus=1, launch=None):
    """Run chip series only after native activation and nominal A07 acceptance."""
    cohorts, _probes = _validate(manifest)
    threads = manifest["common_settings"].get("threads", 1)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (workers, cpus, threads)) or cpus < threads:
        raise ValueError("positive workers/CPU budget must accommodate native threads")
    if image != manifest.get("image"):
        raise ValueError("requested native image differs from the prepared runtime")
    before = collect(manifest)
    if before["status"] in ("PASS", "FAIL"):
        return before
    try:
        nominal = _nominal_control(manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        before["detail"] += "; " + str(exc)
        return before
    if not before.get("metrics", {}).get("native_activation_proven"):
        before["detail"] += "; actual foundry mismatch activation must be proven before cohort series launch"
        return before
    width = min(len(cohorts), workers, cpus // threads)
    inner = min(workers // width, cpus // (width * threads))
    def one(cohort):
        return (launch or capture.series_main)([cohort["project"], "--block", manifest["block"],
            "--settings", cohort["settings"]["path"], "--out", str(Path(cohort["score"]).parent),
            "--score", cohort["score"], "--container", container, "--image", image,
            "--workers", str(inner), "--cpus", str(inner * threads)])
    with ThreadPoolExecutor(max_workers=width) as executor:
        codes = list(executor.map(one, cohorts))
    result = collect(manifest)
    result.setdefault("native_inputs", {})["nominal_A07_score"] = nominal
    if not _current({"nominal_A07_score": nominal}) and result["status"] != "FAIL":
        result["status"] = "NOT_MEASURED"
        result["detail"] += "; source nominal A07 score changed during cohort execution"
    result.setdefault("metrics", {})["execution_budget"] = {"series_returncodes": codes,
        "chip_workers": width, "phase_workers_per_chip": inner, "native_threads_per_phase": threads,
        "total_phase_workers": width * inner, "total_cpu_ceiling": width * inner * threads}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="operation", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("project", type=Path); prep.add_argument("--block", required=True)
    prep.add_argument("--settings", type=Path, required=True); prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--samples", type=int, required=True); prep.add_argument("--first-seed", type=int, default=1)
    prep.add_argument("--image", required=True); prep.add_argument("--json", type=Path, required=True)
    prep.add_argument("--reference-ports", nargs=2)
    prep.add_argument("--nominal-score", type=Path)
    for operation in ("collect", "probe", "run"):
        command = sub.add_parser(operation); command.add_argument("manifest", type=Path); command.add_argument("--json", type=Path, required=True)
        if operation in ("probe", "run"):
            command.add_argument("--container", required=True); command.add_argument("--image", required=True)
        if operation == "run":
            command.add_argument("--workers", type=int, default=1); command.add_argument("--cpus", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.operation == "prepare":
            result = prepare(args.project, args.block, args.settings, args.out, args.samples, args.first_seed, args.image, args.reference_ports, args.nominal_score)
        else:
            manifest = json.loads(args.manifest.read_text())
            if args.operation == "probe":
                from analog_native_flow import NativeCommands
                run_probes(manifest, NativeCommands(Path(manifest["project"]), args.json.parent, args.container, args.image), args.image)
            result = run(manifest, args.container, args.image, args.workers, args.cpus) if args.operation == "run" else collect(manifest)
            result.setdefault("native_inputs", {})["statistics_manifest"] = _view(args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"status": "NOT_MEASURED", "detail": str(exc)}
    capture.write_json(args.json, result)
    print(json.dumps({"status": result["status"], "detail": result["detail"], "report": str(args.json)}))
    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
