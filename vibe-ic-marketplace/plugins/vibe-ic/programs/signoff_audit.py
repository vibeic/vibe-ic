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

2026-07-28 -- tapeout mode gained an SI (crosstalk-delay) BLOCKING
CONDITION, separate from the evidence pillars. `si_mcf_sta_check` can
return a VACUOUS_PASS whose own written reason ends "Read this as NOT
CHECKED"; the flow's step-27 gate credits that as a pass, which is right
during development and wrong at a mask order. Tapeout mode now refuses to
certify unless the SI verdict PROVED something, or the specific vacuity is
accepted through the governed waiver channel (`waivers.json`
`waived_steps[*].si_vacuity_accepted`, naming this step, with a human
approver and a reason). A waiver can never launder a genuine SI FAIL, an
absent/unparseable report, or a PASS with no denominator. See the
"Tape-out SI" section below.

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

_PROGRAMS_DIR = str(Path(__file__).resolve().parent)
if _PROGRAMS_DIR not in sys.path:
    sys.path.insert(0, _PROGRAMS_DIR)

import _signoff_drc_format as _sdf  # noqa: E402  (path bootstrap above)

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
# Sign-off-first ranking for the GDS / netlist / timing evidence slots
# ---------------------------------------------------------------------------
# ORGANIC-20260606-existence-only-signoff-gates (#437a) was fixed for the DRC
# slot only. The GDS, netlist and timing slots kept crediting `rglob()[0]` —
# an arbitrary, filesystem-order pick with no ranking and no content check.
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
#   TAPEOUT_GDS_EXISTS (the deferred tail, fixed 2026-07-27 in the same shape)
#     credited steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds —
#     a symlink MIRROR — while the flow's declared stream-out artefact
#     phase3/stage4/gds/spm.gds (881530 B), the exact file step 37's
#     gds_size_check / gds_substance_check / provenance_check verify, and a
#     STALE 1014178 B copy under phase3/stage4/foundry_handoff/ both sat in
#     the same project. The checklist therefore named a path whose substance
#     nothing had checked, and could equally have named the stale copy.
#
# Two changes, mirroring the DRC slot 40 lines below which already does this:
#   (1) rank candidates sign-off-first and cite the best one;
#   (2) REFUSE to credit the slot when EVERY candidate is a self-declared
#       pre-sign-off intermediate. A preliminary netlist, a pre-layout STA or
#       a draft layout is not a thing a tape-out is signed off on, and a gate
#       may explain an absent artefact but may not certify the step without
#       one.
# Ranking only ever REORDERS; the pre-sign-off refusal is a separate,
# separately-named substance rule so the two cannot be confused.
#
# 2026-07-27 REVIEW FOLLOW-UP — (1)+(2) narrowed only the ENTRANCE. Because
# `_gds_rank` returns 0/1/2/3 for every non-draft candidate and the credit
# condition was `rank != _PRESIGNOFF_RANK`, the GDS slot's EXIT stayed at
# CREDITED for ANY `.gds` ANYWHERE: a lone `steps/` mirror, a lone stale
# `foundry_handoff` copy, a stray root-level copy, a 0-byte file at the
# declared path, and the FOUNDRY-SUPPLIED `scribe_line_layout.gds` frame all
# still certified Step 36 — identically to the unfixed tree. So a third change
# applies to the GDS slot only (the netlist/timing slots have no equivalent
# single declared path):
#   (3) only `_CREDITABLE_GDS_RANK` (the declared stream-out) may credit, and
#       only when the file carries GDSII substance (`_gds_stream_substance`).
#       Every other outcome gets its OWN non-crediting rule name.
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


#: the flow's DECLARED stream-out artefact for Step 37 ("GDSII output"):
#: `phase3/stage4/gds/*.gds`. It is also the exact path `gds_size_check`,
#: `gds_substance_check` and `provenance_check` are pointed at by that step's
#: gate, so citing anything else makes the tape-out checklist describe a
#: different file from the one the substance gates verified.
_DECLARED_GDS_DIR_PARTS = ("phase3", "stage4", "gds")
#: Step 38's scribe-line PCM / alignment frame is FOUNDRY-SUPPLIED — the flow
#: yaml says so explicitly and `foundry_handoff_package_check` keeps it out of
#: its required files. It is an INPUT in the same sense as `input/pdk/gds/`,
#: so it must never outrank a design GDS in the tape-out slot.
_FOUNDRY_SUPPLIED_GDS_STEMS = ("scribe_line_layout",)


def _gds_rank(path: Path, project_dir: Path) -> int:
    """Sign-off-first ordering for the tape-out GDS slot.

    0 — the flow's declared stream-out artefact, `phase3/stage4/gds/*.gds`
    1 — any other in-`phase3/` GDS (the P&R hand-off copy, an analog or
        mixed-signal merge, the foundry-handoff copy of the design)
    2 — any other glob hit (a `steps/` mirror, an ad-hoc copy at the root)
    3 — a FOUNDRY-SUPPLIED frame (scribe line / PCM), which is not the
        design and may only ever be a last resort
    9 — self-declared pre-sign-off intermediate (never credited)

    Measured on a completed spm x ihp-sg13g2 run (2026-07-27): four GDS files
    exist and the unranked `rglob()[0]` cited
    `steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds` — a symlink
    mirror — while `phase3/stage4/gds/spm.gds` (the declared artefact, and a
    DIFFERENT 881530 B file from the stale 1014178 B foundry-handoff copy) sat
    in the same project.
    """
    if _is_presignoff_artifact(path, project_dir):
        return _PRESIGNOFF_RANK
    parts = _rel_parts(path, project_dir)
    if any(path.name.lower().startswith(s)
           for s in _FOUNDRY_SUPPLIED_GDS_STEMS):
        return 3
    dirs = parts[:-1]
    for i in range(len(dirs) - len(_DECLARED_GDS_DIR_PARTS) + 1):
        if tuple(dirs[i:i + len(_DECLARED_GDS_DIR_PARTS)]) == \
                _DECLARED_GDS_DIR_PARTS:
            return 0
    if "phase3" in dirs:
        return 1
    return 2


