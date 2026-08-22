#!/usr/bin/env python3
"""general_precheck.py — the tape-out precheck for a design with NO operator.

ENFORCEMENT: advisory here — this gate is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; no one-shot runner invokes it
inline at all. It runs as the FIRST ARM of step 37.5ic, invoked by
``tapeout_precheck``, whose rc IS that step's verdict — so a refusal here refuses
the step. (Until 2026-08-20 it was step 37.5self's own ``program_exit_zero``
clause; the step was retired and this ladder became an arm rather than a route,
which STRENGTHENS the channel: it now runs on every design reaching 37.5ic
instead of only on the ones carrying a self-tape-out marker.) "advisory" names
the RUNNER channel it is absent from, not a verdict this gate cannot reach. The
same words its sibling ``tapeout_readiness_check`` carries, for the same reason
and about the same channel: wiring a new gate into the runner changes what a real
run blocks on, which is the flow owner's call and is recorded here rather than
taken. Declared because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
enforcement decision nobody made — and declaring `blocking` instead was MEASURED
to be worse: the audit reads it against the wiring and reports
``contradiction::general_precheck``, because a gate no runner invokes cannot
block in the venue the word names. Kept in the first 4 kB: `declared_intent`
reads only `text[:4000]`.

WHY THIS EXISTS
===============
The only tape-out precheck this tree had was `tapeout_readiness_check`, which
runs the SHUTTLE OPERATOR's own container. That is the right design for a
design going to that shuttle — an outside party's refusal is the verdict, and a
gate we wrote can be made to pass by editing it. But it is specific to ONE
operator and ONE PDK, and a design doing its own tape-out has nothing to run.

MEASURED, on the flow as it stood (`flow/phase1_phase2_phase3.yaml`, v1.10.98):
step 0.5ic wrote two router files for what are actually THREE routes —
`slots/*.yaml` selected the operator's container (37.5ic) and `NO_TEMPLATE.txt`
selected the IP/hardmacro terminal (37.5ip). A CHIP doing its own tape-out has
no operator template, so 37.5ic's condition excluded it, and it is a die rather
than an IP, so 37.5ip was the wrong terminal for it. Such a design reached
tape-out having passed NO submission check of any kind.

THIS IS ~450 LINES OF ASSEMBLY, NOT A NEW ENGINE
================================================
The operator's precheck is itself a LibreLane `SequentialFlow`: 8 custom step
classes, of which 6 are general and only 2 are operator-specific
(`KLayout.GenerateID`, whose ID ENCODING is theirs, and `KLayout.CheckPadMask`,
whose PAD MASK is theirs). Everything else — DRC, density, antenna, Magic DRC —
is stock. So the general precheck is not a reimplementation of their engine. It
is the same ladder with their two steps removed and the general ones sourced
from where they can be sourced without them.

THREE CLASSES OF CHECK, AND WHERE THE TRUTH COMES FROM
======================================================
    OWN_GEOMETRY   Needs no PDK data and no tool. Read straight out of the
                   GDSII record stream by `_gds_geometry`: origin, top cell,
                   zero-area polygons, database unit.
    DELEGATED      The PDK's own rules. DRC deck, density, antenna, Magic DRC.
                   We CALL the in-tree checker that calls the deck. We never
                   reimplement a rule, a window or a ratio — a copy of one
                   here would be OURS, editable, and able to drift into
                   passing, which is precisely the property that makes the
                   operator's container stronger than anything we write.
    DECLARED       Needs something a human wrote down: the die size, whether a
                   seal ring is required, which layers are forbidden. Compared
                   against `_tapeout_declaration`'s 18 questions. An
                   unanswered question is NOT_DETERMINED here — never a pass,
                   and never a default.

THE ORIGIN CHECK IS THE ONE ADDITION, AND IT IS JUSTIFIED BY MEASUREMENT
========================================================================
The operator's container has no standalone origin check of its own — origin is
folded into their `KLayout.CheckSize`, which also needs their slot table, so a
design with no slot cannot run it. `resolve_in_tree_coverage` recomputed on
this tree reported `KLayout.CheckSize` UNCOVERED: none of
`die_slot_dimension_check`, `seal_ring_check`, `frame_dimension_check` existed.

It is the gate a negative control caught, and the known positive is real and
published. MEASURED on `u_hawaii_adc` sky130A,
`phase3/stage4/gds/ldo.gds` (sha256 369719cf…):

    top cells                 ['ldo']            declared top: u_hawaii_adc
    flattened bbox (um)       (-4.5, -223.305) .. (328.08, 240.11)
    width x height (um)       332.580 x 463.415

and that file is BYTE-IDENTICAL to `phase3/analog/hardmacro/ldo/ldo.gds`. The
negative origin is not corruption and not a GDS-writer defect: every device
cell in it is origin-CENTRED by its generator's convention, and the macro's own
LEF DECLARES the offset — `ORIGIN 4.500 223.305 ; SIZE 332.580 BY 463.415 ;`,
matching the measured box to the micron. It is legal for a HARDMACRO and it is
not legal for a DIE, and what happened is that an analog hardmacro was copied
into the chip-GDS position. So the origin check fires there, and firing there
is correct — the thing in the chip position is not a chip. That is why
`deliverable` is the first question the declaration asks and the first answer
this program reads.

THE TWO OPERATOR-SPECIFIC STEPS ARE EXCLUDED, AND SAID SO
=========================================================
`KLayout.CheckPadMask` and `KLayout.GenerateID` are NOT in this ladder, because
there is no operator, so there is no pad mask and no id encoding to check
against. They are listed in the report under `operator_specific_excluded` with
that reason. Silently dropping them would make this ladder look shorter than
the operator's for no stated cause, and a reader comparing the two reports side
by side has to be able to see that the difference is deliberate.

THE THREE VERDICTS, AND WHY THERE ARE ONLY THREE
================================================
Identical to `tapeout_readiness_check`, on purpose, so the two reports read the
same way:

    PASS            every ladder step ran and carries passing evidence.
    FAIL            a step refused, against the layout or the declaration.
    NOT_DETERMINED  no verdict was obtained: no layout, an unreadable layout,
                    a question left unanswered, or a delegated checker that
                    could not run. "NOT DETERMINED" beats a guess.

No `SKIPPED`, `N/A` or `BLOCKED`. All three read as "nothing to worry about
here" in an aggregate, and nothing-to-worry-about is exactly what a design
nobody checked is not entitled to.

EXIT CODES
==========
    0  PASS
    1  FAIL **and** NOT_DETERMINED — every non-pass
    2  usage / unreadable input

rc 3 is NOT used (`flow_compliance_check` reads it as PASS_WITH_WAIVERS and
promotes the step to WAIVED-DEFERRED). rc 2 is not used for NOT_DETERMINED
either: this repo credits a rc-2 `VACUOUS_PASS` as a pass repo-wide. Either
would route "we did not find out" back into a green light.

DENOMINATOR
===========
Every verdict line states how many ladder steps were required, how many carry
evidence, how many declaration questions were answered out of 18, and which
layout was examined. A run that examined no layout says `layouts_found=0` and
refuses rather than passing over an empty set.

chip-AGNOSTIC: no vendor, foundry, process node, SKU, chip codename or design
literal. Every layer number, dimension, top-cell name and PDK path is read from
the layout or from the declaration.

USAGE
-----
    python3 general_precheck.py <project>
        [--gds PATH]            # default: discovered under the project
        [--declaration PATH]    # default: <project>/input/submission_template/
                                #          tapeout_declaration.json
        [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _gds_geometry as _geom                                   # noqa: E402
import _tapeout_declaration as _decl                            # noqa: E402
import plugin_manifest_discovery as _pmd                        # noqa: E402
from _atomic_artefact import write_text as atomic_write_text    # noqa: E402

ATTRIBUTION = "general_precheck"

PASS = "PASS"
FAIL = "FAIL"
NOT_DETERMINED = "NOT_DETERMINED"

#: Where the truth for a step comes from. Recorded per step in the report,
#: because "we measured this" and "we asked the PDK" and "we compared it to
#: what you told us" are three different strengths of claim.
OWN_GEOMETRY = "OWN_GEOMETRY"
DELEGATED = "DELEGATED"
DECLARED = "DECLARED"

#: Where this gate's verdict belongs. Named once so the producer and any
#: consumer cannot drift onto different paths.
PRECHECK_ARTEFACT = "reports/phase3/general_precheck.json"

#: Layout discovery. Identical to `tapeout_readiness_check._LAYOUT_GLOBS` so a
#: design cannot be judged on one file by one gate and a different file by the
#: other. Nothing here is chip-specific.
_LAYOUT_GLOBS: Tuple[str, ...] = (
    "phase3/stage4/gds/*.gds",
    "phase3/stage4/gds/*.gds.gz",
    "phase3/stage4/gds/*.oas",
    "**/stage4/gds/*.gds",
)

#: The operator's ladder steps that this route CANNOT and MUST NOT run, with
#: the reason each one is out. Reported, never silently dropped.
OPERATOR_SPECIFIC_EXCLUDED: Tuple[Tuple[str, str], ...] = (
    ("KLayout.CheckPadMask",
     "the pad mask is the OPERATOR's, published per purchasable slot. With no "
     "operator there is no mask to check the pad openings against, and a mask "
     "of our own invention would be a rule we wrote pretending to be theirs."),
    ("KLayout.GenerateID",
     "the die-identification cells and their ID ENCODING are the OPERATOR's, "
     "shipped as pre-built fixtures in their project template. With no "
     "template there are no fixtures and no encoding to conform to."),
)

#: Where a DELEGATED checker's artefact goes. THIS LADDER'S OWN DIRECTORY, with
#: basenames of its own, and both halves of that are load-bearing.
#:
#: Until this constant existed, the five delegates wrote to the FLOW'S canonical
#: report paths — `reports/phase3/{die_finishing,antenna_signoff,drc_router,
#: drc_signoff,density_signoff}.json` — four of which the flow itself produces
#: from a step gate, and three of which a step declares as a `required_output`.
#: This ladder therefore OVERWROTE four sign-off artefacts it does not own, with
#: the output of a WEAKER invocation. MEASURED on `reports/phase3/drc_signoff.json`,
#: the two argv forms aimed at that one path:
#:
#:     step 31   drc_report_check . --mode drc --signoff \
#:                   --under reports/phase3/drc_signoff.rpt --json <path>
#:               -> 811 B, findings [DRC_REPORT_EXISTS, SCOPE_NOT_FOUND],
#:                  summary.scoped_under = ['reports/phase3/drc_signoff.rpt']
#:     here      drc_report_check . --mode drc --json <path>
#:               -> 308 B, findings [DRC_REPORT_EXISTS], no scope keys at all
#:
#: `--signoff` is a WRAPPER flag adding two independent refusals (a producer
#: that is a rule deck applied to a layout, and evidence of a streamed layout);
#: `--under` scopes discovery to the artefact step 31 declares. This ladder
#: passes neither, so what it left behind was a strictly weaker verdict wearing
#: the sign-off's filename — and `signoff_ladder_run.check_tier_1_drc` grades
#: release-gating tier T1 off that file while `final_report_generate` echoes it
#: into the sign-off summary a reader treats as the deliverable.
#:
#: THE BASENAMES ARE DIFFERENT TOO, not just the directory. Discovery in this
#: tree is by recursive glob — `reports/**/drc_signoff.json`,
#: `reports/**/antenna.json`, `reports/**/metal_density*.json` — so a copy of
#: ours under a private directory keeping the canonical NAME would still be
#: found and could still be graded as the sign-off. `test_general_precheck`
#: asserts no delegate report path collides with anything the flow declares or
#: designates, so the next delegate added cannot reintroduce this.
DELEGATE_REPORT_DIR = "reports/phase3/general_precheck"

#: How a delegated checker is invoked and what its rc means. `argv_tail` is
#: appended after the project directory. `report_rel` is where the checker's
#: own artefact goes, so the evidence quoted is the checker's, not ours.
#:
#: rc MAPPING, and the one that matters: rc 2 is NOT_DETERMINED here. Repo-wide
#: a rc-2 is credited as `VACUOUS_PASS`; a checker that could not find its
#: input has not cleared the design, and crediting it would put the exact state
#: this program exists to publish back into a green light.
@dataclass(frozen=True)
class Delegate:
    program: str
    argv_tail: Tuple[str, ...]
    report_rel: str
    positional: str = "project"      # "project" | "reports_dir"


@dataclass(frozen=True)
class Step:
    step_id: str
    label: str
    order: int
    source: str
    refuses_on: str
    delegate: Optional[Delegate] = None
    note: str = ""


# --------------------------------------------------------------------------- #
# THE LADDER — the operator's own step order, minus their two steps, plus ours.
#
# Stated in SUBMISSION-FAILURE ORDER, which is upstream's own sequence: a
# reader going top to bottom hits the refusals where a real submission would,
# so the first FAIL is the first thing that would actually stop a hand-off.
#
# `General.*` ids are OURS and are prefixed so they cannot be mistaken for a
# step the operator's tool emits. Two of them are additions with no upstream
# analogue and each says why below.
# --------------------------------------------------------------------------- #
LADDER: Tuple[Step, ...] = (
    Step("KLayout.ReadLayout", "Read the Layout", 1, OWN_GEOMETRY,
         "the layout file cannot be read as GDSII"),
    Step("General.DatabaseUnit", "Database Unit vs the Tech File", 2,
         DECLARED,
         "the stream's UNITS record disagrees with the declared database unit",
         note="OURS; upstream folds this into its reader. Separated because a "
              "stream written at a different grid than the tech file declares "
              "is off-grid everywhere at once and nothing downstream says so."),
    Step("KLayout.CheckTopLevel", "Check Top-Level Name", 3, DECLARED,
         "more than one top-level cell, or its name is not the declared top"),
    Step("KLayout.CheckSize", "Check Origin and Die Size", 4, DECLARED,
         "the origin is not where it was declared, or the die dimensions do "
         "not match the declared die area",
         note="THE ORIGIN CHECK. Upstream folds origin into this step and "
              "needs its slot table to run it; this compares against the "
              "DECLARATION instead, which is the only source a design with no "
              "operator has."),
    Step("General.SealRing", "Seal Ring Present", 5, DELEGATED,
         "a seal ring was declared as required and the layout does not carry "
         "one",
         delegate=Delegate("die_finishing_check", (),
                           f"{DELEGATE_REPORT_DIR}/precheck_seal_ring.json"),
         note="Placed here because this is where the live operator tool "
              "MEASURABLY refused a published layout (2026-08-18, ladder step "
              "3 of 16, 'requires a seal ring (guard ring) around the die')."),
    Step("General.ForbiddenLayers", "No Forbidden Layers Used", 6, DECLARED,
         "the layout draws on a layer the declaration forbids"),
    Step("Checker.KLayoutDensity", "Density Checker", 7, DELEGATED,
         "layer density outside the accepted window",
         delegate=Delegate("metal_layer_density_check", (),
                           f"{DELEGATE_REPORT_DIR}/precheck_density.json",
                           positional="reports_dir")),
    Step("Checker.KLayoutZeroAreaPolygons", "Zero Area Polygons Checker", 8,
         OWN_GEOMETRY, "the layout contains zero-area polygons"),
    Step("Checker.KLayoutAntenna", "Antenna Checker", 9, DELEGATED,
         "antenna ratio violations",
         delegate=Delegate("antenna_report_check", (),
                           f"{DELEGATE_REPORT_DIR}/precheck_antenna.json")),
    Step("Checker.MagicDRC", "Magic DRC Checker", 10, DELEGATED,
         "Magic DRC violations",
         delegate=Delegate("drc_report_check", ("--mode", "drc"),
                           f"{DELEGATE_REPORT_DIR}/precheck_magic_drc.json")),
    Step("Checker.KLayoutDRC", "KLayout DRC Checker", 11, DELEGATED,
         "KLayout DRC violations",
         delegate=Delegate("drc_report_check", ("--mode", "drc"),
                           f"{DELEGATE_REPORT_DIR}/precheck_klayout_drc.json")),
)


@dataclass
class StepEvidence:
    step_id: str
    label: str
    order: int
    source: str
    verdict: str
    refuses_on: str
    evidence: str = ""
    measured: Optional[Dict[str, Any]] = None
    delegated_to: Optional[str] = None
    returncode: Optional[int] = None
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PrecheckReport:
    project: str
    verdict: str
    reason: str
    layouts_found: int
    layout: Optional[str] = None
    layout_sha256: Optional[str] = None
    declaration: Optional[str] = None
    declaration_present: bool = False
    declaration_refusals: List[Dict[str, Any]] = field(default_factory=list)
    declaration_audit: Dict[str, Any] = field(default_factory=dict)
    deliverable: str = NOT_DETERMINED
    required_steps: int = 0
    steps_with_evidence: int = 0
    steps: List[StepEvidence] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    undetermined_steps: List[str] = field(default_factory=list)
    operator_specific_excluded: List[Dict[str, str]] = field(
        default_factory=lambda: [{"step_id": s, "reason": r}
                                 for s, r in OPERATOR_SPECIFIC_EXCLUDED])
    geometry: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["steps"] = [s.as_dict() for s in self.steps]
        d["emitted_by"] = _pmd.emitted_by(ATTRIBUTION)
        return d

    def summary_line(self) -> str:
        """One line that ALWAYS states the denominator."""
        a = self.declaration_audit or {}
        return (
            f"{self.verdict}: general_precheck (no operator) — "
            f"layouts_found={self.layouts_found}, "
            f"ladder_steps_required={self.required_steps}, "
            f"steps_with_evidence={self.steps_with_evidence}, "
            f"failed={len(self.failed_steps)}, "
            f"undetermined={len(self.undetermined_steps)}, "
            f"declaration_answered={a.get('answered', 0)}/"
            f"{a.get('questions_total', len(_decl.QUESTIONS))} — {self.reason}")


#: Injectable seam so the delegation is testable with NO EDA tool present.
Runner = Callable[[List[str], Optional[float]], Tuple[int, str, str]]


def default_runner(cmd: List[str], timeout: Optional[float]
                   ) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "[timeout]"
    except (OSError, subprocess.SubprocessError) as exc:
        return 125, "", f"[runner error] {exc!r}"


def discover_layouts(project: Path) -> List[Path]:
    """Every finished layout under `project`, in a stable order.

    Returns [] for a project that has none — a refusal, not a pass over an
    empty set.
    """
    for pattern in _LAYOUT_GLOBS:
        hits = sorted(p for p in project.glob(pattern) if p.is_file())
        if hits:
            return hits
    return []


def _sha256(path: Path) -> Optional[str]:
    import hashlib
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _blank(step: Step) -> StepEvidence:
    return StepEvidence(
        step_id=step.step_id, label=step.label, order=step.order,
        source=step.source, verdict=NOT_DETERMINED,
        refuses_on=step.refuses_on, note=step.note,
        delegated_to=step.delegate.program if step.delegate else None)


def _close(v: float, w: float, dbu_um: Optional[float]) -> bool:
    """Equal to within HALF a database unit.

    The tolerance is the LAYOUT'S OWN GRID, not a constant of ours. A GDSII
    coordinate is an integer count of database units, so a declared micron
    value that lands between two grid points cannot be hit exactly and the
    nearest representable answer is half a unit away. Anything looser would be
    a threshold somebody could widen; anything tighter would refuse a layout
    that is exactly right.

    With no database unit known, falls back to exact equality — the strict
    direction, because guessing a grid is guessing.
    """
    if dbu_um is None or dbu_um <= 0:
        return v == w
    return abs(v - w) <= dbu_um / 2.0


# --------------------------------------------------------------------------- #
# The three OWN_GEOMETRY / DECLARED steps that read the layout directly
# --------------------------------------------------------------------------- #
def _step_read_layout(ev: StepEvidence, geom: Optional[Dict[str, Any]],
                      read_error: Optional[str]) -> None:
    if read_error:
        ev.verdict, ev.evidence = FAIL, read_error
        return
    assert geom is not None
    if geom["truncated"]:
        ev.verdict = FAIL
        ev.evidence = f"the stream is truncated: {geom['truncated_reason']}"
        return
    if geom["cell_count"] == 0:
        ev.verdict = FAIL
        ev.evidence = "the stream carries 0 structures; it is not a layout"
        return
    ev.verdict = PASS
    ev.evidence = (f"read {geom['cell_count']} structure(s), "
                   f"{geom['polygon_count']} polygon(s)")
    ev.measured = {"cell_count": geom["cell_count"],
                   "polygon_count": geom["polygon_count"],
                   "dangling_references": geom["dangling_references"]}


def _step_database_unit(ev: StepEvidence, geom: Optional[Dict[str, Any]],
                        declared: Any) -> None:
    if geom is None:
        ev.evidence = "the layout was not read, so its UNITS record is unknown"
        return
    measured = geom.get("dbu_um")
    ev.measured = {"measured_dbu_um": measured, "declared_dbu_um": declared}
    if measured is None:
        ev.evidence = "the stream carries no UNITS record"
        return
    if declared == _decl.NOT_DETERMINED:
        ev.evidence = (
            "the layout's database unit is "
            f"{measured} um, and `database_unit_um` was not declared, so "
            "there is nothing to compare it against")
        return
    # Relative comparison: a database unit is a ratio, and two ratios that
    # differ in the 12th decimal are the same grid expressed differently.
    if abs(measured - declared) <= abs(declared) * 1e-9:
        ev.verdict = PASS
        ev.evidence = f"UNITS declares {measured} um, matching the tech file"
    else:
        ev.verdict = FAIL
        ev.evidence = (f"UNITS declares {measured} um; the tech file declares "
                       f"{declared} um. Every coordinate in this stream is on "
                       "the wrong grid")


def _step_top_level(ev: StepEvidence, geom: Optional[Dict[str, Any]],
                    declared_top: Any) -> None:
    if geom is None:
        ev.evidence = "the layout was not read, so its top cell is unknown"
        return
    tops = geom["top_cells"]
    ev.measured = {"top_cells": tops, "top_cell_count": len(tops),
                   "declared_top_cell": declared_top}
    if len(tops) != 1:
        ev.verdict = FAIL
        ev.evidence = (
            f"the stream carries {len(tops)} top-level cell(s) {tops}; a "
            "submission carries exactly one")
        return
    if declared_top == _decl.NOT_DETERMINED:
        ev.evidence = (f"the top cell is {tops[0]!r} and `top_cell` was not "
                       "declared, so there is nothing to compare it against")
        return
    if tops[0] == declared_top:
        ev.verdict = PASS
        ev.evidence = f"the single top-level cell is {tops[0]!r}, as declared"
    else:
        ev.verdict = FAIL
        ev.evidence = (f"the top-level cell is {tops[0]!r}; the declaration "
                       f"names {declared_top!r}. This layout is not this "
                       "design")


def _step_size(ev: StepEvidence, geom: Optional[Dict[str, Any]],
               deliverable: Any, origin: Any, die_area: Any) -> None:
    """THE ORIGIN CHECK, and the declared-die-size check beside it."""
    if geom is None:
        ev.evidence = "the layout was not read, so its extent is unknown"
        return
    bbox = geom.get("bbox_um")
    dbu = geom.get("dbu_um")
    ev.measured = {"bbox_um": bbox, "declared_die_origin_um": origin,
                   "declared_die_area_um": die_area,
                   "deliverable": deliverable,
                   "bbox_complete": geom.get("bbox_complete"),
                   "bbox_cycles": geom.get("bbox_cycles"),
                   "bbox_missing_cells": geom.get("bbox_missing_cells")}
    if bbox is None:
        ev.evidence = ("no bounding box could be computed: the examined top "
                       "cell holds no geometry, or the database unit is "
                       "unknown")
        return
    if not geom.get("bbox_complete"):
        ev.evidence = (
            "the bounding box is INCOMPLETE — the hierarchy walk hit "
            f"cycles={geom.get('bbox_cycles')} "
            f"missing={geom.get('bbox_missing_cells')} — so the measured "
            "extent may be smaller than the real one and cannot be compared")
        return
    if deliverable == _decl.NOT_DETERMINED:
        ev.evidence = (
            f"the layout's extent is {bbox}, and `deliverable` was not "
            "declared. A DIE must start at the declared origin; a HARDMACRO "
            "need not, because its LEF declares the offset. Which rule "
            "applies is not knowable, so nothing is concluded")
        return

    problems: List[str] = []
    checked: List[str] = []

    if deliverable == _decl.DELIVERABLE_DIE:
        if origin == _decl.NOT_DETERMINED:
            ev.evidence = (
                f"the layout's lower-left is ({bbox[0]}, {bbox[1]}) um and "
                "`die_origin_um` was not declared, so there is nothing to "
                "compare it against")
            return
        if _close(bbox[0], origin[0], dbu) and _close(bbox[1], origin[1], dbu):
            checked.append(
                f"lower-left ({bbox[0]}, {bbox[1]}) um is the declared origin")
        else:
            problems.append(
                f"the layout's lower-left is ({bbox[0]}, {bbox[1]}) um; the "
                f"declaration requires ({origin[0]}, {origin[1]}) um. A die is "
                "fabricated at the coordinates it is drawn at")
    else:
        checked.append(
            "origin not checked: a HARDMACRO's geometry may sit off the cell "
            "origin because its LEF ORIGIN declares the offset")

    if die_area == _decl.NOT_DETERMINED:
        if deliverable == _decl.DELIVERABLE_DIE:
            # An unanswered `die_area_um` stops this step from reaching a PASS.
            # It must NOT stop it from reaching a FAIL: a refusal already found
            # is a fact, and discarding it because a LATER question went
            # unanswered would let one missing answer suppress a real one. That
            # is the bug this branch was written with and a test caught.
            if problems:
                ev.verdict = FAIL
                ev.evidence = ("; ".join(problems)
                               + "; `die_area_um` was additionally not "
                                 "declared, so the dimensions were not checked "
                                 "at all")
            else:
                ev.evidence = ("; ".join(checked) +
                               "; `die_area_um` was not declared, so the die "
                               "dimensions have nothing to be compared against")
            return
    else:
        want_w = die_area[2] - die_area[0]
        want_h = die_area[3] - die_area[1]
        got_w, got_h = geom["width_um"], geom["height_um"]
        if _close(got_w, want_w, dbu) and _close(got_h, want_h, dbu):
            checked.append(f"the extent is {got_w} x {got_h} um, as declared")
        else:
            problems.append(
                f"the layout measures {got_w} x {got_h} um; the declaration "
                f"pins {want_w} x {want_h} um")

    if problems:
        ev.verdict, ev.evidence = FAIL, "; ".join(problems)
    elif checked:
        ev.verdict, ev.evidence = PASS, "; ".join(checked)


def _step_zero_area(ev: StepEvidence, geom: Optional[Dict[str, Any]]) -> None:
    if geom is None:
        ev.evidence = "the layout was not read, so its polygons were not counted"
        return
    total = geom["polygon_count"]
    bad = geom["zero_area_polygon_count"]
    ev.measured = {"polygon_count": total, "zero_area_polygon_count": bad,
                   "examples": geom["zero_area_polygons"][:10]}
    if total == 0:
        # NOT a pass. Zero violations over zero polygons is an empty layout,
        # not a clean one, and the denominator is the only thing that tells
        # them apart.
        ev.evidence = ("the layout carries 0 polygons, so 0 zero-area "
                       "polygons is an empty result and not a clean one")
        return
    if bad == 0:
        ev.verdict = PASS
        ev.evidence = f"0 zero-area polygons out of {total} examined"
    else:
        ev.verdict = FAIL
        ev.evidence = (f"{bad} zero-area polygon(s) out of {total}; first: "
                       f"{geom['zero_area_polygons'][0]}")


def _step_forbidden_layers(ev: StepEvidence, layers: Optional[Dict[Any, int]],
                           forbidden: Any) -> None:
    if layers is None:
        ev.evidence = "the layout was not read, so its layers are unknown"
        return
    used = sorted(f"{l}/{d}" for (l, d) in layers)
    ev.measured = {"layers_used": used[:200],
                   "layers_used_count": len(used),
                   "declared_forbidden": forbidden}
    if forbidden == _decl.NOT_DETERMINED:
        ev.evidence = (f"the layout draws on {len(used)} layer/datatype "
                       "pair(s), and `forbidden_layers` was not declared, so "
                       "no layer can be called forbidden")
        return
    if not isinstance(forbidden, (list, tuple)):
        ev.evidence = (f"`forbidden_layers` is {type(forbidden).__name__}, "
                       "not a list of \"layer/datatype\" strings")
        return
    hits = sorted(set(str(f).strip() for f in forbidden) & set(used))
    if hits:
        ev.verdict = FAIL
        ev.evidence = (f"the layout draws on forbidden layer(s) "
                       f"{', '.join(hits)}")
    else:
        ev.verdict = PASS
        ev.evidence = (f"none of the {len(forbidden)} forbidden layer(s) "
                       f"appears among the {len(used)} in use")


# --------------------------------------------------------------------------- #
# DELEGATED steps — call the in-tree checker, report its rc. Never its rules.
# --------------------------------------------------------------------------- #
def _step_delegate(ev: StepEvidence, step: Step, project: Path,
                   runner: Runner, programs_dir: Path,
                   timeout: Optional[float],
                   seal_required: Any = None) -> None:
    d = step.delegate
    assert d is not None
    if step.step_id == "General.SealRing" and seal_required is _decl.NOT_DETERMINED:
        ev.evidence = ("`seal_ring_required` was not declared. Whether this "
                       "layout owes a seal ring is the taking party's rule, "
                       "and with no party named there is no rule to apply")
        return
    if step.step_id == "General.SealRing" and seal_required is False:
        ev.evidence = ("the declaration states no seal ring is required, so "
                       "the layout was not measured for one. Declared-away is "
                       "not the same as checked-and-clean")
        return

    prog = programs_dir / f"{d.program}.py"
    if not prog.is_file():
        ev.evidence = (f"the in-tree checker {d.program!r} does not exist in "
                       f"{programs_dir}; this step was never run. A rule of "
                       "our own invented in its place would be worse than not "
                       "knowing")
        return
    positional = (str(project) if d.positional == "project"
                  else str(project / "reports" / "phase3"))
    out = project / d.report_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(prog), positional, *d.argv_tail,
           "--json", str(out)]
    rc, stdout, stderr = runner(cmd, timeout)
    ev.returncode = rc
    tail = (stderr.strip() or stdout.strip())[-400:]
    ev.measured = {"command": cmd, "report": str(out),
                   "report_written": out.is_file()}
    if rc == 0:
        ev.verdict = PASS
        ev.evidence = f"{d.program} exited 0: {tail}" if tail else \
            f"{d.program} exited 0"
    elif rc == 1:
        ev.verdict = FAIL
        ev.evidence = f"{d.program} refused: {tail}"
    else:
        ev.evidence = (f"{d.program} exited rc={rc}, which is neither a pass "
                       f"nor a refusal: {tail}")


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(project: Path,
             layout: Optional[Path] = None,
             declaration_path: Optional[Path] = None,
             runner: Optional[Runner] = None,
             programs_dir: Optional[Path] = None,
             timeout: Optional[float] = 3600.0) -> PrecheckReport:
    """Run the general ladder and report what came back — including nothing."""
    run = runner or default_runner
    pdir = programs_dir or _HERE
    steps = [_blank(s) for s in LADDER]

    decl_path = declaration_path or (project / _decl.DECLARATION_REL)
    doc, decl_error = _decl.load(decl_path) if decl_path.is_file() else (None, None)
    refusals: List[Dict[str, Any]] = []
    if doc is None:
        # No declaration is NOT a refusal of the layout. It is the reason
        # every DECLARED step below reports NOT_DETERMINED, one by one, naming
        # the question it went without — which is a far more useful artefact
        # than a single "no declaration" line at the top.
        doc = _decl.blank_declaration()
        if decl_error:
            refusals.append({"rule": "DECLARATION_UNREADABLE",
                             "message": decl_error})
    else:
        refusals = _decl.validate(doc)
        if refusals:
            # A MALFORMED declaration cannot be read, so it must not be half
            # read. Fall back to a blank one: every DECLARED step then reports
            # NOT_DETERMINED, and the refusals say why.
            doc = _decl.blank_declaration()

    ans = doc.get("answers") or {}
    audit = _decl.audit(doc)
    deliverable = _decl.answer(doc, "deliverable")

    rep = PrecheckReport(
        project=str(project), verdict=NOT_DETERMINED, reason="",
        layouts_found=0, declaration=str(decl_path),
        declaration_present=decl_path.is_file(),
        declaration_refusals=refusals, declaration_audit=audit,
        deliverable=deliverable, required_steps=len(LADDER), steps=steps)

    hits = ([layout] if (layout and layout.is_file())
            else ([] if layout else discover_layouts(project)))
    rep.layouts_found = len(hits)
    if not hits:
        rep.reason = (
            "no finished layout found under the project (searched "
            f"{len(_LAYOUT_GLOBS)} layout location(s) below {project}); "
            "nothing was examined, so nothing was determined")
        rep.undetermined_steps = [s.step_id for s in steps]
        return rep
    chosen = hits[0]
    rep.layout = str(chosen)
    rep.layout_sha256 = _sha256(chosen)

    geom: Optional[Dict[str, Any]] = None
    layers: Optional[Dict[Any, int]] = None
    read_error: Optional[str] = None
    try:
        lay = _geom.read_layout(chosen)
        declared_top = _decl.answer(doc, "top_cell")
        top = (declared_top if declared_top != _decl.NOT_DETERMINED
               and declared_top in lay.cells else None)
        geom = _geom.summarise(lay, top)
        layers = _geom.layers_used(lay)
        rep.geometry = geom
    except _geom.GdsError as exc:
        read_error = str(exc)
        rep.geometry = {"read_error": read_error}

    by_id = {s.step_id: s for s in steps}
    for step in LADDER:
        ev = by_id[step.step_id]
        if step.step_id == "KLayout.ReadLayout":
            _step_read_layout(ev, geom, read_error)
        elif step.step_id == "General.DatabaseUnit":
            _step_database_unit(ev, geom, _decl.answer(doc, "database_unit_um"))
        elif step.step_id == "KLayout.CheckTopLevel":
            _step_top_level(ev, geom, _decl.answer(doc, "top_cell"))
        elif step.step_id == "KLayout.CheckSize":
            _step_size(ev, geom, deliverable,
                       _decl.answer(doc, "die_origin_um"),
                       _decl.answer(doc, "die_area_um"))
        elif step.step_id == "Checker.KLayoutZeroAreaPolygons":
            _step_zero_area(ev, geom)
        elif step.step_id == "General.ForbiddenLayers":
            _step_forbidden_layers(
                ev, layers, _decl.answer(doc, _decl.FORBIDDEN_LAYERS_KEY))
        elif step.delegate is not None:
            seal = ans.get("seal_ring_required")
            _step_delegate(ev, step, project, run, pdir, timeout,
                           seal_required=(seal if _decl.is_answered(seal)
                                          else _decl.NOT_DETERMINED))

    with_evidence = sum(1 for s in steps if s.verdict != NOT_DETERMINED)
    failed = [s.step_id for s in steps if s.verdict == FAIL]
    undet = [s.step_id for s in steps if s.verdict == NOT_DETERMINED]
    rep.steps_with_evidence = with_evidence
    rep.failed_steps = failed
    rep.undetermined_steps = undet

    if failed:
        rep.verdict = FAIL
        rep.reason = ("the general precheck refused: " + ", ".join(failed)
                      + " — each refusal is quoted from the measurement or the "
                        "checker that produced it")
    elif undet:
        rep.verdict = NOT_DETERMINED
        rep.reason = ("ladder step(s) produced no verdict: "
                      + ", ".join(undet)
                      + ". A step that could not be evaluated is not a pass"
                      + (f" ({audit['unanswered']} of "
                         f"{audit['questions_total']} declaration question(s) "
                         "unanswered)" if audit["unanswered"] else ""))
    else:
        rep.verdict = PASS
        rep.reason = (f"every one of the {len(LADDER)} general ladder step(s) "
                      "carries passing evidence; the "
                      f"{len(OPERATOR_SPECIFIC_EXCLUDED)} operator-specific "
                      "step(s) are excluded and named")
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="The general tape-out precheck, for a design with no "
                    "shuttle operator. PASS only when every general ladder "
                    "step carries passing evidence; NOT_DETERMINED whenever a "
                    "question was left unanswered or a checker could not run "
                    "(rc 1, same as a refusal, because a silence credited as "
                    "a pass is the defect this gate exists for).")
    p.add_argument("project", type=Path,
                   help="Project directory holding the finished layout.")
    p.add_argument("--gds", type=Path, default=None, dest="layout",
                   help="Explicit layout file; default is discovered under "
                        "the project.")
    p.add_argument("--declaration", type=Path, default=None,
                   help="The tape-out declaration (default: <project>/"
                        + _decl.DECLARATION_REL + ").")
    p.add_argument("--timeout", type=float, default=3600.0,
                   help="Seconds to allow each delegated checker "
                        "(default: %(default)s).")
    p.add_argument("--json", type=Path, dest="out_json", default=None,
                   help="Write the verdict JSON here (default: <project>/"
                        + PRECHECK_ARTEFACT + ").")
    args = p.parse_args(argv)

    if not args.project.is_dir():
        print(f"ERROR: project directory not found: {args.project}",
              file=sys.stderr)
        return 2

    rep = evaluate(project=args.project, layout=args.layout,
                   declaration_path=args.declaration, timeout=args.timeout)
    payload = rep.as_dict()
    out_json = args.out_json or (args.project / PRECHECK_ARTEFACT)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_json, json.dumps(payload, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(rep.summary_line())
    return 0 if rep.verdict == PASS else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
