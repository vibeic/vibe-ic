#!/usr/bin/env python3
"""synth_area_stats_emit.py — publish the synthesis area figure as an artefact.

WHAT GAP THIS CLOSES
--------------------
The flow's synthesis step declares an area artefact
(`<synth>/area.rpt OR <synth>/stats.json`) and nothing ever wrote either one,
so every published cell that shipped a mapped netlist shipped no area figure.
The number was never actually missing: a liberty-aware `stat` pass already
prints it into the synthesis log. It was simply never lifted out into the
declared artefact.

Two properties make the naive lift wrong, and both are enforced here.

1. A SYNTHESIS LOG CARRIES MANY AREA LINES AND MOST OF THEM ARE NOT THE ANSWER.
   The statistics pass emits one block per selected module, and each block's
   figure is that module's LOCAL area, EXCLUDING its submodules. A top module
   whose logic all lives in children therefore prints `0.000000`. When a top
   module is known, the pass appends a `design hierarchy` roll-up block whose
   figure INCLUDES submodules — that, and only that, is the design total.
   Measured on a purpose-built three-level hierarchy: the per-module lines read
   0.0 / 0.0 / 28.7776 while the true total was 115.1104, so "take the last
   area line", "take the biggest" and "take the line naming the top module" all
   return a confidently wrong number. The rule below keys on the roll-up's
   distinct wording instead of on position.

2. THE LOG IS APPEND-ONLY ACROSS FRONTEND RETRIES. A run that falls back to a
   different HDL frontend concatenates each attempt's full transcript into one
   file, so a log can hold several complete statistics sections from several
   different elaborations of the same design.

REFUSAL IS A RESULT
-------------------
When the log holds several distinct per-module figures and NO roll-up, the
design total is not present in the log at all and every candidate is wrong.
This program then writes NOTHING and reports the refusal. Emitting the
artefact with a null area would satisfy the step's existence check while
carrying no number — that would switch off the very signal the check exists to
raise, so absence is preserved deliberately.

CORROBORATION (a wrong pick must be REFUTABLE, not merely unlikely)
-------------------------------------------------------------------
The selected figure is checked against two independent sources and is
discarded unless both agree:

  R1 INTERNAL — the block prints a per-cell-type area column. Those rows must
     sum to the figure. A figure lifted from a different block than the rows
     fails this.
  R2 EXTERNAL — the block prints a per-cell-type COUNT column. The netlist the
     same statistics pass produced must instantiate exactly those cells, that
     many times. This is the independent artefact: it is written by a
     different pass, from the same in-memory design.

     R2 compares a per-module count column against a per-module netlist, so it
     applies only when the netlist holds ONE module (the flattened shape this
     flow synthesises). A multi-module netlist counts each module's body once
     while the roll-up counts every instance, so the two are not comparable and
     R2 records itself as not applicable rather than pretending to agree.

chip/PDK-AGNOSTIC: every module name, cell name and figure is read out of the
caller's log and netlist. No design, vendor, foundry or library literal appears
here; the parser keys only on the synthesis tool's own output wording.

    synth_area_stats_emit <project_dir> [--log L] [--netlist N] [--top T]
                          [--out O] [--json J]
    main(argv) -> int : 0 emitted / 2 disclosed refusal (nothing written)
                        1 error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover - direct-script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _path_layout as _pl

# The identity binding is SHARED with the other producer of this same declared
# artefact (`_yosys_stat`, which the phase-2 synth step uses). Both write
# `<synth>/stats.json`, so a consumer must be able to check the binding without
# first working out which of them wrote the file — one helper, one field name,
# no schema drift. The digest algorithm and the field name live there.
import _yosys_stat as _ystat

SCHEMA = "vibe-ic/synth-stats/1"

# A statistics block header, e.g. "=== some_module ===".
_RE_BLOCK = re.compile(r"^=== (.+?) ===\s*$")
# The roll-up block's header uses this reserved name rather than a module name.
_ROLLUP_BLOCK = "design hierarchy"
# The area line. The `top ` group is what distinguishes the design roll-up
# (area INCLUDING submodules) from a per-module local figure (EXCLUDING them).
_RE_AREA = re.compile(
    r"Chip area for (?P<top>top )?module '\\?(?P<mod>[^']+)': (?P<val>[0-9.]+)")
_RE_SEQ = re.compile(
    r"of which used for sequential elements: (?P<val>[0-9.]+)")
# A tabulated row: "<count> <area-or-dash> <name>". Pseudo-cells that the
# library prices nothing for print "-" in the area column; they are counted
# but contribute no area, and both facts are needed to prove the per-type list
# was read COMPLETELY (see the completeness check in `corroborate`).
_RE_ROW = re.compile(
    r"^\s+(?P<n>\d+)\s+(?P<area>-|[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?\d+)?)"
    r"\s+(?P<cell>[A-Za-z_$][A-Za-z0-9_$.\\/]*)\s*$")
# The block's own summary row. The per-type rows belong to it and the tool
# indents them one nesting level deeper; SIBLING summaries (other categories
# the same block tabulates) return to this row's own indent. That indent is
# therefore the terminator, which is why the column is captured here.
_RE_CELLS = re.compile(
    r"^\s+(?P<n>\d+)\s+(?P<area>-|[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?\d+)?)"
    r"\s+cells\s*$")
# The netlist the same invocation wrote, named in the tool's echoed command.
_RE_WRITE_V = re.compile(r"write_verilog[^;']*?\s(?P<path>[^\s;']+\.v)\b")
_RE_TOOL_VER = re.compile(r"^\s*(?P<v>Yosys [^\r\n]+?)\s*$", re.M)

# Relative agreement band for R1. The per-type area column is printed at
# limited significant width (and switches to exponent form on large designs),
# so the row sum can never be bit-exact against the full-precision figure. A
# figure lifted from the WRONG block differs by a factor, not by rounding.
_R1_REL_TOL = 0.02
_R1_ABS_FLOOR = 1.0


class Block:
    """One statistics block: its header, its per-type rows and its area line."""

    __slots__ = ("name", "rows", "unpriced", "cells_n", "area",
                 "area_is_rollup", "area_module", "area_line_no",
                 "area_line_text", "seq_area")

    def __init__(self, name: str) -> None:
        self.name = name
        # priced per-type rows: (count, area, cell_type)
        self.rows: List[Tuple[int, float, str]] = []
        # rows the library prices nothing for: (count, cell_type)
        self.unpriced: List[Tuple[int, str]] = []
        self.cells_n: Optional[int] = None
        self.area: Optional[float] = None
        self.area_is_rollup = False
        self.area_module: Optional[str] = None
        self.area_line_no: Optional[int] = None
        self.area_line_text: Optional[str] = None
        self.seq_area: Optional[float] = None

    @property
    def row_area_sum(self) -> float:
        return sum(r[1] for r in self.rows)

    @property
    def row_cell_sum(self) -> int:
        return sum(r[0] for r in self.rows)

    @property
    def tabulated_cell_sum(self) -> int:
        """Every cell the block tabulated, priced or not."""
        return self.row_cell_sum + sum(n for n, _c in self.unpriced)


def parse_blocks(text: str) -> List[Block]:
    """Split a synthesis log into statistics blocks that carry an area figure.

    Blocks without an area line (the tool also runs a statistics pass with no
    library loaded, which prints counts only) are dropped: they hold no figure
    to select and must not dilute the ambiguity test.
    """
    blocks: List[Block] = []
    cur: Optional[Block] = None
    # Column at which the governing summary row's noun starts. Rows nested
    # deeper than this belong to it; a row returning to this column starts a
    # sibling category and ends the list. -1 means "not collecting".
    name_col = -1
    for i, line in enumerate(text.splitlines(), start=1):
        mh = _RE_BLOCK.match(line)
        if mh:
            cur = Block(mh.group(1).strip())
            blocks.append(cur)
            name_col = -1
            continue
        if cur is None:
            continue
        mc = _RE_CELLS.match(line)
        if mc:
            cur.cells_n = int(mc.group("n"))
            cur.rows = []
            cur.unpriced = []
            name_col = line.rindex("cells")
            continue
        ma = _RE_AREA.search(line)
        if ma:
            cur.area = float(ma.group("val"))
            cur.area_is_rollup = bool(ma.group("top"))
            cur.area_module = ma.group("mod")
            cur.area_line_no = i
            cur.area_line_text = line.rstrip("\n")
            name_col = -1
            continue
        ms = _RE_SEQ.search(line)
        if ms and cur.area is not None and cur.seq_area is None:
            cur.seq_area = float(ms.group("val"))
            continue
        if name_col >= 0:
            mr = _RE_ROW.match(line)
            if not mr:
                continue
            col = mr.start("cell")
            if col <= name_col:
                # Sibling category summary — the per-type list is over.
                name_col = -1
                continue
            if mr.group("area") == "-":
                cur.unpriced.append((int(mr.group("n")), mr.group("cell")))
            else:
                cur.rows.append(
                    (int(mr.group("n")), float(mr.group("area")),
                     mr.group("cell")))
    return [b for b in blocks if b.area is not None]


def select_block(blocks: List[Block]) -> Tuple[Optional[Block], str, str]:
    """Apply the validated selection rule.

    Returns (block, rule, note). `block` is None when the design total is not
    recoverable from this log, in which case `rule` names the refusal.
    """
    if not blocks:
        return None, "NO_AREA_IN_LOG", (
            "the log holds no area figure at all — the synthesis script ran "
            "its statistics pass without a cell library, so no area was ever "
            "computed")
    rollups = [b for b in blocks if b.area_is_rollup]
    if rollups:
        # The roll-up INCLUDES submodules and is the design total. Several
        # exist when the log concatenates frontend retries; the last one
        # belongs to the elaboration that produced the surviving netlist, and
        # R2 refutes that assumption if it is wrong.
        return rollups[-1], "DESIGN_HIERARCHY_ROLLUP", (
            "selected the roll-up block, whose figure includes submodules")
    names = {b.area_module for b in blocks}
    if len(names) == 1:
        # No roll-up is printed when the design collapsed to a single module,
        # because there is no hierarchy to roll up. Local area is then the
        # total. Repeats are retries of that same single module.
        return blocks[-1], "SINGLE_MODULE_NO_HIERARCHY", (
            "no roll-up block exists because the design holds one module, so "
            "its local figure is the total")
    return None, "AMBIGUOUS_LOCAL_AREAS_NO_ROLLUP", (
        "the log holds per-module local figures for "
        f"{len(names)} distinct modules and no roll-up block. Each figure "
        "EXCLUDES submodules, so none of them is the design total and the "
        "total is not present in this log")


def count_netlist_cells(netlist_text: str,
                        cell_types: List[str]) -> Tuple[Dict[str, int], int]:
    """Count instantiations of each named cell type in a structural netlist."""
    per: Dict[str, int] = {}
    for cell in cell_types:
        per[cell] = len(re.findall(
            r"^[ \t]*" + re.escape(cell) + r"[ \t]+\S+[ \t]*\(", netlist_text,
            re.M))
    return per, sum(per.values())


def count_netlist_modules(netlist_text: str) -> int:
    return len(re.findall(r"^\s*module\s+\S+", netlist_text, re.M))


def corroborate(block: Block, netlist_path: Optional[Path]) -> Dict[str, Any]:
    """Run R1 and R2 against the selected block."""
    out: Dict[str, Any] = {}
    # -- R0: the per-type list must have been read COMPLETELY. The block
    # states how many cells it tabulated; if the rows actually parsed do not
    # add up to that, the list was truncated or mis-read and every figure
    # derived from it is untrustworthy. Without this, a parser that silently
    # collected NO rows would make R1 and R2 compare zero against zero and
    # report agreement — a vacuous pass that proves nothing.
    out["r0_completeness"] = {
        "what": "rows parsed out of the block against the count the block "
                "states it tabulated",
        "stated_cells": block.cells_n,
        "parsed_priced": block.row_cell_sum,
        "parsed_unpriced": sum(n for n, _c in block.unpriced),
        "parsed_total": block.tabulated_cell_sum,
        "status": ("AGREE"
                   if (block.cells_n is not None and block.rows
                       and block.tabulated_cell_sum == block.cells_n)
                   else "REFUTED"),
    }
    # -- R1: the per-type area column must sum to the selected figure.
    row_sum = block.row_area_sum
    tol = max(_R1_ABS_FLOOR, _R1_REL_TOL * (block.area or 0.0))
    delta = abs(row_sum - (block.area or 0.0))
    out["r1_internal"] = {
        "what": "per-cell-type area column summed against the selected figure",
        "row_area_sum": round(row_sum, 6),
        "selected_area": block.area,
        "delta": round(delta, 6),
        "tolerance": round(tol, 6),
        # No rows is NOT "not applicable" — it is a failure to corroborate.
        "status": "AGREE" if (block.rows and delta <= tol) else "REFUTED",
    }
    # -- R2: the netlist that the same statistics pass's design produced.
    r2: Dict[str, Any] = {
        "what": "per-cell-type count column against instantiations in the "
                "netlist the same invocation wrote",
    }
    if not block.rows:
        r2["status"] = "REFUTED"
        r2["reason"] = ("no per-cell-type rows were parsed, so there is "
                        "nothing to compare against the netlist")
    elif netlist_path is None or not netlist_path.is_file():
        r2["status"] = "NOT_APPLICABLE"
        r2["reason"] = "no netlist available to compare against"
    else:
        ntext = netlist_path.read_text(errors="replace")
        nmods = count_netlist_modules(ntext)
        r2["netlist"] = netlist_path.name
        r2["netlist_modules"] = nmods
        if nmods != 1:
            r2["status"] = "NOT_APPLICABLE"
            r2["reason"] = (
                "the netlist holds more than one module, so its textual "
                "instantiation counts are per-module while the selected "
                "block's counts include every instance — the two are not "
                "comparable")
        else:
            per, total = count_netlist_cells(ntext, [r[2] for r in block.rows])
            mism = {c: {"block": n, "netlist": per[c]}
                    for n, _a, c in block.rows if per[c] != n}
            r2["block_cell_count"] = block.row_cell_sum
            r2["netlist_instantiations"] = total
            r2["status"] = "AGREE" if not mism else "REFUTED"
            if mism:
                r2["mismatches"] = dict(sorted(mism.items())[:20])
    out["r2_external"] = r2
    return out


def _project_relative(path: Optional[Path], root: Path) -> Optional[str]:
    """``path`` spelled relative to ``root`` when it lives under it, else its
    own string. ``None`` stays ``None`` — an unresolved netlist is recorded as
    absent, not as an empty path."""
    if path is None:
        return None
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def resolve_netlist(text: str, log_path: Path,
                    explicit: Optional[Path]) -> Optional[Path]:
    """Find the netlist the log's own write pass named.

    Self-anchoring on purpose: the synthesis directory can hold a netlist left
    by a DIFFERENT and older tool invocation, and comparing against that one
    would refute a correct figure. Measured on a published cell whose
    directory held both a current netlist and a stale one from an older tool
    version — the stale one disagreed on every cell type.
    """
    if explicit is not None:
        return explicit
    hits = _RE_WRITE_V.findall(text)
    for cand in reversed(hits):
        p = Path(cand)
        local = log_path.parent / p.name
        if local.is_file():
            return local
        if p.is_file():
            return p
    return None


def build_report(project: Path, log_path: Path,
                 netlist: Optional[Path]) -> Tuple[Optional[Dict[str, Any]],
                                                   Dict[str, Any]]:
    text = log_path.read_text(errors="replace")
    blocks = parse_blocks(text)
    block, rule, note = select_block(blocks)
    diag: Dict[str, Any] = {
        "log": str(log_path),
        "area_blocks_found": len(blocks),
        "candidates": [
            {"block": b.name, "module": b.area_module, "area": b.area,
             "includes_submodules": b.area_is_rollup, "line": b.area_line_no}
            for b in blocks],
        "rule": rule,
        "note": note,
    }
    if block is None:
        return None, diag
    nl = resolve_netlist(text, log_path, netlist)
    checks = corroborate(block, nl)
    diag["corroboration"] = checks
    refuted = [k for k, v in checks.items() if v.get("status") == "REFUTED"]
    if refuted:
        diag["rule"] = "REFUTED_BY_CORROBORATION"
        diag["note"] = (
            "a figure was selected but an independent source disagreed with "
            f"it ({', '.join(refuted)}), so it was discarded")
        return None, diag
    mver = _RE_TOOL_VER.search(text)
    # IDENTITY BINDING. This artefact shares a path with `_yosys_stat`'s, and a
    # consumer that finds it beside a netlist has no way to tell whether the
    # figure was measured on THAT netlist or on the one a previous pass wrote
    # to the same name. The digest of the file R2 corroborated against is what
    # makes the question answerable; the name alone cannot answer it, and a
    # byte-identical alias under a second name is not a different design.
    # `None` when there was no netlist to hash — an absent binding, never a
    # stand-in value.
    report = {
        "schema": SCHEMA,
        "netlist": _project_relative(nl, project),
        _ystat.NETLIST_DIGEST_FIELD: _ystat.netlist_digest(nl),
        "top_module": block.area_module,
        # Unit is whatever the cell library declares; the tool prints the
        # figure in the library's own area unit and does not restate it, so
        # naming a concrete unit here would be an invention.
        "chip_area": block.area,
        "chip_area_unit": "cell-library area unit (as declared by the "
                          "library the synthesis script loaded)",
        "sequential_area": block.seq_area,
        "cell_count": block.row_cell_sum,
        "cell_types": len(block.rows),
        "includes_submodules": block.area_is_rollup,
        "selection": {
            "rule": rule,
            "why": note,
            "source_log": log_path.name,
            "source_line": block.area_line_no,
            "source_text": block.area_line_text,
            "source_block": block.name,
            "area_lines_in_log": len(blocks),
        },
        "corroboration": checks,
        "tool_version": mver.group("v") if mver else None,
    }
    return report, diag


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit the synthesis area figure as a published artefact.")
    ap.add_argument("project")
    ap.add_argument("--log", default=None,
                    help="synthesis log (default: discover in the synth dir)")
    ap.add_argument("--netlist", default=None,
                    help="netlist to corroborate against (default: the one "
                         "the log's own write pass named)")
    ap.add_argument("--out", default=None,
                    help="artefact path (default: <synth>/stats.json)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the full diagnostic report here")
    a = ap.parse_args(argv)

    project = Path(a.project)
    synth = _pl.synth_dir(project)
    if a.log:
        log_path = Path(a.log)
    else:
        cands = sorted(p for p in synth.glob("*.log") if p.is_file())
        # Prefer a log that actually carries an area figure.
        withval = [p for p in cands
                   if "Chip area for" in p.read_text(errors="replace")]
        log_path = (withval[-1] if withval else (cands[-1] if cands else None))
    if log_path is None or not log_path.is_file():
        print(f"[synth-stats] no synthesis log under {synth} — nothing to "
              f"emit", file=sys.stderr)
        return 2

    report, diag = build_report(
        project, log_path, Path(a.netlist) if a.netlist else None)
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(diag, indent=2) + "\n")
    if report is None:
        print(f"[synth-stats] REFUSED to emit: {diag['note']} "
              f"(rule={diag['rule']}, candidates={diag['area_blocks_found']})",
              file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else (synth / "stats.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"[synth-stats] {out} area={report['chip_area']} "
          f"top={report['top_module']} rule={report['selection']['rule']} "
          f"line={report['selection']['source_line']}")
    return 0


def emit_for_run(project: Path, log_path: Path,
                 netlist: Optional[Path] = None) -> Optional[Path]:
    """In-run entry point. Returns the artefact path, or None if refused.

    The artefact must be produced DURING the run: the synthesis log is a
    working file that publication does not necessarily carry, so a tool that
    scrapes it after the fact works where the run happened and finds nothing
    in a fresh clone.
    """
    try:
        report, _diag = build_report(project, log_path, netlist)
        if report is None:
            return None
        out = _pl.synth_dir(project) / "stats.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")
        return out
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
