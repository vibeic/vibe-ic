#!/usr/bin/env python3
"""Read-validate an existing analog DUT against its current typed design.

This writes a new validation receipt. It never rewrites the DUT, testbench,
topology, or an emission-provenance record, and makes no performance claim.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import analog_a3_netlist_emit as emitter
import analog_bound_measurements as bound

RECEIPT = "existing_design_validation.json"
SCHEMA = "vibe-ic/existing-design-validation/1"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _view(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": _sha(path)}


def _number(token):
    match = re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?)(meg|[tgkmunpf])?", token, re.I)
    if not match:
        return token.casefold()
    scales = {"": "1", "t": "1e12", "g": "1e9", "meg": "1e6", "k": "1e3",
              "m": "1e-3", "u": "1e-6", "n": "1e-9", "p": "1e-12", "f": "1e-15"}
    return str((Decimal(match[1]) * Decimal(scales[(match[2] or "").casefold()])).normalize())


def _cards(text, directory):
    """Exact named devices, ordered terminals, models and parameter values."""
    lines = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith(("*", ";")):
            continue
        raw = raw.split("$", 1)[0].strip()
        if raw.startswith("+"):
            if not lines:
                raise ValueError("orphan SPICE continuation")
            lines[-1] += " " + raw[1:]
        else:
            lines.append(raw)
    ports, devices, directives, opened, ended = None, {}, [], False, False
    for line in lines:
        fields = shlex.split(line)
        head = fields[0].casefold()
        if head == ".subckt":
            if opened or ended or len(fields) < 3:
                raise ValueError("exactly one typed DUT subcircuit is required")
            opened = True
            ports = [value.casefold() for value in fields[1:]]
        elif head == ".ends":
            if not opened or (len(fields) > 1 and fields[1].casefold() != ports[0]):
                raise ValueError("unmatched DUT .ends")
            opened, ended = False, True
        elif head in (".lib", ".include", ".inc") and not opened:
            if len(fields) != (3 if head == ".lib" else 2):
                raise ValueError("model include/section declaration is malformed")
            path = Path(fields[1]); path = path if path.is_absolute() else directory / path
            directives.append([".lib" if head == ".lib" else ".include", _sha(path),
                               fields[2].casefold() if head == ".lib" else ""])
        elif head in (".option", ".options") and not opened:
            directives.append([".options", *sorted(value.casefold() for value in fields[1:])])
        elif opened and head.startswith("x"):
            split = next((i for i, value in enumerate(fields) if "=" in value), len(fields))
            if split < 4 or head in devices:
                raise ValueError("duplicate or malformed DUT device: " + fields[0])
            params = {}
            for value in fields[split:]:
                if "=" not in value:
                    raise ValueError("malformed device parameter")
                key, value = value.split("=", 1); key = key.casefold()
                if key in params:
                    raise ValueError("duplicate device parameter")
                params[key] = _number(value)
            devices[head] = {"nets": [value.casefold() for value in fields[1:split - 1]],
                             "model": fields[split - 1].casefold(), "params": params}
        else:
            raise ValueError("card is outside the typed device model: " + fields[0])
    if opened or not ended or not devices:
        raise ValueError("complete nonempty DUT subcircuit is required")
    return {"ports": ports, "directives": directives, "devices": devices}


def _closure_signature(views):
    paths = [Path(row["path"]) for row in views.values()]
    if not paths:
        raise ValueError("PDK model/include closure is empty")
    base = Path(os.path.commonpath(paths))
    if base.is_file():
        base = base.parent
    return sorted((str(path.relative_to(base)), views["include:" + str(path)]["sha256"])
                  for path in paths)


def _context(project, block, ir, pdk, container):
    entries, _ = emitter.block_entries(project)
    domain = emitter.block_voltage_domains(project, entries).get(block)
    return emitter.resolve_pdk_context(project, pdk, container,
        sorted({device["role"] for device in ir["devices"]}), domain)


def validate(project, block, pdk, container=""):
    """Recompute the current read validation; receipt status is never authority."""
    project = Path(project).resolve()
    row = {"schema": SCHEMA, "producer": "analog_existing_design_validate",
           "operation": "validate_existing", "block": block, "pdk": pdk,
           "container": container, "status": "FAIL", "scope": "typed design content; no native performance claim"}
    try:
        if not block or Path(block).name != block or block in (".", ".."):
            raise ValueError("invalid analog block name")
        bdir = project / "phase3/analog" / block
        paths = {"netlist": bdir / (block + ".sp"), "topology": bdir / "topology.json",
                 "spec": bdir / "spec.json", "validator": Path(__file__),
                 "renderer": Path(emitter.__file__), "sizing_reader": Path(emitter._a2.__file__),
                 "registry": Path(emitter.__file__).with_name("pdk_registry.json")}
        for key, path in (("sizing_inputs", bdir / "sizing_inputs.json"),
                          ("declared_pdk", project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"),
                          ("block_list", bdir.parent / "analog_block_list.json")):
            if path.is_file():
                paths[key] = path
        inputs = {role: _view(path) for role, path in paths.items()}
        actual_models = bound.consumed_input_views(project, paths["netlist"])
        inputs.update(actual_models)
        ir = json.loads(paths["topology"].read_text())
        spec = json.loads(paths["spec"].read_text())
        for source in (ir.get("_provenance") or {}).get("inputs") or []:
            if not isinstance(source, dict) or not source.get("path") or not source.get("sha256"):
                continue
            path = Path(source["path"])
            path = path if path.is_absolute() else project / path
            if _sha(path) != source["sha256"] or (path.name == "spec.json" and source["sha256"] != inputs["spec"]["sha256"]):
                raise ValueError("typed IR's recorded source input is stale: " + str(path))
            inputs["typed_source:" + str(path.resolve())] = _view(path)
        if ir.get("block") != block or not ir.get("devices"):
            raise ValueError("typed IR does not declare this nonempty DUT")
        ids = [device["name"].casefold() for device in ir["devices"]]
        if len(ids) != len(set(ids)):
            raise ValueError("typed IR has duplicate device identities")
        values = emitter.spec_values(spec)
        if not values:
            raise ValueError("current source specification has no bound values")
        sizing = emitter._a2.read_sizing_inputs(project, block)
        if sizing:
            knobs, devices = copy.deepcopy(ir.get("knobs") or {}), copy.deepcopy(ir["devices"])
            emitter._a2.apply_sizing_inputs(sizing, knobs, dict(ir.get("knob_sources") or {}), [],
                devices, ir.get("device_param_exprs") or [], {}, {}, ir.get("spec_knobs"))
            if knobs != (ir.get("knobs") or {}) or devices != ir["devices"]:
                raise ValueError("ordinary sizing inputs disagree with the frozen typed IR")
        context = _context(project, block, ir, pdk, container)
        if context.get("status") != "OK" or not emitter.pdk_request_is_bound(pdk, context.get("family"), context.get("registry_family")):
            raise ValueError("current PDK model binding is unavailable or disagrees with the requested PDK")
        problems = emitter._validate_ir(ir, context, project)
        if problems:
            raise ValueError("; ".join(problems))
        overrides, spec_bound, _nominal, _env = emitter._resolve_params(ir, values)
        indexed = {device["name"]: device for device in ir["devices"]}
        for name, params in sizing.get("device_parameters", {}).items():
            for key, requested in params.items():
                resolved = overrides.get(name, {}).get(key, indexed[name].get(key))
                if resolved != requested:
                    raise ValueError("explicit sizing differs from final resolved geometry: " + name + "." + key)
        for expr in ir.get("device_param_exprs") or []:
            if expr["param"] not in overrides.get(expr["device"], {}):
                raise ValueError("typed parameter expression did not resolve")
        for device in ir["devices"]:
            for key in ("w", "l", "m"):
                value = overrides.get(device["name"], {}).get(key, device.get(key))
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
                    raise ValueError("invalid resolved device geometry")
        limits = emitter.bound_geometry_limit_violations(ir, context, overrides)
        if limits:
            raise ValueError("; ".join(limits))
        actual = _cards(paths["netlist"].read_text(), bdir)
        with tempfile.TemporaryDirectory(prefix="analog-existing-design-") as temp:
            scratch = Path(temp) / "expected.sp"
            expected_text = emitter.render_netlist(ir, context, [], overrides, deck_dir=scratch.parent)
            scratch.write_text(expected_text)
            expected = _cards(expected_text, scratch.parent)
            expected_models = bound.consumed_input_views(project, scratch)
        if actual != expected:
            different = sorted(name for name in set(actual["devices"]) | set(expected["devices"])
                               if actual["devices"].get(name) != expected["devices"].get(name))
            raise ValueError("existing DUT differs from current typed render: " + (", ".join(different[:8]) or "ports/model directives"))
        if _closure_signature(actual_models) != _closure_signature(expected_models):
            raise ValueError("actual and resolved PDK model/include bytes differ")
        inputs.update({"reference_model:" + view["path"]: view for view in expected_models.values()})
        if any(_sha(view["path"]) != view["sha256"] for view in inputs.values()):
            raise ValueError("consumed input changed during read validation")
        row.update(status="PASS", detail="existing DUT exactly matches the current typed design and PDK binding",
                   design_content="structure_and_geometry" if spec_bound else "structure_only",
                   inputs=inputs, device_count=len(actual["devices"]),
                   normalized_cards_sha256=hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest())
    except (FileNotFoundError, emitter._ce.ContainerImageMismatch) as exc:
        row.update(status="NOT_MEASURED", detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        row.update(detail=str(exc))
    return row


def consume(block_dir):
    """Only a matching fresh read receipt can disclose this existing DUT."""
    block_dir = Path(block_dir).resolve()
    path = block_dir / RECEIPT
    try:
        if block_dir.parent.name != "analog" or block_dir.parent.parent.name != "phase3":
            return None
        prior = json.loads(path.read_text())
        if prior.get("schema") != SCHEMA or prior.get("status") != "PASS" or prior.get("operation") != "validate_existing":
            return None
        if prior.get("inputs", {}).get("netlist", {}).get("path") != str(block_dir / (block_dir.name + ".sp")):
            return None
        current = validate(block_dir.parents[2], block_dir.name, prior["pdk"], prior.get("container", ""))
        if current != prior:
            return None
        return current
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--block", required=True)
    parser.add_argument("--pdk", required=True)
    parser.add_argument("--container", default="")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    row = validate(args.project, args.block, args.pdk, args.container)
    destination = args.project / "phase3/analog" / args.block / RECEIPT
    destination.write_text(json.dumps(row, indent=2) + "\n")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(row, indent=2) + "\n")
    print(row["status"] + ": " + row["detail"])
    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[row["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
