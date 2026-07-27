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
  * ZERO-violation DRC evidence for the block, read with the SAME
    EVIDENCE PRECEDENCE `analog_a6_block_pv_check` uses one step later:
    a DRC report (`drc.report` / `*.drc.report` / `*.lyrdb` / `drc.rpt`
    / `*.drc`) FIRST, and only then `drc_clean.flag` — the flag counting
    solely when it carries an explicit violation count (`violations: 0`
    / `0 errors` / `DRC clean` …). A bare or `touch`-created flag with
    no DRC report beside it is NOT sign-off evidence.
  * MATCH LVS evidence with the same precedence: `comp.json`, then
    `lvs.report` / `*.lvs.report` / `lvs.rpt` / `comp.out` / `*.lvs`,
    then `lvs_match.flag` carrying an explicit match verdict
    (`lvs: match` / `netlists match` / `match: true` …).

    A5 delegates BOTH to A6's own `_drc_violations` / `_lvs_match`, so
    the two gates can never disagree about the same block directory.
    Reading the flag ALONE (v1.7.49–v1.7.58) made A5 red a block whose
    PV evidence lived in the report files A6 prefers, while A6 stayed
    green on the same directory — a blocking false-fail, since A5's flow
    leg is a `program_exit_zero` inside `all_of`.

Failure rules:
  A5_LAYOUT_MISSING        — neither layout.mag nor <block>.gds present
  A5_LAYOUT_TOO_SMALL      — layout source < 200 bytes (stub)
  A5_LAYOUT_EMPTY_GEOMETRY — layout source has no placed geometry (empty
                             stream or padded/deterministic stub)
  A5_DRC_FLAG_MISSING      — no DRC report AND no drc_clean.flag
  A5_DRC_FLAG_EMPTY        — no DRC report and drc_clean.flag is
                             empty/whitespace
  A5_DRC_FLAG_NO_EVIDENCE  — no DRC report and drc_clean.flag carries no
                             violation verdict
  A5_DRC_NOT_CLEAN         — the winning DRC evidence reports > 0
                             violations
  A5_LVS_FLAG_MISSING      — no LVS report/comp.json AND no lvs_match.flag
  A5_LVS_FLAG_EMPTY        — no LVS report and lvs_match.flag is
                             empty/whitespace
  A5_LVS_FLAG_NO_EVIDENCE  — no LVS report and lvs_match.flag carries no
                             match verdict
  A5_LVS_NOT_MATCH         — the winning LVS evidence reports a mismatch

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


