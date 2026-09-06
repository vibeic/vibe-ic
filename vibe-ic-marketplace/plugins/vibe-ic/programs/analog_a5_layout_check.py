#!/usr/bin/env python3
"""analog_a5_layout_check.py — A5 deterministic gate.

Verifies that the upstream `analog-layout` skill has emitted the
canonical per-block A5 artefact:

    analog/<block>/layout.mag   (Magic source) OR
    analog/<block>/<block>.gds  (streamed GDS)

with substance:

  * layout source is one of {layout.mag, <block>.gds} (either
    representation is acceptable for A5 closure)
  * layout source size > 200 bytes (the v10627 64-byte HEADER+ENDLIB
    GDS stub trips this)
  * layout source carries REAL PLACED GEOMETRY — at least one placed
    device / paint rectangle / cell instance (ORGANIC #144): the
    presence+size test alone let an empty-geometry stream (an
    `eda_analog_layout` `readspice`+`gds write` with no placement) or
    the runner's own `"x"*400` padded `layout.mag` stub PASS. The gate
    now parses the .mag (paint `rect` / instance `use` lines) or walks
    the .gds record stream (BOUNDARY/PATH/SREF/AREF/BOX records) and
    rejects a geometry-empty or `deterministic_stub`-marked layout.

SCOPE — WHY THIS GATE DOES NOT JUDGE DRC/LVS SIGN-OFF
-----------------------------------------------------
This gate used to ALSO require `<block>/drc_clean.flag` and
`<block>/lvs_match.flag` to carry clean verdicts. Those two files are
step A6's DECLARED required_outputs, and A6 declares `blocks_on: [A5]`,
so the declared ordering ran A6 -> A5 while the gate's read ran A5 -> A6:
a literal dependency cycle that no `blocks_on` value can express.

The cycle was broken on the A5 side, and here is how the direction was
decided rather than guessed:

  * A6 CANNOT run without A5's output. `analog_a6_block_pv_check` reports
    `A6_PV_BLOCK_DIR_MISSING` ("A5 layout did not run for this block")
    when the layout dir is absent — DRC and LVS are run ON the layout.
    A5 -> A6 is a DATA dependency.
  * A5 does not need PV evidence to PRODUCE a layout. The flag reads were
    a verification-SCOPE choice, not a data need.
  * The flags are physically written by the A6 step, not the A5 step:
    `analog_one_shot_runner._emit_deterministic_stub` writes them under
    `step_name == "A6_block_pv"`, and writes `layout.mag` under
    `"A5_layout"`. The runner executes A5_layout BEFORE A6_block_pv, so
    with the flag rules in place A5 reported FAIL on every correct
    single-pass run, for a condition A5 itself cannot satisfy.

So the PV verdict now lives ONLY in A6, where a STRICTER version of the
same rules already ran: `analog_a6_block_pv_check` prefers real DRC/LVS
REPORTS over the flags, rejects a bare/verdict-less flag, and FAILs
(never SKIPs) on a block directory with no evidence. See
`programs/tests/test_analog_a5_layout_check.py`, section "A5 -> A6 PV
OWNERSHIP", which re-runs the inputs this gate used to reject through the
A6 gate and asserts rc=1.

WHAT THE HANDOVER DID **NOT** PRESERVE ON ITS OWN, corrected 2026-07-28
rather than left as an over-broad claim. Old A5 read the FLAGS
(`drc_clean.flag` / `lvs_match.flag`); A6 prefers the REPORT and only
falls back to the flag. Two consequences follow, and they are different:

  * A block whose FLAG CONTRADICTS ITS REPORT was rejected rc=1 by old A5
    and, for a while, accepted rc=0 by BOTH gates. Measured on
    `drc_clean.flag: "violations: 5"` beside `drc.report: "total
    violations: 0"`, and `lvs_match.flag: "lvs: mismatch"` beside
    `lvs.report: "netlists match"`: baseline A5 rc=1; after the cycle fix
    and before the repair, A5 rc=0 and A6 rc=0 with no findings at all.
    That is CLOSED — `analog_a6_block_pv_check._witness_disagreements`
    now FAILs on it (A6_PV_DRC_WITNESS_DISAGREEMENT /
    A6_PV_LVS_WITNESS_DISAGREEMENT), and it is non-waivable, because a
    waiver accepts a measured risk and here the measurement is in dispute.
    Re-measured on all 23 tracked analog run roots: A6's rc is unchanged
    on 23 of 23, so the rule bought no false alarm.
  * A block carrying a CLEAN REPORT and NO FLAG is rejected by old A5
    (A5_DRC_FLAG_MISSING / A5_LVS_FLAG_MISSING) and accepted by A6. That
    is DELIBERATE and is NOT called a lost defect class: the report is the
    tool's own output and is richer evidence than a flag file; demanding
    a flag beside it was A5 over-reaching, not A5 catching anything.

ONE THING DID CHANGE, and it is not "no defect class". This gate never
had a waiver code path, so it was a second, independently
NON-SILENCEABLE gate on per-block DRC/LVS; A6 carries the flow-wide
waiver path, so a project-side `waived_steps: [{id: analog_block_pv}]`
entry now reaches the class. The asymmetry that matters is closed in A6
(`_NON_WAIVABLE_RULES`): a waiver may suppress a MEASURED defect
(DRC count > 0, LVS mismatch) — a ticketed accepted risk, which is what
the flow's waiver mechanism is for and what waivers_schema_check /
waiver_legitimacy_check / foundry_signoff_plan_check police — but it can
never suppress an ABSENT measurement (block dir missing, no parseable
DRC/LVS result). So the exact claim is: every input this gate used to
reject is still rejected rc=1 by A6, and for the evidence-ABSENCE
classes that holds even under a project-side step waiver.

WHAT THE GEOMETRY RULES CANNOT SEE — the matching disclosure
------------------------------------------------------------
Every rule above answers "is there a layout?". None of them answers "is it
the layout this block needed?", and the gate one step later cannot either:
A6's netgen compare is TOPOLOGY-only, so N isolated devices in N slots close
it exactly as green as a common-centroid quad, and dummies — the thing the
authoring skill mandates two of per side — actively HURT the compare.

So this gate now also reads the block's own record of its matching structure,
`layout_matching.json`, and puts the answer in its report on EVERY verdict
path. `matching_style: "none"` is a legitimate, certifying answer; what is
recorded is the DIFFERENCE between a block that says so and one that says
nothing. The rules below fire only on a record that EXISTS, so writing one
costs nothing but having to mean it. See `_analog_layout_matching`.

Failure rules:
  A5_LAYOUT_MISSING        — neither layout.mag nor <block>.gds present
  A5_LAYOUT_TOO_SMALL      — layout source < 200 bytes (stub)
  A5_LAYOUT_EMPTY_GEOMETRY — layout source has no placed geometry (empty
                             stream or padded/deterministic stub)
  A5_MATCHING_DISCLOSURE_MALFORMED
                           — layout_matching.json exists and answers nothing
  A5_MATCHING_STYLE_GROUPS_CONTRADICT
                           — `matching_style` and `matched_groups` disagree
  A5_MATCHING_GROUP_DUMMIES_INSUFFICIENT
                           — a matched group declares < 2 dummies per side
  A5_MATCHING_DUMMIES_LVS_UNRECONCILED
                           — dummies declared, no `lvs_dummy_waiver` names how
                             the A6 LVS compare reconciles them
  A5_DEVICE_PARTITION_WIDTH_MISMATCH
                           — an N-way device split whose layout widths do not
                             sum to `w_um x m`
  A5_LAYOUT_DRAWN_SHORT    — the producer's own record says two routed nets
                             are ONE conductor in this layout, with the chain
                             of rectangles that joins them
  A5_DEVICE_ABOVE_PDK_MAXIMUM
                           — the producer's own record says a device was asked
                             for above the PDK's stated maximum. A magic
                             gencell does not refuse that: it CLAMPS and
                             draws, so the drawn device is not the netlist's.
                             MEASURED: eight `delta_sigma` capacitors asked
                             for at l = 34.75 .. 629.08 um against a gencell
                             `lmax 30.0` were all drawn at 30 um, and the LVS
                             cross-reference named those eight and only those
                             eight, differing in `l` alone.

A DRAWN SHORT IS NOT A CLEARANCE PREDICTION. Every other number in
`layout_provenance.json` is a distance this gate deliberately does NOT judge:
the sign-off deck adjudicates those, at A6, over richer evidence. A short is
different in kind — it is two nets of the netlist being one conductor in the
drawn geometry, measured by union-find over the producer's own manifest plus
the placed gencells' own geometry, and no deck adjudicates it away. MEASURED
on u_hawaii_adc (ihp-sg13g2): 13 of them across two blocks while this gate
reported PASS and the A6 LVS reported `mismatch` with nothing between the two
able to say why.

WHAT THIS RULE CANNOT SEE, said plainly: it reads the producer's RECORD, so a
block whose layout was drawn by something that writes no record — or whose
record was removed — is not asked. That is why the producer ALSO exits
non-zero on its own shorts (`analog_a5_layout_emit`, exit 1): the record is
the gate's evidence, not the enforcement.

Project-level verdicts (no `--block`):
  VACUOUS_PASS — no `analog_block_list.json` under `phase3/analog/` or
                 `phase1/analog/`, or it declares no blocks; or EVERY
                 declared block is still missing its layout (the step
                 has not run at all → defer to skill `analog-layout`).
  INCOMPLETE   — SOME declared blocks produced a layout and others produced
                 none (exit 1). A5's own requirement was never met for the
                 uncovered blocks, so the gate must not certify the step:
                 it names the uncovered blocks instead of reporting PASS.
  PASS         — every declared block cleared every check.
chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
)
import _analog_layout_matching as _lm

GATE = "analog_a5_layout_check"
SKILL = "analog-layout"
MIN_LAYOUT_BYTES = 200

#: The producer's own record, beside the layout, and the deviation quantity
#: it writes for a DRAWN SHORT. The name is imported rather than spelled
#: twice so the gate and the producer cannot drift apart.
PROVENANCE_NAME = "layout_provenance.json"
SHORT_QUANTITY = "routed_nets_per_conductor"
OVER_MAXIMUM_QUANTITY = "device_geometry_above_pdk_maximum"

#: quantity -> the rule this gate reports it under. Every entry is a
#: deviation that says the producer did NOT draw the netlist it was given —
#: not a clearance A6's deck adjudicates. Keyed by the producer's own
#: `analog_a5_layout_emit.BLOCKING_QUANTITIES`, so the two cannot drift.
BLOCKING_RULES = {
    SHORT_QUANTITY: "A5_LAYOUT_DRAWN_SHORT",
    OVER_MAXIMUM_QUANTITY: "A5_DEVICE_ABOVE_PDK_MAXIMUM",
}


# Project-level INCOMPLETE (exit 1) — some declared blocks produced a layout
# and others produced none — is emitted by the SHARED
# `_analog_a_check_common.emit_incomplete`, the same emitter A1-A4 use.
#
# An earlier fix shipped a byte-local copy of that emitter here, because the
# shared helper was landing on a sibling branch at the same time and three
# branches adding an identically-named function to one file would have
# collided. Those branches have landed. The local copy produced a REPORT that
# differed from A1-A4's for the same verdict: it carried no
# `incomplete_blocks`, no `suggested_skill` and no `reason`, so a consumer
# reading an A5 INCOMPLETE report could not learn which blocks were uncovered
# or which skill to invoke, while the A1-A4 report told it both. Same verdict
# string and same exit code, so nothing that keys on those is affected.


# ORGANIC #144 — real-geometry parsing.
# A stub / empty-geometry layout carries a size but NO placed geometry.
# The runner's deterministic A5 stub self-identifies with this marker; an
# `eda_analog_layout` empty stream has neither the marker nor any geometry.
_STUB_MARKER_RE = re.compile(r"deterministic[_\-\s]*stub", re.IGNORECASE)
# Magic .mag paint (`rect xbot ybot xtop ytop`) + instance (`use <cell> <id>`)
# lines. Real placed geometry = at least one of either.
_MAG_RECT_RE = re.compile(
    r"(?m)^\s*rect\s+-?\d+\s+-?\d+\s+-?\d+\s+-?\d+\s*$")
_MAG_USE_RE = re.compile(r"(?m)^\s*use\s+\S+")
# GDS record types that carry geometry / placement (not just header/struct
# bookkeeping): BOUNDARY 0x08, PATH 0x09, SREF 0x0A, AREF 0x0B, BOX 0x2D.
_GDS_GEOMETRY_RECORD_TYPES = frozenset({0x08, 0x09, 0x0A, 0x0B, 0x2D})


def _mag_geometry_count(text: str) -> int:
    """Count placed geometry in a Magic .mag source: paint `rect` lines +
    cell-instance `use` lines. chip-AGNOSTIC (pure text parse, no tool)."""
    return (len(_MAG_RECT_RE.findall(text))
            + len(_MAG_USE_RE.findall(text)))


def _gds_geometry_count(data: bytes) -> int:
    """Walk a binary GDS-II record stream and count geometry/placement
    records (BOUNDARY/PATH/SREF/AREF/BOX). Pure-Python record walk — no
    KLayout dependency, so the gate is deterministic without a container.
    Malformed / truncated streams stop the walk (count stays honest)."""
    i, n, count = 0, len(data), 0
    while i + 4 <= n:
        rlen = (data[i] << 8) | data[i + 1]
        rtype = data[i + 2]
        if rlen < 4:
            break  # a valid record is at least the 4-byte header
        if rtype in _GDS_GEOMETRY_RECORD_TYPES:
            count += 1
        i += rlen
    return count


def _layout_has_real_geometry(path: Path) -> tuple[bool, str]:
    """Return (has_geometry, detail). A layout has real geometry when its
    .mag carries ≥1 paint/instance line or its .gds carries ≥1
    geometry/placement record. A `deterministic_stub`-marked layout is
    rejected outright regardless of size."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return False, f"unreadable ({e})"
    if path.suffix.lower() == ".gds":
        recs = _gds_geometry_count(raw)
        if recs > 0:
            return True, f"{recs} GDS geometry/placement record(s)"
        return False, "GDS stream carries no BOUNDARY/PATH/SREF/AREF/BOX record"
    # .mag (or any text layout source)
    text = raw.decode("utf-8", errors="replace")
    if _STUB_MARKER_RE.search(text):
        return False, "carries a deterministic_stub marker (padded stub)"
    geo = _mag_geometry_count(text)
    if geo > 0:
        return True, f"{geo} placed geometry line(s) (rect paint / use instance)"
    return False, "no placed geometry (no rect paint / use instance lines)"


