#!/usr/bin/env python3
"""tapeout_readiness_check.py — the EXTERNAL refusal interface, pointed at a
shuttle that still exists.

ENFORCEMENT: advisory here — this gate is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; no one-shot runner invokes
it inline at all. It runs as the SECOND ARM of step 37.5ic, invoked by
``tapeout_precheck`` whenever the PDK ships a shuttle precheck and that
operator's template was fetched; ``tapeout_precheck``'s rc IS that step's
verdict, so a refusal here refuses the step. "advisory" names the RUNNER channel
it is absent from, not a verdict this gate cannot reach. Declared because
vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
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

THE IMAGE IS PINNED BY DIGEST, AND IT RUNS OFFLINE
=================================================
Two properties, and both are about whether a refusal means anything.

PINNED BY DIGEST, never by `:main` or `:latest`. A tag is a mutable pointer:
the same layout could be refused today and accepted tomorrow with nothing in
this tree having changed, and the first question anyone asks of a refusal —
"would it refuse again?" — would have no answer. A digest names bytes, and
`docker run` verifies it. The report additionally records the content id and
repo digests read back from the daemon AFTER resolution, so it names what
actually answered even when a caller passed `--image` with a tag.

RUN WITH `--network=none`. A precheck that can reach the network is a precheck
whose result depends on something outside the artefact — a deck fetched at run
time, a registry consulted, an operator's server having an opinion today. The
flag is also upstream's own documented invocation, so this is not a restriction
imposed on their tool; it is their tool run the way they document it.

THE MEASUREMENT THAT SETTLED IT (2026-08-18, re-run 2026-08-21 on the pin)
=========================================================================
#1744 asked for one thing above argument: run the live precheck against a
layout this project has already published, and see what comes back. Done,
against `ic/spm/v1.9.96_gf180mcuD/phase3/stage4/gds/chip_top.gds`
(sha256 fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255),
with the image pinned at
`ghcr.io/wafer-space/gf180mcu-precheck@sha256:f6c0cb88efce8769ec87de5a2035ada7`
`31fd8fffb1b3e5e1968078f6dd191c2f` and `--network=none`.

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

AND A `state`, BECAUSE THREE VERDICTS CANNOT SAY WHAT HAPPENED
=============================================================
`verdict` answers "may this be submitted". Six different things reduce to
NOT_DETERMINED, and they are not interchangeable: an image that is not on this
host is a config mistake somebody fixes in a minute; a container that would not
start is a broken host; a retired counterparty is neither. So every terminal
path also names a `state` from a closed vocabulary, and the summary line leads
with it.

`IMAGE_ABSENT` and `CONTAINER_FAILED_TO_START` are separate states, they FAIL
the gate (rc 1), and on those paths the report says
`THE COUNTERPARTY WAS NEVER ASKED — 0 of 16 stage(s) ran` and lists every stage
under `stages_never_ran`. Without that, both would present as `failed=0` beside
an empty refusal list, which reads — to a human skimming and to an aggregator
counting — as "no refusals found". That is the exact defect this repo hunts, and
having it inside the gate built to remove it would be the worst place for it.

"3 OF 16" IS THE SHAPE. "1 FAILURE" IS NOT.
===========================================
The registry carries the FULL upstream stage sequence, not the reduced set of
stages that can refuse, because the reduced set cannot state the only number a
refusal is really about. Our published GDS did not produce "1 failure": it
produced a verdict on stage 3 and NOTHING AT ALL on stages 4 through 16. A
report that says `failed=1` has quietly converted thirteen stages of silence
into an implied all-clear.

So the report states `upstream_stages_total`, `stages_attempted`,
`stopped_at_stage` and the full `stages_never_ran` list, and each stage carries
`ran` alongside its verdict — NEVER RAN and PASSED are different facts.

The sequence is hard-coded from one pinned image, so it can go stale, so
`stage_map_drift` compares it against the directories the tool actually wrote on
every run. A slug or an ordinal the registry does not declare makes the verdict
NOT_DETERMINED with `state=STAGE_MAP_STALE` — never a PASS, because a
denominator we cannot trust is not one we may pass on.

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
# STATES — WHY THE THREE VERDICTS ARE NOT ENOUGH ON THEIR OWN
#
# `verdict` answers "may this be submitted". `state` answers "what happened",
# and the two are not the same question. Six distinct things all reduce to
# NOT_DETERMINED, and one of them — the image is not there — is a config
# mistake somebody can fix in a minute, while another — the container refused
# to start — is a broken host. A reader given only NOT_DETERMINED has to guess
# which, and an aggregator counting `failed_steps` sees 0 for BOTH and can
# report "no refusals found", which is the exact defect this gate exists to
# remove, re-created inside the gate itself.
#
# So every terminal path names its state, the vocabulary is CLOSED, and the
# summary line leads with it. `IMAGE_ABSENT` and `CONTAINER_FAILED_TO_START`
# are separate members for that reason and not merged into a tidier "tool
# unavailable": they have different causes, different fixes, and different
# people to hand them to.
#
# NONE of these is an accept. `ACCEPT_STATES` is a one-element set, and
# `verdict_for_state` is what maps state to verdict, so a state added later
# without a decision about what it means cannot default into a pass.
# --------------------------------------------------------------------------- #
STATE_LADDER_PASSED = "LADDER_PASSED"                    # PASS
STATE_LADDER_REFUSED = "LADDER_REFUSED"                  # FAIL
STATE_UNKNOWN_SHUTTLE = "UNKNOWN_SHUTTLE"                # NOT_DETERMINED
STATE_SHUTTLE_RETIRED = "SHUTTLE_RETIRED"                # NOT_DETERMINED
STATE_NO_LAYOUT = "NO_LAYOUT"                            # NOT_DETERMINED
STATE_IMAGE_ABSENT = "IMAGE_ABSENT"                      # NOT_DETERMINED
STATE_CONTAINER_FAILED_TO_START = "CONTAINER_FAILED_TO_START"
STATE_ORCHESTRATION_ERROR = "ORCHESTRATION_ERROR"        # NOT_DETERMINED
STATE_NO_EVIDENCE = "NO_EVIDENCE"                        # NOT_DETERMINED
STATE_LADDER_INCOMPLETE = "LADDER_INCOMPLETE"            # NOT_DETERMINED
STATE_STAGE_MAP_STALE = "STAGE_MAP_STALE"                # NOT_DETERMINED
STATE_TOOL_DISAGREED = "TOOL_DISAGREED"                  # NOT_DETERMINED

#: The ONLY state that is an accept. Written as a set of one so that adding a
#: state is not the same edit as deciding it passes.
ACCEPT_STATES = frozenset({STATE_LADDER_PASSED})

#: The states in which the counterparty was never reached at all. Named as a
#: group because these are the ones an aggregator must not read as "clean": no
#: stage refused, and no stage was asked either.
NEVER_ASKED_STATES = frozenset({
    STATE_UNKNOWN_SHUTTLE, STATE_SHUTTLE_RETIRED, STATE_NO_LAYOUT,
    STATE_IMAGE_ABSENT, STATE_CONTAINER_FAILED_TO_START,
    STATE_ORCHESTRATION_ERROR,
})


def verdict_for_state(state: str) -> str:
    """PASS for the one accepting state, FAIL for a refusal, else NOT_DETERMINED.

    Deliberately NOT a dict lookup with a default: an unrecognised state is a
    state nobody decided about, and the safe reading of a decision nobody made
    is that no verdict was obtained."""
    if state == STATE_LADDER_PASSED:
        return PASS
    if state == STATE_LADDER_REFUSED:
        return FAIL
    return NOT_DETERMINED


#: `docker run`'s OWN exit codes for "the container never started": 125 the
#: daemon could not create it, 126 the entrypoint was not executable, 127 it was
#: not found. Documented by docker itself, and disjoint from the upstream
#: precheck's own exits (`precheck.py` leaves via `sys.exit(1)` or 0). Our
#: `default_runner` reuses 125 when the docker binary itself could not be
#: executed, which is the same class of event.
_CONTAINER_START_RCS = frozenset({125, 126, 127})


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
    cob_only: bool = False             # only in the stage list when --cob is set
    #: Can this stage REFUSE a submission, or does it only move data?
    #:
    #: Both kinds must COMPLETE for a PASS — a transport step that died is a run
    #: that did not finish, and this gate may not read that as clean. The flag
    #: exists for the OTHER two questions: which stages carry a property an
    #: in-tree gate could cover (`uncovered_in_tree` is computed over the
    #: refusing ones alone, because "we have no counterpart for Render" is not
    #: a gap anybody should act on), and which stage a report should lead with.
    refusing: bool = True


@dataclass(frozen=True)
class Shuttle:
    shuttle_id: str
    status: str                      # LIVE / RETIRED
    tool: str                        # the external tool this WRAPS
    upstream: str                    # where that tool lives
    #: THE IMAGE THIS GATE RUNS, PINNED BY DIGEST — never by a tag.
    #:
    #: A tag is a mutable pointer. `:main` and `:latest` name whatever the
    #: operator pushed most recently, so the same layout can be refused today
    #: and accepted tomorrow with nothing in this tree having changed, and the
    #: first question anybody asks of a refusal — "would it refuse again?" —
    #: becomes unanswerable. A digest names bytes. `docker run` verifies it on
    #: the way in, so a digest ref cannot silently resolve to different content.
    #:
    #: This repo's own hermetic landing runner already pins itself this way
    #: (`tools/ci/protected_landing_transition.json` -> runner.image); this is
    #: the same discipline pointed at somebody else's container.
    default_image: str
    #: The MOVING tag the digest above was resolved from. Recorded for humans
    #: (`docker pull <tag>` is what an operator types) and NEVER used to run:
    #: `default_image` is the only thing that reaches an argv.
    image_tag: str
    entrypoint: Tuple[str, ...]      # argv prefix inside the container
    #: THE FULL UPSTREAM STAGE SEQUENCE, in the tool's own order — every stage,
    #: not only the ones that can refuse.
    #:
    #: The reduced list this used to carry could not state the one number a
    #: refusal is actually about. A run that dies at CheckSize has not produced
    #: "1 failure"; it has produced a verdict on stage 3 and NOTHING AT ALL on
    #: stages 4 through 16, and those two readings lead to opposite decisions.
    #: Keeping the whole sequence is what lets the report say "3 of 16" and name
    #: the thirteen that never ran.
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


# The live path.
#
# STAGE ORDER IS `PrecheckFlow.Steps`, VERBATIM AND COMPLETE — all sixteen, in
# the tool's own sequence, read out of the pinned image rather than remembered:
#
#     docker run --rm --network=none <the digest below> \
#         python -c "print(open('/workspace/precheck.py').read())"
#
# and confirmed against a real run's own directory names (`01-klayout-readlayout`
# … `16-klayout-writelayout`). `--cob` inserts `CheckPadMask` immediately after
# `CheckSize` (`precheck.py`, `Flow.Substitute([("+KLayout.CheckSize",
# CheckPadMask)])`), which is why that one entry is `cob_only` and why the total
# is 17 under `--cob`.
#
# THE LIST IS AN ORDERING AND AN EVIDENCE MAP. It carries no slot dimension, no
# density window, no DRC rule — nothing that could disagree with the tool. What
# it carries is the DENOMINATOR: sixteen is how many stages a submission has to
# survive, so a run that died at three has thirteen stages of silence behind it
# and this file is what lets the report say so.
#
# STALENESS IS DETECTED, NOT ASSUMED AWAY. A hard-coded sequence goes wrong when
# upstream adds a stage. `_stage_map_drift` compares this list against the
# directories the tool actually wrote; a slug or an ordinal that is not in here
# makes the verdict NOT_DETERMINED with `state=STAGE_MAP_STALE`, never a PASS.
_WAFER_SPACE_GF180MCU = Shuttle(
    shuttle_id="wafer_space_gf180mcu",
    status=LIVE,
    tool="gf180mcu-precheck",
    upstream="https://github.com/wafer-space/gf180mcu-precheck",
    # PINNED BY DIGEST. Resolved 2026-08-21 from the tag below, and it is this
    # digest — not the tag — that produced every measurement quoted in this
    # file. `docker run` verifies it, so a refusal recorded against this pin can
    # be re-run against the same bytes for as long as the registry keeps them.
    default_image=("ghcr.io/wafer-space/gf180mcu-precheck@sha256:"
                   "f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e19"
                   "68078f6dd191c2f"),
    image_tag="ghcr.io/wafer-space/gf180mcu-precheck:latest",
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
            # FOUR SEPARATE REFUSALS LIVE IN THIS ONE STAGE, and the clause used
            # to name only two of them. `check_size.py` runs its predicates in
            # order and exits on the FIRST one that fails, so the stage that
            # refused our published GDS reported the seal ring and said nothing
            # about the die size behind it. A reader who is told only "die
            # dimensions" cannot tell which of the two stopped the submission,
            # and cannot tell that a second refusal is still queued behind the
            # one they can see. Both are named, in the order the tool tests
            # them.
            # NAMED AS PROPERTIES, NOT AS THE OPERATOR'S CONSTANTS. Which
            # marker layer, which database unit, which metal is the ceiling and
            # how big the slot is are all THEIRS; writing any of them down here
            # would be the first half of a reimplementation, and
            # `test_it_wraps_rather_than_reimplements` refuses it. The concrete
            # values reach the report where they belong — quoted verbatim out of
            # the counterparty's own run directory, as evidence rather than as
            # rules.
            "the origin is not at (0,0); or the layout's database unit is not "
            "the one the operator requires; or the layout uses metal above the "
            "operator's stack ceiling; or the seal-ring marker layer is absent; "
            "or the die dimensions do not match the purchased slot. The tool "
            "exits on the FIRST of these that fails, so a refusal here names "
            "one of them and leaves the other four untested",
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
            "the pad openings on the Pad layer do not match the pad mask "
            "published for the purchased slot",
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
            "KLayout.Render", "Render the Layout",
            "the layout could not be rendered",
            refusing=False),
        LadderStep(
            "KLayout.Density", "Density Deck",
            "the density deck could not be run to completion",
            refusing=False),
        LadderStep(
            "Checker.KLayoutDensity", "Density Checker",
            "layer density outside the accepted window",
            covered_by=("metal_layer_density_check",
                        "metal_fill_density_check")),
        LadderStep(
            "KLayout.ZeroAreaPolygons", "Zero Area Polygons Deck",
            "the zero-area deck could not be run to completion",
            refusing=False),
        LadderStep(
            "Checker.KLayoutZeroAreaPolygons", "Zero Area Polygons Checker",
            "the layout contains zero-area polygons",
            # `general_precheck` counts them EXACTLY, from the integer shoelace
            # area of every BOUNDARY/BOX in the stream — no tolerance, because
            # a GDSII coordinate is an integer and a tolerance would be a
            # threshold of ours that somebody could widen.
            covered_by=("general_precheck", "zero_area_polygon_check")),
        LadderStep(
            "KLayout.Antenna", "Antenna Deck",
            "the antenna deck could not be run to completion",
            refusing=False),
        LadderStep(
            "Checker.KLayoutAntenna", "Antenna Checker",
            "antenna ratio violations",
            covered_by=("antenna_report_check",)),
        LadderStep(
            "Magic.DRC", "Magic DRC Deck",
            "the Magic DRC deck could not be run to completion",
            refusing=False),
        LadderStep(
            "Checker.MagicDRC", "Magic DRC Checker",
            "Magic DRC violations",
            covered_by=("drc_report_check", "drc_vacuous_pass_check")),
        LadderStep(
            "KLayout.DRC", "KLayout DRC Deck",
            "the KLayout DRC deck could not be run to completion",
            refusing=False),
        LadderStep(
            "Checker.KLayoutDRC", "KLayout DRC Checker",
            "KLayout DRC violations",
            covered_by=("drc_report_check",)),
        LadderStep(
            "KLayout.WriteLayout", "Write the Layout",
            "the accepted layout could not be written back",
            refusing=False),
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
    # NOT PINNED, AND IT CANNOT BE. A digest names bytes in a registry that
    # somebody keeps serving; this operator stopped. The tag is recorded because
    # it is what the three surviving programs still name, and neither field is
    # ever read on this path — `evaluate` returns NOT_DETERMINED on `status ==
    # RETIRED` before any image is resolved. Left visibly unpinned rather than
    # given a plausible-looking digest, which would claim a reproducibility this
    # entry does not have.
    default_image="efabless/mpw_precheck:latest",
    image_tag="efabless/mpw_precheck:latest",
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
    #: Can this stage refuse, or does it only move data? See `LadderStep`.
    refusing: bool = True
    #: Did the tool create a directory for this stage at all? `False` is the
    #: honest word for the thirteen stages behind an early exit: not "passed",
    #: not "failed", NEVER RAN. Reported as its own field rather than left to be
    #: inferred from `verdict == NOT_DETERMINED`, which also covers the very
    #: different case of a stage that ran and logged nothing usable.
    ran: bool = False

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
    #: WHAT HAPPENED, from the closed vocabulary above. `verdict` says whether
    #: this may be submitted; `state` says why, and the two are read by
    #: different people.
    state: str = ""
    #: THE DENOMINATOR A REFUSAL IS ACTUALLY ABOUT. How many stages the
    #: counterparty's flow has, how many it got a directory for, and — when it
    #: stopped early — which one it stopped in and which ones therefore never
    #: ran. "stage 3 of 16" is the shape; "1 failure" is not, because it hides
    #: thirteen stages of silence behind a number that reads like completeness.
    upstream_stages_total: int = 0
    stages_attempted: int = 0
    #: THE FIRST STAGE THAT REFUSED, with its position in the sequence — the
    #: "3" in "stage 3 of 16".
    #:
    #: NOT called `stopped_at`, and the difference was measured. Some upstream
    #: checkers DEFER their error: a real run of a die with DRC violations
    #: refuses at stage 15 and then still runs stage 16. So the stage that
    #: refused and the stage the flow stopped after are not always the same
    #: stage, and `stages_never_ran` — computed from which directories the tool
    #: actually wrote — is the field that answers the second question.
    refused_at_stage: Optional[Dict[str, Any]] = None
    stages_never_ran: List[str] = field(default_factory=list)
    image: str = ""
    #: HOW THE IMAGE WAS NAMED, and WHICH BYTES ANSWERED.
    #:
    #: `image_pinned_by` is `digest` / `tag` / `unresolved`. A digest makes the
    #: verdict re-runnable; a tag does not, and a report that did not say which
    #: it used would leave "would it refuse again?" unanswerable. `image_id` and
    #: `image_repo_digests` are read back from the daemon AFTER resolution, so
    #: the record names the content that ran however the caller spelled it —
    #: including a `--image` override that came in on a moving tag.
    image_tag: str = ""
    image_pinned_by: str = "unresolved"
    image_id: str = ""
    image_repo_digests: List[str] = field(default_factory=list)
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
        """One line that ALWAYS states the denominator (#447).

        LEADS WITH THE STATE, on purpose. The old line led with counts, and for
        every path where the counterparty was never reached those counts read
        `failed=0, undetermined=9` — which a human skims as "nothing refused"
        and an aggregator reads as zero findings. The state is the first thing
        after the verdict now, and the stage arithmetic is stated as "stopped at
        N of M, K never ran" rather than as a failure tally."""
        head = (f"{self.verdict} [{self.state or 'UNSET'}]: "
                f"shuttle={self.shuttle} ({self.shuttle_status}) "
                f"tool={self.tool}")
        if self.state in NEVER_ASKED_STATES:
            # No stage refused AND no stage was asked. Say the second part, or
            # the first reads as an all-clear.
            stages = (f"THE COUNTERPARTY WAS NEVER ASKED — "
                      f"0 of {self.upstream_stages_total} stage(s) ran")
        elif self.refused_at_stage:
            stages = (f"REFUSED at stage {self.refused_at_stage['order']} of "
                      f"{self.upstream_stages_total} "
                      f"({self.refused_at_stage['label']}), "
                      f"{self.stages_attempted} stage(s) ran, "
                      f"{len(self.stages_never_ran)} NEVER RAN")
        else:
            stages = (f"{self.stages_attempted} of "
                      f"{self.upstream_stages_total} stage(s) ran, "
                      f"{len(self.stages_never_ran)} NEVER RAN")
        return (
            f"{head} — layouts_found={self.layouts_found}, {stages}, "
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
    unreachable tool would have passed.

    `docker image inspect`, NOT `docker images -q`, AND THE DIFFERENCE IS A BUG
    ------------------------------------------------------------------------
    `docker images -q` matches on repository:TAG. Given a digest reference it
    prints NOTHING and exits 0 — the same output as for an image that genuinely
    is not there. Measured on the pinned image while it was present locally:

        $ docker images -q ghcr.io/…/gf180mcu-precheck@sha256:f6c0cb88…
        (no output, rc 0)
        $ docker image inspect ghcr.io/…/gf180mcu-precheck@sha256:f6c0cb88… \
              --format '{{.Id}}'
        sha256:4f58bb5de3159afe26ebf17310c5129234fe0bc7b9697723164ad0fab984fc40

    So the moment this gate was pinned by digest — which is the whole point of
    pinning it — the old probe reported IMAGE_ABSENT on every host that had the
    image, and the gate stopped asking the counterparty anything. Not a hedge
    against a hypothetical: with the digest pin in place and this probe left
    alone, EVERY run is a non-run. `docker image inspect` resolves tags and
    digests alike and exits non-zero when the reference is not present, which is
    the question actually being asked."""
    if not shutil.which(docker_bin):
        return None
    if _image_is_local(image, docker_bin):
        return image
    if not allow_pull:
        return None
    try:
        p = subprocess.run([docker_bin, "pull", image],
                           capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError):
        return None
    # A pull that reported success but left nothing inspectable is not a
    # resolution. Re-ask rather than trusting the exit code.
    return image if (p.returncode == 0
                     and _image_is_local(image, docker_bin)) else None


def _image_is_local(image: str, docker_bin: str = "docker") -> bool:
    try:
        q = subprocess.run([docker_bin, "image", "inspect", image,
                            "--format", "{{.Id}}"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return q.returncode == 0 and bool(q.stdout.strip())


def image_identity(image: str,
                   docker_bin: str = "docker") -> Tuple[str, List[str]]:
    """(content id, repo digests) for a resolved image, or ("", []).

    WHICH BYTES ANSWERED, read back from the daemon rather than assumed from the
    string the caller typed. A refusal is only re-runnable if the record names
    the image content, and `--image` lets a caller name it however they like —
    including with a tag that will point somewhere else next week. Best-effort:
    a daemon that will not answer degrades the RECORD, and must not change the
    VERDICT, so this never raises and never returns a guess."""
    # `{{json .RepoDigests}}`, not `{{join .RepoDigests ","}}`. Measured: on
    # this daemon `join` fails with `wrong type for value; expected []string;
    # got []interface {}` and the whole inspect exits 1, so the identity came
    # back empty on the very runs it exists to record. `json` renders any shape.
    try:
        q = subprocess.run(
            [docker_bin, "image", "inspect", image,
             "--format", "{{.Id}}\n{{json .RepoDigests}}"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "", []
    if q.returncode != 0:
        return "", []
    parts = (q.stdout or "").strip().splitlines()
    ident = parts[0].strip() if parts else ""
    digests: List[str] = []
    if len(parts) > 1:
        try:
            loaded = json.loads(parts[1])
        except ValueError:
            loaded = None
        if isinstance(loaded, list):
            digests = [str(d) for d in loaded if d]
    return ident, digests


def pin_kind(image: str) -> str:
    """`digest` when the reference names content, `tag` when it names a pointer.

    The whole test is whether an `@sha256:` appears, because that is the whole
    difference: docker verifies a digest reference against the content it
    fetched and rejects a mismatch, and verifies nothing at all about a tag."""
    return "digest" if "@sha256:" in (image or "") else "tag"


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


def observed_stages(rundir: Path) -> List[Tuple[int, str, bool]]:
    """(ordinal, flattened slug, completed) for every stage directory the tool wrote.

    The counterparty's own record of which stages it ATTEMPTED. A stage with no
    directory was not attempted; that is the difference between "this stage was
    checked and was fine" and "this stage never ran", and it is the whole reason
    a refusal is reported as `3 of 16` rather than as a failure count."""
    seen: Dict[int, Tuple[int, str, bool]] = {}
    for run_root in _run_roots(rundir):
        try:
            kids = sorted(d for d in run_root.iterdir()
                          if d.is_dir() and _numbered_step_dir(d.name))
        except OSError:
            continue
        for d in kids:
            head, _, slug = d.name.partition("-")
            seen[int(head)] = (int(head), _flat(slug),
                               (d / "state_out.json").is_file())
    return [seen[k] for k in sorted(seen)]


def stage_map_drift(shuttle_stages: Tuple[LadderStep, ...],
                    observed: List[Tuple[int, str, bool]]) -> List[str]:
    """Ways the declared stage sequence disagrees with the run, as sentences.

    A HARD-CODED SEQUENCE HAS TO BE ABLE TO GO WRONG OUT LOUD. The stage list in
    the registry was read out of one pinned image; upstream can add a stage,
    rename one, or reorder them, and a gate that kept counting against a stale
    list would report a confident `12 of 16` for a flow that now has eighteen.
    Every disagreement found here makes the verdict NOT_DETERMINED with
    `state=STAGE_MAP_STALE` — never a PASS, because a denominator we cannot
    trust is not a denominator we may pass on.

    Deliberately compares against what the TOOL wrote, so the check needs no
    second source and cannot itself go stale."""
    declared = {_flat(_slug(s.step_id)): i
                for i, s in enumerate(shuttle_stages, start=1)}
    problems: List[str] = []
    for order, slug, _done in observed:
        if slug not in declared:
            problems.append(
                f"the run wrote stage {order} '{slug}', which is not in this "
                f"registry's declared sequence of {len(shuttle_stages)} stage(s)")
        elif declared[slug] != order:
            problems.append(
                f"the run wrote '{slug}' as stage {order}; this registry "
                f"declares it as stage {declared[slug]}")
    if observed and observed[-1][0] > len(shuttle_stages):
        problems.append(
            f"the run reached stage {observed[-1][0]}, beyond the "
            f"{len(shuttle_stages)} this registry declares")
    return problems


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
        rep = ReadinessReport(
            project=str(project), shuttle=shuttle_id, shuttle_status="UNKNOWN",
            tool="", upstream="", verdict=NOT_DETERMINED,
            reason=f"unknown shuttle '{shuttle_id}'; known shuttles: {known}",
            layouts_found=0, state=STATE_UNKNOWN_SHUTTLE)
        return rep

    # The stages this run has, in the tool's own order. `--cob` inserts one, so
    # the denominator is a property of the invocation and not a constant.
    ladder = tuple(s for s in shuttle.ladder if cob or not s.cob_only)
    total_stages = len(ladder)
    steps = _blank_steps(ladder, programs_dir)
    # Coverage is asked of the stages that can REFUSE. "no in-tree counterpart
    # for Render" is not a gap; naming it as one would bury the two that are.
    uncovered = [s.step_id for s in steps if s.refusing and not s.covered]

    def _report(state: str, reason: str, **kw: Any) -> ReadinessReport:
        rep = ReadinessReport(
            project=str(project), shuttle=shuttle.shuttle_id,
            shuttle_status=shuttle.status, tool=shuttle.tool,
            upstream=shuttle.upstream, verdict=verdict_for_state(state),
            state=state, reason=reason,
            required_steps=total_stages, steps=steps,
            uncovered_in_tree=uncovered,
            upstream_stages_total=total_stages,
            image_tag=shuttle.image_tag, **kw)
        return rep

    def _never_asked(state: str, reason: str, **kw: Any) -> ReadinessReport:
        """A terminal path on which the counterparty was never reached.

        Every stage is NOT_DETERMINED and `stages_never_ran` is ALL of them —
        stated rather than left empty, because an empty never-ran list beside an
        empty failed list is precisely the "no refusals found" reading this gate
        exists to make impossible."""
        rep = _report(state, reason, **kw)
        rep.undetermined_steps = [s.step_id for s in steps]
        rep.stages_never_ran = [s.step_id for s in steps]
        rep.stages_attempted = 0
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
        return _never_asked(
            STATE_SHUTTLE_RETIRED,
            f"the '{shuttle.shuttle_id}' shuttle is RETIRED, so its precheck "
            f"tool '{shuttle.tool}' was never run: {shuttle.retired_reason}",
            layouts_found=0)

    # (2) Which layout? A project with none refuses over the empty set (#564).
    if layout is None:
        hits = discover_layouts(project)
    else:
        hits = [layout] if layout.is_file() else []
    if not hits:
        return _never_asked(
            STATE_NO_LAYOUT,
            "no finished layout found under the project "
            f"(searched {len(_LAYOUT_GLOBS)} layout location(s) below "
            f"{project}); nothing was submitted to the shuttle, so nothing was "
            "determined", layouts_found=0)
    chosen = hits[0]
    top = top or chosen.name.split(os.extsep)[0]

    # (3) Resolve the external tool.
    #
    #     IMAGE ABSENT IS ITS OWN STATE AND IT FAILS THE GATE. It is not a
    #     variety of "nothing found" and it must never aggregate as one: no
    #     stage refused because no stage was asked, and the difference between
    #     those two sentences is the difference between shipping and not.
    img = image or shuttle.default_image
    pinned_by = pin_kind(img)
    resolve = image_resolver or default_image_resolver
    resolved = resolve(img, allow_pull)
    if not resolved:
        return _never_asked(
            STATE_IMAGE_ABSENT,
            f"the shuttle precheck image '{img}' is not available"
            + (" and could not be pulled" if allow_pull else "")
            + f". Pull it with: {docker_bin} pull {img} (upstream: "
            f"{shuttle.upstream}). The counterparty was never asked, so no "
            "external verdict exists and NO STAGE OF THE LADDER RAN",
            layouts_found=len(hits), layout=str(chosen), image=img,
            image_pinned_by=pinned_by)

    # WHICH BYTES ANSWERED. Read back from the daemon after resolution, so the
    # record is of content rather than of the string somebody typed.
    ident, repo_digests = image_identity(resolved, docker_bin)
    img_facts = dict(image=resolved, image_pinned_by=pin_kind(resolved),
                     image_id=ident, image_repo_digests=repo_digests)

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
        return _never_asked(
            STATE_ORCHESTRATION_ERROR,
            f"the shuttle precheck orchestration raised {e!r} before producing "
            "evidence; no external verdict exists and NO STAGE OF THE LADDER "
            "RAN",
            layouts_found=len(hits), layout=str(chosen),
            rundir=str(run_root), command=cmd, **img_facts)

    # (5) Read the tool's OWN run directory.
    observed = observed_stages(run_root)
    evidence = parse_run_evidence(run_root)
    for st in steps:
        hit = evidence.get(_flat(_slug(st.step_id)))
        if hit is None:
            continue          # never ran -> stays NOT_DETERMINED, ran stays False
        st.ran = True
        st.verdict, st.source, st.evidence = hit
        if st.verdict == FAIL and not st.evidence:
            st.evidence = _tail(out, err)

    with_evidence = sum(1 for s in steps if s.verdict != NOT_DETERMINED)
    failed = [s.step_id for s in steps if s.verdict == FAIL]
    undet = [s.step_id for s in steps if s.verdict == NOT_DETERMINED]
    never_ran = [s.step_id for s in steps if not s.ran]
    # THE FIRST STAGE THAT REFUSED — attempted, and did not complete.
    #
    # There can be MORE than one, and that was measured rather than assumed: a
    # checker whose error is DEFERRED lets the flow carry on, so a real run
    # against a die with both density and DRC violations refuses at stage 7 AND
    # at stage 15 and still writes stage 16. `failed_steps` names them all;
    # this names the one a reader should look at first, because it is the one
    # a submission hits first.
    refused = next((s for s in steps if s.ran and s.verdict == FAIL), None)
    refused_at = ({"order": refused.order, "step_id": refused.step_id,
                   "label": refused.label} if refused else None)

    common = dict(layouts_found=len(hits), layout=str(chosen),
                  rundir=str(run_root), returncode=rc, command=cmd,
                  stdout_tail=out[-4000:], stderr_tail=err[-4000:],
                  stages_attempted=len(observed),
                  refused_at_stage=refused_at,
                  stages_never_ran=never_ran, **img_facts)

    def _finish(state: str, reason: str) -> ReadinessReport:
        rep = _report(state, reason, **common)
        rep.steps_with_evidence = with_evidence
        rep.failed_steps = failed
        rep.undetermined_steps = undet
        return rep

    # (5a) DID THE COUNTERPARTY'S FLOW STILL HAVE THE SHAPE WE COUNT AGAINST?
    #      Asked before any verdict, because every number below is stated over
    #      a denominator this registry supplies, and a denominator that no
    #      longer matches the tool makes all of them meaningless — including,
    #      and especially, a PASS.
    drift = stage_map_drift(ladder, observed)
    if drift:
        return _finish(
            STATE_STAGE_MAP_STALE,
            "the counterparty's flow no longer matches the stage sequence this "
            "registry declares, so no stage arithmetic here can be trusted: "
            + "; ".join(drift)
            + ". Re-read `PrecheckFlow.Steps` from the pinned image and update "
              "the registry; until then no verdict is claimed")

    if not with_evidence:
        return _finish(
            STATE_CONTAINER_FAILED_TO_START if rc in _CONTAINER_START_RCS
            else STATE_NO_EVIDENCE,
            # BOTH BRANCHES FAIL THE GATE, and they are kept apart because they
            # are handed to different people: a container that would not start
            # is a broken host, and a container that started and wrote nothing
            # is a broken invocation.
            (f"the container did not start (rc={rc}, which is docker's own "
             f"code for it); the counterparty was never asked and NO STAGE OF "
             f"THE LADDER RAN"
             if rc in _CONTAINER_START_RCS else
             f"the shuttle precheck exited rc={rc} but wrote no per-stage "
             f"evidence under {run_root}; the ladder did not run, so no "
             f"external verdict exists")
            + f". Last output: {_tail(out, err) or '(none)'}")

    if failed:
        where = (f"at stage {refused_at['order']} of {total_stages} "
                 f"({refused_at['label']})" if refused_at else "")
        return _finish(
            STATE_LADDER_REFUSED,
            f"the shuttle refused {where}: " + ", ".join(failed)
            + " — this is the counterparty's verdict, quoted from its own run "
              "directory"
            + (f". {len(never_ran)} stage(s) NEVER RAN and are UNKNOWN, not "
               f"clean: " + ", ".join(never_ran) if never_ran else ""))

    if undet:
        return _finish(
            STATE_LADDER_INCOMPLETE,
            "ladder stage(s) produced no evidence: " + ", ".join(undet)
            + ". A stage that never ran is not a pass")

    if rc != 0:
        return _finish(
            STATE_TOOL_DISAGREED,
            f"every one of the {total_stages} stage(s) carries passing evidence "
            f"but the tool exited rc={rc}; the disagreement is not ours to "
            "resolve in favour of a pass")

    return _finish(
        STATE_LADDER_PASSED,
        f"the shuttle precheck ran and every one of the {total_stages} "
        "stage(s) carries passing evidence in the tool's own run directory")


def _blank_steps(ladder: Tuple[LadderStep, ...],
                 programs_dir: Optional[Path]) -> List[StepEvidence]:
    out: List[StepEvidence] = []
    for i, st in enumerate(ladder, start=1):
        cov = resolve_in_tree_coverage(st, programs_dir)
        out.append(StepEvidence(
            step_id=st.step_id, label=st.label, order=i,
            verdict=NOT_DETERMINED, refuses_on=st.refuses_on,
            covered_in_tree_by=cov, covered=cov is not None,
            refusing=st.refusing))
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
                   help="Override the shuttle precheck container image. The "
                        "registry default is pinned BY DIGEST; an override "
                        "given as a tag is honoured and recorded as "
                        "image_pinned_by=tag, because a tag can point "
                        "somewhere else tomorrow and a verdict nobody can "
                        "re-run is worth less than one they can.")
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
    # rc 0 for the one accepting state and nothing else. Asked of the state
    # rather than of the verdict so that a state added without a decision about
    # what it means cannot fall through to a green light.
    return 0 if rep.state in ACCEPT_STATES else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
