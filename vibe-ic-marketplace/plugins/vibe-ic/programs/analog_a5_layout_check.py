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
(never SKIPs) on a block directory with no evidence. No defect class is
lost — see `programs/tests/test_analog_a5_layout_check.py`, section
"A5 -> A6 PV OWNERSHIP", which re-runs every input this gate used to
reject through the A6 gate and asserts rc=1.

Failure rules:
  A5_LAYOUT_MISSING        — neither layout.mag nor <block>.gds present
  A5_LAYOUT_TOO_SMALL      — layout source < 200 bytes (stub)
  A5_LAYOUT_EMPTY_GEOMETRY — layout source has no placed geometry (empty
                             stream or padded/deterministic stub)

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

import re
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
)

GATE = "analog_a5_layout_check"
SKILL = "analog-layout"
MIN_LAYOUT_BYTES = 200


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


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    bdir = project / "phase3" / "analog" / block
    mag = bdir / "layout.mag"
    gds = bdir / f"{block}.gds"

    findings: List[dict] = []
    layout_path: Optional[Path] = None
    if mag.is_file():
        layout_path = mag
    elif gds.is_file():
        layout_path = gds
    if layout_path is None:
        # Treat as MISSING (not FAIL) so --block mode → WAIVED.
        return "MISSING", [{
            "block": block, "rule": "A5_LAYOUT_MISSING",
            "rel_path": str(bdir.relative_to(project)),
            "detail": "neither layout.mag nor <block>.gds present",
        }]
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
    # NOTE: per-block DRC / LVS sign-off is deliberately NOT judged here —
    # see the module docstring's "SCOPE" section. It is step A6's verdict,
    # over A6's own (richer) evidence, at the point in the flow where that
    # evidence exists.
    if findings:
        return "FAIL", findings
    return "PASS", []


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
    for block in blocks:
        status, fs = _check_block(project, block)
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
    }

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