def _drawn_shorts(project: Path, bdir: Path, block: str) -> List[dict]:
    """The producer's BLOCKING deviations, out of its own record.

    Silent when there is no record and when the record is unreadable — this
    gate reports what a record SAYS, and "could not read it" is not "read it
    and it was clean". An unreadable record is not invented into a pass or a
    fail here; the producer's own non-zero exit is the enforcement."""
    rec = bdir / PROVENANCE_NAME
    if not rec.is_file():
        return []
    try:
        data = json.loads(rec.read_text())
    except (OSError, ValueError):
        return []
    devs = data.get("deviations")
    if not isinstance(devs, list):
        return []
    out: List[dict] = []
    for d in devs:
        if not isinstance(d, dict):
            continue
        rule = BLOCKING_RULES.get(d.get("quantity"))
        if rule is None:
            continue
        out.append({
            "block": block, "rule": rule,
            "rel_path": str(rec.relative_to(project)),
            "detail": str(d.get("detail")
                          or "the producer did not draw this netlist"),
        })
    return out


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict], "_lm.Disclosure"]:
    bdir = project / "phase3" / "analog" / block
    mag = bdir / "layout.mag"
    gds = bdir / f"{block}.gds"
    disclosure = _lm.read_disclosure(bdir, block)

    findings: List[dict] = []
    layout_path: Optional[Path] = None
    if mag.is_file():
        layout_path = mag
    elif gds.is_file():
        layout_path = gds
    if layout_path is None:
        # Treat as MISSING (not FAIL) so --block mode → WAIVED. A block with
        # no layout at all is not asked about its matching structure: there is
        # nothing drawn to have one.
        return "MISSING", [{
            "block": block, "rule": "A5_LAYOUT_MISSING",
            "rel_path": str(bdir.relative_to(project)),
            "detail": "neither layout.mag nor <block>.gds present",
        }], _lm.Disclosure(_lm.DISCLOSURE_UNDISCLOSED, None, [], [])
    try:
        size = layout_path.stat().st_size
    except OSError:
        size = 0
    if size < MIN_LAYOUT_BYTES:
        findings.append({
            "block": block, "rule": "A5_LAYOUT_TOO_SMALL",
            "rel_path": str(layout_path.relative_to(project)),
            "detail": f"{size}B < min {MIN_LAYOUT_BYTES}B (stub)",
        })
    else:
        # ORGANIC #144 — a layout that clears the size bar must ALSO carry
        # real placed geometry. This rejects the empty-geometry stream an
        # `eda_analog_layout` `readspice`+`gds write` produces (netlist
        # loaded, nothing placed) and the runner's `"x"*400` padded
        # `layout.mag` stub, both of which passed the presence+size gate.
        has_geo, geo_detail = _layout_has_real_geometry(layout_path)
        if not has_geo:
            findings.append({
                "block": block, "rule": "A5_LAYOUT_EMPTY_GEOMETRY",
                "rel_path": str(layout_path.relative_to(project)),
                "detail": f"{size}B but no real placed geometry: {geo_detail}",
            })
    # THE PRODUCER'S OWN RECORD, for the ONE thing in it that is not a
    # clearance prediction. See the module docstring.
    findings.extend(_drawn_shorts(project, bdir, block))
    # NOTE: per-block DRC / LVS sign-off is deliberately NOT judged here —
    # see the module docstring's "SCOPE" section. It is step A6's verdict,
    # over A6's own (richer) evidence, at the point in the flow where that
    # evidence exists.
    #
    # The MATCHING record is read here, where the layout is. Its findings join
    # this block's list; its CLASS is reported by `main` on every path,
    # including this one's failures.
    findings.extend(disclosure.findings)
    if findings:
        return "FAIL", findings, disclosure
    return "PASS", [], disclosure