#: The ONLY rank the tape-out GDS slot may be CREDITED by: the flow's own
#: declared stream-out artefact, `phase3/stage4/gds/*.gds`.
#:
#: 2026-07-27 review of the ranking change above: ranking alone only decided
#: WHICH file the checklist cites, never WHETHER the slot is credited. The
#: credit condition was `rank != _PRESIGNOFF_RANK`, so ranks 0/1/2/3 all
#: credited and ANY `.gds` ANYWHERE certified Step 36. Measured: a lone
#: `steps/` mirror (rank 2), a lone stale `foundry_handoff` copy (rank 1), a
#: stray `.gds` at the project root (rank 2) and — worst — the FOUNDRY-SUPPLIED
#: `scribe_line_layout.gds` (rank 3, an INPUT this file's own comment says
#: "must never outrank a design GDS") each credited the slot on their own.
#:
#: A tape-out GDS slot certifies "the layout that is being taped out exists".
#: Only the artefact the flow DECLARES as the stream-out — the exact path
#: step 37's `gds_size_check` / `gds_substance_check` / `provenance_check` are
#: pointed at — is that layout. Every other candidate is a copy, a mirror, a
#: work-in-progress hand-off or somebody else's file, so each of them now
#: produces a NAMED, NON-crediting finding instead of a certificate.
_CREDITABLE_GDS_RANK = 0

#: A GDSII stream's FIRST record is HEADER: a 4-byte record prologue whose
#: length is 0x0006 and whose record type is 0x0002 (2-byte-integer data).
#: Every GDSII writer emits it and nothing else does, so it is the cheapest
#: fact that separates "a stream-out" from "a file at the stream-out path".
#: This is the same record `gds_size_check` inspects (it warns; the tape-out
#: checklist, being the last gate before mask order, refuses to CERTIFY).
#: chip-AGNOSTIC: a stream-FORMAT fact, never a vendor / PDK / design fact.
_GDSII_HEADER_RECORD_TYPE = 0x0002


def _gds_stream_substance(path: Path) -> str:
    """Classify a GDS candidate BY ITS OWN BYTES. Pure; stats the file and
    reads at most 4 bytes.

    Returns:
      "ok"        — non-empty AND its first record is a GDSII HEADER
      "empty"     — zero bytes, or unreadable / a dangling symlink
      "not_gdsii" — carries bytes but does not begin with a GDSII HEADER

    Why the slot needs this at all: `phase3/stage4/gds/<top>.gds` existing is
    a statement about the FILESYSTEM. Measured, a 0-byte file at exactly that
    path credited the tape-out GDS slot — the checklist certified a layout
    that contains nothing. "Non-empty" is the floor; "is actually a GDSII
    stream" is the same question asked one byte further in, and a 4-byte
    placeholder is the same defect as a 0-byte one.
    """
    try:
        size = path.stat().st_size          # follows symlinks by design
    except OSError:
        return "empty"                      # dangling mirror → no substance
    if size == 0:
        return "empty"
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return "empty"
    if len(head) < 4:
        return "not_gdsii"
    if ((head[2] << 8) | head[3]) != _GDSII_HEADER_RECORD_TYPE:
        return "not_gdsii"
    return "ok"


def _gds_rank_note(path: Path, project_dir: Path) -> str:
    """Plain-language name for WHY a candidate is not the declared stream-out.
    Used only to make the non-crediting findings self-explanatory."""
    rank = _gds_rank(path, project_dir)
    if rank == 3:
        return ("a FOUNDRY-SUPPLIED frame (scribe line / PCM), which is an "
                "input, not the design")
    if rank == 1:
        return ("an in-phase3 copy / hand-off duplicate, not the declared "
                "stream-out")
    if rank == 2:
        return "a steps/ mirror or an ad-hoc copy"
    return "not the declared stream-out"


def _rank_signoff_first(paths: List[Path], project_dir: Path, ranker) -> List[Path]:
    """Order candidates sign-off-first. Never drops a candidate.

    The `steps/` tree mirrors phase2/phase3 artefacts through symlinks, so a
    real file and its mirror tie on rank; the real file wins the tie-break
    (so the evidence cites the canonical path, not a duplicate of it) and the
    remaining order is deterministic by path string.
    """
    return sorted(paths, key=lambda p: (ranker(p, project_dir),
                                        p.is_symlink(), str(p)))


#: How much of a report's head decides which deck produced it. The markers
#: below are header lines; nothing past this bound has ever been consulted.
_DRC_RANK_HEAD_CHARS = 2000


def _drc_rank(p: Path) -> int:
    """Sign-off-first rank for a DRC report: 0 named sign-off, 1 KLayout
    sign-off database, 2 router projection / unknown, 3 unreadable.

    READS AT MOST ``_DRC_RANK_HEAD_CHARS`` (#797). This was
    ``p.read_text(errors="replace")[:2000]`` — decode the WHOLE file, then
    discard all but the first 2000 characters — and it is the `key=` of a
    `sorted()` over every `*drc*.rpt|log` an rglob of the project finds. A
    router report is the largest artefact a run produces: measured 2026-08-04
    at 2.48 GB / 94.9M lines on one cell, against 11.7 MB for the largest
    report tracked in this repo. So the cost was unbounded in the one input
    that is unbounded, to inspect a header.

    The failure mode is the reason this is a correctness bug and not a
    performance note: a checker that cannot finish is killed, and downstream a
    killed checker is indistinguishable from a checker that ran and found
    nothing. The step's timeout arrives as the step's verdict.
    """
    n = p.name.lower()
    if "signoff" in n:
        return 0
    try:
        # `open(...).read(N)` and not `read_text()[:N]`: the bound has to be
        # applied by the READ, not after it. Same decoding and same
        # `errors="replace"`, so the head compared is byte-identical.
        with p.open("r", errors="replace") as fh:
            head = fh.read(_DRC_RANK_HEAD_CHARS)
    except OSError:
        return 3
    if "<report-database>" in head:   # KLayout signoff database
        return 1
    if "detailed_route" in head or "openroad" in head.lower():
        return 2                       # router projection — last
    return 2


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


# Canonical tapeout-checklist step id in the phase1_phase2_phase3 flow. Used by
# the SI blocking condition below (which waiver entries target this step) and by
# the #651 waiver-entry emitter further down.
_TAPEOUT_STEP_ID = 36


