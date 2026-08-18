#!/usr/bin/env python3
"""
rig_topology_disclosure_check.py — verify hardware rig topology is declared.

Fresh agents waste FPGA compile cycles guessing pin assignments when a
project's input docs don't declare the hardware rig (board, pin map,
scope channels, tester port).  This gate checks that the project
contains a rig topology declaration with the minimum required fields.

Searched locations (first match wins)
-------------------------------------
1. ``<project>/rig_topology.json``
2. ``<project>/rig_topology.yaml``
3. ``<project>/rig_topology.md``  (presence only — no field validation)
4. ``<project>/input/rig_topology.{json,yaml,md}``
5. ``<project>/generated_docs/rig_topology.{json,yaml,md}``
6. ``rig_topology`` key inside ``<project>/spec.json``
7. ``rig_topology`` key inside ``<project>/generated_docs/L9_INTEGRATION_SPEC.json``

Required fields (ERROR if missing)
-----------------------------------
- ``fpga_board``  (str)
- ``fpga_pin_assignments``  (dict)
- ``dut_connection``  (str | dict)

Optional fields (WARN if missing)
----------------------------------
- ``scope_channel_map``
- ``tester_port``

Usage
-----
    rig_topology_disclosure_check.py <project_dir> [--json]

Exit codes
----------
    0 = PASS (topology found and valid)
    1 = FAIL (missing topology or missing required fields)
    2 = input missing (project dir doesn't exist)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpga_board_capability as _fpga_cap  # noqa: E402


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    message: str


_REQUIRED_FIELDS = ("fpga_board", "fpga_pin_assignments", "dut_connection")
_OPTIONAL_FIELDS = ("scope_channel_map", "tester_port")

_RIG_BASENAMES = ("rig_topology.json", "rig_topology.yaml", "rig_topology.md")
_SEARCH_SUBDIRS = ("", "input", "generated_docs")


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(errors="replace"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_yaml(path: Path) -> dict | None:
    if not _HAS_YAML:
        return None
    try:
        data = yaml.safe_load(path.read_text(errors="replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _find_topology(project: Path) -> tuple[dict | None, str | None]:
    """Return (topology_dict, source_description) or (None, None)."""
    for subdir in _SEARCH_SUBDIRS:
        base = project / subdir if subdir else project
        if not base.is_dir():
            continue
        for name in _RIG_BASENAMES:
            candidate = base / name
            if not candidate.is_file():
                continue
            if name.endswith(".md"):
                return {}, str(candidate)
            if name.endswith(".json"):
                data = _load_json(candidate)
            else:
                data = _load_yaml(candidate)
            if data is not None:
                return data, str(candidate)

    for json_name in ("spec.json", "phase1/generated_docs/L9_INTEGRATION_SPEC.json"):
        candidate = project / json_name
        if candidate.is_file():
            data = _load_json(candidate)
            if data and "rig_topology" in data and isinstance(data["rig_topology"], dict):
                return data["rig_topology"], f"{candidate}#rig_topology"

    return None, None


def _validate(topo: dict, source: str) -> list[Finding]:
    findings: list[Finding] = []

    if source.endswith(".md"):
        findings.append(Finding(
            "INFO", "rig_topology_markdown",
            source,
            "Rig topology declared as Markdown — field validation skipped.",
        ))
        return findings

    for field in _REQUIRED_FIELDS:
        if field not in topo:
            findings.append(Finding(
                "ERROR", "rig_topology_missing_required",
                source,
                f"Required field `{field}` missing from rig topology.",
            ))
        elif field == "fpga_pin_assignments" and not isinstance(topo[field], dict):
            findings.append(Finding(
                "ERROR", "rig_topology_bad_type",
                source,
                f"`fpga_pin_assignments` must be a dict, got {type(topo[field]).__name__}.",
            ))

    for field in _OPTIONAL_FIELDS:
        if field not in topo:
            findings.append(Finding(
                "WARN", "rig_topology_missing_optional",
                source,
                f"Optional field `{field}` not declared — agent may guess.",
            ))

    return findings


def check(project: Path) -> tuple[list[Finding], str | None]:
    topo, source = _find_topology(project)
    if topo is None:
        # A hardware rig topology is meaningless without hardware to wire it
        # to. When this run HONESTLY discloses no FPGA board is part of it
        # (#607's predicate, shared via fpga_board_capability.py — the same
        # signal that already exempts the dedicated FPGA-board flow steps),
        # a missing rig_topology.json is not a gap; it is correctly absent.
        # Still DISCLOSED, not silent: an INFO finding is emitted either way,
        # and if FPGA bring-up is later added to this project, the ERROR
        # returns the moment quartus_map_audit.json no longer discloses SKIP.
        # The NARROW predicate: waiving a documentation requirement needs
        # "no board was ever part of this run", not merely "no .sof exists".
        if _fpga_cap.fpga_absent_from_run(project):
            return [Finding(
                "INFO", "rig_topology_na_no_fpga_run",
                str(project),
                "No rig topology declared, and none is needed: this run "
                "discloses no FPGA board is part of it "
                "(reports/phase2/fpga/quartus_map_audit.json verdict=SKIP, "
                "sof_present=false).",
            )], None
        return [Finding(
            "ERROR", "rig_topology_not_found",
            str(project),
            "No rig topology declaration found. Create rig_topology.json "
            "with at least: fpga_board, fpga_pin_assignments, dut_connection.",
        )], None
    return _validate(topo, source), source


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check that a project declares its hardware rig topology.",
    )
    ap.add_argument("project_dir", help="Project root directory.")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH",
                    help="Emit JSON. Bare flag prints to stdout; with PATH writes to file.")
    args = ap.parse_args()

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    findings, source = check(project)
    errors = [f for f in findings if f.severity == "ERROR"]
    warns = [f for f in findings if f.severity == "WARN"]
    verdict = "PASS" if not errors else "FAIL"

    result = {
        "project": str(project),
        "source": source,
        "errors": len(errors),
        "warnings": len(warns),
        "findings": [asdict(f) for f in findings],
        "verdict": verdict,
    }

    if args.json:
        txt = json.dumps(result, indent=2)
        if args.json == "-":
            print(txt)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}")
            print(f"        {f.message}")
        print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
        print(verdict)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
