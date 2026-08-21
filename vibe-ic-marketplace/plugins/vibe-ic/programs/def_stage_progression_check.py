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
  4b. Signal-routing check   — of that geometry, the NETS section (design
                               interconnect) must carry some. Check 4 alone is
                               satisfied by the power grid, which the PDN
                               writes before detailed routing runs, so it
                               answers "yes" for four of the five stages and
                               cannot distinguish "detailed routing completed"
                               from "detailed routing aborted".

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
    has_routing: bool = False  # routed-wire indicator (ANY section)
    signal_route_stmts: int = 0   # `+ ROUTED`/`+ SHAPE` inside NETS
    special_route_stmts: int = 0  # ... inside SPECIALNETS (the power grid)
    declared_signal_nets: int = 0  # `NETS <n> ;`


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


def _routing_by_section(path: Path) -> tuple[int, int, int]:
    """Split routing geometry by the DEF section that carries it.

    Returns ``(signal_route_stmts, special_route_stmts, declared_signal_nets)``.

    `_has_routing` above answers "does this DEF contain ANY routed-wire
    geometry", and that is the question Check 4 used to ask. It is not the
    question Check 4 means. A DEF's power grid lives in ``SPECIALNETS`` and is
    written by the PDN step, which runs BEFORE detailed routing — so from
    `placed.def` onward every stage answers "yes" whether or not the detailed
    router ever ran. The column is constant across four of the five stages and
    therefore carries no information about the one event it is read for.

    The property Check 4 means is *design interconnect*: routing statements
    inside the ``NETS`` section. This function separates the two, and also
    reports the declared signal-net count so "0 routed" can be distinguished
    from "0 declared" (a design with no signal nets is not unrouted, it is
    empty, and that is a different finding).

    chip-AGNOSTIC: DEF grammar only — no PDK, library, or design literal.
    """
    sig = spc = declared = 0
    in_special = in_nets = False
    try:
        with path.open(errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("SPECIALNETS"):
                    in_special, in_nets = True, False
                    continue
                if s.startswith("END SPECIALNETS"):
                    in_special = False
                    continue
                if s.startswith("NETS"):
                    in_nets, in_special = True, False
                    m = re.match(r"NETS\s+(\d+)\s*;", s)
                    if m:
                        declared = int(m.group(1))
                    continue
                if s.startswith("END NETS"):
                    in_nets = False
                    continue
                if "+ ROUTED" in line or "+ SHAPE" in line:
                    if in_nets:
                        sig += 1
                    elif in_special:
                        spc += 1
    except OSError:
        return 0, 0, 0
    return sig, spc, declared


def _count_route_segments(path: Path) -> int:
    """Count routed-wire statements in a DEF: each `+ ROUTED` / `+ SHAPE` wire
    start plus every `NEW <layer> …` continuation segment. This is a monotone
    proxy for routing WORK: detailed routing can only ADD segments over the
    global/estimated routing carried by the prior stage, and a truncated or
    stubbed DEF cannot inflate it. Used to prove a post_hold -> routed byte
    SHRINK is a compact re-encoding (more segments, fewer bytes), not a
    truncation. Pure aside from the read; PDK-agnostic (DEF syntax, not a
    chip literal)."""
    n = 0
    try:
        with path.open(errors="replace") as f:
            for line in f:
                if "+ ROUTED" in line or "+ SHAPE" in line:
                    n += 1
                elif line.lstrip().startswith("NEW "):
                    n += 1
    except OSError:
        return 0
    return n


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

# The implicit marker above is emitted by `catch {detailed_route}`, so it
# fires for BOTH states it is asked to tell apart:
#   (a) the PDK has no detailed-router rule files, the router refuses at
#       setup, and an unrouted DEF is the expected, declared outcome; and
#   (b) the router loaded the tech, started on the design, and ABORTED —
#       an unrouted DEF that is a failure.
# Keyed on the marker alone, a routing abort is silently reclassified as the
# intentional mode, which is the one reading that must never be automatic.
# These markers are printed only once the router is past tech/rule setup and
# working on the design, so their presence is positive evidence of (b).
# chip-AGNOSTIC: router phase markers, not chip, PDK or library literals.
_DETAILED_ROUTER_REACHED_DESIGN = (
    "Start pin access",      # DRT-0165 — per-instance pin work has begun
    "No access point for",   # DRT-0073 — a finding about a design instance
)


def _detailed_router_ran_on_design(project: Path) -> bool:
    """True when the PnR log proves the detailed router got past tech setup
    and began working on the design. Distinguishes a routing ABORT from a
    genuine global-route-only PDK, which cannot reach these phases."""
    pnr_dir = _pl.pnr_dir(project) if hasattr(_pl, "pnr_dir") else (
        project / "phase3" / "stage3" / "pnr")
    if not pnr_dir.is_dir():
        return False
    for log in pnr_dir.rglob("*.log"):
        try:
            with log.open(errors="replace") as f:
                for line in f:
                    if any(m in line for m in _DETAILED_ROUTER_REACHED_DESIGN):
                        return True
        except OSError:
            continue
    return False


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
        (info.signal_route_stmts,
         info.special_route_stmts,
         info.declared_signal_nets) = _routing_by_section(path)
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
    # A SECOND legitimate byte-shrink lives at the post_hold -> routed pair.
    # Detailed routing REPLACES the prior stage's global/estimated routing with
    # the final per-net geometry, and that re-encoding can come back a few
    # percent SMALLER while carrying strictly MORE routing — the routed DEF is a
    # compact superset, not a truncation. Measured on caravel_user_project x
    # sky130A: routed.def 38,573,330 B vs post_hold.def 38,998,185 B (-1.09%)
    # while COMPONENTS grew 9,991 -> 10,078 and routed-wire segments grew
    # 479,307 -> 484,980. A byte-monotone rule false-FAILs that, cascading Steps
    # 22/24/25/26/27/28/32-37. The exemption is gated on POSITIVE proof that
    # routing WORK did not shrink — instances non-decreasing AND routing present
    # AND route-segment count non-decreasing — so a genuinely truncated routed
    # DEF (which loses segments) still FAILs, and Check 3 (instance count) /
    # Check 4 (routing presence) remain the truncation guards. chip-AGNOSTIC:
    # the evidence is the DEF's own COMPONENTS / routed-segment counts.
    _NOOP_SHRINK_TOL = 0.01  # 1% — a re-ordering, not a truncation
    _noop_pair_ok = _hold_clean_noop_ok(project)
    prev_size = 0
    prev_name = None
    prev_info = None
    for i in infos:
        if i.size < prev_size:
            benign_noop = (
                prev_name == "post_cts" and i.name == "post_hold"
                and _noop_pair_ok
                and i.size >= prev_size * (1.0 - _NOOP_SHRINK_TOL)
            )
            benign_route = (
                prev_name == "post_hold" and i.name == "routed"
                and prev_info is not None
                and i.num_components >= prev_info.num_components
                and i.has_routing
                and _count_route_segments(project / i.path)
                    >= _count_route_segments(project / prev_info.path)
            )
            if not (benign_noop or benign_route):
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
        prev_info = i

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
    # --- Check 4b: the routing that is present must be DESIGN routing ---
    # Check 4 above is satisfied by ANY `+ ROUTED` statement, including the
    # ones the PDN writes into SPECIALNETS before detailed routing begins.
    # A run whose `detailed_route` aborts therefore still ships a routed.def
    # that answers "routing: yes" on the strength of its power grid alone,
    # while every signal net in it is bare. Downstream that state does not
    # present as "unrouted" — it presents as a large DRC count, an LVS
    # extraction with no interconnect and an EM report with no current, i.e.
    # three sign-off failures attributed to sign-off rather than to routing.
    # Ask the question directly.
    if rt.declared_signal_nets > 0 and rt.signal_route_stmts == 0:
        _msg = (
            f"routed.def declares {rt.declared_signal_nets} signal net(s) in "
            f"NETS but ZERO of them carry routing geometry — every "
            f"`+ ROUTED` / `+ SHAPE` statement in the file "
            f"({rt.special_route_stmts}) is in SPECIALNETS, i.e. the power "
            f"grid, which is written before detailed routing runs. The design "
            f"interconnect is absent from this DEF."
        )
        _aborted = _detailed_router_ran_on_design(project)
        if _is_global_route_only(project) and not _aborted:
            findings.append(Finding(
                severity="warning",
                rule="signal-nets-unrouted-global-route-only",
                message=_msg + " Demoted from error to warning: this run is "
                               "declared global-route-only and the PnR log "
                               "shows the detailed router never reached the "
                               "design.",
            ))
        else:
            findings.append(Finding(
                severity="error",
                rule="signal-nets-unrouted",
                message=_msg + (
                    " The PnR log shows the detailed router DID reach the "
                    "design and then stopped, so this is an aborted route, "
                    "not global-route-only mode." if _aborted else ""),
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
              f"sig_route={i.signal_route_stmts:>6}/{i.declared_signal_nets:<5} "
              f"pg_route={i.special_route_stmts:<5} "
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
    # Only claim routed geometry when the SIGNAL nets carry it. Saying
    # "routed geometry present" on the strength of the power grid is the
    # sentence this gate exists to make impossible.
    _rt = next((i for i in infos if i.name == "routed"), None)
    if _rt is not None and _rt.signal_route_stmts > 0:
        print("\nResult: OK — 5 stages present, distinct, monotone, "
              f"{_rt.signal_route_stmts} signal-net routing statement(s) "
              "present.")
    else:
        print("\nResult: OK (with warnings) — 5 stages present, distinct, "
              "monotone; NO signal-net routing recorded in routed.def.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
