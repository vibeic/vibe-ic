#!/usr/bin/env python3
"""_yosys_stat.py — parse a yosys ``stat`` design summary out of a synth log.

WHY THIS EXISTS
---------------
`flow/phase1_phase2_phase3.yaml` step 9 (Synthesis) declares

    phase2/stage2/synth/area.rpt OR phase2/stage2/synth/stats.json

as a required output.  A whole-tree grep on v1.7.36 found ZERO producers for
either path under ``phase2/stage2/synth`` — every ``area.rpt`` in the plugin is
the phase-3 OpenROAD one (``report_design_area > phase3/stage3/pnr/area.rpt``).
So the declared artefact was unproducible and, after #455 made
``required_outputs`` ALL-of-N, step 9 reports MISSING on every run no matter how
well synthesis went (measured on ~/campaign_pr427/spm/converge_ihp-sg13g2).

The measurement itself was never missing — both synth producers already run
yosys ``stat`` and both already keep the log.  It was simply never persisted in
a machine-readable form.  This module is the shared parser, so
`design_one_shot_runner.step_yosys_synth` (generic mapping) and
`phase3_one_shot_runner.step_synth` (liberty mapping) emit the SAME schema.

ANTI-FABRICATION CONTRACT
-------------------------
``parse_stat_block`` returns ``None`` when the log carries no yosys stat count
line at all.  Callers MUST NOT write ``stats.json`` in that case: a synth pass
whose stdout capture came back empty (the docker-fallback path can return rc=0
with nothing captured) has measured NOTHING, and a zeroed stats.json would flip
step 9 from an honest MISSING to a PASS on an unmeasured synthesis.  ``None``
means "no measurement", which is different from a measured zero.

FORMAT COVERAGE
---------------
yosys prints the ``stat`` summary in three interchangeable shapes depending on
build and on whether ``-liberty`` was passed:

    Number of cells:               446        (classic labelled form)
          446 cells                           (bare form, no liberty)
          349 5.84E+03 cells                  (liberty form: count + area col)

plus, with ``-liberty``, a design-area line:

       Chip area for module '\\spm': 5841.196200

All three count forms and the area line are parsed here.  chip-AGNOSTIC: pure
yosys-output-format parsing, no chip / PDK / vendor literal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# `=== <module> ===` section header that opens each per-module stat block.
_MODULE_RE = re.compile(r"^\s*===\s+(\S+)\s+===\s*$", re.M)
# `Number of cells:  NNNN`
_LABELLED_CELLS_RE = re.compile(r"^\s*Number of cells:\s*([0-9][0-9,]*)\s*$", re.M)
# `   NNNN cells` and the liberty `   NNNN 5.84E+03 cells` variant.
_BARE_CELLS_RE = re.compile(
    r"^\s*([0-9][0-9,]*)\s+(?:[0-9][0-9.eE+-]*\s+)?cells\s*$", re.M)
# `   Chip area for module '\top': 5841.196200`
_CHIP_AREA_RE = re.compile(
    r"^\s*Chip area for module\s+'\\?([^']+)':\s*([0-9][0-9.eE+-]*)\s*$", re.M)
# One histogram row: `   64 3.14E+03   sg13g2_dfrbpq_1` / `   64   $_DFF_P_`
_HISTOGRAM_RE = re.compile(
    r"^\s+([0-9][0-9,]*)\s+(?:[0-9][0-9.eE+-]*\s+)?"
    r"([\\$A-Za-z_][\w$\\.:\[\]-]*)\s*$")

# Stat metric rows that are NOT cell types (they share the histogram shape).
_NOT_A_CELL = frozenset({
    "wires", "bits", "ports", "cells", "memories", "processes",
})


def _to_int(raw: str) -> Optional[int]:
    try:
        return int(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _last_module_name(text: str) -> Optional[str]:
    names = _MODULE_RE.findall(text)
    return names[-1] if names else None


def _cell_count(text: str) -> Tuple[Optional[int], Optional[str]]:
    """(count, which-form-matched). Prefers the labelled form; falls back to
    the bare / liberty-annotated form. Returns the LAST match — yosys prints
    the design-level summary last."""
    labelled = _LABELLED_CELLS_RE.findall(text)
    if labelled:
        return _to_int(labelled[-1]), "number_of_cells"
    bare = _BARE_CELLS_RE.findall(text)
    if bare:
        return _to_int(bare[-1]), "bare_cells_line"
    return None, None


def _histogram(text: str) -> Dict[str, int]:
    """Cell-type histogram from the LAST stat block. Only rows AFTER that
    block's `cells` summary line are considered, so the `wires` / `ports`
    metric rows above it cannot masquerade as cell types."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if _BARE_CELLS_RE.match(ln) or _LABELLED_CELLS_RE.match(ln):
            start = i + 1
    if start is None:
        return {}
    hist: Dict[str, int] = {}
    for ln in lines[start:]:
        if not ln.strip():
            break
        m = _HISTOGRAM_RE.match(ln)
        if not m:
            break
        name = m.group(2)
        if name.lower() in _NOT_A_CELL:
            continue
        n = _to_int(m.group(1))
        if n is not None:
            hist[name] = hist.get(name, 0) + n
    return hist