# ---------------------------------------------------------------------------
# Tape-out SI (crosstalk-delay) blocking condition
# ---------------------------------------------------------------------------
# Crosstalk is a mechanism that kills silicon. `si_mcf_sta_check` carries three
# verdict tiers: PASS (the MCF fold was re-derived and proved), VACUOUS_PASS
# (rc 2 — it re-derived NOTHING, and its own written reason ends "Read this as
# NOT CHECKED"), and FAIL. The flow's step-27 gate credits rc 2 as a pass, which
# is the right call DURING DEVELOPMENT: a design that has not been extracted yet
# should not be blocked on an SI proof it cannot have.
#
# It is the wrong call at the moment a mask set is committed. "SI was checked
# and is clean" and "SI was never checked" then become the same green light, and
# the second one is the state that ships a chip whose aggressors were never
# looked at. So the tapeout sign-off is where the two must separate.
#
# WHAT THIS BLOCK DOES. Tapeout mode refuses to certify on a VACUOUS SI verdict
# unless the vacuity is ACCEPTED through the repo's ONE governed waiver channel,
# `<project>/waivers.json`, as a normal `waived_steps` entry naming this step and
# carrying `si_vacuity_accepted`::
#
#     {"growth_rationale": "<why this release carries one more waiver>",
#      "growth_rationale_covers": <the root-waiver population that rationale was
#                                  written against; vibe-ic#922 — a rationale
#                                  with no recorded population authorises
#                                  unlimited growth forever, so
#                                  `waiver_growth_check` requires either the
#                                  COUNT (an integer equal to the current root
#                                  count) or the POPULATION (a list naming each
#                                  root waiver by a value it publishes under
#                                  ticket/id/step). The list is the stronger
#                                  spelling: a count says how many the reason
#                                  was written about, never which, so a count
#                                  survives a swap that the reason does not>,
#      "waived_steps": [
#       {"id": 36,
#        "reason": "<>=20 chars saying why this vacuity is acceptable>",
#        "approver": "<a human; self-approval is refused>",
#        "approved_at": "<ISO-8601 timestamp>",
#        "review_required": true,
#        "ticket": "<tracker id for closing this waiver>",
#        "si_vacuity_accepted": ["SPEF_NO_COUPLING_PAIRS"]}
#     ]}
#
# Only `id`, `reason`, `approver` and `si_vacuity_accepted` are read by THIS
# condition. The other four are what the SIBLING waiver gates need, and they
# are written here because an example that this gate accepts and its siblings
# reject is a trap: measured on the four-field entry, `waiver_growth_check`
# returns rc 1 (`UNJUSTIFIED_WAIVER_GROWTH` — net count grew with no
# `growth_rationale`), `waiver_staleness_check` rc 2 (no parseable
# `approved_at`, so the entry can never AGE), and `waivers_schema_check` warns
# `review-required-missing` / `ticket-missing`. A waiver that no gate can age
# or close is a permanent one, which is the opposite of what a disclosure is
# for.
#
# The code in `si_vacuity_accepted` is the one THIS RUN's SI report published in
# `summary.denominator.details.vacuity_code`. Naming it is what makes the entry
# a disclosure rather than a blanket: an acceptance of "the extraction produced
# no inter-net coupling" does not also accept "the SPEF could not be read", and
# when the underlying state changes the code changes and the old entry stops
# matching. A wildcard (`*`, `ALL`, `ANY`, ...) is refused for the same reason.
#
# Placement in `waivers.json` is deliberate and follows `pg_rail_geometry_check`:
# the four waiver-legitimacy gates (`waivers_schema_check`,
# `waiver_legitimacy_check`, `waiver_growth_check`, `waiver_staleness_check`) all
# read `waived_steps`, so an entry written here is subject to every one of them,
# and the reason/approver predicates are IMPORTED from `waivers_schema_check`
# rather than restated. A marker file of this gate's own would be a parallel,
# ungoverned channel; a code comment discloses nothing to a machine at all.
#
# WHAT A WAIVER MAY NEVER DO.
#   * It may never launder a genuine SI violation. `verdict: FAIL` is refused
#     with the waiver present and named in the report (`si_waiver_refused`).
#   * It may never cover an ABSENT or unparseable report. That is not vacuity —
#     vacuity is a gate that ran and disclosed that it proved nothing. A missing
#     report is a gate that did not run, and there is no disclosure to accept.
#   * It may never cover a PASS that does not carry a denominator proving it
#     examined something. A bare `verdict: PASS` with no `denominator` block is
#     the exact false-clean shape the SI gate was fixed for, and this consumer
#     cannot tell such a report apart from one produced before the fix.
#   * It may never cover a report that CONTRADICTS ITSELF, on either branch.
#     `verdict: PASS` with `denominator.examined == 0`, and `verdict:
#     VACUOUS_PASS` with `examined != 0`, with ERROR findings in its body, or
#     with `summary.pass`/`summary.vacuous` disagreeing with the verdict, are
#     all refused. Those two refusals are MIRRORS and must stay so: the report
#     body is the evidence the emitter derives its verdict from, so relabelling
#     the verdict field does not relabel the report. Defending only the PASS
#     side would leave the waivable state — the one this whole condition exists
#     to govern — as the undefended one.
#
# WHAT THIS BLOCK CANNOT DO, stated so nobody reads more into it. Every check
# here reads ONE file, so it can only catch a report that indicts ITSELF. A
# report whose body has been rewritten end to end — the ERROR findings deleted,
# `errors_count` zeroed, the flags and the denominator all made to agree with a
# forged verdict — is indistinguishable from a genuine vacuity to any consumer
# of that file alone, and it is waivable. What the mirror buys is the COST: the
# laundering that worked before was editing one word, and now it is fabricating
# the whole body. Closing the remainder needs evidence this consumer does not
# have (re-running the gate, or an artefact signature), not a stricter read of
# the same bytes.
#
# The waiver does NOT make the tapeout a bare PASS. It demotes the verdict to
# PASS_WITH_WAIVERS (rc 3 + the stdout sentinel), so the accepted vacuity is
# carried in the exit code and in the flow's step listing, never absorbed
# (CLAUDE.md rule 11 / #651).
#
# chip-AGNOSTIC: nothing here names a design, a PDK, a rail or a cell.

#: `si_mcf_sta_check`'s report, at the path the step-27 flow gate writes it to.
_SI_REPORT_REL = "reports/phase3/si_mcf_sta_check.json"

#: The `waivers.json` field that accepts a named SI vacuity at the tapeout step.
SI_DISCLOSURE_FIELD = "si_vacuity_accepted"

#: Classification of the SI verdict this project carries into tapeout.
SI_PROVED = "PROVED"            # a fold was re-derived and proved: clean
SI_VACUOUS = "VACUOUS"          # disclosed skip — the ONLY waivable state
SI_VIOLATION = "VIOLATION"      # the gate found a defect — never waivable
SI_UNDISCLOSED = "UNDISCLOSED"  # a report that does not say what it examined
SI_ABSENT = "ABSENT"            # no report, or bytes that are not a report

#: Only one state may be accepted through the waiver channel. Named as a set so
#: a future tier cannot become waivable by accident.
_SI_WAIVABLE_STATES = frozenset({SI_VACUOUS})

#: Tokens that would turn a named acceptance back into a blanket one.
_SI_BLANKET_CODES = frozenset({
    "*", "ALL", "ANY", "SI", "EVERYTHING", "VACUOUS", "VACUOUS_PASS", "-", "_",
})


