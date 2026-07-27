#!/usr/bin/env python3
"""analog_a5_layout_check.py — A5 deterministic gate (v1.6.35).

Verifies that the upstream `analog-layout` skill has emitted the
canonical per-block A5 artefacts:

    analog/<block>/layout.mag   (Magic source) OR
    analog/<block>/<block>.gds  (streamed GDS)
    analog/<block>/drc_clean.flag
    analog/<block>/lvs_match.flag

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
  * `drc_clean.flag` present AND carrying an explicit zero-violation
    verdict (`violations: 0` / `0 errors` / `DRC clean` …). A bare or
    `touch`-created flag is NOT sign-off evidence — this is exactly the
    standard `analog_a6_block_pv_check` already enforces one step later.
  * `lvs_match.flag` present AND carrying an explicit match verdict
    (`lvs: match` / `netlists match` / `match: true` …). Same rule.

Failure rules:
  A5_LAYOUT_MISSING        — neither layout.mag nor <block>.gds present
  A5_LAYOUT_TOO_SMALL      — layout source < 200 bytes (stub)
  A5_LAYOUT_EMPTY_GEOMETRY — layout source has no placed geometry (empty
                             stream or padded/deterministic stub)
  A5_DRC_FLAG_MISSING      — drc_clean.flag absent
  A5_DRC_FLAG_EMPTY        — drc_clean.flag present but empty/whitespace
  A5_DRC_FLAG_NO_EVIDENCE  — drc_clean.flag carries no violation verdict
  A5_DRC_NOT_CLEAN         — drc_clean.flag reports > 0 violations
  A5_LVS_FLAG_MISSING      — lvs_match.flag absent
  A5_LVS_FLAG_EMPTY        — lvs_match.flag present but empty/whitespace
  A5_LVS_FLAG_NO_EVIDENCE  — lvs_match.flag carries no match verdict
  A5_LVS_NOT_MATCH         — lvs_match.flag reports a mismatch

Project-level verdicts (no `--block`):
  VACUOUS_PASS — `analog/analog_block_list.json` missing or empty, or
                 EVERY declared block is still missing its layout (the
                 step has not run at all → defer to skill `analog-layout`).
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
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, write_report,
)

GATE = "analog_a5_layout_check"
SKILL = "analog-layout"
MIN_LAYOUT_BYTES = 200


# ── sign-off flag CONTENT (d5) ─────────────────────────────────────────────
# A5 used to accept `drc_clean.flag` / `lvs_match.flag` on `is_file()` alone,
# so a `touch`-created 0-byte flag certified DRC and LVS sign-off. That is
# weaker than this module's own docstring ("any non-empty file") AND weaker
# than the standard the flow already enforces one step later:
# `analog_a6_block_pv_check` rejects a bare flag with
# "Bare flag with no count line -> NOT acceptable evidence".
# Reuse A6's parsers rather than writing a second dialect of the same rule —
# they are tool-generic (Magic / KLayout / Calibre / Netgen phrasings), so
# this stays chip-AGNOSTIC.
def _load_pv_parsers():
    """Return (parse_drc_count, parse_lvs_match) from the A6 gate, or
    (None, None) when that module cannot be imported. NEVER fail open and
    never turn every block red on an import error: the caller degrades to
    the docstring's stated minimum (a non-empty flag) instead."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import analog_a6_block_pv_check as _a6
        return _a6._parse_drc_count, _a6._parse_lvs_match
    except Exception:  # nosec — degraded mode is handled by the caller
        return None, None


_PARSE_DRC_COUNT, _PARSE_LVS_MATCH = _load_pv_parsers()


def _flag_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _drc_flag_defect(path: Path) -> Optional[tuple[str, str]]:
    """Return (rule, detail) when `drc_clean.flag` is not real DRC sign-off
    evidence, else None."""
    text = _flag_text(path)
    if not text.strip():
        return ("A5_DRC_FLAG_EMPTY",
                "drc_clean.flag is empty/whitespace — DRC was not signed "
                "off, the flag was merely created")
    if _PARSE_DRC_COUNT is None:
        return None  # degraded: non-empty is the documented minimum
    count = _PARSE_DRC_COUNT(text)
    if count is None:
        return ("A5_DRC_FLAG_NO_EVIDENCE",
                "drc_clean.flag carries no DRC verdict; need an explicit "
                "violation count (e.g. `violations: 0`) as A6 requires")
    if count > 0:
        return ("A5_DRC_NOT_CLEAN",
                f"drc_clean.flag reports {count} violation(s) (must be 0)")
    return None


