#!/usr/bin/env python3
"""
signoff_audit.py -- Multi-mode signoff evidence checker (LEGACY gate).

Deterministic compliance program that verifies signoff readiness by scanning
for evidence of completed pipeline stages and tapeout prerequisites.

This is the LEGACY coarse-grained gate. For the 33-step Vibe-IC canonical
flow, use `flow_compliance_check.py` instead — it validates every mandatory
step, not just 4 coarse buckets.

Modes:
  tapeout  -- Check for GDS, netlist, timing report, DRC report, LVS report
  flow     -- Check for synth, pnr, gds, sta stage evidence

Default threshold (updated 2026-04-21): strict, ALL slots required.
(Previously 3 of 4 — that was too lenient and let 7-of-28-step designs
pass as "signed off". The lenient mode was removed in v1.6.21.)

2026-07-27 -- tapeout mode gained a FIFTH pillar (LVS) and lost two
existence-only slots:

  * LVS: a foundry tape-out is DEFINED by a genuine LVS match. The
    tapeout-tier LVS gate (`lvs_tapeout_signoff_check`) already existed
    but was ORPHANED — nothing in the executed flow ever invoked it, so
    Step 36 certified "tapeout checklist" on a project that had never
    proven layout-vs-schematic. The tapeout threshold is now 5 of 5.
  * netlist / timing: both slots credited `rglob()[0]` — an arbitrary
    filesystem-order pick, the same existence-only bug class the DRC slot
    was fixed for in #437a. They now rank candidates sign-off-first (the
    post-route netlist and the post-route/SPEF STA outrank synthesis and
    pre-layout artefacts) and REFUSE to credit the slot when every
    candidate is a self-declared pre-sign-off intermediate.

v0.52 (2026-04-24): file discovery now excludes `input/`, `pdk/`,
`vendor_ref/`, `references/` path segments. Prior versions counted
PDK standard-cell GDS under `input/pdk/gds/` as design GDS evidence
— a false-positive surfaced by the `phase2+3_v051` fresh-agent run.

Usage:
    python3 signoff_audit.py <project_dir> --mode tapeout
    python3 signoff_audit.py <project_dir> --mode flow --json out.json

Exit codes:
    0 = PASS (sufficient evidence found, NO waivers — a bare/absolute PASS)
    1 = FAIL (insufficient evidence)
    3 = PASS_WITH_WAIVERS (sufficient evidence, but at least one slot was
        credited via a WAIVER — e.g. a DRC step waived because it was
        100% stdcell-library-internal, or DRC/LVS ENV_UNAVAILABLE). A
        distinct rc so the flow gate (`tapeout_signoff_check`, an rc-only
        `program_exit_zero` predicate) can carry the WITH_WAIVERS
        distinction instead of collapsing it onto a bare PASS. #651 /
        CLAUDE.md rule 11: PASS_WITH_WAIVERS must NEVER read as bare PASS.

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

# #651 — dedicated, documented exit code for the PASS_WITH_WAIVERS verdict
# tier. Distinct from 0 (bare PASS) and 1 (FAIL); also distinct from the
# flow-runner's rc=2 "VACUOUS/SKIP input-missing" convention so a waived
# tapeout is NEVER misread as either a clean pass or a no-op skip.
WAIVER_EXIT_CODE = 3

# #651 — stdout sentinel printed (line-start) alongside rc=WAIVER_EXIT_CODE.
# The flow gate (`flow_compliance_check._check_program_exit_zero`) promotes
# a step to WAIVED-DEFERRED only when BOTH the rc AND this sentinel are
# present, so an unrelated program that merely happens to exit 3 cannot be
# mis-promoted into a waiver.
WAIVER_STDOUT_SENTINEL = "PASS_WITH_WAIVERS:"


def _resolve_threshold(default_strict: int, total: int) -> int:
    """Return the strict threshold (lenient mode removed in v1.6.21)."""
    return default_strict


# v1.6.178 (#72 P2-7) — DRC/LVS ENV_UNAVAILABLE waiver detection.
# When Calibre is absent (open-source containers don't ship it),
# `phase3_one_shot_runner` records DRC/LVS steps as
# `status: "ENV_UNAVAILABLE"`. The tapeout-mode signoff gate must
# treat that as a waiver tier (PASS_WITH_WAIVERS) rather than
# silently PASS — a tapeout checklist that couldn't run DRC is
# not really tapeout-ready. chip-AGNOSTIC: the marker is a
# structural property of the phase3 report, never a chip-class
# literal. The check looks at every plausible phase3_one_shot.json
# location since `_pl.report_path` has rotated across the post-
# Wave-91 canonical layout.
_PHASE3_REPORT_CANDIDATES = (
    "reports/phase3_one_shot.json",
    "reports/orchestrator/phase3_one_shot.json",
    "phase3/reports/phase3_one_shot.json",
)


def _read_phase3_env_unavailable_steps(project_dir: Path) -> List[str]:
    """Return the names of phase3 steps reported as ENV_UNAVAILABLE.

    Only DRC / LVS-relevant step names are returned (other ENV_UNAVAILABLE
    steps are not Step-33 waivers). Missing / unreadable / parse-error
    reports return an empty list — callers fall through to the strict
    threshold check.
    """
    for cand in _PHASE3_REPORT_CANDIDATES:
        p = project_dir / cand
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        steps = data.get("steps")
        if not isinstance(steps, list):
            continue
        env_unavail: List[str] = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip().lower()
            status = str(s.get("status", "")).strip()
            if status == "ENV_UNAVAILABLE" and name in (
                    "drc", "lvs", "perc"):
                env_unavail.append(name)
        return env_unavail
    return []


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------
# Path segments that contain INPUTS (PDK / vendor docs / OTP image / etc.) and
# must never be counted as design OUTPUT evidence. The 2026-04-24 v0.51 pilot
# exposed this bug: the gate accepted `input/pdk/gds/<stdcell>.gds` as proof
# of a tape-out-ready design GDS. PDK standard-cell views are inputs, not the
# chip you're shipping.
_INPUT_PATH_SEGMENTS = {"input", "inputs", "pdk", "vendor_ref",
                        "references", "ref"}


def _is_input_path(path: Path, project_dir: Path) -> bool:
    """True if any path segment between project_dir and the file is an input
    directory (case-insensitive)."""
    try:
        rel = path.relative_to(project_dir)
    except ValueError:
        return False
    for part in rel.parts[:-1]:  # exclude the file name itself
        if part.lower() in _INPUT_PATH_SEGMENTS:
            return True
    return False


def _has_files(project_dir: Path, patterns: List[str],
               exclude_inputs: bool = True) -> List[Path]:
    """Return list of matching files for any of the glob patterns.

    By default, excludes anything under input/ / inputs/ / pdk/ / vendor_ref/
    / references/ — those are design INPUTS, not output evidence. Set
    exclude_inputs=False for callers that legitimately want to scan inputs."""
    found: List[Path] = []
    for pat in patterns:
        for p in project_dir.rglob(pat):
            if exclude_inputs and _is_input_path(p, project_dir):
                continue
            found.append(p)
    return found


# ---------------------------------------------------------------------------
# Sign-off-first ranking for the netlist / timing evidence slots
# ---------------------------------------------------------------------------
# ORGANIC-20260606-existence-only-signoff-gates (#437a) was fixed for the DRC
# slot only. The netlist and timing slots kept crediting `rglob()[0]` — an
# arbitrary, filesystem-order pick with no ranking and no content check.
#
# Measured on a completed spm x ihp-sg13g2 run (2026-07-27, main @ v1.7.36):
#   TAPEOUT_NETLIST_EXISTS credited phase2/stage2/dft/scan_netlist_prelim.v
#     while the post-route netlist phase3/stage3/pnr/spm_pnr.v (100847 B) sat
#     in the same project — and matched NONE of the four netlist globs, so it
#     could not have been credited even if the slot had ranked its candidates.
#   TAPEOUT_TIMING_EXISTS credited steps/10_pre_layout_sta_multi_corner/
#     pre_pnr_timing.rpt — a PRE-layout STA — while
#     phase3/stage3/sta/post_route_timing.rpt existed.
# Both slots reported `true` and the checklist read 4/4 PASS.
#
# Two changes, mirroring the DRC slot 40 lines below which already does this:
#   (1) rank candidates sign-off-first and cite the best one;
#   (2) REFUSE to credit the slot when EVERY candidate is a self-declared
#       pre-sign-off intermediate. A preliminary netlist or a pre-layout STA
#       is not a thing a tape-out is signed off on, and a gate may explain an
#       absent artefact but may not certify the step without one.
# Ranking only ever REORDERS; the pre-sign-off refusal is a separate,
# separately-named substance rule so the two cannot be confused.
_PRESIGNOFF_MARKERS = (
    "prelim",          # covers "preliminary"
    "draft",
    "provisional",
    "pre_pnr", "pre-pnr", "prepnr",
    "pre_layout", "pre-layout", "prelayout",
    "pre_route", "pre-route", "preroute",
    "pre_place", "pre-place", "preplace",
    "preview",
)


def _rel_parts(path: Path, project_dir: Path) -> List[str]:
    """Lower-cased path segments of `path` relative to `project_dir`.

    Falls back to the file name alone when `path` is not under
    `project_dir`, so a project checked out below e.g. /home/x/draft/ can
    never be mistaken for a project full of draft artefacts.
    """
    try:
        rel = path.relative_to(project_dir)
    except ValueError:
        return [path.name.lower()]
    return [p.lower() for p in rel.parts]


def _is_presignoff_artifact(path: Path, project_dir: Path) -> bool:
    """True when the artefact's own in-project path DECLARES it a
    pre-sign-off intermediate (prelim / pre-layout / pre-PnR / draft)."""
    joined = "/".join(_rel_parts(path, project_dir))
    return any(marker in joined for marker in _PRESIGNOFF_MARKERS)


#: rank assigned to a self-declared pre-sign-off artefact — always last, and
#: the value the substance rule refuses to credit.
_PRESIGNOFF_RANK = 9


def _netlist_rank(path: Path, project_dir: Path) -> int:
    """Sign-off-first ordering for the tape-out netlist slot.

    0 — post-route / P&R netlist (the netlist that is actually taped out)
    1 — synthesis / gate-level mapped netlist
    2 — any other glob hit
    9 — self-declared pre-sign-off intermediate (never credited)
    """
    if _is_presignoff_artifact(path, project_dir):
        return _PRESIGNOFF_RANK
    parts = set(_rel_parts(path, project_dir)[:-1])
    name = path.name.lower()
    if "pnr" in parts or any(t in name for t in (
            "pnr", "post_route", "postroute", "routed", "place_route")):
        return 0
    if "synth" in parts or any(t in name for t in (
            "synth", "mapped", "gate")):
        return 1
    return 2


def _timing_rank(path: Path, project_dir: Path) -> int:
    """Sign-off-first ordering for the tape-out timing slot.

    0 — post-route / parasitic-annotated / multi-corner sign-off STA
    1 — any other glob hit
    9 — self-declared pre-sign-off (pre-layout / pre-PnR) STA (never credited)
    """
    if _is_presignoff_artifact(path, project_dir):
        return _PRESIGNOFF_RANK
    name = path.name.lower()
    if any(t in name for t in ("post_route", "postroute", "post_layout",
                               "postlayout", "signoff", "sign_off", "spef",
                               "ocv", "mcorner", "multi_corner")):
        return 0
    return 1


def _rank_signoff_first(paths: List[Path], project_dir: Path, ranker) -> List[Path]:
    """Order candidates sign-off-first. Never drops a candidate.

    The `steps/` tree mirrors phase2/phase3 artefacts through symlinks, so a
    real file and its mirror tie on rank; the real file wins the tie-break
    (so the evidence cites the canonical path, not a duplicate of it) and the
    remaining order is deterministic by path string.
    """
    return sorted(paths, key=lambda p: (ranker(p, project_dir),
                                        p.is_symlink(), str(p)))


def _has_dir(project_dir: Path, name: str) -> bool:
    """Check if a stage directory exists (case-insensitive search). Looks
    at the top level and inside the canonical phase2/<stage>/ and
    phase3/<stage>/ subtrees, but NOT inside `input/`, `inputs/`, `pdk/`,
    `vendor_ref/`, `references/` — those are design INPUTS, not output
    evidence (so `input/pdk/gds/` does NOT count as a `gds` stage)."""
    name_l = name.lower()
    skip = {"input", "inputs", "pdk", "vendor_ref", "references"}
    # Top level
    for child in project_dir.iterdir():
        if child.is_dir() and child.name.lower() == name_l:
            return True
    # Canonical phase2/<stage*>/<name>/ and phase3/<stage*>/<name>/
    for phase in ("phase2", "phase3"):
        phase_dir = project_dir / phase
        if not phase_dir.is_dir():
            continue
        for stage_dir in phase_dir.iterdir():
            if not stage_dir.is_dir() or stage_dir.name.lower() in skip:
                continue
            for child in stage_dir.iterdir():
                if child.is_dir() and child.name.lower() == name_l:
                    return True
    return False


# ---------------------------------------------------------------------------
# Tape-out LVS pillar
# ---------------------------------------------------------------------------
# `lvs_tapeout_signoff_check` — the tapeout-tier LVS gate that refuses to
# credit a netgen POWER_PIN_ONLY waiver as a genuine sign-off match — has been
# in programs/ since v1.3.94 and is invoked by NOTHING in the executed flow
# (grep: no flow/*.yaml step, no runner call — only signoff_ladder_run.py,
# which is itself never invoked). So Step 36 certified "tapeout checklist"
# with no LVS evidence of any kind. This pillar wires the existing checker in.
#
# We locate the report ourselves rather than calling `lvs_tapeout_signoff_check
# .check()`: that helper's last-resort glob is a bare `*.rpt`, which in a
# project with no LVS report at all would hand us the DRC report and label it
# LVS evidence. We reuse the part that carries the substance — the pure
# `evaluate()` verdict — and apply signoff_audit's own input-path exclusion.
_LVS_REPORT_CANDIDATES = (
    "reports/phase3/lvs.rpt",
    "reports/lvs.rpt",
    "phase3/reports/lvs.rpt",
)
_LVS_GLOBS = ["*lvs*.rpt", "*lvs*.out", "*netgen*.rpt", "*.lvs.report",
              "comp.out"]


def _find_lvs_report(project_dir: Path):
    """Locate the LVS sign-off report, canonical path first. None if absent."""
    for cand in _LVS_REPORT_CANDIDATES:
        p = project_dir / cand
        if p.is_file():
            return p
    hits = [p for p in _has_files(project_dir, _LVS_GLOBS) if p.is_file()]
    if not hits:
        return None
    # Deterministic, and prefer a real file over a `steps/` mirror symlink.
    return sorted(hits, key=lambda p: (p.is_symlink(), str(p)))[0]


def _evaluate_lvs(project_dir: Path):
    """Return (report_path, verdict_dict). Either element may be None.

    verdict_dict is `lvs_tapeout_signoff_check.evaluate()`'s output. A None
    verdict with a non-None path means the tapeout-tier LVS evaluator could
    not be imported or the report could not be read — an UNVERIFIABLE state
    that is treated as missing evidence, never as a pass.
    """
    rpt = _find_lvs_report(project_dir)
    if rpt is None:
        return None, None
    try:
        blob = rpt.read_text(errors="replace")
    except OSError:
        return rpt, None
    try:
        _here = str(Path(__file__).resolve().parent)
        if _here not in sys.path:
            sys.path.insert(0, _here)
        from lvs_tapeout_signoff_check import evaluate as _lvs_evaluate
    except Exception:
        return rpt, None
    try:
        return rpt, _lvs_evaluate(blob)
    except Exception:
        return rpt, None


# ---------------------------------------------------------------------------
# Mode: tapeout
# ---------------------------------------------------------------------------
def _check_tapeout(project_dir: Path) -> AuditResult:
    result = AuditResult(program="signoff_audit:tapeout", passed=False)
    evidence: dict = {}
    evidence_count = 0
    # #515 (continues #513): set when the DRC slot is credited because the
    # signoff DRC report is 100% stdcell-library-internal (design-level == 0)
    # — a routing-DRC-clean design whose only DRC items are foundry-cell
    # internal rules. Demotes the final verdict to PASS_WITH_WAIVERS.
    drc_library_internal_waived = False
    # 2026-07-27: set when the LVS slot is credited by a POWER_PIN_ONLY
    # netgen waiver rather than a genuine match — same demotion contract.
    lvs_power_pin_waived = False

    # (a) GDS file exists
    gds_files = _has_files(project_dir, ["*.gds", "*.gds2", "*.gdsii",
                                          "*.GDS", "*.GDSII"])
    if gds_files:
        evidence["gds"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_GDS_EXISTS", severity="INFO",
            message=f"GDS file found: {gds_files[0].name}",
            file=str(gds_files[0])))
    else:
        evidence["gds"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_GDS_EXISTS", severity="ERROR",
            message="No GDS file found (*.gds, *.gds2, *.gdsii)"))

    # (b) Tape-out netlist exists — RANKED, and never a pre-sign-off draft.
    # `*pnr*.v` / `*routed*.v` were added 2026-07-27: the canonical
    # post-route netlist the flow emits at phase3/stage3/pnr/<top>_pnr.v
    # matched none of the four original globs, so the slot could only ever be
    # credited by a synthesis-or-earlier netlist.
    netlist_files = _has_files(project_dir, ["*netlist*.v", "*synth*.v",
                                              "*gate*.v", "*mapped*.v",
                                              "*pnr*.v", "*routed*.v"])
    netlist_files = _rank_signoff_first(netlist_files, project_dir,
                                        _netlist_rank)
    netlist_signoff = [p for p in netlist_files
                       if _netlist_rank(p, project_dir) != _PRESIGNOFF_RANK]
    if netlist_signoff:
        chosen_netlist = netlist_signoff[0]
        evidence["netlist"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_NETLIST_EXISTS", severity="INFO",
            message=f"Tape-out netlist found: {chosen_netlist.name}",
            file=str(chosen_netlist)))
    elif netlist_files:
        # Candidates exist but every one of them DECLARES itself a
        # pre-sign-off intermediate. Naming the files is the disclosure; the
        # slot is still not credited (#437a: substance, not existence).
        evidence["netlist"] = False
        _names = ", ".join(sorted({p.name for p in netlist_files})[:5])
        result.findings.append(Finding(
            rule="TAPEOUT_NETLIST_PRESIGNOFF_ONLY", severity="ERROR",
            message=(f"Only pre-sign-off netlist(s) found ({_names}) — a "
                     f"preliminary/pre-P&R netlist is not the netlist a "
                     f"tape-out is signed off on. Produce the post-route "
                     f"netlist (phase3/stage3/pnr/<top>_pnr.v) before "
                     f"claiming Step 36."),
            file=str(netlist_files[0])))
    else:
        evidence["netlist"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_NETLIST_EXISTS", severity="ERROR",
            message=("No tape-out netlist found (*netlist*.v, *synth*.v, "
                     "*gate*.v, *mapped*.v, *pnr*.v, *routed*.v)")))

    # (c) Timing report exists — RANKED, and never a pre-layout STA.
    timing_files = _has_files(project_dir, ["*timing*.rpt", "*sta*.rpt",
                                             "*timing*.log", "*STA*.rpt"])
    timing_files = _rank_signoff_first(timing_files, project_dir,
                                       _timing_rank)
    timing_signoff = [p for p in timing_files
                      if _timing_rank(p, project_dir) != _PRESIGNOFF_RANK]
    if timing_signoff:
        chosen_timing = timing_signoff[0]
        evidence["timing"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_TIMING_EXISTS", severity="INFO",
            message=f"Timing report found: {chosen_timing.name}",
            file=str(chosen_timing)))
    elif timing_files:
        evidence["timing"] = False
        _names = ", ".join(sorted({p.name for p in timing_files})[:5])
        result.findings.append(Finding(
            rule="TAPEOUT_TIMING_PRESIGNOFF_ONLY", severity="ERROR",
            message=(f"Only pre-sign-off timing report(s) found ({_names}) "
                     f"— a pre-layout / pre-P&R STA is not tape-out timing "
                     f"sign-off. Produce the post-route (SPEF-annotated / "
                     f"multi-corner) STA before claiming Step 36."),
            file=str(timing_files[0])))
    else:
        evidence["timing"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_TIMING_EXISTS", severity="ERROR",
            message="No timing report found (*timing*.rpt, *sta*.rpt)"))

    # (d) DRC — SUBSTANCE, not existence.
    # ORGANIC-20260606-existence-only-signoff-gates (#437a): the pre-fix
    # gate PASSed on the FIRST `*drc*` glob hit — in one audited project
    # that was the clean detailed-router DRC (0 items) while the KLayout
    # SIGNOFF DRC in the same project carried 204,079 violations the
    # checklist never read. The signoff deck's report is the authority:
    # prefer it explicitly, parse its violation count, and FAIL on a
    # nonzero count (waivable only via the documented step-waiver path,
    # never by pointing at a different report).
    drc_files = _has_files(project_dir, ["*drc*.rpt", "*drc*.log",
                                          "*DRC*.rpt", "*DRC*.log"])
    # signoff-first ordering: a report whose NAME or CONTENT marks it as
    # the signoff deck outranks router/projection reports.
    def _drc_rank(p: Path) -> int:
        n = p.name.lower()
        if "signoff" in n:
            return 0
        try:
            head = p.read_text(errors="replace")[:2000]
        except OSError:
            return 3
        if "<report-database>" in head:   # KLayout signoff database
            return 1
        if "detailed_route" in head or "openroad" in head.lower():
            return 2                       # router projection — last
        return 2
    drc_files = sorted(drc_files, key=_drc_rank)

    def _drc_violation_count(p: Path):
        """Best-effort violation count; None when unparseable."""
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            return None
        if "<report-database>" in txt[:2000]:
            return txt.count("<item>")
        # SVRF-native sign-off DRC (the vibeic KLayout `svrfdrc` buddy running the
        # foundry's OWN Calibre `.rule` deck — the AUTHORITATIVE commercial-PDK
        # sign-off report). Its per-rule result lines are `FAIL|PASS|SKIP <rule>
        # <op> … -> <n>`; the design-level violation count is the number of FAIL
        # rules (NOT the generic "total violations:" text, which this report never
        # emits — so without this branch a genuinely 0-FAIL sign-off DRC would be
        # mis-read as UNPARSED and hard-FAIL the tapeout slot). Detected by the
        # svrfdrc header OR the presence of the deck's PASS/FAIL result grammar.
        # Chip-AGNOSTIC: keys off report FORMAT, never a design/PDK name.
        head = txt[:4000]
        _svrf_line = re.compile(r"(?m)^(FAIL|PASS|SKIP)\s+\S+\s+\S+.*->\s*\d+\s*$")
        if ("SVRF-native DRC" in head or "svrfdrc" in head.lower()
                or _svrf_line.search(txt)):
            fails = len(re.findall(r"(?m)^FAIL\s+\S+", txt))
            passes = len(re.findall(r"(?m)^PASS\s+\S+", txt))
            if fails or passes:            # a real per-rule tally was present
                return fails
        m = (re.search(r"(?i)\btotal\s+(?:errors|violations)\s*[:=]?\s*(\d+)", txt)
             or re.search(r"(?i)\bviolations?\s*[:=]\s*(\d+)", txt))
        return int(m.group(1)) if m else None

    def _drc_classify_summary(p):
        """Rule-layer classification (#513 `classify_xml`) of a KLayout
        report-database DRC report. Returns the classify summary dict, or
        None when the report is NOT a report-database XML (a plain-text DRC
        log can't be rule-layer classified, so library-internal can't be
        PROVEN → the caller keeps the strict raw-count FAIL)."""
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            return None
        if "<report-database>" not in txt[:2000]:
            return None
        try:
            from drc_rule_layer_classify import classify_xml
            _per, classify_summary = classify_xml(txt)
        except Exception:
            return None
        return classify_summary

    if drc_files:
        chosen = drc_files[0]
        vcount = _drc_violation_count(chosen)
        classify = (_drc_classify_summary(chosen)
                    if vcount is not None and vcount > 0 else None)
        # The classifier is only trustworthy here when it actually ACCOUNTED
        # for every violation the raw count saw: classified_total == vcount.
        # A report-database whose <item>s carry no <category> (malformed /
        # partial) yields classified_total 0 while vcount > 0 — that is NOT
        # a proven-library-internal design, so design_level must stay unknown
        # and the slot keeps the strict FAIL.
        classified_total = (classify.get("total_violations")
                            if classify else None)
        design_level = (classify.get("design_level_count")
                        if classify and classified_total == vcount
                        else None)
        if (vcount is not None and vcount > 0
                and classified_total == vcount and design_level == 0):
            # #515: nonzero raw count but design-level == 0 → 100%
            # stdcell-library-internal (foundry-cell li/ct/m1 internal
            # rules below the router metal stack, #513). The design is
            # routing-DRC-clean: consume the DESIGN-LEVEL count, not the
            # raw total, and credit the tapeout DRC slot AS A WAIVER so a
            # routing-DRC-clean design reaches 4/4 without a hand-written
            # cascaded tapeout waiver. Real design-level defects
            # (design_level > 0) still hard-FAIL below.
            evidence["drc"] = "library_internal_waived"
            evidence_count += 1
            drc_library_internal_waived = True
            result.findings.append(Finding(
                rule="TAPEOUT_DRC_LIBRARY_INTERNAL_WAIVED", severity="WARNING",
                message=(f"signoff DRC report '{chosen.name}' carries "
                         f"{vcount} violation(s) but design-level count is "
                         f"0 (100% stdcell-library-internal per rule-layer "
                         f"classify #513) — DRC slot credited as a "
                         f"library-internal waiver; tapeout verdict demoted "
                         f"to PASS_WITH_WAIVERS (no cascaded waiver needed)."),
                file=str(chosen)))
        elif vcount is not None and vcount > 0:
            evidence["drc"] = False
            _dl_note = ("" if design_level is None
                        else f" ({design_level} at design level — met2+/via+)")
            result.findings.append(Finding(
                rule="TAPEOUT_DRC_VIOLATIONS", severity="ERROR",
                message=(f"signoff DRC report '{chosen.name}' carries "
                         f"{vcount} violation(s){_dl_note} — the tapeout "
                         f"checklist gates on the design-level COUNT, not "
                         f"on file existence (#437a/#515). Waivable only "
                         f"via the documented step-waiver path."),
                file=str(chosen)))
        elif vcount is None:
            evidence["drc"] = False
            result.findings.append(Finding(
                rule="TAPEOUT_DRC_UNPARSED", severity="ERROR",
                message=(f"DRC report '{chosen.name}' found but its "
                         f"violation count could not be parsed — refusing "
                         f"an existence-only PASS (#437a); verify the "
                         f"signoff deck output manually."),
                file=str(chosen)))
        else:
            evidence["drc"] = True
            evidence_count += 1
            result.findings.append(Finding(
                rule="TAPEOUT_DRC_CLEAN", severity="INFO",
                message=(f"signoff DRC report '{chosen.name}': "
                         f"0 violations (count parsed, not just "
                         f"existence)"),
                file=str(chosen)))
    else:
        evidence["drc"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_DRC_EXISTS", severity="ERROR",
            message="No DRC report found (*drc*.rpt/log)"))

    # (e) LVS — SUBSTANCE, via the tapeout-tier gate that already exists.
    # A foundry tape-out is DEFINED by "Circuits match uniquely, zero
    # mismatch". A netgen POWER_PIN_ONLY mismatch is a reasoned TRIAGE
    # waiver, so it is credited ONLY through the PASS_WITH_WAIVERS demotion
    # path — never as a bare PASS. A signal-net mismatch, an incomplete
    # compare, an unreadable report and an absent report are all
    # missing evidence.
    lvs_report, lvs_result = _evaluate_lvs(project_dir)
    lvs_verdict = (lvs_result or {}).get("tapeout_verdict")
    if lvs_verdict == "GENUINE_MATCH":
        evidence["lvs"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_LVS_MATCH", severity="INFO",
            message=(f"LVS sign-off report '{lvs_report.name}': genuine "
                     f"netgen match (unique match + Final result line)"),
            file=str(lvs_report)))
    elif lvs_verdict == "WAIVED_PENDING_POWER_AWARE":
        evidence["lvs"] = "power_pin_only_waived"
        evidence_count += 1
        lvs_power_pin_waived = True
        result.findings.append(Finding(
            rule="TAPEOUT_LVS_POWER_PIN_WAIVED", severity="WARNING",
            message=(f"LVS report '{lvs_report.name}' is a POWER_PIN_ONLY "
                     f"mismatch — a reasoned triage waiver, NOT a genuine "
                     f"tape-out match. LVS slot credited as a waiver; "
                     f"tapeout verdict demoted to PASS_WITH_WAIVERS. Reach a "
                     f"genuine match with a power-aware gate netlist "
                     f"(VPWR/VGND top ports + PG connectivity) before mask "
                     f"order."),
            file=str(lvs_report)))
    elif lvs_verdict == "SIGNAL_NET_MISMATCH":
        evidence["lvs"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_LVS_MISMATCH", severity="ERROR",
            message=(f"LVS report '{lvs_report.name}' carries a real "
                     f"signal-net mismatch — an open connectivity defect. "
                     f"Never waved through."),
            file=str(lvs_report)))
    elif lvs_report is not None and lvs_result is None:
        evidence["lvs"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_LVS_UNVERIFIABLE", severity="ERROR",
            message=(f"LVS report '{lvs_report.name}' found but the "
                     f"tapeout-tier LVS evaluator could not read/classify "
                     f"it — refusing an existence-only PASS (#437a)."),
            file=str(lvs_report)))
    elif lvs_report is not None:
        evidence["lvs"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_LVS_INCOMPLETE", severity="ERROR",
            message=(f"LVS report '{lvs_report.name}' did not reach a "
                     f"top-level compare (verdict {lvs_verdict}) — missing "
                     f"evidence, never a tape-out pass."),
            file=str(lvs_report)))
    else:
        evidence["lvs"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_LVS_EXISTS", severity="ERROR",
            message=("No LVS sign-off report found (reports/phase3/lvs.rpt, "
                     "*lvs*.rpt, *netgen*.rpt) — a tape-out is DEFINED by a "
                     "genuine layout-vs-schematic match; the checklist "
                     "cannot certify Step 36 without one.")))

    threshold = _resolve_threshold(default_strict=5, total=5)
    result.passed = evidence_count >= threshold

    # v1.6.178 (#72 P2-7) — DRC/LVS ENV_UNAVAILABLE waiver.
    # When phase3 step records indicate DRC/LVS could not run for
    # environment reasons (no Calibre in container), demote a
    # passing tapeout-checklist to PASS_WITH_WAIVERS (still rc=0)
    # AND backfill evidence credit for any DRC slot still missing.
    # This makes the human-facing verdict honest — Step 33 cannot
    # be PASS in absolute terms when DRC didn't actually run.
    env_unavailable_steps = _read_phase3_env_unavailable_steps(project_dir)
    verdict_tier = "PASS" if result.passed else "FAIL"
    if env_unavailable_steps:
        # If DRC slot is missing but DRC step was ENV_UNAVAILABLE,
        # backfill credit so threshold can be reached.
        if not evidence.get("drc") and "drc" in env_unavailable_steps:
            evidence["drc"] = "env_unavailable"
            evidence_count += 1
            for f in result.findings:
                if (f.rule == "TAPEOUT_DRC_EXISTS"
                        and f.severity == "ERROR"):
                    f.severity = "WARNING"
                    f.message = (
                        f"DRC report missing AND phase3 step "
                        f"reports ENV_UNAVAILABLE — waived. "
                        f"Step 33 demoted to PASS_WITH_WAIVERS; "
                        f"explicit human signoff required before "
                        f"mask order.")
                    break
            else:
                result.findings.append(Finding(
                    rule="TAPEOUT_DRC_WAIVED_ENV_UNAVAILABLE",
                    severity="WARNING",
                    message=(
                        f"DRC step reported ENV_UNAVAILABLE in "
                        f"phase3_one_shot.json; tapeout checklist "
                        f"demoted to PASS_WITH_WAIVERS.")))
            result.passed = evidence_count >= threshold
        # Same backfill for the LVS slot: `_read_phase3_env_unavailable_steps`
        # has always returned 'lvs', but before the LVS pillar existed there
        # was no slot for it to credit.
        if not evidence.get("lvs") and "lvs" in env_unavailable_steps:
            evidence["lvs"] = "env_unavailable"
            evidence_count += 1
            for f in result.findings:
                if (f.rule.startswith("TAPEOUT_LVS_")
                        and f.severity == "ERROR"):
                    f.severity = "WARNING"
                    f.message = (
                        f"LVS evidence missing AND phase3 step reports "
                        f"ENV_UNAVAILABLE — waived. Step 36 demoted to "
                        f"PASS_WITH_WAIVERS; explicit human signoff "
                        f"required before mask order.")
                    break
            else:
                result.findings.append(Finding(
                    rule="TAPEOUT_LVS_WAIVED_ENV_UNAVAILABLE",
                    severity="WARNING",
                    message=(
                        f"LVS step reported ENV_UNAVAILABLE in "
                        f"phase3_one_shot.json; tapeout checklist "
                        f"demoted to PASS_WITH_WAIVERS.")))
            result.passed = evidence_count >= threshold
        if result.passed:
            verdict_tier = "PASS_WITH_WAIVERS"
            result.findings.append(Finding(
                rule="TAPEOUT_ENV_UNAVAILABLE_DEMOTION",
                severity="WARNING",
                message=(
                    f"Phase 3 step(s) {env_unavailable_steps} reported "
                    f"ENV_UNAVAILABLE; tapeout checklist verdict is "
                    f"PASS_WITH_WAIVERS — explicit human waiver entry "
                    f"required before mask order.")))

    # #515: a library-internal DRC waiver (design-level == 0) also demotes a
    # passing tapeout checklist to PASS_WITH_WAIVERS — the raw count is
    # nonzero (open-deck-vs-foundry-cell divergence), so it is not an
    # absolute PASS, but it auto-cascades the #513 waiver into Step-36 so no
    # hand-written cascaded tapeout waiver is required.
    if result.passed and drc_library_internal_waived and verdict_tier == "PASS":
        verdict_tier = "PASS_WITH_WAIVERS"

    # Same contract for the LVS pillar: a POWER_PIN_ONLY netgen waiver is not
    # a genuine tape-out match, so it may reach the threshold but it may
    # NEVER read as a bare PASS (CLAUDE.md rule 11 / #651).
    if result.passed and lvs_power_pin_waived and verdict_tier == "PASS":
        verdict_tier = "PASS_WITH_WAIVERS"

    result.summary = {
        "evidence": evidence,
        "evidence_count": evidence_count,
        "threshold": threshold,
        "env_unavailable_steps": env_unavailable_steps,
        "drc_library_internal_waived": drc_library_internal_waived,
        "lvs_power_pin_only_waived": lvs_power_pin_waived,
        "lvs_report": str(lvs_report) if lvs_report else "",
        "lvs_verdict": lvs_verdict or "",
        "verdict_tier": verdict_tier,
    }
    return result


# ---------------------------------------------------------------------------
# Mode: flow
# ---------------------------------------------------------------------------
def _check_flow(project_dir: Path) -> AuditResult:
    result = AuditResult(program="signoff_audit:flow", passed=False)
    stages: dict = {}
    stage_count = 0

    # synth stage
    synth_dir = _has_dir(project_dir, "synth")
    synth_logs = _has_files(project_dir, ["*synth*.log", "*synthesis*.log",
                                           "*synth*.rpt"])
    if synth_dir or synth_logs:
        stages["synth"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_SYNTH_EVIDENCE", severity="INFO",
            message="Synthesis stage evidence found"))
    else:
        stages["synth"] = False
        result.findings.append(Finding(
            rule="FLOW_SYNTH_EVIDENCE", severity="ERROR",
            message="No synthesis evidence (synth/ dir or synth log)"))

    # pnr stage
    pnr_dir = _has_dir(project_dir, "pnr")
    pnr_logs = _has_files(project_dir, ["*pnr*.log", "*place*.log",
                                          "*route*.log", "*floorplan*.log"])
    if pnr_dir or pnr_logs:
        stages["pnr"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_PNR_EVIDENCE", severity="INFO",
            message="Place-and-route stage evidence found"))
    else:
        stages["pnr"] = False
        result.findings.append(Finding(
            rule="FLOW_PNR_EVIDENCE", severity="ERROR",
            message="No P&R evidence (pnr/ dir or pnr log)"))

    # gds stage
    gds_dir = _has_dir(project_dir, "gds")
    gds_files = _has_files(project_dir, ["*.gds", "*.gds2", "*.gdsii"])
    if gds_dir or gds_files:
        stages["gds"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_GDS_EVIDENCE", severity="INFO",
            message="GDS stage evidence found"))
    else:
        stages["gds"] = False
        result.findings.append(Finding(
            rule="FLOW_GDS_EVIDENCE", severity="ERROR",
            message="No GDS evidence (gds/ dir or *.gds file)"))

    # sta stage
    sta_files = _has_files(project_dir, ["*sta*.rpt", "*timing*.rpt",
                                          "*STA*.rpt", "*timing*.log"])
    if sta_files:
        stages["sta"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_STA_EVIDENCE", severity="INFO",
            message="STA stage evidence found"))
    else:
        stages["sta"] = False
        result.findings.append(Finding(
            rule="FLOW_STA_EVIDENCE", severity="ERROR",
            message="No STA evidence (*sta*.rpt, *timing*.rpt)"))

    threshold = _resolve_threshold(default_strict=4, total=4)
    result.passed = stage_count >= threshold
    result.summary = {
        "stages": stages,
        "stage_count": stage_count,
        "threshold": threshold,
    }
    return result


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------
MODE_MAP = {
    "tapeout": _check_tapeout,
    "flow": _check_flow,
}


# ---------------------------------------------------------------------------
# #651 — waivers.json waiver-entry emitter
# ---------------------------------------------------------------------------
# Canonical Step-36 (tapeout checklist) id in the phase1_phase2_phase3 flow.
_TAPEOUT_STEP_ID = 36
_TAPEOUT_WAIVER_TICKET = "ORGANIC-20260613-tapeout-drc-waiver"


def _emit_tapeout_waiver_entry(project_dir: Path, result: "AuditResult") -> None:
    """Record the tapeout DRC/LVS waiver in <project>/waivers.json so
    flow_compliance_check counts the tapeout step as DEFERRED-via-waiver
    (NOT executed-PASS). chip-AGNOSTIC: the entry is keyed on the structural
    Step-36 id + the waiver evidence the auditor already gathered (which
    DRC slot was waived and why), never on a chip/vendor literal.

    The entry shape matches the `waived_steps[*]` schema flow_compliance_check
    consumes: `id` + `reason`/`rationale` + `ticket` + `review_required:true`
    + `evidence[]`. Idempotent: re-running signoff_audit will not duplicate
    the entry, and an existing hand-authored waiver for the same step is left
    untouched (it takes precedence).
    """
    summary = result.summary or {}
    evidence_files = [f.file for f in result.findings
                      if f.file and "WAIVED" in f.rule]
    waiver_entry = {
        "id": _TAPEOUT_STEP_ID,
        "reason": ("tapeout sign-off reached the evidence threshold but a "
                   "DRC/LVS slot was credited via a waiver "
                   "(verdict_tier=PASS_WITH_WAIVERS) — NOT a bare/absolute "
                   "PASS. Production tapeout review must close the waived "
                   "slot before mask order (CLAUDE.md rule 11)."),
        "ticket": _TAPEOUT_WAIVER_TICKET,
        "review_required": True,
        "approver": "tapeout-review-pending",
        "evidence": evidence_files or ["reports/audit/tapeout_checklist.json"],
        "verdict_tier": "PASS_WITH_WAIVERS",
        "drc_library_internal_waived": bool(
            summary.get("drc_library_internal_waived")),
        "env_unavailable_steps": list(summary.get("env_unavailable_steps", [])),
    }
    wpath = project_dir / "waivers.json"
    try:
        if wpath.exists():
            data = json.loads(wpath.read_text(errors="replace"))
            if not isinstance(data, dict):
                data = {}
        else:
            data = {}
    except (json.JSONDecodeError, OSError):
        # Do NOT clobber an existing-but-unreadable waivers.json; leave it
        # for the human/flow-gate to surface as a schema error.
        return
    waived = data.get("waived_steps")
    if not isinstance(waived, list):
        waived = []
    # Idempotent + precedence-preserving: if any entry already targets this
    # step, leave it (a hand-authored waiver outranks this auto-entry).
    for w in waived:
        if isinstance(w, dict) and str(w.get("id")) == str(_TAPEOUT_STEP_ID):
            return
    waived.append(waiver_entry)
    data["waived_steps"] = waived
    try:
        wpath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError:
        return


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-mode signoff evidence checker")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--mode", required=True, choices=list(MODE_MAP.keys()),
                        help="Signoff check mode")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        result = AuditResult(program=f"signoff_audit:{args.mode}", passed=False)
        result.findings.append(Finding(
            rule="PROJECT_DIR_EXISTS", severity="ERROR",
            message=f"Project directory does not exist: {project_dir}"))
        result.summary = {"evidence_count": 0,
                          "threshold": _resolve_threshold(5, 5)}
    else:
        checker = MODE_MAP[args.mode]
        result = checker(project_dir)

    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    # #651 — verdict_tier is the authority for the exit code, not just
    # `result.passed`. A PASS_WITH_WAIVERS run is STILL passing (it cleared
    # the threshold) but at least one slot was credited via a waiver, so it
    # must NOT collapse onto the same rc as a clean/absolute PASS — otherwise
    # the rc-only flow gate (`tapeout_signoff_check`) reports a bare PASS and
    # the WITH_WAIVERS distinction is lost (CLAUDE.md rule 11). The DRC slot
    # being waived was already recorded in the verdict_tier; here we (a) print
    # a line-start sentinel and (b) emit a waivers.json step entry so the
    # waiver is also visible to flow_compliance_check's waiver accounting
    # (counted DEFERRED, never as an executed-PASS).
    verdict_tier = (result.summary or {}).get("verdict_tier", "")
    if result.passed and verdict_tier == "PASS_WITH_WAIVERS":
        _emit_tapeout_waiver_entry(project_dir, result)
        print(f"{WAIVER_STDOUT_SENTINEL} tapeout sign-off passed WITH WAIVERS "
              f"(verdict_tier=PASS_WITH_WAIVERS) — production tapeout review "
              f"must close the waived slot(s) before mask order.")
        print(report_json)
        return WAIVER_EXIT_CODE

    print(report_json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