def _si_defect_evidence(doc: dict, summary: dict) -> str:
    """Prose naming the defect evidence in the report BODY, or ``""``.

    Read BEFORE the verdict string, deliberately. `si_mcf_sta_check` derives
    its verdict FROM this body, and the defect branch outranks every other
    tier::

        no_errors = all(f.severity != "ERROR" for f in findings)
        if not no_errors:      verdict = "FAIL"
        elif denom.is_vacuous: verdict = "VACUOUS_PASS"
        else:                  verdict = "PASS"

    So a report whose body carries an ERROR is a FAIL whatever its ``verdict``
    field has been edited to say. Re-deriving that here instead of trusting the
    label is what keeps the separation between "waivable" and "never waivable"
    off the ORDER the verdict strings happen to be tested in: relabelling a
    genuine FAIL as VACUOUS_PASS does not move it into the waivable branch,
    because its body follows it there.

    Only POSITIVE evidence counts. An absent ``findings`` list or an absent
    ``errors_count`` is not read as a defect — this must not turn a legitimate
    report into an alarm, only refuse one that indicts itself.
    """
    findings = doc.get("findings")
    if isinstance(findings, list):
        errs = [f for f in findings
                if isinstance(f, dict)
                and str(f.get("severity", "")).strip().upper() == "ERROR"]
        if errs:
            first = errs[0]
            # `category` is the field si_mcf_sta_check's `Finding` dataclass
            # actually carries (severity / category / message). Citing only
            # `rule`/`code` degraded the prose to a literal `?` on every report
            # the real gate produces, while the name was sitting in the file.
            named = (first.get("category") or first.get("rule")
                     or first.get("code") or "?")
            return (f"the report body carries {len(errs)} ERROR finding(s) "
                    f"(first: {named} "
                    f"— {str(first.get('message', ''))[:160]})")
    count = summary.get("errors_count")
    if isinstance(count, int) and not isinstance(count, bool) and count > 0:
        return f"the report's own `summary.errors_count` is {count}"
    return ""


def _si_body_malformed(doc: dict, summary: dict) -> str:
    """Prose naming a report body that cannot be AUDITED, or ``""``.

    `_si_defect_evidence` reads only POSITIVE evidence, so a body that has been
    reshaped until that evidence is unreadable — ``findings`` turned into an
    object or a list of strings, ``errors_count`` turned into ``"1"`` — would
    otherwise read as "no defect found" when what actually happened is "the
    defect channel was disabled". Absence is tolerated everywhere; only a field
    that is PRESENT in a shape the emitter never writes refuses.

    Applied to every verdict alike, before the verdict is dispatched on, so the
    two branches cannot drift apart on it.
    """
    findings = doc.get("findings")
    if findings is not None and not isinstance(findings, list):
        return (f"`findings` is {type(findings).__name__}, not a list — the "
                f"gate always writes a list, so the severity channel this "
                f"consumer reads has been reshaped out of view")
    if isinstance(findings, list):
        bad = [f for f in findings if not isinstance(f, dict)]
        if bad:
            return (f"{len(bad)} of {len(findings)} `findings` entries are "
                    f"not objects, so their severity cannot be read")
    count = summary.get("errors_count")
    if count is not None and (isinstance(count, bool)
                              or not isinstance(count, int)):
        return (f"`summary.errors_count` is {count!r}, not an integer — the "
                f"gate writes a count, so this report did not come from it")
    return ""


def _si_defect_channel_unauditable(doc: dict, summary: dict) -> str:
    """Prose naming a report whose DEFECT CHANNEL cannot be audited, or ``""``.

    `_si_defect_evidence` reads only POSITIVE evidence, and `_si_body_malformed`
    tolerates ABSENCE, so between them a report could have its defect channel
    DELETED and then read as "no defect found". Measured: a real emitter FAIL
    (1 ERROR finding, ``errors_count`` 1) needed one relabelled word plus
    ``del findings`` and ``del summary.errors_count`` to reach
    ``PASS_WITH_WAIVERS`` at rc 3 — and, relabelled ``PASS`` instead, to reach
    a clean rc 0 ``PROVED`` with no waiver involved at all.

    "Absence is not evidence of a defect" is right. "Absence is not evidence of
    a CLEAN RUN" is the half that was missing. A report asking to be CREDITED —
    proved, or accepted as a disclosed vacuity — has to expose the channel its
    verdict was derived from. This is applied to both creditable states and to
    neither failing one, so it can never turn a FAIL into something softer.

    Every clause reads a field the EMITTER writes UNCONDITIONALLY, in the same
    dict literal, from the same list::

        "errors_count":   sum(1 for f in findings if f.severity == "ERROR"),
        "findings_count": len(findings),
        "findings":       [asdict(f) for f in findings],

    Verified across all six commits that have ever touched
    `si_mcf_sta_check.py` and against every checker-output report in the tree,
    so ``findings_count != len(findings)`` is unreachable from the emitter and
    an absent key proves the file was edited after it was written.

    WHAT THIS CANNOT DO: a body rewritten END TO END so that all three agree
    with a forged verdict is still indistinguishable from a genuine one. What
    the clause buys is COST — the laundering that worked was two deletions;
    now every count has to be forged consistently — not impossibility. Closing
    the remainder needs evidence this consumer does not have (re-running the
    gate, or a signature over the report).
    """
    findings = doc.get("findings")
    errors_count = summary.get("errors_count")
    findings_count = summary.get("findings_count")

    absent = [name for name, value in (
        ("findings", findings),
        ("summary.errors_count", errors_count),
        ("summary.findings_count", findings_count)) if value is None]
    if absent:
        return ("it does not carry " + ", ".join(f"`{n}`" for n in absent)
                + " — the gate writes all three unconditionally from the same "
                  "findings list, so a report missing one has had the channel "
                  "its verdict was derived from removed. An absent defect "
                  "channel is not a clean run; it is an unauditable one")
    if not isinstance(findings, list):
        return (f"`findings` is {type(findings).__name__}, not a list — the "
                f"severity channel this consumer reads has been reshaped")
    for name, value in (("summary.errors_count", errors_count),
                        ("summary.findings_count", findings_count)):
        if isinstance(value, bool) or not isinstance(value, int):
            return (f"`{name}` is {value!r}, not an integer count — the gate "
                    f"writes an integer, so this report did not come from it")
    # `findings` is `[asdict(f) for f in findings]` over a dataclass whose
    # fields are severity / category / message, so EVERY entry carries a
    # string `severity`. An entry without one is not a finding this gate
    # wrote, and it is the cheap way to blind the severity read while leaving
    # the counts agreeing: renaming the key to `level` kept the ERROR prose
    # legible in the file and still reached a waived rc 3.
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            return (f"`findings[{i}]` is {type(f).__name__}, not an object, so "
                    f"its severity cannot be read")
        if not isinstance(f.get("severity"), str):
            return (f"`findings[{i}]` carries no string `severity` — the gate "
                    f"writes every finding from a dataclass that always has "
                    f"one, so the severity channel has been renamed or "
                    f"removed rather than being absent")
    if findings_count != len(findings):
        return (f"`summary.findings_count` is {findings_count} while "
                f"`findings` holds {len(findings)} entr(y/ies). The gate sets "
                f"that count to `len(findings)` in the same dict literal, so "
                f"the two cannot legitimately disagree — this report indicts "
                f"itself")
    # Narrow by construction, and stated so rather than left looking broader
    # than it is: any POSITIVE disagreement here has already been refused by
    # `_si_defect_evidence`, which fires on an ERROR finding OR on
    # `errors_count > 0`. What reaches this clause is the residue — a count
    # BELOW the number of ERROR findings in the body, i.e. a negative one,
    # which `sum(...)` cannot produce. Measured: of 25 (findings, count)
    # combinations that disagree, exactly the negative-count ones arrive here.
    actual_errors = sum(
        1 for f in findings
        if isinstance(f, dict)
        and str(f.get("severity", "")).strip().upper() == "ERROR")
    if errors_count != actual_errors:
        return (f"`summary.errors_count` is {errors_count} while the body "
                f"carries {actual_errors} ERROR finding(s). The gate derives "
                f"that count from the same list it publishes, so the two "
                f"cannot legitimately disagree")
    return ""


