#!/usr/bin/env python3
"""Portable, byte-bound drawing-grid admission and explicit legacy migration."""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

import _container_exec as _ce


_METADATA = {"basis", "native_probe_cid"}
_FIELDS = {"version", "grid_source", "sources", "models"} | _METADATA
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER_READ = """import pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve(strict=True)
source = (root / sys.argv[2]).resolve(strict=True)
if not root.is_dir() or not source.is_relative_to(root) or not source.is_file():
    raise SystemExit(2)
sys.stdout.buffer.write(source.read_bytes())
"""


@dataclass(frozen=True)
class VerifiedAdmission:
    grid_um: float
    sources: dict
    models: dict


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("GEOMETRY_ADMISSION_DUPLICATE_KEY")
        result[key] = value
    return result


def load_admission(path):
    try:
        return json.loads(Path(path).read_bytes(), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("GEOMETRY_ADMISSION_INVALID_JSON") from exc


def _absolute(key):
    return isinstance(key, str) and (key.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", key)))


def source_parts(key):
    if _absolute(key):
        raise ValueError("GEOMETRY_ADMISSION_LEGACY_ABSOLUTE: regenerate with explicit --map-source")
    if not isinstance(key, str) or key.count(":") != 1:
        raise ValueError("GEOMETRY_ADMISSION_INVALID_SOURCE")
    namespace, relative = key.split(":", 1)
    if (namespace not in ("case", "pdk") or not relative or "\\" in relative
            or any(ord(char) < 32 or ord(char) == 127 for char in relative)
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("GEOMETRY_ADMISSION_INVALID_SOURCE")
    return namespace, relative


def _validate_evidence(evidence, *, legacy=False):
    if not isinstance(evidence, dict):
        raise ValueError("GEOMETRY_ADMISSION_INVALID_DOCUMENT")
    sources = evidence.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("GEOMETRY_ADMISSION_SOURCE_MISSING")
    if legacy:
        if "version" in evidence and (type(evidence["version"]) is not int or evidence["version"] != 1):
            raise ValueError("GEOMETRY_ADMISSION_UNSUPPORTED_VERSION")
    else:
        if any(_absolute(key) for key in sources) or _absolute(evidence.get("grid_source")):
            raise ValueError("GEOMETRY_ADMISSION_LEGACY_ABSOLUTE: regenerate with explicit --map-source")
        if type(evidence.get("version")) is not int or evidence["version"] != 2:
            raise ValueError("GEOMETRY_ADMISSION_UNSUPPORTED_VERSION")
    if set(evidence) - _FIELDS:
        raise ValueError("GEOMETRY_ADMISSION_UNSUPPORTED_FIELD")
    for key, expected in sources.items():
        if legacy:
            if not isinstance(key, str) or not key:
                raise ValueError("GEOMETRY_ADMISSION_INVALID_SOURCE")
        else:
            source_parts(key)
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            raise ValueError("GEOMETRY_ADMISSION_INVALID_HASH")
    grid_source = evidence.get("grid_source")
    if not isinstance(grid_source, str) or grid_source not in sources:
        raise ValueError("GEOMETRY_ADMISSION_GRID_UNBOUND")
    models = evidence.get("models")
    if not isinstance(models, dict):
        raise ValueError("GEOMETRY_ADMISSION_INVALID_MODELS")
    for model, multiples in models.items():
        if not isinstance(model, str) or not model or not isinstance(multiples, dict):
            raise ValueError("GEOMETRY_ADMISSION_INVALID_MODELS")
        if (set(multiples) != {"w", "l"}
                or any(type(value) is not int or value < 1 for value in multiples.values())):
            raise ValueError("GEOMETRY_ADMISSION_INVALID_MULTIPLE")
    if any(not isinstance(evidence[key], str) for key in _METADATA & evidence.keys()):
        raise ValueError("GEOMETRY_ADMISSION_INVALID_METADATA")


def read_source(key, runtime):
    namespace, relative = source_parts(key)
    root = runtime.get("geometry_admission_project" if namespace == "case" else "installed_pdk_root")
    if not isinstance(root, (str, Path)) or not str(root):
        raise ValueError("GEOMETRY_ADMISSION_RUNTIME_ROOT_MISSING: " + namespace)
    try:
        container = runtime.get("container")
        if namespace == "pdk" and container and not _ce.no_container_route():
            result = subprocess.run(
                _ce.docker_exec_argv(container, "python3", "-c", _CONTAINER_READ, str(root), relative),
                capture_output=True, timeout=30)
            if result.returncode:
                raise ValueError("GEOMETRY_ADMISSION_SOURCE_CHANGED: " + key)
            return result.stdout
        root = Path(root).resolve(strict=True)
        source = (root / relative).resolve(strict=True)
        if not root.is_dir() or not source.is_relative_to(root) or not source.is_file():
            raise ValueError("GEOMETRY_ADMISSION_SOURCE_CHANGED: " + key)
        return source.read_bytes()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, _ce.ContainerImageMismatch):
            raise
        raise ValueError("GEOMETRY_ADMISSION_SOURCE_CHANGED: " + key) from exc


def verify_admission(evidence, runtime):
    _validate_evidence(evidence)
    grid_bytes = None
    for key, expected in evidence["sources"].items():
        content = read_source(key, runtime)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("GEOMETRY_ADMISSION_SOURCE_CHANGED: " + key)
        if key == evidence["grid_source"]:
            grid_bytes = content
    from analog_lef_gds_outline_check import manufacturing_grid_um

    with tempfile.NamedTemporaryFile(suffix=".tlef") as staged:
        staged.write(grid_bytes)
        staged.flush()
        grid = manufacturing_grid_um(Path(staged.name).parent, staged.name)
    if grid is None or not math.isfinite(grid) or grid <= 0:
        raise ValueError("GEOMETRY_ADMISSION_GRID_ABSENT")
    return VerifiedAdmission(grid, dict(evidence["sources"]), copy.deepcopy(evidence["models"]))


def migrate_admission(evidence, mappings, runtime):
    """Keep the expected hashes; relocating evidence cannot admit new bytes."""
    _validate_evidence(evidence, legacy=True)
    if set(mappings) != set(evidence["sources"]):
        raise ValueError("GEOMETRY_ADMISSION_MAPPING_INCOMPLETE")
    if len(set(mappings.values())) != len(mappings):
        raise ValueError("GEOMETRY_ADMISSION_DUPLICATE_SOURCE")
    portable = {"version": 2, "grid_source": mappings[evidence["grid_source"]],
                "sources": {mappings[key]: expected for key, expected in evidence["sources"].items()},
                "models": copy.deepcopy(evidence["models"])}
    portable.update({key: evidence[key] for key in _METADATA & evidence.keys()})
    verify_admission(portable, runtime)
    return portable


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--pdk-root", required=True, type=Path)
    parser.add_argument("--container", default="")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--map-source", action="append", default=[], metavar="OLDKEY=case:REL|pdk:REL")
    args = parser.parse_args(argv)
    try:
        mappings = {}
        for item in args.map_source:
            if "=" not in item:
                raise ValueError("GEOMETRY_ADMISSION_INVALID_MAPPING")
            old, new = item.rsplit("=", 1)
            if old in mappings:
                raise ValueError("GEOMETRY_ADMISSION_DUPLICATE_SOURCE")
            source_parts(new)
            mappings[old] = new
        runtime = {"geometry_admission_project": args.project,
                   "installed_pdk_root": args.pdk_root, "container": args.container}
        portable = migrate_admission(load_admission(args.input), mappings, runtime)
        project = args.project.resolve(strict=True)
        output = args.output or project / "input/analog_geometry_admission.json"
        output = output.resolve()
        if not output.is_relative_to(project):
            raise ValueError("GEOMETRY_ADMISSION_OUTPUT_OUTSIDE_PROJECT")
        serialized = (json.dumps(portable, indent=2, sort_keys=True) + "\n").encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as staged:
            temporary = Path(staged.name)
            try:
                staged.write(serialized)
                staged.flush()
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
    except (_ce.ContainerImageMismatch, ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "GEOMETRY_ADMISSION_PUBLICATION_REFUSED")
        return 2
    print("GEOMETRY_ADMISSION_MIGRATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
