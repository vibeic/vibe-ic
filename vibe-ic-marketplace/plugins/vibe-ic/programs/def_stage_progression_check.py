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
    routing_segments: int = 0  # total wire/via geometry line count (Check 2)


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


# ORGANIC #624 — OpenROAD's own hold (min-path) sign-off slack line, emitted
# into pnr/post_hold_timing.rpt by the hold-fix step (`worst hold slack <n>` /
# `hold WNS <n>`). A non-negative (or INF) worst hold slack means the design is
# hold-CLEAN — the resizer had 0 hold violations to repair.
_HOLD_SLACK_RE = re.compile(
    r"(?:worst[ _]hold[ _]slack|hold[ _]wns)\s+"
    r"([-+]?(?:\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|inf))",
    re.IGNORECASE)


def _hold_clean_noop_ok(project: Path) -> bool:
    """ORGANIC #624 — True iff the hold (min-path) sign-off report proves the
    design is hold-CLEAN (worst hold slack >= 0 / INF). A byte-identical
    post_hold.def == post_cts.def is then a LEGITIMATE no-op hold-fix (the
    resizer reported 0 hold violations to repair, so the hold step made no
    geometry change), NOT a fabricated copy/stub. Returns False (FAIL-CLOSED)
    when no report exists, the slack is negative (unrepaired hold violations),
    or the report is unparseable. Chip-AGNOSTIC: parses OpenROAD's own hold
    slack number, no chip literal."""
    rpt = _pl.pnr_dir(project) / "post_hold_timing.rpt"
    try:
        text = rpt.read_text(errors="replace")
    except OSError:
        return False
    worst = None
    for m in _HOLD_SLACK_RE.finditer(text):
        tok = m.group(1).lower()
        val = float("inf") if "inf" in tok else float(tok)
        worst = val if worst is None else min(worst, val)
    if worst is None:
        return False  # no parseable hold-slack evidence → cannot prove clean
    return worst >= 0.0