def _si_flag_contradicts(summary: dict, key: str, forbidden: bool) -> bool:
    """Is ``summary[key]`` PRESENT and equal to `forbidden`, JSON-int spellings
    included?

    ``summary.get("pass") is True`` misses ``pass: 1``, and
    ``summary.get("vacuous") is False`` misses ``vacuous: 0`` — measured: both
    clauses were silently inert on the integer spellings, which is the same
    class of type miss the PASS branch's `examined` clause was already written
    to avoid. Absence is still tolerated: only a flag that is PRESENT and
    contradicts the verdict refuses.
    """
    value = summary.get(key)
    if value is None:
        return False
    if isinstance(value, bool):
        return value is forbidden
    if isinstance(value, int):          # JSON `1` / `0`
        return bool(value) is forbidden
    return False


def _si_vacuity_inconsistency(summary: dict, denom) -> str:
    """Prose naming how a VACUOUS_PASS report contradicts ITSELF, or ``""``.

    The MIRROR of the PASS branch's ``examined <= 0`` refusal, and it exists
    for the same reason. A PASS is a claim that folds were proved, so a PASS
    whose denominator says it examined nothing indicts itself. A VACUOUS_PASS
    is the opposite claim — "the rule was never applied to anything" — so a
    VACUOUS_PASS whose denominator says work WAS examined indicts itself just
    as plainly, and it is the more dangerous of the two: VACUOUS is the ONE
    state this gate lets a waiver through, so an unchecked contradiction there
    is a route to a waived tapeout, whereas an unchecked one on the PASS side
    is only a route to a blocked one.

    Every clause below re-derives an invariant the EMITTER guarantees by
    construction, so none of them can fire on a report it actually produced:

    * ``verdict == "VACUOUS_PASS"`` requires ``denom.is_vacuous``, i.e.
      ``examined == 0`` exactly (`_gate_denominator.Denominator.is_vacuous`).
    * ``Denominator.__post_init__`` REFUSES to construct a zero denominator
      with no ``not_applicable_reason``, so an empty reason proves the object
      did not come from the emitter.
    * ``summary.pass`` is ``verdict == "PASS"`` and ``summary.vacuous`` is
      ``denom.is_vacuous``; both are computed in the same breath as the
      verdict, so neither can disagree with it.

    Fields that are simply ABSENT are tolerated — older reports predate some of
    them. Only a field that is PRESENT and contradicts the verdict refuses.
    """
    if denom is None:
        return ("it carries no `summary.denominator` block, so it never says "
                "that it examined nothing — a vacuity that does not state its "
                "own zero is indistinguishable from a report that simply "
                "never disclosed one")
    examined = denom.get("examined")
    if isinstance(examined, bool) or not isinstance(examined, int):
        return (f"`denominator.examined` is {examined!r}, not an integer "
                f"count — the report does not state what it examined")
    if examined != 0:
        return (f"`denominator.examined` is {examined} — the verdict says the "
                f"fold was never re-derived while the denominator says "
                f"{examined} victim-net comparison(s) WERE examined. The gate "
                f"emits VACUOUS_PASS only when that count is exactly 0")
    reason = denom.get("not_applicable_reason")
    if not isinstance(reason, str) or not reason.strip():
        return ("`denominator.not_applicable_reason` is empty — a gate that "
                "examined 0 units must say why, and the emitter's Denominator "
                "type refuses to be constructed without it, so this report "
                "did not come from the gate")
    if _si_flag_contradicts(summary, "pass", True):
        return ("`summary.pass` is true while the verdict is VACUOUS_PASS — "
                "the emitter sets that flag to `verdict == \"PASS\"`, so the "
                "two cannot legitimately disagree")
    if _si_flag_contradicts(summary, "vacuous", False):
        return ("`summary.vacuous` is false while the verdict is "
                "VACUOUS_PASS — the emitter sets that flag from the same "
                "`is_vacuous` the verdict is derived from")
    return ""