def main(argv: Optional[List[str]] = None) -> int:
    ap = make_argparser(GATE, __doc__)
    args = ap.parse_args(argv)
    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    blocks_all = load_block_list(project)
    if blocks_all is None or (not blocks_all and not args.block):
        return vacuous_pass(GATE, args,
                            BLOCK_LIST_ABSENT_REASON)

    blocks = select_blocks(blocks_all or [], args.block)
    if not blocks:
        return vacuous_pass(GATE, args, "no blocks selected.")

    findings: List[dict] = []
    blocks_pass = 0
    missing_seen: List[dict] = []
    # Only blocks that HAVE a layout are asked what structure it has — a block
    # with nothing drawn has no answer to give, and counting it as "did not
    # say" would report the A5 gap twice under two different names.
    disclosures: dict = {}
    for block in blocks:
        status, fs, disc = _check_block(project, block)
        if status != "MISSING":
            disclosures[block] = disc
        if status == "PASS":
            blocks_pass += 1
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_missing": len(missing_seen),
        "blocks_fail": len(findings),
        **_lm.summarise(disclosures),
    }

    rc = _verdict(args, findings, missing_seen, blocks_pass, summary)
    # LAST, and on every path — same contract as `structure_only_disclosure`.
    _lm.matching_disclosure(GATE, disclosures)
    return rc


def _verdict(args, findings: List[dict], missing_seen: List[dict],
             blocks_pass: int, summary: dict) -> int:
    if args.block:
        if findings:
            return emit_fail(GATE, args, findings, summary)
        if missing_seen:
            return artefact_missing_for_block(
                GATE, args, args.block,
                missing_seen[0]["rel_path"], SKILL)
        return emit_pass(GATE, args, summary)

    if findings:
        return emit_fail(GATE, args, findings, summary)
    if missing_seen and blocks_pass == 0:
        return vacuous_pass(GATE, args,
                            f"all {len(missing_seen)} block(s) missing "
                            f"layout artefacts; defer to skill `{SKILL}`.")
    # PARTIAL COVERAGE (d2) — some declared blocks have a layout, others have
    # none at all. This used to fall through to emit_pass, so a project that
    # laid out 1 of N declared analog blocks was CERTIFIED "A5 done": the
    # step's declaration (`phase3/analog/*/layout.mag OR .../*.gds`) is a glob
    # that ONE matching block satisfies, so only this per-block gate can see
    # the uncovered blocks. Refuse to certify; name them instead.
    if missing_seen:
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