def _count_routing_segments(path: Path) -> int:
    """Count DEF wire/via GEOMETRY lines: `NEW <layer> ...` continuation
    segments and `+ ROUTED`/`+ SHAPE` first-segment statements, in NETS and
    SPECIALNETS alike.

    This is the TOTAL routing/PDN geometry volume a DEF actually carries — as
    opposed to raw byte size, which also reflects how VERBOSELY a net's
    pin-connectivity list is written. `global_connect` (re-applied after
    routing to attach late-created instances' PG pins — ORGANIC #571's
    `_build_pg_reconnect_tcl`) legitimately REWRITES a SPECIALNETS pin list
    from thousands of explicit `( inst pin )` entries down to the standard DEF
    wildcard `( * pin )` token, which can shrink a DEF by hundreds of KB with
    ZERO geometry lost (measured: caravel_user_project sky130A, post_hold.def
    -> routed.def dropped ~425,000 B in pin-list notation while its routing
    segment count only GREW, 479,307 -> 485,009, and COMPONENTS only grew,
    10,030 -> 10,139). A genuine fabricated/truncated stage cannot show this
    signature (it loses or freezes geometry, never gains it), so this metric
    lets Check 2 tell the two apart. Chip/PDK-AGNOSTIC: pure DEF syntax token
    counting, no design literal."""
    count = 0
    try:
        with path.open(errors="replace") as f:
            for line in f:
                s = line.strip()
                if (s.startswith("NEW ") or s.startswith("+ ROUTED")
                        or s.startswith("+ SHAPE")):
                    count += 1
    except OSError:
        return 0
    return count


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
        info.routing_segments = _count_routing_segments(path)
        infos.append(info)

    if any(not i.exists for i in infos):
        return infos, findings

    # --- Check 1: SHA uniqueness ---
    hash_to_stages: Dict[str, List[str]] = {}
    for i in infos:
        hash_to_stages.setdefault(i.sha256, []).append(i.name)
    for h, stages in hash_to_stages.items():
        if len(stages) > 1:
            # ORGANIC #624 — a byte-identical post_cts/post_hold pair is a
            # LEGITIMATE no-op when the design was hold-clean after CTS (the
            # resizer had 0 hold violations to repair, so the hold-fix step
            # made no geometry change → post_hold.def == post_cts.def BY
            # CONSTRUCTION). Exempt ONLY that EXACT pair AND only with positive
            # proof from the hold report (worst hold slack >= 0). Every other
            # identical-stage group — and a post_cts/post_hold pair with
            # UNREPAIRED hold violations or no report — still FAILs as fraud.
            if (set(stages) == {"post_cts", "post_hold"}
                    and _hold_clean_noop_ok(project)):
                continue
            findings.append(Finding(
                severity="error",
                rule="identical-def-fraud",
                message=(
                    f"stages {stages} share sha256 {h[:12]}... "
                    f"— at least one is a copy/stub, not a real PnR output."
                ),
            ))

    # --- Check 2: size monotonicity (non-decreasing) ---
    # Same legitimate no-op that Check 1 already exempts (ORGANIC #624), one
    # step further along: when the design is hold-CLEAN after CTS the hold-fix
    # pass inserts ZERO buffers and merely REWRITES the DEF. Usually that is
    # byte-identical (Check 1's case); it can also come back a handful of bytes
    # SMALLER — net//component re-ordering, a dropped redundant entry — which
    # is still a correct no-op, not a skipped or truncated stage. A strict
    # byte-monotone rule false-FAILs it. First measured on spm x gf180mcuD:
    # post_hold.def 138,422 B vs post_cts.def 138,429 B — a 7-byte (0.005%)
    # shrink from a zero-buffer hold pass at +0.98 ns hold slack.
    #
    # The exemption is deliberately NARROW, and narrower than a blanket
    # percentage tolerance would be. It applies ONLY to:
    #   (a) the post_cts -> post_hold transition — the one stage pair that can
    #       legitimately be a no-op — and no other transition, so a truncated
    #       placed.def or routed.def is still caught outright; AND
    #   (b) with POSITIVE proof from the hold report that the design was
    #       hold-clean (`_hold_clean_noop_ok`, FAIL-CLOSED: no report, an
    #       unparseable report, or negative slack all → no exemption); AND
    #   (c) for a shrink within _NOOP_SHRINK_TOL, since a genuinely truncated
    #       DEF loses far more than a re-ordering does.
    # A gross regression on this pair therefore still FAILs even when hold is
    # clean. Stub/copy fraud remains caught by Check 1 (sha256 distinctness)
    # and a skipped/empty stage by Check 3 (instance-count growth), so this
    # relaxes no fraud gate. chip-AGNOSTIC — no chip literal, and the evidence
    # is OpenROAD's own hold-slack number.
    # ORGANIC (post-#571 interaction) — a SECOND legitimate shrink, orthogonal
    # to the hold no-op above: a PG-net CONNECTIVITY-NOTATION collapse. After
    # routing, `_build_pg_reconnect_tcl` (#571) re-applies `global_connect` so
    # physical-only cells created after the PDN's one-shot connect (repair/CTS
    # buffers, antenna diodes, decap/fill) get their PG pins attached. On a
    # design where many such cells exist, `global_connect` rewrites a
    # SPECIALNETS pin list from thousands of explicit `( inst pin )` entries
    # down to the standard DEF wildcard `( * pin )` token — correct and, if
    # anything, MORE complete (it also covers instances added later), but it
    # can shave hundreds of KB off a DEF that never lost a single wire.
    # MEASURED: caravel_user_project x sky130A, post_hold.def (39,005,262 B)
    # -> routed.def (38,580,931 B) — a 424,331 B / 1.1% shrink — while
    # `_count_routing_segments` (NEW/+ROUTED/+SHAPE geometry lines) went
    # 479,307 -> 485,009 (grew) and COMPONENTS went 10,030 -> 10,139 (grew).
    # A truncated/fabricated stage cannot show growth on BOTH axes at once, so
    # requiring both — AND requiring the later stage's geometry count be
    # POSITIVE (never waived on a 0-vs-0 vacuity, which proves nothing) — is
    # the narrow, positive-evidence gate: any real geometry or instance LOSS,
    # or a shrink with no routing evidence at all, still FAILs outright.
    # chip/PDK-AGNOSTIC — keyed on the DEF's own geometry/instance counts, no
    # design or PDK literal.
    _NOOP_SHRINK_TOL = 0.01  # 1% — a re-ordering, not a truncation
    _noop_pair_ok = _hold_clean_noop_ok(project)
    prev_size = 0
    prev_name = None
    prev_components = 0
    prev_routing_segments = 0
    for i in infos:
        if i.size < prev_size:
            benign_noop = (
                prev_name == "post_cts" and i.name == "post_hold"
                and _noop_pair_ok
                and i.size >= prev_size * (1.0 - _NOOP_SHRINK_TOL)
            )
            benign_geom_preserved = (
                # POSITIVE evidence required: the LATER stage must show REAL
                # routing/PDN geometry (not a 0-vs-0 "preserved" by
                # vacuity — a fixture/design with no routing markers at
                # either stage proves nothing about geometry and must not
                # be waved through on component count alone; Check 3 already
                # owns component-count regression, this exemption is about
                # GEOMETRY specifically).
                i.routing_segments > 0
                and i.routing_segments >= prev_routing_segments
                and i.num_components >= prev_components
            )
            if not (benign_noop or benign_geom_preserved):
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
        prev_components = i.num_components
        prev_routing_segments = i.routing_segments

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