def _lvs_flag_defect(path: Path) -> Optional[tuple[str, str]]:
    """Return (rule, detail) when `lvs_match.flag` is not real LVS sign-off
    evidence, else None."""
    text = _flag_text(path)
    if not text.strip():
        return ("A5_LVS_FLAG_EMPTY",
                "lvs_match.flag is empty/whitespace — LVS was not signed "
                "off, the flag was merely created")
    if _PARSE_LVS_MATCH is None:
        return None  # degraded: non-empty is the documented minimum
    matched = _PARSE_LVS_MATCH(text)
    if matched is None:
        return ("A5_LVS_FLAG_NO_EVIDENCE",
                "lvs_match.flag carries no LVS verdict; need an explicit "
                "match line (e.g. `lvs: match`) as A6 requires")
    if matched is False:
        return ("A5_LVS_NOT_MATCH",
                "lvs_match.flag reports a mismatch (must be a match)")
    return None


def emit_incomplete(gate: str, args, missing: List[dict],
                    summary: dict) -> int:
    """Project-level INCOMPLETE (exit 1): some declared blocks produced a
    layout and others produced none. A gate may EXPLAIN an absent artefact
    (the all-missing VACUOUS_PASS below does exactly that, naming the
    upstream skill) but it may not CERTIFY the step done without one — so
    partial coverage is neither PASS nor a deferral.

    Kept local to this gate on purpose: the same helper is being added to
    `_analog_a_check_common` by the sibling A2/A4 fixes, and duplicating a
    9-line emitter is cheaper than three branches conflicting on one shared
    file. Dedupe into the shared module once those land."""
    report = {
        "gate": gate,
        "verdict": "INCOMPLETE",
        **summary,
        "findings": missing,
    }
    write_report(args.json, report)
    blocks = ", ".join(sorted({str(f.get("block", "?")) for f in missing}))
    print(f"INCOMPLETE: {gate} — "
          f"{summary.get('blocks_pass', 0)}/"
          f"{summary.get('blocks_checked', 0)} block(s) clean, "
          f"{len(missing)} declared block(s) produced NO layout at all "
          f"[{blocks}] — cannot certify A5; invoke skill `{SKILL}` for "
          f"the uncovered block(s)", file=sys.stderr)
    return 1


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
    drc_flag = bdir / "drc_clean.flag"
    lvs_flag = bdir / "lvs_match.flag"

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
    if not drc_flag.is_file():
        findings.append({
            "block": block, "rule": "A5_DRC_FLAG_MISSING",
            "rel_path": str(drc_flag.relative_to(project)),
            "detail": "drc_clean.flag absent (DRC not signed off)",
        })
    else:
        defect = _drc_flag_defect(drc_flag)
        if defect is not None:
            findings.append({
                "block": block, "rule": defect[0],
                "rel_path": str(drc_flag.relative_to(project)),
                "detail": defect[1],
            })
    if not lvs_flag.is_file():
        findings.append({
            "block": block, "rule": "A5_LVS_FLAG_MISSING",
            "rel_path": str(lvs_flag.relative_to(project)),
            "detail": "lvs_match.flag absent (LVS not signed off)",
        })
    else:
        defect = _lvs_flag_defect(lvs_flag)
        if defect is not None:
            findings.append({
                "block": block, "rule": defect[0],
                "rel_path": str(lvs_flag.relative_to(project)),
                "detail": defect[1],
            })
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
                            "phase3/analog/analog_block_list.json missing or "
                            "empty; gate inapplicable.")

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
        return emit_incomplete(GATE, args, missing_seen, summary)
    return emit_pass(GATE, args, summary)


if __name__ == "__main__":
    sys.exit(main())
