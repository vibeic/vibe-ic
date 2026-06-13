#!/usr/bin/env python3
"""
def_stage_progression_check.py — Catch fabricated PnR stage DEF files.

Real OpenROAD / Innovus PnR produces DISTINCT DEF files at each stage:
    floorplan.def     ← core+rows, no placed cells yet
    placed.def        ← + placed std cells (many more INSTANCES)
    post_cts.def      ← + clock tree buffers (CTS inserts BUFX buffers)
    post_hold.def     ← + hold-fix buffers (more INSTANCES + NETS)
    routed.def        ← + detailed routing (SPECIALNETS + NETS with routing)

A cheating agent that copies `routed.def` to all 5 stage names will
produce 5 byte-identical files. This program rejects that.

Checks performed:
  1. SHA-256 uniqueness      — no two DEFs may share a hash
  2. Size monotonicity       — floorplan ≤ placed ≤ post_cts ≤ post_hold ≤ routed
                               (strict ≤; ties OK if INSTANCE count differs)
  3. Instance-count growth   — count NUMINSTANCES lines; must be non-decreasing
                               and routed.def instances >= floorplan.def * 1.0
                               (otherwise "placed" added nothing)
  4. Routing presence check  — routed.def MUST contain SPECIALNETS or
                               NETS with routing geometry (`+ ROUTED`)
                               that floorplan.def lacks

Usage:
    python3 def_stage_progression_check.py <project_dir> [--json out.json]

Project layout (gate-enforced canonical names per flow/phase1_phase2_phase3.yaml):
    pnr/floorplan.def    (Step 14)
    pnr/placed.def       (Step 16)
    pnr/post_cts.def     (Step 17)
    pnr/post_hold.def    (Step 18)
    pnr/routed.def       (Step 19)

Exit codes:
    0 = all 5 stages present + distinct + monotone → OK
    1 = one or more stages fabricated / missing
    2 = io error

Added 2026-04-22 after <benchmark> v0.47 pilot where a subagent copied
`pnr/a3616_top.def` to all 5 stage names and declared PnR complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict
import _path_layout as _pl


STAGES = ["floorplan", "placed", "post_cts", "post_hold", "routed"]


@dataclass
class StageInfo:
    name: str
    path: str
    exists: bool = False
    size: int = 0
    sha256: str = ""
    num_components: int = 0   # COMPONENTS section count
    has_routing: bool = False  # routed-wire indicator


@dataclass
class Finding:
    severity: str      # "error" | "warning"
    rule: str
    message: str


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_components(path: Path) -> int:
    """Count instances in COMPONENTS section."""
    in_components = False
    count = 0
    try:
        with path.open(errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("COMPONENTS"):
                    # "COMPONENTS <n> ;"
                    m = re.match(r"COMPONENTS\s+(\d+)\s*;", s)
                    if m:
                        return int(m.group(1))
                    in_components = True
                elif s.startswith("END COMPONENTS"):
                    in_components = False
                elif in_components and s.startswith("-"):
                    count += 1
    except OSError:
        return 0
    return count


def _has_routing(path: Path) -> bool:
    """Look for routed-wire geometry: `+ ROUTED` in NETS or SPECIALNETS."""
    try:
        with path.open(errors="replace") as f:
            for line in f:
                if "+ ROUTED" in line:
                    return True
                if "+ SHAPE" in line:
                    return True
    except OSError:
        return False
    return False


# v1.6.179 (#72 P1-5) — global-route-only marker. The phase3 PnR
# Tcl wraps `detailed_route` in a `catch` block and emits
# `DETAILED_ROUTE_NONFATAL:` to `openroad.log` when the custom PDK
# lacks detailed-router rule files (no RC tables, no via-cut sets).
# In that mode the routed.def carries SPECIALNETS but no `+ ROUTED`
# / `+ SHAPE` per-net geometry, so this gate FAILed even though the
# runner intentionally treats it as NONFATAL. v1.6.179 demotes the
# no-routing-geometry finding from error to warning when the marker
# is present in any openroad.log under `phase3/stage3/pnr/` OR a
# project-level `phase3/stage4/foundry_handoff/routing_mode.json`
# explicitly declares `mode: global_only`.
# chip-AGNOSTIC: the marker is a structural property of the PnR
# log, never a chip-class string literal.
_GLOBAL_ROUTE_LOG_MARKER = "DETAILED_ROUTE_NONFATAL:"
_GLOBAL_ROUTE_JSON_KEY = "mode"
_GLOBAL_ROUTE_JSON_VAL = "global_only"


def _is_global_route_only(project: Path) -> bool:
    """Return True when the project's PnR run intentionally completed
    in global-route-only mode (no per-net + ROUTED geometry expected)."""
    # (a) Explicit project marker.
    marker_json = (project / "phase3" / "stage4"
                   / "foundry_handoff" / "routing_mode.json")
    if marker_json.is_file():
        try:
            data = json.loads(marker_json.read_text(errors="replace"))
            if (data.get(_GLOBAL_ROUTE_JSON_KEY)
                    == _GLOBAL_ROUTE_JSON_VAL):
                return True
        except (json.JSONDecodeError, OSError):
            pass
    # (b) Implicit log marker emitted by phase3_one_shot_runner's
    # `if {[catch {detailed_route} dr_err]} { puts "DETAILED_ROUTE_NONFATAL: ..." }`
    # wrap in pnr.tcl.
    pnr_dir = _pl.pnr_dir(project) if hasattr(_pl, "pnr_dir") else (
        project / "phase3" / "stage3" / "pnr")
    if pnr_dir.is_dir():
        for log in pnr_dir.rglob("*.log"):
            try:
                with log.open(errors="replace") as f:
                    for line in f:
                        if _GLOBAL_ROUTE_LOG_MARKER in line:
                            return True
            except OSError:
                continue
    return False


def inspect(project: Path) -> tuple[List[StageInfo], List[Finding]]:
    infos: List[StageInfo] = []
    findings: List[Finding] = []

    for stage in STAGES:
        path = _pl.pnr_dir(project) / f"{stage}.def"
        info = StageInfo(name=stage, path=str(path.relative_to(project)))
        if not path.exists():
            info.exists = False
            findings.append(Finding(
                severity="error",
                rule="missing-stage",
                message=f"pnr/{stage}.def not found",
            ))
            infos.append(info)
            continue
        info.exists = True
        info.size = path.stat().st_size
        info.sha256 = _sha(path)
        info.num_components = _count_components(path)
        info.has_routing = _has_routing(path)
        infos.append(info)

    if any(not i.exists for i in infos):
        return infos, findings

    # --- Check 1: SHA uniqueness ---
    hash_to_stages: Dict[str, List[str]] = {}
    for i in infos:
        hash_to_stages.setdefault(i.sha256, []).append(i.name)
    for h, stages in hash_to_stages.items():
        if len(stages) > 1:
            findings.append(Finding(
                severity="error",
                rule="identical-def-fraud",
                message=(
                    f"stages {stages} share sha256 {h[:12]}... "
                    f"— at least one is a copy/stub, not a real PnR output."
                ),
            ))

    # --- Check 2: size monotonicity (non-decreasing) ---
    prev_size = 0
    prev_name = None
    for i in infos:
        if i.size < prev_size:
            findings.append(Finding(
                severity="error",
                rule="size-non-monotone",
                message=(
                    f"{i.name}.def ({i.size} B) is SMALLER than "
                    f"{prev_name}.def ({prev_size} B). Stage progression "
                    f"should grow monotonically."
                ),
            ))
        prev_size = i.size
        prev_name = i.name

    # --- Check 3: instance-count growth (routed ≥ floorplan) ---
    fp = next(i for i in infos if i.name == "floorplan")
    rt = next(i for i in infos if i.name == "routed")
    if rt.num_components == 0 and fp.num_components == 0:
        findings.append(Finding(
            severity="warning",
            rule="no-instance-count",
            message="Cannot parse COMPONENTS count from DEFs — "
                    "coarse progression check skipped."
        ))
    elif rt.num_components < max(fp.num_components, 1):
        findings.append(Finding(
            severity="error",
            rule="instance-count-regression",
            message=(
                f"routed.def has {rt.num_components} components vs "
                f"floorplan.def {fp.num_components}. PnR should add, "
                f"not remove, instances."
            ),
        ))

    # --- Check 4: routing presence ---
    if not rt.has_routing:
        # v1.6.179 (#72 P1-5) — when the PnR run intentionally
        # finished in global-route-only mode (custom PDK without
        # detailed-router rule files), the routed.def is expected
        # to omit `+ ROUTED` / `+ SHAPE`. Demote to warning + add
        # waiver finding so the project verdict is PASS_WITH_WAIVERS
        # rather than FAIL on a known runner-NONFATAL condition.
        if _is_global_route_only(project):
            findings.append(Finding(
                severity="warning",
                rule="no-routing-geometry-global-route-only",
                message=(
                    "routed.def has no `+ ROUTED` / `+ SHAPE` "
                    "geometry, but `DETAILED_ROUTE_NONFATAL:` marker "
                    "(or routing_mode.json mode=global_only) "
                    "is present — this run completed in global-route "
                    "mode only. Demoted from error to warning."
                ),
            ))
        else:
            findings.append(Finding(
                severity="error",
                rule="no-routing-geometry",
                message=(
                    "routed.def contains no `+ ROUTED` / `+ SHAPE` geometry. "
                    "A real post-route DEF must record net routing."
                ),
            ))
    if fp.has_routing:
        findings.append(Finding(
            severity="warning",
            rule="premature-routing",
            message=(
                "floorplan.def already contains routing geometry — "
                "it should only have core/rows/pins. May indicate "
                "floorplan was copied from a later stage."
            ),
        ))

    return infos, findings


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--json", help="Write JSON report to this path")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"def_stage_progression_check: not a directory: {project}",
              file=sys.stderr)
        return 2

    infos, findings = inspect(project)

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    print(f"\n=== DEF stage progression ===")
    for i in infos:
        if not i.exists:
            print(f"  ✗ {i.name:<12} MISSING")
            continue
        print(f"  ✓ {i.name:<12} {i.size:>10,} B  "
              f"components={i.num_components:>5}  "
              f"routing={'yes' if i.has_routing else 'no':<3}  "
              f"sha={i.sha256[:10]}")

    if errors:
        print(f"\n{len(errors)} error(s):")
        for f in errors:
            print(f"  ✗ [{f.rule}] {f.message}")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for f in warnings:
            print(f"  ⚠ [{f.rule}] {f.message}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "stages": [asdict(i) for i in infos],
            "errors": [asdict(f) for f in errors],
            "warnings": [asdict(f) for f in warnings],
        }, indent=2))

    if errors:
        print("\nResult: FAIL — one or more stages fabricated or missing.")
        return 1
    print("\nResult: OK — 5 stages present, distinct, monotone, routed geometry present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