def _classify_si(project_dir: Path) -> tuple:
    """Return ``(state, detail)`` for this project's SI crosstalk-delay verdict.

    ``detail`` always carries ``report`` (the path looked at) and ``why`` (prose
    a human can act on); it carries ``vacuity_code`` only in the VACUOUS state.

    Fail-closed at every step: an unreadable file, bytes that are not JSON, JSON
    that is not an object, a missing verdict and an unrecognised verdict all
    land in a non-creditable state, never in PROVED.

    The verdict FIELD is never trusted on its own. The report body is read
    first (`_si_defect_evidence`), and each verdict tier is then checked
    against its own denominator (`_si_vacuity_inconsistency` for VACUOUS_PASS,
    the `examined <= 0` clause for PASS), so a report that contradicts itself
    is refused on EITHER branch rather than only on the branch a waiver
    cannot reach.
    """
    path = project_dir / _SI_REPORT_REL
    detail = {"report": str(path)}
    if not path.is_file():
        detail["why"] = (
            f"no SI crosstalk-delay verdict at {_SI_REPORT_REL}. That is not a "
            f"vacuous check — it is the ABSENCE of one. Nothing ran, so there "
            f"is no disclosure to accept and no waiver can cover it.")
        return SI_ABSENT, detail
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        detail["why"] = (
            f"the SI crosstalk-delay report at {_SI_REPORT_REL} could not be "
            f"read as JSON ({exc.__class__.__name__}) — an unreadable verdict "
            f"is no verdict; no waiver can cover it.")
        return SI_ABSENT, detail
    if not isinstance(doc, dict):
        detail["why"] = (
            f"the SI crosstalk-delay report at {_SI_REPORT_REL} parses to "
            f"{type(doc).__name__}, not an object — no verdict can be read "
            f"out of it; no waiver can cover it.")
        return SI_ABSENT, detail

    verdict = doc.get("verdict")
    summary = doc.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    denom = summary.get("denominator")
    denom = denom if isinstance(denom, dict) else None
    detail["verdict"] = verdict if isinstance(verdict, str) else ""

    # THE BODY OUTRANKS THE LABEL, and is read before it. `verdict` is one
    # editable string; the ERROR findings and the error count are the evidence
    # the emitter DERIVED it from. Checking them first means no reordering of
    # the verdict branches below can ever make a defect-carrying report
    # waivable — which is the property that must not depend on branch order,
    # because VACUOUS is the one state a waiver may pass.
    defect = _si_defect_evidence(doc, summary)
    if defect or verdict == "FAIL":
        if defect and verdict != "FAIL":
            detail["why"] = (
                f"the SI crosstalk-delay report carries verdict {verdict!r}, "
                f"but {defect}. The gate derives FAIL from exactly that "
                f"evidence, so this report is a FAILURE wearing another "
                f"label — read as a defect, never as a vacuity to accept.")
        else:
            detail["why"] = (
                "the SI crosstalk-delay gate FAILED — a defect was found. A "
                "vacuity waiver accepts a check that proved nothing; it does "
                "not accept a check that proved something wrong."
                + (f" ({defect})" if defect else ""))
        return SI_VIOLATION, detail
    # ...and a body that has been reshaped until the defect channel cannot be
    # read is not "no defect found". Checked for every verdict, so neither
    # branch can be hardened without the other.
    malformed = _si_body_malformed(doc, summary)
    if malformed:
        detail["why"] = (
            f"the SI crosstalk-delay report carries verdict {verdict!r}, but "
            f"{malformed}. A report this consumer cannot audit is not read as "
            f"a pass or accepted as a vacuity.")
        return SI_UNDISCLOSED, detail
    # A report asking to be CREDITED — proved, or accepted as a disclosed
    # vacuity — must expose the defect channel its verdict was derived from.
    # Applied to both creditable verdicts and to neither failing one, so the
    # branches cannot drift and no FAIL is ever softened by it. Without this,
    # deleting `findings` and `summary.errors_count` from a genuine FAIL turned
    # it into a waived rc 3 under VACUOUS_PASS and into a clean rc 0 under
    # PASS, because absence was read as "no defect found".
    if verdict in ("VACUOUS_PASS", "PASS"):
        unauditable = _si_defect_channel_unauditable(doc, summary)
        if unauditable:
            detail["why"] = (
                f"the SI crosstalk-delay report carries verdict {verdict!r}, "
                f"but {unauditable}. A verdict this consumer cannot audit is "
                f"not credited as a pass and is not accepted as a vacuity a "
                f"waiver may cover.")
            return SI_UNDISCLOSED, detail
    if verdict == "VACUOUS_PASS":
        # THE MIRROR of the PASS branch's internal-consistency refusal below.
        # A vacuity is the ONLY waivable state, so a VACUOUS_PASS that
        # contradicts its own body is refused here rather than carried into
        # the waiver channel. See `_si_vacuity_inconsistency`.
        bad = _si_vacuity_inconsistency(summary, denom)
        if bad:
            detail["why"] = (
                f"the SI verdict is VACUOUS_PASS but {bad}. A report in that "
                f"shape is internally inconsistent — it is forged or "
                f"corrupt, not a disclosed skip — so it is refused rather "
                f"than accepted or waived.")
            if isinstance(denom, dict):
                detail["examined"] = denom.get("examined")
            return SI_UNDISCLOSED, detail
        code = ""
        details = denom.get("details")
        if isinstance(details, dict):
            raw = details.get("vacuity_code")
            if isinstance(raw, str):
                code = raw.strip().upper()
        if not code:
            detail["why"] = (
                "the SI verdict is VACUOUS_PASS but the report does not name "
                "WHICH vacuity (summary.denominator.details.vacuity_code is "
                "absent or empty). An acceptance cannot name a vacuity the "
                "report refuses to identify, so there is nothing waivable "
                "here.")
            return SI_UNDISCLOSED, detail
        detail["vacuity_code"] = code
        detail["why"] = str(denom.get("not_applicable_reason", "")).strip()
        return SI_VACUOUS, detail
    if verdict == "PASS":
        if denom is None:
            detail["why"] = (
                "the SI verdict is PASS but the report carries no "
                "`summary.denominator` block, so it never says how many folds "
                "it proved. A PASS over an unstated denominator is the exact "
                "false-clean this gate was fixed for and is not creditable at "
                "tapeout.")
            return SI_UNDISCLOSED, detail
        examined = denom.get("examined")
        if isinstance(examined, bool) or not isinstance(examined, int):
            detail["why"] = (
                f"the SI verdict is PASS but `denominator.examined` is "
                f"{examined!r}, not an integer count — the report does not "
                f"state what it examined.")
            return SI_UNDISCLOSED, detail
        if examined <= 0:
            # Mirrored by `_si_vacuity_inconsistency` on the VACUOUS_PASS
            # branch above. Both branches refuse a report that contradicts its
            # own denominator; neither may be defended without the other.
            detail["why"] = (
                "the SI verdict is PASS but `denominator.examined` is 0 — the "
                "gate signed off over nothing. A report in that shape is "
                "internally inconsistent (the gate emits VACUOUS_PASS for it), "
                "so it is refused rather than accepted or waived.")
            detail["examined"] = examined
            return SI_UNDISCLOSED, detail
        detail["examined"] = examined
        detail["why"] = (f"{examined} victim-net MCF fold(s) re-derived and "
                         f"proved against the bounded SPEF.")
        return SI_PROVED, detail

    detail["why"] = (
        f"the SI crosstalk-delay report carries verdict {verdict!r}, which "
        f"this gate does not recognise. An unrecognised verdict is not read "
        f"as a pass.")
    return SI_UNDISCLOSED, detail