def _stat_block_tail(text: str, max_lines: int = 60) -> List[str]:
    """The tail of the LAST `=== <module> ===` section, verbatim, so a reviewer
    can check the parsed numbers against the tool's own words."""
    idx = None
    for m in _MODULE_RE.finditer(text):
        idx = m.start()
    if idx is None:
        return []
    return text[idx:].splitlines()[:max_lines]


def parse_stat_block(text: str) -> Optional[Dict[str, Any]]:
    """Parse the last yosys ``stat`` summary in ``text``.

    Returns ``None`` when no cell-count line is present at all (NO MEASUREMENT
    — the caller must not write a stats artefact). Otherwise a dict with:

        cells             int    — cell count from the tool's own stat line
        cells_source      str    — which stat line form was parsed
        top_module        str|None
        chip_area_um2     float|None  — only present with `stat -liberty`
        cell_histogram    {cell_type: count}
        stat_block        [str]  — verbatim tail of the parsed block
    """
    if not text:
        return None
    cells, source = _cell_count(text)
    if cells is None:
        return None
    out: Dict[str, Any] = {
        "cells": cells,
        "cells_source": source,
        "top_module": _last_module_name(text),
        "chip_area_um2": None,
        "cell_histogram": _histogram(text),
        "stat_block": _stat_block_tail(text),
    }
    areas = _CHIP_AREA_RE.findall(text)
    if areas:
        mod, val = areas[-1]
        try:
            out["chip_area_um2"] = float(val)
        except ValueError:
            out["chip_area_um2"] = None
        if out["top_module"] is None:
            out["top_module"] = mod
    return out


def build_stats_payload(text: str, *, log_rel: str, netlist_rel: str,
                        tool: str, frontend: Optional[str] = None,
                        liberty: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """`parse_stat_block` + the provenance fields step 9 needs, or None.

    ``None`` propagates the anti-fabrication contract: no stat block parsed →
    no artefact written → step 9 stays honestly MISSING."""
    parsed = parse_stat_block(text)
    if parsed is None:
        return None
    payload: Dict[str, Any] = dict(parsed)
    payload["tool"] = tool
    payload["measured_from"] = log_rel
    payload["netlist"] = netlist_rel
    if frontend:
        payload["synth_frontend"] = frontend
    if liberty:
        payload["liberty"] = liberty
    return payload


STATS_FILENAME = "stats.json"


def emit_stats_json(synth_dir: Path, text: str, **prov: Any) -> Optional[Path]:
    """Write ``<synth_dir>/stats.json`` from a yosys log capture, or nothing.

    Returns the path written, or ``None`` when the capture carried no yosys
    stat block (NO MEASUREMENT — step 9 must stay honestly MISSING rather than
    gain a fabricated zero) or when the write itself failed. Never raises: a
    report write must not turn a real synth PASS into a FAIL.

    Both synth producers (`design_one_shot_runner.step_yosys_synth` and
    `phase3_one_shot_runner.step_synth`) go through here so the two cannot
    drift into different schemas for the same declared artefact.
    """
    payload = build_stats_payload(text, **prov)
    if payload is None:
        return None
    out = Path(synth_dir) / STATS_FILENAME
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return out