# ── per-block DRC / LVS SIGN-OFF EVIDENCE (d5 + its follow-up) ─────────────
# A5 used to accept `drc_clean.flag` / `lvs_match.flag` on `is_file()` alone,
# so a `touch`-created 0-byte flag certified DRC and LVS sign-off. That is
# weaker than this module's own docstring ("any non-empty file") AND weaker
# than the standard the flow enforces one step later.
#
# v1.7.49 (PR #464) closed that by parsing the FLAG's content with A6's
# parsers — but justified it as "exactly the standard A6 already enforces",
# which was NOT true: A6 reads the block's TOOL REPORTS first
# (`_drc_violations` / `_lvs_match` walk drc.report / *.lyrdb / comp.json /
# lvs.report …) and treats the flag only as a LAST-RESORT fallback. Reading
# the flag alone therefore turned a block whose PV evidence lives in those
# reports RED at A5 while A6 stayed GREEN on the same directory — a blocking
# false-fail, because A5's flow leg is a `program_exit_zero` inside `all_of`.
#
# So A5 now borrows A6's whole EVIDENCE RESOLVER, not just its string
# parsers: one gate cannot contradict the other about one directory, and the
# accepted phrasings stay tool-generic (Magic / KLayout / Calibre / Netgen),
# so this stays chip-AGNOSTIC.
def _load_pv_evidence_readers():
    """Return (drc_violations, lvs_match) — A6's per-block EVIDENCE readers,
    each `(block_dir) -> (verdict|None, evidence_filename)` — or
    (None, None) when that module cannot be imported. NEVER fail open and
    never turn every block red on an import error: the caller degrades to
    the docstring's stated minimum (a non-empty flag) instead."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import analog_a6_block_pv_check as _a6
        return _a6._drc_violations, _a6._lvs_match
    except Exception:  # nosec — degraded mode is handled by the caller
        return None, None


_DRC_VIOLATIONS, _LVS_MATCH = _load_pv_evidence_readers()


def _flag_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _no_evidence_defect(flag: Path, kind: str, reports: str
                        ) -> tuple[str, str, Path]:
    """Classify WHY a block has no acceptable {DRC,LVS} evidence, keeping the
    absent-vs-contentless split so a finding still tells an operator whether
    to RUN the tool or to FIX its output."""
    prefix = "A5_DRC" if kind == "DRC" else "A5_LVS"
    verdict_hint = ("an explicit violation count (e.g. `violations: 0`)"
                    if kind == "DRC"
                    else "an explicit match line (e.g. `lvs: match`)")
    if not flag.is_file():
        return (f"{prefix}_FLAG_MISSING",
                f"no {kind} evidence for this block: neither a {kind} report "
                f"({reports}) nor {flag.name} — {kind} was not signed off",
                flag)
    if not _flag_text(flag).strip():
        return (f"{prefix}_FLAG_EMPTY",
                f"{flag.name} is empty/whitespace and no {kind} report "
                f"({reports}) sits beside it — {kind} was not signed off, "
                f"the flag was merely created",
                flag)
    return (f"{prefix}_FLAG_NO_EVIDENCE",
            f"{flag.name} carries no {kind} verdict and no {kind} report "
            f"({reports}) sits beside it; supply either, or put "
            f"{verdict_hint} in the flag",
            flag)


_DRC_REPORT_SHAPES = "drc.report / *.drc.report / *.lyrdb / drc.rpt / *.drc"
_LVS_REPORT_SHAPES = "comp.json / lvs.report / *.lvs.report / lvs.rpt / *.lvs"


def _drc_defect(bdir: Path) -> Optional[tuple[str, str, Path]]:
    """Return (rule, detail, evidence_path) when a block has no zero-violation
    DRC sign-off, else None. Evidence precedence is A6's (report first, flag
    last), delegated to A6's own resolver so the two gates agree."""
    flag = bdir / "drc_clean.flag"
    if _DRC_VIOLATIONS is None:
        # Degraded: A6 unavailable → the docstring's stated minimum applies.
        # Still never fails OPEN on an absent/0-byte flag.
        if not flag.is_file() or not _flag_text(flag).strip():
            return _no_evidence_defect(flag, "DRC", _DRC_REPORT_SHAPES)
        return None
    count, evidence = _DRC_VIOLATIONS(bdir)
    if count is None:
        return _no_evidence_defect(flag, "DRC", _DRC_REPORT_SHAPES)
    if count > 0:
        return ("A5_DRC_NOT_CLEAN",
                f"{evidence} reports {count} violation(s) (must be 0)",
                bdir / evidence)
    return None


def _lvs_defect(bdir: Path) -> Optional[tuple[str, str, Path]]:
    """Return (rule, detail, evidence_path) when a block has no LVS-match
    sign-off, else None. Same A6 evidence precedence as `_drc_defect`."""
    flag = bdir / "lvs_match.flag"
    if _LVS_MATCH is None:
        if not flag.is_file() or not _flag_text(flag).strip():
            return _no_evidence_defect(flag, "LVS", _LVS_REPORT_SHAPES)
        return None
    matched, evidence = _LVS_MATCH(bdir)
    if matched is None:
        return _no_evidence_defect(flag, "LVS", _LVS_REPORT_SHAPES)
    if matched is False:
        return ("A5_LVS_NOT_MATCH",
                f"{evidence} reports a mismatch (must be a match)",
                bdir / evidence)
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
    for defect in (_drc_defect(bdir), _lvs_defect(bdir)):
        if defect is None:
            continue
        rule, detail, evidence = defect
        findings.append({
            "block": block, "rule": rule,
            "rel_path": str(evidence.relative_to(project)),
            "detail": detail,
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