def _si_vacuity_disclosures(project_dir: Path) -> dict:
    """Vacuity codes this project's governed waivers ACCEPT for the tapeout step.

    Returns ``{CODE: {"source", "approver", "reason"}}``. An entry counts only
    when it targets the tapeout step id AND would survive `waivers_schema_check`
    — a reason of real length that is not a placeholder, and a named approver
    who is neither a self-approver nor an unfilled scaffold slot. Those
    predicates are IMPORTED, not restated, so this gate and the schema gate
    cannot drift apart.

    Fail-closed at every step: a missing file, unreadable bytes, malformed JSON,
    or JSON that is legal but is not an object all accept nothing.
    """
    out: dict = {}
    try:
        _here = str(Path(__file__).resolve().parent)
        if _here not in sys.path:
            sys.path.insert(0, _here)
        import waivers_schema_check as _wv
    except Exception:
        # No vocabulary to validate against => nothing is disclosable and every
        # vacuity blocks. Fail-closed, never fail-open.
        return out
    p = project_dir / "waivers.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return out
    if not isinstance(doc, dict):
        return out
    entries = doc.get("waived_steps")
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # NAMES THE STEP. A waiver filed against some other step is not an
        # acceptance of this one.
        if str(entry.get("id")) != str(_TAPEOUT_STEP_ID):
            continue
        codes = entry.get(SI_DISCLOSURE_FIELD)
        if not isinstance(codes, list) or not codes:
            continue
        reason = entry.get("reason")
        if (not isinstance(reason, str)
                or len(reason.strip()) < _wv.MIN_REASON_LEN
                or _wv._is_placeholder(reason)):
            continue
        approver = entry.get("approver")
        if (not isinstance(approver, str) or not approver.strip()
                or _wv._is_self_approver(approver)
                or _wv._is_placeholder_approver(approver)):
            continue
        for name in codes:
            if not isinstance(name, str):
                continue
            code = name.strip().upper()
            if not code or code in _SI_BLANKET_CODES:
                continue
            out[code] = {
                "source": "waivers.json",
                "approver": approver.strip(),
                "reason": reason.strip(),
            }
    return out


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

    # (a) GDS — the DECLARED stream-out, with substance. Not "a .gds exists".
    #
    # Two separate questions, and the 2026-07-27 ranking change only answered
    # the first: (i) WHICH candidate does the checklist cite, and (ii) MAY the
    # slot be credited at all. Ranking alone left (ii) as `rank !=
    # _PRESIGNOFF_RANK`, i.e. any `.gds` anywhere still certified Step 36 —
    # a lone `steps/` mirror, a lone stale `foundry_handoff` copy, a stray
    # root-level copy, a 0-byte file at the declared path, and even the
    # FOUNDRY-SUPPLIED `scribe_line_layout.gds` frame each did so on its own.
    #
    # The slot is credited by ONE thing: the flow's declared stream-out
    # artefact (`_CREDITABLE_GDS_RANK`, i.e. `phase3/stage4/gds/*.gds` — the
    # exact path step 37's substance gates verify) carrying actual GDSII
    # substance (`_gds_stream_substance`). Everything else is DISCLOSED by a
    # named, NON-crediting finding, mirroring TAPEOUT_GDS_PRESIGNOFF_ONLY:
    #   TAPEOUT_GDS_EMPTY                  declared path present, 0 bytes
    #   TAPEOUT_GDS_NOT_A_STREAM           declared path present, not GDSII
    #   TAPEOUT_GDS_NOT_DECLARED_STREAMOUT only mirrors/copies/foundry frames
    #   TAPEOUT_GDS_PRESIGNOFF_ONLY        only self-declared drafts
    #   TAPEOUT_GDS_EXISTS (ERROR)         nothing at all
    # Ranking still decides which file each finding CITES.
    gds_files = _has_files(project_dir, ["*.gds", "*.gds2", "*.gdsii",
                                          "*.GDS", "*.GDSII"])
    gds_files = _rank_signoff_first(gds_files, project_dir, _gds_rank)
    gds_declared = [p for p in gds_files
                    if _gds_rank(p, project_dir) == _CREDITABLE_GDS_RANK]
    gds_creditable = [p for p in gds_declared
                      if _gds_stream_substance(p) == "ok"]
    gds_fallback = [p for p in gds_files
                    if _gds_rank(p, project_dir) not in (_CREDITABLE_GDS_RANK,
                                                         _PRESIGNOFF_RANK)]
    if gds_creditable:
        chosen_gds = gds_creditable[0]
        evidence["gds"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_GDS_EXISTS", severity="INFO",
            message=(f"Declared stream-out GDS found: {chosen_gds.name} "
                     f"({chosen_gds.stat().st_size} bytes, GDSII HEADER "
                     f"record present)"),
            file=str(chosen_gds)))
    elif gds_declared:
        # The declared path IS populated — and the file there is not a layout.
        # Naming it is the disclosure; the slot is not credited.
        evidence["gds"] = False
        _worst = gds_declared[0]
        _substance = {p: _gds_stream_substance(p) for p in gds_declared}
        _byted = [p for p in gds_declared if _substance[p] == "not_gdsii"]
        if _byted:
            _cite = _byted[0]
            result.findings.append(Finding(
                rule="TAPEOUT_GDS_NOT_A_STREAM", severity="ERROR",
                message=(f"Declared stream-out '{_cite.name}' "
                         f"({_cite.stat().st_size} bytes) does not begin with "
                         f"a GDSII HEADER record — it is a file at the "
                         f"stream-out path, not a stream-out. The tape-out "
                         f"checklist certifies a LAYOUT, not a filename "
                         f"(#437a). Re-run Step 37 stream-out."),
                file=str(_cite)))
        else:
            result.findings.append(Finding(
                rule="TAPEOUT_GDS_EMPTY", severity="ERROR",
                message=(f"Declared stream-out '{_worst.name}' is present but "
                         f"carries no bytes (or is unreadable / a dangling "
                         f"mirror) — an empty file is not the GDS a tape-out "
                         f"is signed off on. Re-run Step 37 stream-out."),
                file=str(_worst)))
    elif gds_fallback:
        # Candidates exist, none of them is the declared stream-out. This is
        # the exact shape the ranking change alone still certified.
        evidence["gds"] = False
        _cite = gds_fallback[0]
        _names = ", ".join(sorted({p.name for p in gds_fallback})[:5])
        result.findings.append(Finding(
            rule="TAPEOUT_GDS_NOT_DECLARED_STREAMOUT", severity="ERROR",
            message=(f"No declared stream-out GDS "
                     f"(phase3/stage4/gds/<top>.gds). The only GDS(es) found "
                     f"({_names}) rank below it — best candidate "
                     f"'{_cite.name}' is "
                     f"{_gds_rank_note(_cite, project_dir)}. A mirror, a "
                     f"copy or a foundry-supplied frame is not the layout a "
                     f"tape-out is signed off on; stream out Step 37 before "
                     f"claiming Step 36."),
            file=str(_cite)))
    elif gds_files:
        # Candidates exist but every one of them DECLARES itself a
        # pre-sign-off intermediate. Naming the files is the disclosure; the
        # slot is still not credited (#437a: substance, not existence).
        evidence["gds"] = False
        _names = ", ".join(sorted({p.name for p in gds_files})[:5])
        result.findings.append(Finding(
            rule="TAPEOUT_GDS_PRESIGNOFF_ONLY", severity="ERROR",
            message=(f"Only pre-sign-off GDS(es) found ({_names}) — a "
                     f"draft/preview layout is not the GDS a tape-out is "
                     f"signed off on. Stream out the sign-off layout "
                     f"(phase3/stage4/gds/<top>.gds) before claiming "
                     f"Step 36."),
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
        #
        # The grammar itself now lives in `_signoff_drc_format` — this file is
        # where it was first written, and two other programs needed it (the
        # step-31 substance gate could not read a clean foundry-deck sign-off at
        # all, measuring `determined_files:0`). It is imported rather than
        # copied a fourth time; the behaviour is byte-identical.
        _svrf = _sdf.svrf_fail_count(txt)
        if _svrf is not None:
            return _svrf
        # A router detailed-route DRC report is ITERATIVE — one count per repair
        # iteration, and possibly across more than one route pass — so the
        # sequence is non-monotone and only the LAST count is the geometry that
        # ships. The generic `re.search` below returns the FIRST match, i.e. the
        # pre-repair state, which can be larger than the final count (over-report
        # → false FAIL on a clean design) or smaller (under-report → false PASS
        # on a design that never converged). Read the final count through the
        # SAME shared helper `phase3_one_shot_runner._drt_final_violations` uses,
        # so the two readers of this grammar cannot drift apart (they used to:
        # re.search-first here vs findall-last there). Returns None when the
        # report has no router-iteration grammar, so a genuine summary-only
        # report still falls through to the text fallback below.
        _drt = _sdf.router_iter_last_count(txt)
        if _drt is not None:
            return _drt
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

    # ── SI crosstalk-delay: the blocking condition, not an evidence slot ──
    # Deliberately NOT a sixth pillar. The pillars ask "is the artefact there
    # and is it sign-off-grade"; this asks "was the question ANSWERED". It can
    # therefore veto a run that reached the threshold, which an evidence slot
    # cannot express, and it can do so without shifting the 5-of-5 denominator
    # every existing consumer of `summary.threshold` reads.
    si_state, si_detail = _classify_si(project_dir)
    si_accepted = _si_vacuity_disclosures(project_dir)
    si_code = si_detail.get("vacuity_code", "")
    si_waiver = si_accepted.get(si_code) if si_code else None
    si_waived = False
    si_waiver_refused = ""
    if si_state == SI_PROVED:
        result.findings.append(Finding(
            rule="TAPEOUT_SI_PROVED", severity="INFO",
            message=(f"SI crosstalk-delay sign-off: {si_detail['why']}"),
            file=si_detail["report"]))
    elif si_state == SI_VACUOUS and si_waiver is not None:
        si_waived = True
        result.findings.append(Finding(
            rule="TAPEOUT_SI_VACUITY_WAIVED", severity="WARNING",
            message=(
                f"SI crosstalk-delay was NOT CHECKED (vacuity {si_code}) and "
                f"the vacuity is ACCEPTED for this step by "
                f"{si_waiver['approver']} in waivers.json: "
                f"{si_waiver['reason']} — tapeout verdict is "
                f"PASS_WITH_WAIVERS, never a bare PASS. Gate said: "
                f"{si_detail['why']}"),
            file=si_detail["report"]))
    elif si_state == SI_VACUOUS:
        # A waiver may exist and still not fit: wrong code, blanket code, no
        # approver, placeholder reason, filed against another step. Say which.
        near = sorted(si_accepted)
        why_not = (f"the only accepted vacuit(y/ies) for this step are {near}"
                   if near else
                   "no governed waiver entry for this step accepts any SI "
                   "vacuity (a code comment, a marker file or an absent report "
                   "is not a disclosure)")
        result.findings.append(Finding(
            rule="TAPEOUT_SI_VACUOUS_UNWAIVED", severity="ERROR",
            message=(
                f"SI crosstalk-delay was NOT CHECKED (vacuity {si_code}) and "
                f"nothing accepts it: {why_not}. Crosstalk kills silicon; "
                f"'checked and clean' and 'never checked' are not the same "
                f"green light at a mask order. To proceed, add a waivers.json "
                f"`waived_steps` entry with id {_TAPEOUT_STEP_ID}, a named "
                f"human `approver`, a reason, and "
                f"`{SI_DISCLOSURE_FIELD}: [\"{si_code}\"]`. Gate said: "
                f"{si_detail['why']}"),
            file=si_detail["report"]))
    else:
        # VIOLATION / UNDISCLOSED / ABSENT — none of them waivable. If a waiver
        # is nonetheless present, record that it was REFUSED, so an attempt to
        # launder a real failure leaves a trace instead of vanishing.
        if si_accepted:
            si_waiver_refused = (
                f"waivers.json accepts SI vacuit(y/ies) {sorted(si_accepted)} "
                f"for this step, but the SI state is {si_state}, which is not "
                f"a vacuity. A vacuity waiver accepts a check that proved "
                f"nothing; it never accepts a failed, missing or undisclosed "
                f"one.")
        result.findings.append(Finding(
            rule=f"TAPEOUT_SI_{si_state}", severity="ERROR",
            message=((f"SI crosstalk-delay sign-off refused ({si_state}): "
                      f"{si_detail['why']}")
                     + (f" {si_waiver_refused}" if si_waiver_refused else "")),
            file=si_detail["report"]))

    if si_state != SI_PROVED and not si_waived:
        # Veto. Whatever the evidence pillars said, this run is not signed off.
        result.passed = False
        verdict_tier = "FAIL"
    elif result.passed and si_waived and verdict_tier == "PASS":
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
        "si_signoff": {
            "state": si_state,
            "report": si_detail.get("report", ""),
            "verdict": si_detail.get("verdict", ""),
            "vacuity_code": si_code,
            "folds_proved": si_detail.get("examined", 0),
            "waived": si_waived,
            "waiver_approver": (si_waiver or {}).get("approver", ""),
            "waiver_reason": (si_waiver or {}).get("reason", ""),
            "waiver_refused": si_waiver_refused,
            "accepted_vacuity_codes": sorted(si_accepted),
            "why": si_detail.get("why", ""),
        },
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
# (`_TAPEOUT_STEP_ID` is defined above, beside the SI blocking condition that
# also keys on it.)
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
