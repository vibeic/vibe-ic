"""Project structured document declarations; no circuit or clock-name inference.

Input is a JSON object in a Markdown ``json`` fence (or a whole JSON text).
The declared containers are instances, analog_blocks[].instances, nets and
clock_groups, using the L9/L8 field spellings. Missing bindings remain unresolved.
This is extraction, not physical-view, placement or clock-cut authorization.
"""
from __future__ import annotations

import copy
import json
import re

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _identifier(value):
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def documents(extracted, is_current):
    """Yield only explicit JSON objects, retaining source and line provenance."""
    for filename, text in (extracted or {}).items():
        source = str(filename)
        if not source.startswith("input/"):
            source = "input/docs/" + source
        stripped = text.lstrip()
        bodies = [(text, 0)] if stripped.startswith("{") else [
            (m.group(1), m.start()) for m in re.finditer(
                r"(?m)^```json\s*\n(.*?)^```\s*$", text, re.S)]
        for body, offset in bodies:
            if not is_current(text, offset):
                continue
            evidence = {"doc": source, "line": text.count("\n", 0, offset) + 1,
                        "quote": body.strip()}
            duplicates = []

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        duplicates.append(key)
                    result[key] = value
                return result

            try:
                data = json.loads(body, object_pairs_hook=unique)
            except ValueError:
                # Unrelated JSON examples are not connectivity declarations.
                if re.search(r'"(?:instances|analog_blocks|clock_groups)"\s*:', body):
                    yield {}, evidence, "DECLARED_CONNECTIVITY_JSON_INVALID"
                continue
            if isinstance(data, dict):
                yield data, evidence, ("DECLARED_CONNECTIVITY_JSON_DUPLICATE_KEY" if duplicates else None)


def project(extracted, is_current):
    """Return declared rows and named refusals, excluding conflicting identities."""
    instances, clocks, nets = {}, {}, set()
    instance_refusals, clock_refusals = [], []
    blocked_instances, blocked_clocks = set(), set()

    def refuse(target, reason, evidence, name=None):
        target.append({"reason": reason, "name": name, "evidence": evidence})

    def accept(target, blocked, row, failures, kind, evidence):
        name = row["name"]
        if name in blocked:
            return
        if name in target and any(target[name].get(k) != v for k, v in row.items() if k != "evidence"):
            target.pop(name)
            blocked.add(name)
            refuse(failures, kind + "_CONFLICT", evidence, name)
        else:
            target.setdefault(name, {**row, "evidence": evidence})

    for data, evidence, error in documents(extracted, is_current):
        if error:
            refuse(instance_refusals, error, evidence)
            refuse(clock_refusals, error, evidence)
            continue
        for net in data.get("nets", []) if isinstance(data.get("nets", []), list) else []:
            name = net.get("name") if isinstance(net, dict) else net
            if _identifier(name):
                nets.add(name)
        rows = data.get("instances", [])
        rows = list(rows) if isinstance(rows, list) else [None]
        blocks = data.get("analog_blocks", [])
        if not isinstance(blocks, list):
            blocks = [None]
        for block in blocks:
            if not isinstance(block, dict):
                refuse(instance_refusals, "L9_ANALOG_MACRO_DECLARATION_INVALID", evidence)
                continue
            declared = block.get("instances")
            if not isinstance(declared, list) or not declared:
                refuse(instance_refusals, "L9_ANALOG_MACRO_INSTANCES_UNDECLARED", evidence, block.get("name"))
                continue
            for row in declared:
                if isinstance(row, dict):
                    rows.append({"block_type": block.get("type"), **row})
                else:
                    rows.append(row)
        for row in rows:
            if not isinstance(row, dict) or not _identifier(row.get("name")) or not _identifier(row.get("block_type")):
                refuse(instance_refusals, "L9_DECLARED_INSTANCE_IDENTITY_UNRESOLVED", evidence)
                continue
            name = row["name"]
            ports = row.get("ports")
            if (not isinstance(ports, list) or not ports
                    or any(not isinstance(p, dict) or not _identifier(p.get("name"))
                           or not _identifier(p.get("net")) or p.get("type") not in
                           ("analog", "digital", "power", "ground", "clock", "reset")
                           or p.get("direction") not in ("input", "output", "inout") for p in ports)
                    or len({p["name"] for p in ports}) != len(ports)):
                blocked_instances.add(name)
                instances.pop(name, None)
                refuse(instance_refusals, "L9_DECLARED_INSTANCE_PORT_UNRESOLVED", evidence, name)
                continue
            bindings = {p["name"]: p["net"] for p in ports}
            if any(key in row and row[key] != bindings for key in ("port_map", "connections")):
                blocked_instances.add(name)
                instances.pop(name, None)
                refuse(instance_refusals, "L9_DECLARED_INSTANCE_CONFLICT", evidence, name)
                continue
            projected = {"name": name, "block_type": row["block_type"],
                         "ports": copy.deepcopy(ports), "port_map": bindings,
                         "connections": bindings.copy(), "parameters": copy.deepcopy(row.get("parameters", {}))}
            # Physical master/placement must be supplied explicitly by the design.
            for key in ("master", "placement"):
                if key in row:
                    projected[key] = copy.deepcopy(row[key])
            accept(instances, blocked_instances, projected, instance_refusals, "L9_DECLARED_INSTANCE", evidence)
        groups = data.get("clock_groups", [])
        if not isinstance(groups, list):
            groups = [None]
        for row in groups:
            if (not isinstance(row, dict) or not _identifier(row.get("name"))
                    or not isinstance(row.get("clocks"), list) or len(row["clocks"]) < 2
                    or any(not _identifier(c) for c in row["clocks"])
                    or len(set(row["clocks"])) != len(row["clocks"])
                    or row.get("relationship") not in ("synchronous", "asynchronous", "exclusive")):
                name = row.get("name") if isinstance(row, dict) else None
                if _identifier(name):
                    blocked_clocks.add(name)
                    clocks.pop(name, None)
                refuse(clock_refusals, "L8_DECLARED_CLOCK_GROUP_UNRESOLVED", evidence, name)
                continue
            projected = {k: copy.deepcopy(row[k]) for k in ("name", "clocks", "relationship")}
            accept(clocks, blocked_clocks, projected, clock_refusals, "L8_DECLARED_CLOCK_GROUP", evidence)
    return list(instances.values()), list(clocks.values()), nets, instance_refusals, clock_refusals
