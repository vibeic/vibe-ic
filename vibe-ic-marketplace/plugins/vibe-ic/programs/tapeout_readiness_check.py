#!/usr/bin/env python3
"""tapeout_readiness_check.py — the EXTERNAL refusal interface, pointed at a
shuttle that still exists.

ENFORCEMENT: advisory here — this gate is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; no one-shot runner invokes
it inline at all. It runs as the SECOND ARM of step 37.5ic, invoked by
``tapeout_precheck`` whenever the PDK ships a shuttle precheck and that
operator's template was fetched; ``tapeout_precheck``'s rc IS that step's
verdict, so a refusal here refuses the step. "advisory" names the RUNNER channel
it is absent from, not a verdict this gate cannot reach. Declared because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
enforcement decision nobody made; wiring it into the runner would change what a
real run blocks on, which is the flow owner's call and is recorded, not taken
here. Kept in the first 4 kB: `declared_intent` reads only `text[:4000]`.

WHY THIS EXISTS (vibe-ic#1744)
==============================
Every other gate in this tree we wrote. A gate we wrote can be made to pass by
editing it. There is exactly ONE interface where an outside party's refusal is
the verdict — the shuttle precheck — and until this program it was aimed at
`efabless/mpw_precheck`, whose operator ceased operating in 2025.

Three programs deep, all of it pointed there:

    mpw_precheck_driver           invokes efabless/mpw_precheck in its container
    mpw_precheck_result_gate      parses that run directory into a verdict
    caravel_integration_runner    step_c1_run_precheck emits the command hint

None of those is wrong about what it does. They are pointed at a counterparty
that no longer answers, and a counterparty that no longer answers cannot refuse.

WHAT WAS MEASURED, NOT ASSUMED
------------------------------
`tapeout_checklist_gen` is, by its own docstring, a DERIVED-VIEW generator that
"does NOT run any EDA tool itself". Its `mpw_precheck` row is ADVISORY and
presence-globbed, and its verdict is computed from BLOCKER rows alone. Measured
on a project carrying every blocker artefact and NO shuttle evidence of any
kind, it emits:

    {"verdict": "READY_FOR_TAPEOUT", "blockers_present": 10, "blockers_total": 10}

rc 0. `signoff_audit.py` — the authority behind `tapeout_signoff_check`, the
Step-36 gate — contains no reference to a precheck, a shuttle, or an external
submission at all. So the dead vendor's silence and a clean shuttle run are the
same output, which is this repo's recurring shape one more time: an empty result
indistinguishable from a clean one.

This program is the missing half. It does not decide whether the layout is
submittable — it ASKS SOMETHING ELSE and reports what came back, including
"nothing came back".

IT WRAPS. IT DOES NOT REIMPLEMENT.
==================================
The live open-MPW path is wafer.space, whose runs require a layout to pass
`gf180mcu-precheck` (https://github.com/wafer-space/gf180mcu-precheck) before a
submission is accepted. That tool is somebody else's, it is maintained by the
party that takes the money, and THAT IS THE POINT. A reimplementation of its
ladder inside this tree would be ours again, would be editable by us, and could
drift into passing — which is exactly the property that makes every other gate
here weaker than this one.

So this program contains NO slot dimension, NO density window, NO DRC rule and
NO pad-mask geometry. It resolves the upstream tool, runs it unmodified, and
reads the run directory the tool itself wrote. The ladder below is an ORDERING
and an EVIDENCE MAP, not a set of rules: it names the step ids the upstream flow
emits so the report can be stated in submission-failure order and so a step that
produced no evidence can be named as such.

THE MEASUREMENT THAT SETTLED IT (2026-08-18)
===========================================
#1744 asked for one thing above argument: run the live precheck against a
layout this project has already published, and see what comes back. Done, with
`ghcr.io/wafer-space/gf180mcu-precheck:latest` against
`ic/spm/v1.9.96_gf180mcuD/phase3/stage4/gds/chip_top.gds`
(sha256 fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255).

REFUSED, at ladder step 3 of 16:

    [Error]: Layer 'GUARD_RING_MK' is not used. wafers.space requires a seal
    ring (guard ring) around the die.

That is the gap the issue predicted, from the counterparty's own tool rather
than from us: a flow that has only ever built a core has no seal ring, and the
refusal lands on the submission FRAME — before density, before antenna, before
either DRC deck. "Are we submittable" is therefore answered, and the answer is
no. The run directory is kept verbatim at
`tests/fixtures/shuttle_precheck_refusal/` so the parser is tested against what
the tool actually emits.

The gap is also RECOMPUTED, never asserted: `resolve_in_tree_coverage` resolves
each ladder step against the real `programs/` directory, so the claim "this tree
has no submission-frame check" is re-derived on every run and stops being true
the moment somebody lands one.

SUBMISSION-FAILURE ORDER
========================
The ladder is stated in the order a real submission hits it, which is the
upstream flow's own step order — not alphabetical, not by severity, not by how
interesting the check is. A user who reads this report top-to-bottom hits the
refusals in the sequence the counterparty would hit them, so the first FAIL is
the first thing that would actually stop the submission.

THE RETIRED PATH IS KEPT, AND IT IS `NOT_DETERMINED`
====================================================
The Efabless entry is NOT deleted. Deleting it would erase the record that this
tree once had an external interface and would make the three programs above look
orphaned rather than retired. It is marked RETIRED, and a RETIRED shuttle's
verdict is `NOT_DETERMINED` — never PASS, and never FAIL either. FAIL would be a
lie in the other direction: the vendor did not refuse this layout, the vendor
stopped answering. A dead vendor's silence must not read as a clean run, and it
must not read as a rejection.

THE THREE VERDICTS, AND WHY THERE ARE ONLY THREE
================================================
    PASS            the tool RAN and every ladder step it ran carries explicit
                    passing evidence in the tool's own run directory.
    FAIL            the tool RAN and a ladder step refused. The refusal is the
                    counterparty's, quoted from its own artefact.
    NOT_DETERMINED  no verdict was obtained: the shuttle is retired, the tool
                    could not be resolved, no layout was found, the run produced
                    no usable evidence, or a required ladder step is missing
                    from the evidence. "NOT DETERMINED" beats a guess.

There is deliberately no fourth tier. `SKIPPED`, `N/A` and `BLOCKED` all read as
"nothing to worry about here" in an aggregate, and the whole point of this gate
is that nothing-to-worry-about is precisely what we are not entitled to say.

EXIT CODES, AND THE ONE THAT IS DELIBERATELY NOT USED
=====================================================
    0  PASS
    1  FAIL **and** NOT_DETERMINED — every non-pass
    2  usage / unreadable input

rc 3 is NOT used: `flow_compliance_check` reads rc 3 as PASS_WITH_WAIVERS and
promotes the step to WAIVED-DEFERRED. rc 2 is NOT used for NOT_DETERMINED
either: this repo credits a rc-2 `VACUOUS_PASS` as a pass repo-wide. Either
would route the exact state this program exists to publish — "we did not find
out" — straight back into a green light. The distinction between FAIL and
NOT_DETERMINED lives in the `verdict` field of the JSON, where an aggregator
must read it deliberately rather than infer it from a number that already means
something else here.

DENOMINATOR
===========
Every verdict line states how many ladder steps were required, how many carried
evidence, and which layout was examined. A run that examined no layout says
`layouts_found=0` and refuses (rc 1) rather than passing over an empty set.

chip-AGNOSTIC: the shuttle registry names PUBLIC open-MPW programmes and their
OPEN PDKs — the same class of name `pdk_registry.json` already carries. No
commercial SKU, no chip codename, no project literal appears in any decision
rule. The layout path, top cell, slot and id are all parameters.

USAGE
-----
    python3 tapeout_readiness_check.py <project>
        [--shuttle wafer_space_gf180mcu]      # or efabless_open_mpw (RETIRED)
        [--gds PATH]        # default: discovered under the project
        [--top NAME] [--slot 1x1] [--cob] [--id HEX]
        [--image IMG] [--precheck-src DIR] [--pull]
        [--rundir DIR] [--timeout SECONDS] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import plugin_manifest_discovery as _pmd  # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402  vibe-ic#1082 (helper from PR #1094)

try:  # sibling module; programs/ is on sys.path when run as a script
    import _docker_memory as _dmem
except ImportError:  # pragma: no cover - packaged/flattened layouts
    from . import _docker_memory as _dmem  # type: ignore

ATTRIBUTION = "tapeout_readiness_check"

#: The only three verdicts. See "THE THREE VERDICTS" above.
PASS = "PASS"
FAIL = "FAIL"
NOT_DETERMINED = "NOT_DETERMINED"

#: Shuttle lifecycle. RETIRED is kept in the registry ON PURPOSE (#1744).
LIVE = "LIVE"
RETIRED = "RETIRED"


# --------------------------------------------------------------------------- #
# The shuttle registry — WHO refuses, and what their ladder is called.
#
# `ladder` is an ORDERING + EVIDENCE MAP in SUBMISSION-FAILURE ORDER, taken from
# the upstream flow's own step sequence. It carries NO check logic: no slot
# dimension, no density window, no DRC rule. `covered_by` names the vibe-ic
# program (if any) that examines the SAME property from inside this tree — it is
# resolved against the real programs/ directory at run time, never asserted, so
# the "we have no check of our own for this" claim cannot go stale.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LadderStep:
    step_id: str          # the upstream tool's own step id
    label: str            # human label for the report
    refuses_on: str       # what the counterparty refuses for, in one clause
    covered_by: Tuple[str, ...] = ()   # candidate in-tree counterpart programs
    cob_only: bool = False             # only in the ladder when --cob is set


@dataclass(frozen=True)
class Shuttle:
    shuttle_id: str
    status: str                      # LIVE / RETIRED
    tool: str                        # the external tool this WRAPS
    upstream: str                    # where that tool lives
    default_image: str
    entrypoint: Tuple[str, ...]      # argv prefix inside the container
    ladder: Tuple[LadderStep, ...]
    #: WHICH PDK THIS SHUTTLE'S PRECHECK IS FOR — the FAMILY name, not a
    #: variant. It is the answer to "does this PDK ship a shuttle precheck",
    #: and it was previously written down NOWHERE: the fact lived only inside
    #: the `shuttle_id` string and the prose. A consumer that has a PDK and
    #: needs to know whether a second, external authority exists for it had to
    #: parse an id, so this is stated as a field.
    #:
    #: NOT duplicated into `pdk_registry.json`. That registry answers "how do I
    #: build on this PDK" (site, decks, cells); this one answers "who else
    #: refuses submissions on it". One fact, one authority — a copy in the
    #: other file would be a second place to forget.
    pdk: str = ""
    note: str = ""
    retired_reason: str = ""


# The live path. Ladder order is `PrecheckFlow.Steps` from the upstream tool,
# reduced to the steps that can REFUSE a submission. `ReadLayout` IS one of them
# — an unreadable or unsupported layout is a refusal — while `Render` and
# `WriteLayout` only move data and are left out. The paired raw runner steps
# (`KLayout.Density`, `KLayout.Antenna`, `KLayout.DRC`) are left out too: their
# `Checker.*` siblings are what stop the flow, and they are here. The cost of
# that choice is stated rather than hidden — if a raw runner crashes, its
# `Checker.*` sibling never gets a directory and this gate reports that step
# NOT_DETERMINED instead of naming a FAIL. That under-reports in the SAFE
# direction: the overall verdict is still not a PASS.
_WAFER_SPACE_GF180MCU = Shuttle(
    shuttle_id="wafer_space_gf180mcu",
    status=LIVE,
    tool="gf180mcu-precheck",
    upstream="https://github.com/wafer-space/gf180mcu-precheck",
    default_image="ghcr.io/wafer-space/gf180mcu-precheck:latest",
    pdk="gf180mcu",
    # The upstream image's own documented invocation (its Dockerfile carries
    # this as org.opencontainers.image.usage); the entrypoint is a nix dev-shell
    # wrapper, so the argv is the bare `python precheck.py …`.
    entrypoint=("python", "precheck.py"),
    ladder=(
        LadderStep(
            "KLayout.ReadLayout", "Read the Layout",
            "the layout file cannot be read in a supported format",
            covered_by=("gds_substance_check", "chip_gds_canonical_real_file_check",
                        "gds_size_check")),
        LadderStep(
            "KLayout.CheckTopLevel", "Check Top-Level Name",
            "more than one top-level cell, or its name is not the declared top",
            covered_by=("gds_topcell_name_check",)),
        LadderStep(
            "KLayout.CheckSize", "Check Slot Size",
            "origin is not at (0,0), or the die dimensions do not match the "
            "purchased slot",
            # `gds_size_check` is a FILE-size gate (missing / empty / bad header
            # / below a byte threshold). It is NOT a die-DIMENSION gate and is
            # deliberately not claimed here: naming it would report coverage this
            # tree does not have.
            #
            # `general_precheck` IS claimed, and the claim is the point of
            # recomputing this: it examines the SAME property — the flattened
            # bounding box's lower-left against a declared origin, and its
            # extent against a declared die area — for a design with no
            # operator. Until it landed this step recomputed as UNCOVERED, and
            # the artefact that proves the gap was real is published:
            # `u_hawaii_adc` sky130A streams a `phase3/stage4/gds/ldo.gds`
            # whose flattened box starts at (-4.5, -223.305) um, byte-identical
            # to that design's own analog hardmacro.
            covered_by=("general_precheck", "die_slot_dimension_check",
                        "seal_ring_check", "frame_dimension_check")),
        LadderStep(
            "KLayout.CheckPadMask", "Check Pad Mask",
            "the pad openings do not match the pad mask for the slot",
            # `pad_side_constraint_check` verifies pin SIDES against an L-doc
            # table; the shuttle checks pad OPENING GEOMETRY against its own pad
            # mask. Different property, so it is not claimed.
            covered_by=("pad_ring_mask_check", "padframe_check"),
            cob_only=True),
        LadderStep(
            "KLayout.GenerateID", "Generate ID",
            "the frame marker / id cells are absent, duplicated, or not at the "
            "template location",
            covered_by=("frame_marker_check", "die_id_marker_check")),
        LadderStep(
            "Checker.KLayoutDensity", "Density Checker",
            "layer density outside the accepted window",
            covered_by=("metal_layer_density_check",
                        "metal_fill_density_check")),
        LadderStep(
            "Checker.KLayoutZeroAreaPolygons", "Zero Area Polygons Checker",
            "the layout contains zero-area polygons",
            # `general_precheck` counts them EXACTLY, from the integer shoelace
            # area of every BOUNDARY/BOX in the stream — no tolerance, because
            # a GDSII coordinate is an integer and a tolerance would be a
            # threshold of ours that somebody could widen.
            covered_by=("general_precheck", "zero_area_polygon_check")),
        LadderStep(
            "Checker.KLayoutAntenna", "Antenna Checker",
            "antenna ratio violations",
            covered_by=("antenna_report_check",)),
        LadderStep(
            "Checker.MagicDRC", "Magic DRC Checker",
            "Magic DRC violations",
            covered_by=("drc_report_check", "drc_vacuous_pass_check")),
        LadderStep(
            "Checker.KLayoutDRC", "KLayout DRC Checker",
            "KLayout DRC violations",
            covered_by=("drc_report_check",)),
    ),
    note="wafer.space open-MPW; the precheck is a LibreLane flow the shuttle "
         "operator maintains.",
)


# The retired path. KEPT, marked, and never a PASS. Its ladder is the mpw ladder
# the two surviving programs already model, restated here only so the report can
# name what is no longer being asked.
_EFABLESS_OPEN_MPW = Shuttle(
    shuttle_id="efabless_open_mpw",
    status=RETIRED,
    tool="mpw_precheck",
    upstream="https://github.com/efabless/mpw_precheck",
    default_image="efabless/mpw_precheck:latest",
    pdk="sky130",
    entrypoint=("python3", "mpw_precheck.py"),
    ladder=(
        LadderStep("license", "License", "licence files missing or wrong"),
        LadderStep("makefile", "Makefile", "the submission Makefile is not the "
                                           "expected one"),
        LadderStep("default", "Default", "default project content left in place"),
        LadderStep("documentation", "Documentation", "required documentation "
                                                     "missing"),
        LadderStep("consistency", "Consistency", "netlist/layout inconsistency"),
        LadderStep("gpio_defines", "GPIO-Defines", "gpio defines do not match"),
        LadderStep("xor", "XOR", "XOR against the golden wrapper is non-empty"),
        LadderStep("magic_drc", "Magic DRC", "Magic DRC violations"),
        LadderStep("klayout_feol", "KLayout FEOL", "FEOL rule violations"),
        LadderStep("klayout_beol", "KLayout BEOL", "BEOL rule violations"),
        LadderStep("klayout_offgrid", "KLayout Offgrid", "off-grid geometry"),
        LadderStep("lvs", "LVS", "layout does not match the netlist"),
        LadderStep("oeb", "OEB", "output-enable bar convention violated"),
    ),
    retired_reason=(
        "the shuttle operator ceased operating in 2025. The counterparty no "
        "longer accepts or refuses submissions, so no run of this ladder can "
        "produce an external verdict. The path is kept — not deleted — so the "
        "three programs still pointed at it (mpw_precheck_driver, "
        "mpw_precheck_result_gate, caravel_integration_runner.step_c1_run_"
        "precheck) read as RETIRED rather than orphaned."),
    note="Efabless / chipIgnite open-MPW. RETIRED — see retired_reason.",
)

SHUTTLES: Dict[str, Shuttle] = {
    s.shuttle_id: s for s in (_WAFER_SPACE_GF180MCU, _EFABLESS_OPEN_MPW)
}

#: The shuttle a bare invocation asks. The LIVE one, by construction.
DEFAULT_SHUTTLE = _WAFER_SPACE_GF180MCU.shuttle_id


# --------------------------------------------------------------------------- #
# "Does this PDK ship a shuttle precheck?" — asked of the registry above.
#
# WHY THIS LIVES HERE AND NOT IN THE CALLER. The registry IS the answer, and a
# caller that re-derived it from the `shuttle_id` string would be a second copy
# of the mapping with nothing tying the two together.
#
# A RETIRED SHUTTLE IS NOT AN ANSWER OF YES. The whole value of this arm is
# that the verdict is somebody else's; a counterparty that stopped answering
# cannot refuse, so it is not a second authority, and demanding a run from one
# that no longer exists would make every design on that PDK permanently
# unpassable. `shuttle_for_pdk` therefore resolves LIVE entries only, and
# `retired_shuttles_for_pdk` exists beside it so a report can still NAME the
# retired one — "this PDK once had an external bar and no longer does" is a
# fact a reader is entitled to, and it is not the same fact as "this PDK never
# had one".
# --------------------------------------------------------------------------- #
def shuttle_for_pdk(pdk_name: str) -> Optional[Shuttle]:
    """The LIVE shuttle whose precheck covers `pdk_name`, or None.

    Matching is by the SAME identity rule the tree already uses to decide
    whether a declared PDK target and a library name are the same process —
    `declared_pdk_is_the_pdk_used_check.shares_identity` — so a declaration of
    `gf180mcuD` and a registry entry of `gf180mcu` resolve to each other and an
    interior fragment does not. Re-implementing the comparison here would be a
    second rule that could drift into matching more, or less, than the gate
    that already owns the question.

    Returns None for an empty/unknown name. None means "this registry names no
    live shuttle for it" — it does NOT mean "no PDK was determined"; the caller
    must keep those two apart, because one is a legitimate missing arm and the
    other is a thing nobody looked up.
    """
    return _first_matching(pdk_name, LIVE)


def retired_shuttles_for_pdk(pdk_name: str) -> Tuple[Shuttle, ...]:
    """Every RETIRED shuttle whose precheck once covered `pdk_name`.

    Reported, never run. See the block comment above.
    """
    matches = tuple(sh for sh in SHUTTLES.values()
                    if sh.status == RETIRED and _pdk_matches(pdk_name, sh))
    return matches


def _first_matching(pdk_name: str, status: str) -> Optional[Shuttle]:
    for sh in SHUTTLES.values():
        if sh.status == status and _pdk_matches(pdk_name, sh):
            return sh
    return None


def _pdk_matches(pdk_name: str, shuttle: Shuttle) -> bool:
    if not (pdk_name or "").strip() or not shuttle.pdk:
        return False
    try:
        import declared_pdk_is_the_pdk_used_check as _pdkid
    except ImportError:                      # pragma: no cover - defensive
        # NEVER silently fall back to a looser rule. A comparison we could not
        # load is a comparison that did not happen, and reporting "no shuttle"
        # from it would be exactly the silence this file exists to refuse. Exact
        # equality is the STRICT direction, so the worst it can do is under-claim
        # an arm — which the caller reports as NOT_DETERMINED, never as a pass.
        return pdk_name.strip().lower() == shuttle.pdk.strip().lower()
    return _pdkid.shares_identity(_pdkid.tokens(pdk_name), shuttle.pdk)

#: Where a finished layout lives in this repo's project layout. Ordered; the
#: first glob that matches anything wins. Nothing here is chip-specific.
_LAYOUT_GLOBS: Tuple[str, ...] = (
    "phase3/stage4/gds/*.gds",
    "phase3/stage4/gds/*.gds.gz",
    "phase3/stage4/gds/*.oas",
    "**/stage4/gds/*.gds",
)

#: Where this gate's verdict belongs, and where `tapeout_checklist_gen` looks
#: for it. Named in ONE place so the two halves cannot drift into a row that
#: watches a path nothing writes.
READINESS_ARTEFACT = "reports/audit/tapeout_readiness.json"

#: Container-side mount points. Two binds, because the layout and the run
#: directory do not share a host parent in the general case.
_C_DESIGN = "/data/design"
_C_RUNDIR = "/data/rundir"

#: Bound each log read so a pathological tool dump cannot exhaust memory.
_MAX_LOG_BYTES = 8 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class StepEvidence:
    step_id: str
    label: str
    order: int                  # 1-based position in submission-failure order
    verdict: str                # PASS / FAIL / NOT_DETERMINED
    refuses_on: str
    evidence: str = ""          # the tool's own line / artefact path
    source: Optional[str] = None
    covered_in_tree_by: Optional[str] = None   # resolved in-tree counterpart
    covered: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReadinessReport:
    project: str
    shuttle: str
    shuttle_status: str
    tool: str
    upstream: str
    verdict: str
    reason: str
    layouts_found: int
    layout: Optional[str] = None
    required_steps: int = 0
    steps_with_evidence: int = 0
    steps: List[StepEvidence] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    undetermined_steps: List[str] = field(default_factory=list)
    uncovered_in_tree: List[str] = field(default_factory=list)
    image: str = ""
    rundir: Optional[str] = None
    returncode: Optional[int] = None
    command: List[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["steps"] = [s.as_dict() for s in self.steps]
        d["emitted_by"] = _pmd.emitted_by(ATTRIBUTION)
        return d

    def summary_line(self) -> str:
        """One line that ALWAYS states the denominator (#447)."""
        return (
            f"{self.verdict}: shuttle={self.shuttle} ({self.shuttle_status}) "
            f"tool={self.tool} — layouts_found={self.layouts_found}, "
            f"ladder_steps_required={self.required_steps}, "
            f"steps_with_evidence={self.steps_with_evidence}, "
            f"failed={len(self.failed_steps)}, "
            f"undetermined={len(self.undetermined_steps)} — {self.reason}"
        )


# Injectable seams so the orchestration is testable with NO live image.
ImageResolver = Callable[[str, bool], Optional[str]]
Runner = Callable[[List[str], Optional[float]], Tuple[int, str, str]]


# --------------------------------------------------------------------------- #
# Live seam implementations
# --------------------------------------------------------------------------- #
def default_image_resolver(image: str, allow_pull: bool,
                           docker_bin: str = "docker") -> Optional[str]:
    """Return `image` when it is locally available (optionally pulling), else None.

    Any docker error — daemon down, docker absent, pull refused — resolves to
    None, and the caller then reports NOT_DETERMINED. It never guesses that an
    unreachable tool would have passed."""
    if not shutil.which(docker_bin):
        return None
    try:
        q = subprocess.run([docker_bin, "images", "-q", image],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if q.returncode == 0 and q.stdout.strip():
        return image
    if not allow_pull:
        return None
    try:
        p = subprocess.run([docker_bin, "pull", image],
                           capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError):
        return None
    return image if p.returncode == 0 else None


def default_runner(cmd: List[str],
                   timeout: Optional[float]) -> Tuple[int, str, str]:
    """Run `cmd`, returning (returncode, stdout, stderr).

    A timeout surfaces as rc 124 with the partial output; the caller still reads
    the run directory, because a precheck that logged real refusals before a late
    timeout has produced real evidence."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as e:
        out, err = e.stdout or "", e.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return 124, out, err + "\n[timeout]"
    except (OSError, subprocess.SubprocessError) as e:  # noqa: PERF203
        return 125, "", f"[runner error] {e!r}"


# --------------------------------------------------------------------------- #
# Layout discovery
# --------------------------------------------------------------------------- #
def discover_layouts(project: Path) -> List[Path]:
    """Every finished layout under `project`, in a stable order.

    Returns [] for a project that has none — which is a refusal (rc 1), not a
    pass over an empty set (#564)."""
    for pattern in _LAYOUT_GLOBS:
        hits = sorted(p for p in project.glob(pattern) if p.is_file())
        if hits:
            return hits
    return []


# --------------------------------------------------------------------------- #
# In-tree coverage — RESOLVED, never asserted
# --------------------------------------------------------------------------- #
def resolve_in_tree_coverage(step: LadderStep,
                             programs_dir: Optional[Path] = None
                             ) -> Optional[str]:
    """Name the vibe-ic program that examines the same property, or None.

    Resolved against the real programs/ directory so a registry entry naming a
    program that does not exist reports NO coverage rather than a comforting
    name. This is what turns "we have no submission-frame check" from an opinion
    into something the report recomputes on every run."""
    pdir = programs_dir or _HERE
    for cand in step.covered_by:
        if (pdir / f"{cand}.py").is_file():
            return cand
    return None


# --------------------------------------------------------------------------- #
# Command construction — the upstream tool's OWN documented invocation
# --------------------------------------------------------------------------- #
def build_command(
    shuttle: Shuttle,
    image: str,
    layout: Path,
    rundir: Path,
    top: str,
    slot: str,
    cob: bool,
    die_id: str,
    docker_bin: str = "docker",
) -> List[str]:
    """Assemble the container argv for the LIVE shuttle's precheck.

    Shape MEASURED against the real image on 2026-08-18, not assumed — three
    plausible variants were tried first and each failed in its own way, and the
    failures are the reason this function looks like it does:

      * `-u $(id -u):$(id -g)` — the upstream image is nix-based and the
        entrypoint is a nix dev-shell. An unknown uid has no home, so nix exits
        `cannot determine user's home directory`; supplying `-e HOME=…` then
        gets `opening lock file "/nix/var/nix/db/big-lock": Permission denied`.
        Upstream's own documented invocation passes no `-u`, and neither does
        this. CONSEQUENCE, stated because it is a real one: the run directory
        comes back owned by the container user.
      * `-w <hostpath>` — the entrypoint resolves the flake from the working
        directory, so overriding it gets `unable to find a flake before
        encountering filesystem boundary`. The image's own WORKDIR is correct
        and is left alone; `precheck.py` is therefore named relatively, exactly
        as the image documents on itself.
      * one bind of a common host parent — the layout and the run directory do
        not share one in the general case. Two binds do not need them to.

    `--network=none` is upstream's own documented flag and is kept: a check that
    can reach the network while it runs is a check that can be told what to say.
    """
    layout = layout.resolve()
    rundir = rundir.resolve()
    cmd: List[str] = [docker_bin, "run", "--rm", "--network=none",
                      *_dmem.docker_memory_flags()]
    cmd += ["-v", f"{layout.parent}:{_C_DESIGN}:ro"]
    cmd += ["-v", f"{rundir}:{_C_RUNDIR}"]
    cmd += [image]
    cmd += list(shuttle.entrypoint)
    cmd += ["--input", f"{_C_DESIGN}/{layout.name}", "--dir", _C_RUNDIR]
    if top:
        cmd += ["--top", top]
    if slot:
        cmd += ["--slot", slot]
    if die_id:
        cmd += ["--id", die_id]
    if cob:
        cmd += ["--cob"]
    return cmd


def _read_bounded(p: Path) -> str:
    try:
        if p.stat().st_size > _MAX_LOG_BYTES:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                return fh.read(_MAX_LOG_BYTES)
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_run_evidence(rundir: Path) -> Dict[str, Tuple[str, str, str]]:
    """Map step slug -> (verdict, source, evidence), read from the tool's own run.

    THE DISCRIMINATOR IS `state_out.json`, AND IT WAS MEASURED
    ---------------------------------------------------------
    The upstream precheck is a LibreLane SequentialFlow. Every step it STARTS
    gets a `<NN>-<slug>/` directory containing `config.json`, `state_in.json`
    and its own `<slug>.log`. A step that COMPLETES additionally writes
    `state_out.json` (and `runtime.txt`); the step the flow dies in writes
    neither. Observed on a real refusing run: `01-klayout-readlayout` and
    `02-klayout-checktoplevel` both carry `state_out.json`, and
    `03-klayout-checksize` — the step that refused — does not.

    So: directory + `state_out.json` = the counterparty ran it and moved on;
    directory without it = the counterparty stopped here; no directory at all =
    it never got that far, which is NOT_DETERMINED and never a pass.

    Deliberately NOT keyed on scraping the log for the word "error". The step
    logs are tool-specific free text, a scraper over them is a rule of ours
    about somebody else's output, and a scraper that misses a new phrasing fails
    OPEN — it would report a clean pass for a refusal it did not recognise. The
    structural signal cannot fail that way: an unrecognised refusal still leaves
    the step directory without a `state_out.json`. The log text is quoted as
    EVIDENCE, never used to decide.
    """
    found: Dict[str, Tuple[str, str, str]] = {}
    for run_root in _run_roots(rundir):
        run_error = _read_bounded(run_root / "error.log").strip()
        try:
            kids = sorted(d for d in run_root.iterdir()
                          if d.is_dir() and _numbered_step_dir(d.name))
        except OSError:
            continue
        for d in kids:
            _, _, slug = d.name.partition("-")
            key = _flat(slug)
            completed = (d / "state_out.json").is_file()
            step_log = d / f"{slug}.log"
            text = _read_bounded(step_log).strip() if step_log.is_file() else ""
            if completed:
                found[key] = (PASS, str(d.name), text[-400:])
            else:
                found[key] = (FAIL, str(step_log.name if step_log.is_file()
                                        else d.name),
                              (text or run_error)[-400:])
    return found


def _run_roots(rundir: Path) -> List[Path]:
    """Every plausible run root under `rundir`, newest last.

    `--dir X` makes the tool write `X/runs/<tag>/`; a caller who pointed at the
    tagged directory itself is also tolerated, because which one is handed here
    depends on `--dir` / `--run-tag`."""
    if not rundir.is_dir():
        return []
    roots: List[Path] = []
    runs = rundir / "runs"
    if runs.is_dir():
        roots.extend(sorted(d for d in runs.iterdir() if d.is_dir()))
    roots.append(rundir)
    return roots


def _numbered_step_dir(name: str) -> bool:
    """`03-klayout-checksize` style: digits, a dash, then a slug."""
    head, _, tail = name.partition("-")
    return head.isdigit() and bool(tail)


def _slug(step_id: str) -> str:
    """The upstream directory slug for a step id.

    LibreLane lowercases the id and drops the dot, so `KLayout.CheckSize`
    becomes `klayout-checksize` and `Checker.MagicDRC` becomes
    `checker-magicdrc`. Matching is done on the alphanumerics only, so a
    separator change upstream degrades that step to NOT_DETERMINED — the safe
    direction — rather than to a silent pass."""
    return step_id.lower().replace(".", "-").replace("_", "-")


def _flat(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(
    project: Path,
    shuttle_id: str = DEFAULT_SHUTTLE,
    layout: Optional[Path] = None,
    top: str = "",
    slot: str = "1x1",
    cob: bool = False,
    die_id: str = "",
    image: str = "",
    rundir: Optional[Path] = None,
    timeout: Optional[float] = 7200.0,
    allow_pull: bool = False,
    image_resolver: Optional[ImageResolver] = None,
    runner: Optional[Runner] = None,
    docker_bin: str = "docker",
    programs_dir: Optional[Path] = None,
) -> ReadinessReport:
    """Ask the shuttle, and report what came back — including nothing."""
    shuttle = SHUTTLES.get(shuttle_id)
    if shuttle is None:
        known = ", ".join(sorted(SHUTTLES))
        return ReadinessReport(
            project=str(project), shuttle=shuttle_id, shuttle_status="UNKNOWN",
            tool="", upstream="", verdict=NOT_DETERMINED,
            reason=f"unknown shuttle '{shuttle_id}'; known shuttles: {known}",
            layouts_found=0)

    ladder = tuple(s for s in shuttle.ladder if cob or not s.cob_only)
    steps = _blank_steps(ladder, programs_dir)
    uncovered = [s.step_id for s in steps if not s.covered]

    def _report(verdict: str, reason: str, **kw: Any) -> ReadinessReport:
        rep = ReadinessReport(
            project=str(project), shuttle=shuttle.shuttle_id,
            shuttle_status=shuttle.status, tool=shuttle.tool,
            upstream=shuttle.upstream, verdict=verdict, reason=reason,
            required_steps=len(ladder), steps=steps,
            uncovered_in_tree=uncovered, **kw)
        return rep

    # (1) A RETIRED shuttle can never produce an external verdict. Not a PASS,
    #     and not a FAIL either — the vendor did not refuse, the vendor stopped.
    if shuttle.status == RETIRED:
        # NAME WHAT WAS UNSUPPORTED, the way the unreachable-tool branch below
        # already names the image. LibreLane's own unsupported-configuration
        # decline (`KLayout.SealRing`, steps/klayout.py:933) states the unset
        # variable AND the PDK in one sentence, because a decline that says
        # only "not supported" is one nobody can act on. Measured here: the
        # registry's `retired_reason` explains the RETIREMENT and never says
        # which shuttle it belongs to, so the prose channel alone could not
        # tell one retired counterparty from another. Composed from the
        # registry entry, so it names any future retired shuttle too.
        rep = _report(
            NOT_DETERMINED,
            f"the '{shuttle.shuttle_id}' shuttle is RETIRED, so its precheck "
            f"tool '{shuttle.tool}' was never run: {shuttle.retired_reason}",
            layouts_found=0)
        rep.undetermined_steps = [s.step_id for s in steps]
        return rep

    # (2) Which layout? A project with none refuses over the empty set (#564).
    if layout is None:
        hits = discover_layouts(project)
    else:
        hits = [layout] if layout.is_file() else []
    if not hits:
        rep = _report(
            NOT_DETERMINED,
            "no finished layout found under the project "
            f"(searched {len(_LAYOUT_GLOBS)} layout location(s) below "
            f"{project}); nothing was submitted to the shuttle, so nothing was "
            "determined", layouts_found=0)
        rep.undetermined_steps = [s.step_id for s in steps]
        return rep
    chosen = hits[0]
    top = top or chosen.name.split(os.extsep)[0]

    # (3) Resolve the external tool. Unreachable is NOT_DETERMINED, never a pass.
    img = image or shuttle.default_image
    resolve = image_resolver or default_image_resolver
    resolved = resolve(img, allow_pull)
    if not resolved:
        rep = _report(
            NOT_DETERMINED,
            f"the shuttle precheck image '{img}' is not available"
            + (" and could not be pulled" if allow_pull else "")
            + f". Pull it with: {docker_bin} pull {img} (upstream: "
            f"{shuttle.upstream}). The counterparty was never asked, so no "
            "external verdict exists",
            layouts_found=len(hits), layout=str(chosen), image=img)
        rep.undetermined_steps = [s.step_id for s in steps]
        return rep

    # (4) Run the real tool, unmodified.
    run_root = (rundir or (project / "reports" / "phase3" /
                           "shuttle_precheck")).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    cmd = build_command(shuttle, resolved, chosen, run_root,
                        top, slot, cob, die_id, docker_bin=docker_bin)
    run = runner or default_runner
    try:
        rc, out, err = run(cmd, timeout)
    except Exception as e:  # noqa: BLE001 — any orchestration crash is undetermined
        rep = _report(
            NOT_DETERMINED,
            f"the shuttle precheck orchestration raised {e!r} before producing "
            "evidence; no external verdict exists",
            layouts_found=len(hits), layout=str(chosen), image=resolved,
            rundir=str(run_root), command=cmd)
        rep.undetermined_steps = [s.step_id for s in steps]
        return rep

    # (5) Read the tool's OWN run directory.
    evidence = parse_run_evidence(run_root)
    for st in steps:
        hit = evidence.get(_flat(_slug(st.step_id)))
        if hit is None:
            continue          # never ran -> stays NOT_DETERMINED
        st.verdict, st.source, st.evidence = hit
        if st.verdict == FAIL and not st.evidence:
            st.evidence = _tail(out, err)

    with_evidence = sum(1 for s in steps if s.verdict != NOT_DETERMINED)
    failed = [s.step_id for s in steps if s.verdict == FAIL]
    undet = [s.step_id for s in steps if s.verdict == NOT_DETERMINED]

    common = dict(layouts_found=len(hits), layout=str(chosen), image=resolved,
                  rundir=str(run_root), returncode=rc, command=cmd,
                  stdout_tail=out[-4000:], stderr_tail=err[-4000:])

    if not with_evidence:
        rep = _report(
            NOT_DETERMINED,
            f"the shuttle precheck exited rc={rc} but wrote no per-step "
            f"evidence under {run_root}; the ladder did not run, so no external "
            "verdict exists", **common)
        rep.undetermined_steps = undet
        rep.steps_with_evidence = 0
        return rep

    if failed:
        rep = _report(
            FAIL,
            "the shuttle refused: " + ", ".join(failed)
            + " — this is the counterparty's verdict, quoted from its own run "
              "directory", **common)
    elif undet:
        rep = _report(
            NOT_DETERMINED,
            "ladder step(s) produced no evidence: " + ", ".join(undet)
            + ". A step that never ran is not a pass", **common)
    elif rc != 0:
        rep = _report(
            NOT_DETERMINED,
            f"every ladder step carries passing evidence but the tool exited "
            f"rc={rc}; the disagreement is not ours to resolve in favour of a "
            "pass", **common)
    else:
        rep = _report(
            PASS,
            f"the shuttle precheck ran and every one of the {len(ladder)} "
            "ladder step(s) carries passing evidence in the tool's own run "
            "directory", **common)
    rep.steps_with_evidence = with_evidence
    rep.failed_steps = failed
    rep.undetermined_steps = undet
    return rep


def _blank_steps(ladder: Tuple[LadderStep, ...],
                 programs_dir: Optional[Path]) -> List[StepEvidence]:
    out: List[StepEvidence] = []
    for i, st in enumerate(ladder, start=1):
        cov = resolve_in_tree_coverage(st, programs_dir)
        out.append(StepEvidence(
            step_id=st.step_id, label=st.label, order=i,
            verdict=NOT_DETERMINED, refuses_on=st.refuses_on,
            covered_in_tree_by=cov, covered=cov is not None))
    return out


def _tail(out: str, err: str) -> str:
    return (err.strip()[-400:] or out.strip()[-400:])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Ask the LIVE open-MPW shuttle precheck whether this "
                    "layout would be accepted, by running the shuttle "
                    "operator's own tool and reading its run directory. "
                    "PASS only on a real run with passing evidence for every "
                    "ladder step; NOT_DETERMINED whenever the counterparty was "
                    "not reached (rc 1, same as a refusal, because a silence "
                    "credited as a pass is the defect this gate exists for).")
    p.add_argument("project", type=Path,
                   help="Project directory holding the finished layout.")
    p.add_argument("--shuttle", default=DEFAULT_SHUTTLE,
                   choices=sorted(SHUTTLES),
                   help="Shuttle to ask (default: %(default)s). The RETIRED "
                        "entry is selectable and always NOT_DETERMINED.")
    p.add_argument("--gds", type=Path, default=None, dest="layout",
                   help="Explicit layout file; default is discovered under the "
                        "project.")
    p.add_argument("--top", default="",
                   help="Top-level cell name (default: the layout file stem).")
    p.add_argument("--slot", default="1x1",
                   help="Purchased slot size, passed through to the shuttle "
                        "tool verbatim (default: %(default)s).")
    p.add_argument("--cob", action="store_true",
                   help="Chip-on-board packaging: adds the pad-mask step to the "
                        "ladder, exactly as the shuttle tool does.")
    p.add_argument("--id", default="", dest="die_id",
                   help="Die id passed through to the shuttle tool.")
    p.add_argument("--image", default="",
                   help="Override the shuttle precheck container image.")
    p.add_argument("--pull", action="store_true",
                   help="Attempt to pull the image when it is not local.")
    p.add_argument("--rundir", type=Path, default=None,
                   help="Run directory (default: "
                        "<project>/reports/phase3/shuttle_precheck).")
    p.add_argument("--timeout", type=float, default=7200.0,
                   help="Seconds to allow the precheck (default: %(default)s). "
                        "A real DRC ladder takes minutes to hours; a short "
                        "timeout reports zeros that look like success.")
    p.add_argument("--json", type=Path, dest="out_json", default=None,
                   help="Write the verdict JSON here (default: "
                        "<project>/" + READINESS_ARTEFACT + "). This is the "
                        "path the tape-out checklist reads, so the default "
                        "keeps the row and the gate pointed at one file.")
    args = p.parse_args(argv)

    project = args.project
    if not project.is_dir():
        print(f"ERROR: project directory not found: {project}", file=sys.stderr)
        return 2

    rep = evaluate(
        project=project, shuttle_id=args.shuttle, layout=args.layout,
        top=args.top, slot=args.slot, cob=args.cob, die_id=args.die_id,
        image=args.image, rundir=args.rundir, timeout=args.timeout,
        allow_pull=args.pull,
    )
    payload = rep.as_dict()
    out_json = args.out_json or (project / READINESS_ARTEFACT)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_json, json.dumps(payload, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(rep.summary_line())
    return 0 if rep.verdict == PASS else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
