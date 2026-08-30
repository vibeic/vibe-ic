#!/usr/bin/env python3
"""
drc_vacuous_pass_check.py -- Reject a "0 DRC violations" verdict when the
layout the checker ran on was EMPTY.

For skill: benchmark-verify (Pillar 2 — "No vacuous result counts as PASS")

The defect this catches (real, from benchmark_clean runs)
--------------------------------------------------------
Magic / KLayout can be handed a GDS that streamed in with **zero geometry**
(a cell read that dropped all layers, a wrong cell name, an empty top cell).
The DRC engine then dutifully reports "0 DRC errors" / "Total errors: 0"
because there is nothing to check. A naive gate sees `errors == 0` and
stamps the design DRC-CLEAN. That is a *vacuous* PASS: the layout was never
actually checked.

The discriminator: a MEASURED observable, never the tool's prose
---------------------------------------------------------------
A DRC run is non-vacuous iff the layout it checked actually CONTAINED
geometry. That is measurable independently of what the tool chose to print,
and this checker decides on the measurement alone:

  (A) MEASURED LAYOUT  -- the strongest evidence. The layout artifact the run
      consumed (.gds/.gds.gz/.oas/.def) is opened and its shape records are
      counted directly (a pure-Python GDSII record walk; klayout.db when the
      module happens to be importable; the DEF `COMPONENTS <N>` header for
      DEF). `shapes > 0` establishes geometry; a measured `shapes == 0` is
      DECISIVE VACUOUS and overrides any claim the log makes.
  (B) REPORTED POSITIVE COUNT -- a NUMERIC shape/cell/polygon/area count the
      checker itself reports, in any word order ("4211 shapes", "cells: 87",
      "shape count: 4211"). The NUMBER is the observable; a count of 0 is not
      evidence of geometry, it is evidence of the opposite.
  (C) NON-ZERO VIOLATION COUNT -- N>=1 violations cannot be produced by an
      empty layout, so the run demonstrably examined geometry.

Prose such as "Loading <cell>", "Reading ...", "Layout read", "checking ..."
is recorded as an EXPLANATION (`wording_hints`) and is NEVER part of the
decision. That phrasing proves only that the tool opened a file — an empty
top cell loads exactly as happily as a populated one — so keying the verdict
on it re-opened the very false-clean hole this program exists to close.

FAIL-SAFE: geometry must be POSITIVELY established. If none of (A)/(B)/(C)
holds -- an unreadable, garbled or unrecognised report, or a clean 0-count
with nothing measurable behind it -- the verdict is INCONCLUSIVE. A clean is
never the default; it must be earned.

AND GEOMETRY ALONE IS NOT ENOUGH. Establishing geometry proves the LAYOUT was
worth checking; it says nothing about whether the CHECKER ran. A scope in
which no file reported a violation count at all -- not zero, not non-zero --
is a scope with no verdict in it, and exit 0 there claims a clean nobody
stated. That is refused too (`DRC_NO_VERDICT_IN_SCOPE`), at SCOPE level: an
unparsed report sitting beside one that DID state a count still defers.

(D) PROOF, PER STEP, THAT THE CHECKER EXAMINED SOMETHING. The scope rule
      cannot help when a scope holds two checkers and only one of them ran:
      the finished one supplies a count, the scope has a verdict in it, and
      the one that never started is deferred over. So before deferring on an
      unparsed report, that step must PROVE its checker examined a cell -- a
      report-database naming one. No proof, no deferral
      (`DRC_STEP_NEVER_REPORTED`); a finished checker elsewhere in the scope
      does not speak for it. Only the database's HEAD is read.

      REQUIRES PROOF, does not hunt for a confession, and the difference is
      the whole point. Asking "is there a database that says UNKNOWN?" is an
      absence-shaped tell in a positive disguise: delete that database and the
      pass comes back, which is exactly how the 0-byte-report rule above was
      defeated. Keyed this way round there is no file whose REMOVAL buys a
      pass -- removing one can only remove proof.

      Its blast radius is one case. A scope whose only unparsed report lacks
      proof was ALREADY INCONCLUSIVE, via `DRC_NO_VERDICT_IN_SCOPE`, because
      nothing in it stated a count. So requiring proof changes the verdict
      nowhere except where another checker WAS reporting -- the masking case,
      which is the defect.

This is a *structural* check on the DRC run — it does NOT re-run DRC and does
NOT replace the violation-count gate; it sits in front of it.

Honest-failure contract
------------------------
  - No DRC log found             -> SKIP (exit 2)  -- nothing to vet, never PASS
  - Unreadable log file          -> INCONCLUSIVE (exit 1)
  - 0-byte DRC report            -> INCONCLUSIVE (exit 1)  -- the checker
                                    terminated without reporting; that is not
                                    a count of zero, and it OUTRANKS the SKIP
                                    above because it must block
  - measured layout has 0 shapes -> INCONCLUSIVE (exit 1)  -- the bug, decisive
  - 0-count, geometry NOT established -> INCONCLUSIVE (exit 1)  -- the bug
  - unparseable verdict, geometry NOT established -> INCONCLUSIVE (exit 1)
  - NO violation count anywhere in scope -> INCONCLUSIVE (exit 1) -- geometry
                                    established and every report unparsed, so
                                    the deferral has nothing to defer TO
  - unparsed report with no proof its checker examined a cell -> INCONCLUSIVE
                                    (exit 1) -- whatever another checker in
                                    the same scope reported
  - 0-count + geometry established -> PASS (exit 0)
  - non-zero violation count       -> PASS (exit 0)  -- not vacuous; a real
                                     violation gate (eda_report_audit) handles it

Usage:
    python3 drc_vacuous_pass_check.py <project_dir_or_logfile> [--json <out>]
                                      [--layout <gds_or_def>]

Exit codes:
    0 = PASS         (verdict is earned — geometry was checked)
    1 = INCONCLUSIVE (a 0-violation verdict on an empty/unchecked layout)
    2 = SKIP         (no DRC log to evaluate / I/O error)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import fnmatch
import gzip
import io
import json
import re
import struct
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple

import _routed_checker_progress as _routed_progress
import _semantic_child_progress as _semantic_progress


PROGRESS_SCOPE = "routed-def:drc-vacuous-pass"
_ACTIVE_INPUT_PLAN: Optional[_routed_progress.FiniteInputPlan] = None


def _read_input_text(path: Path, *, encoding: str | None = None,
                     errors: str = "strict") -> str:
    if _ACTIVE_INPUT_PLAN is not None:
        return _ACTIVE_INPUT_PLAN.text_for(
            path, encoding=encoding, errors=errors)
    return Path(path).read_text(encoding=encoding, errors=errors)


def _read_input_bytes(path: Path) -> bytes:
    if _ACTIVE_INPUT_PLAN is not None:
        return _ACTIVE_INPUT_PLAN.bytes_for(path)
    return Path(path).read_bytes()


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
    program: str = "drc_vacuous_pass_check"
    verdict: str = "SKIP"          # PASS | INCONCLUSIVE | SKIP
    passed: bool = False
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token tables
# ---------------------------------------------------------------------------
# A clean DRC verdict: an explicit "0 <violation-word>" or "<violation-word>
# [found/reported/detected] : 0". An optional intervening report verb lets
# Magic's "Total DRC errors found: 0" match.
_VWORD = r"(?:violation|error|issue)s?"
_REPORT_VERB = r"(?:\s+(?:found|reported|detected|present))?"
_ZERO_COUNT_RE = [
    re.compile(r"\b0\s+(?:drc\s+)?" + _VWORD + r"\b", re.I),
    re.compile(r"(?:total\s+)?(?:drc\s+)?" + _VWORD + _REPORT_VERB
               + r"\s*[:=]\s*0\b", re.I),
    re.compile(r"\bdrc\s+(?:is\s+)?(?:clean|clear)\b", re.I),
    re.compile(r"\bno\s+(?:drc\s+)?" + _VWORD + r"\s+found\b", re.I),
]

# A NON-zero violation count: "<N> errors" / "errors found: <N>" with N>=1.
_NONZERO_COUNT_RE = [
    re.compile(r"\b([1-9]\d*)\s+(?:drc\s+)?" + _VWORD + r"\b", re.I),
    re.compile(r"(?:total\s+)?(?:drc\s+)?" + _VWORD + _REPORT_VERB
               + r"\s*[:=]\s*([1-9]\d*)\b", re.I),
]

# The checker's OWN NUMERIC geometry count, in whatever word order it prints
# it. The captured NUMBER is the observable — these patterns do not decide
# anything by themselves, they only harvest counts for `_reported_counts`.
_GEOM_WORD = r"(?:rectangle|polygon|shape|geometr(?:y|ies)|cell)s?"
_REPORTED_COUNT_RE = [
    # "4211 shapes" / "0 cells"
    re.compile(r"\b(\d+)\s+" + _GEOM_WORD + r"\b", re.I),
    # "cells: 87" / "shapes = 0"
    re.compile(r"\b" + _GEOM_WORD + r"\s*[:=]\s*(\d+)\b", re.I),
    # "shape count 0" / "cell count: 87" — the word order that slipped past the
    # old prose table and produced a FALSE CLEAN on a provably empty layout.
    re.compile(r"\b" + _GEOM_WORD + r"\s+count\s*[:=]?\s*(\d+)\b", re.I),
    # "Total area: 12345.6" — a positive checked area is geometry.
    re.compile(r"\btotal\s+area\s*[:=]?\s*(\d+(?:\.\d+)?)", re.I),
]

# Phrases a tool prints when it opens a layout. These prove the tool opened a
# FILE, not that the file held geometry — an empty top cell loads exactly as
# happily as a populated one. Kept ONLY to explain a verdict in the report;
# never consulted by the decision. (This table used to BE the decision.)
_WORDING_HINT_RE = [
    ("loading_reading", re.compile(r"\b(?:loading|reading)\s+(?:cell\s+)?\S", re.I)),
    ("cell_loaded", re.compile(r"\bcell\s+\S+\s+loaded\b", re.I)),
    ("layout_read", re.compile(r"\blayout\s+read\b", re.I)),
    ("checking", re.compile(r"\bchecking\s+\S", re.I)),
    ("empty_diagnostic",
     re.compile(r"\bcontains?\s+no\s+geometr|\bempty\s+(?:cell|layout|top\s*cell|design)\b"
                r"|\bnothing\s+to\s+check\b|\bcell\s+\(\?\)\s|\bcouldn'?t\s+find\b", re.I)),
]

_DRC_GLOBS = ["*drc*.rpt", "*drc*.log", "*drc*.txt", "*drc*.out",
              "*DRC*.rpt", "*DRC*.log", "*DRC*.txt", "*DRC*.out"]

# ---------------------------------------------------------------------------
# (D) THE CHECKER'S OWN STATEMENT OF WHAT IT EXAMINED.
#
# A KLayout-format report-database (`.lyrdb`, and the `.rpt` files that carry
# the same XML) names the cell the run was performed on. A run that never got
# as far as loading a cell names none, and the flow's converter writes the
# literal placeholder `UNKNOWN` there.
#
# MEASURED across all 30 report-databases this work produced, from 161 B to
# 88 MB: exactly ONE names no cell, and it is the one run that is independently
# known not to have finished (Magic ran 14:47 and stopped at "Loading DRC CIF
# style."). The three genuine zero-violation runs are 162 B -- ONE BYTE larger
# than the non-run, and the byte that differs is inside the cell name:
#
#     did not run   <cells><cell><name>UNKNOWN</name></cell></cells>  161 B
#     ran, found 0  <cells><cell><name>chip_top</name></cell></cells> 162 B
#
# Both have empty <categories> and empty <items>, so emptiness is NOT the
# discriminator and a rule keyed on it would condemn the genuine zeros. The
# NAME is the discriminator.
#
# Only the HEAD is read. A real sign-off database reaches 88 MB and this
# question is answered in its first few hundred bytes (`<top-cell>` sits at
# byte 200 of a KLayout database; the compact converter form starts with
# `<cells>`). Not finding either in the head returns None -- "not a report
# database, or could not tell" -- which defers, never condemns.
_REPORT_DB_HEAD = 65536
_RE_DB_TOP_CELL = re.compile(rb"<top-cell>\s*([^<]*)</top-cell>")
_RE_DB_CELLS_NAME = re.compile(
    rb"<cells>\s*<cell>\s*<name>\s*([^<]*)</name>")
# What a database writes when it has no cell to name.
_DB_NO_CELL = {b"", b"unknown", b"(unknown)", b"none", b"n/a", b"?"}


def report_db_cell(path: Path) -> Optional[bytes]:
    """The cell a report-database says it examined.

    b"" when it names none, the name when it does, None when this is not a
    report-database or the head could not be read (both of which DEFER).
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(_REPORT_DB_HEAD)
    except OSError:
        return None
    if b"<report-database" not in head:
        return None
    for rx in (_RE_DB_TOP_CELL, _RE_DB_CELLS_NAME):
        m = rx.search(head)
        if m:
            name = m.group(1).strip()
            return b"" if name.lower() in _DB_NO_CELL else name
    return None


def _databases_beside(fp: Path) -> List[Path]:
    """The report-databases that belong to the same step as `fp`.

    A step writes its log at `<step>/x-drc.log` and its database at
    `<step>/reports/x.lyrdb`, so both directions are searched, plus `fp`
    itself, which may BE a database (`drc_signoff.rpt` is one).

    THE ASCENT IS CONDITIONAL, and it matters. Climbing to `fp.parent.parent`
    unconditionally puts `<run>/` in scope for a log at `<step>/x-drc.log`, so
    a database sitting at run level would have proved that THIS step ran --
    which is the cross-step attribution error this whole rule exists to
    prevent, reintroduced inside its own helper. The ascent is therefore taken
    only from inside a `reports/` directory, where the parent IS the step.
    """
    out = [fp]
    ups = [fp.parent, fp.parent / "reports"]
    if fp.parent.name == "reports":
        ups.append(fp.parent.parent)
    for d in ups:
        try:
            if d.is_dir():
                out.extend(sorted(d.glob("*.lyrdb")))
        except OSError:
            continue
    seen, uniq = set(), []
    for c in out:
        try:
            key = c.resolve()
        except OSError:
            key = c
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def completion_proof(fp: Path) -> Optional[Path]:
    """The database proving the checker behind `fp` DID examine a cell.

    REQUIRES PROOF; it does not hunt for a confession. The first version of
    this asked "is there a database here that says UNKNOWN?", and that is an
    absence-shaped tell wearing a positive disguise: MEASURED, deleting the
    161-byte database alongside the already-deleted 0-byte report put the same
    unfinished step back to PASS. Keyed this way round, deletion can only ever
    make the rule FIRE -- there is no file whose removal buys a pass.
    """
    for cand in _databases_beside(fp):
        cell = report_db_cell(cand)
        if cell:                      # names a real cell -> this checker ran
            return cand
    return None

_LAYOUT_GLOBS = ["*.gds", "*.gds.gz", "*.gdsii", "*.GDS",
                 "*.oas", "*.oasis", "*.def", "*.DEF"]


def _matches_name(relative: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(Path(relative).name, pattern)
               for pattern in patterns)


def _default_disk_population(project: Path,
                             patterns: List[str]) -> List[Path]:
    """Historical project-dir discovery order, independent of active cache."""
    out: List[Path] = []
    seen = set()
    for pattern in patterns:
        for path in sorted(Path(project).rglob(pattern)):
            try:
                identity = path.resolve()
            except OSError:
                identity = path.absolute()
            if identity in seen or not path.is_file():
                continue
            seen.add(identity)
            out.append(path)
    return out


def _input_plan(project: Path) -> _routed_progress.FiniteInputPlan:
    project = Path(project)
    index = _routed_progress.IndexSnapshot(project)
    reports = index.select(
        lambda relative: _matches_name(relative, _DRC_GLOBS),
        _default_disk_population(project, _DRC_GLOBS),
        population="vacuous DRC report population")
    layouts = index.select(
        lambda relative: _matches_name(relative, _LAYOUT_GLOBS),
        _default_disk_population(project, _LAYOUT_GLOBS),
        population="vacuous DRC layout population")
    reads = [
        *_routed_progress.planned_reads("drc-report", reports),
        *_routed_progress.planned_reads("layout", layouts),
    ]
    return _routed_progress.FiniteInputPlan(
        [index.population_unit("drc-vacuous-pass:git-index")], reads)


def semantic_progress_units(cell: Path) -> List[str]:
    """Trusted parent's exact finite manifest for the default cell argv."""
    return _input_plan(Path(cell)).units


# ---------------------------------------------------------------------------
# (A) MEASURED geometry — read the layout the DRC ran on and count its shapes.
#     This is the observable the verdict rests on. Pure Python: a GDSII record
#     walk needs no layout tool, so the gate is decidable wherever it runs.
# ---------------------------------------------------------------------------
# GDSII element records that carry actual drawn geometry. TEXT (0x0C) is a
# label, not geometry; SREF/AREF (0x0A/0x0B) are references whose shapes are
# already counted inside the referenced structure.
_GDS_REC_BGNSTR = 0x05
_GDS_SHAPE_RECS = {0x08, 0x09, 0x2D}   # BOUNDARY, PATH, BOX


@dataclass
class LayoutMeasure:
    """A measurement of one layout artifact. `shapes is None` means the file
    could not be measured — which is NOT evidence of geometry (fail-safe)."""
    file: str
    fmt: str
    shapes: Optional[int] = None
    cells: Optional[int] = None
    method: str = ""
    error: str = ""


def _open_maybe_gz(path: Path):
    if path.suffix.lower() == ".gz" or path.name.lower().endswith(".gds.gz"):
        import gzip
        return gzip.open(path, "rb")
    return path.open("rb")


def count_gds_geometry(path: Path) -> LayoutMeasure:
    """Count drawn-shape records and structures in a GDSII file by walking its
    records — the same minimal record walk gds_streamout_layermap_check uses.
    No layout tool required, so an empty layout is provable anywhere."""
    m = LayoutMeasure(file=str(path), fmt="gds", method="gds_record_walk")
    shapes = 0
    cells = 0
    try:
        if _ACTIVE_INPUT_PLAN is not None:
            payload = _read_input_bytes(path)
            raw = io.BytesIO(payload)
            fh = (gzip.GzipFile(fileobj=raw, mode="rb")
                  if path.suffix.lower() == ".gz"
                  or path.name.lower().endswith(".gds.gz") else raw)
        else:
            fh = _open_maybe_gz(path)
        expanded = 0
        with fh:
            while True:
                head = fh.read(4)
                expanded += len(head)
                if (expanded > _semantic_progress.MAX_WORK_FILE_BYTES
                        and _ACTIVE_INPUT_PLAN is not None):
                    raise _semantic_progress.ProgressProtocolError(
                        "compressed GDS expansion exceeds the routed checker "
                        "resource bound")
                if len(head) < 4:
                    break
                length, rtype = struct.unpack(">H", head[:2])[0], head[2]
                if length < 4:
                    break                      # malformed record — stop honestly
                body = fh.read(length - 4)
                expanded += len(body)
                if (expanded > _semantic_progress.MAX_WORK_FILE_BYTES
                        and _ACTIVE_INPUT_PLAN is not None):
                    raise _semantic_progress.ProgressProtocolError(
                        "compressed GDS expansion exceeds the routed checker "
                        "resource bound")
                if len(body) < length - 4:
                    break
                if rtype in _GDS_SHAPE_RECS:
                    shapes += 1
                elif rtype == _GDS_REC_BGNSTR:
                    cells += 1
    except _semantic_progress.ProgressProtocolError:
        raise
    except Exception as e:                      # unreadable/corrupt -> unmeasured
        m.error = f"{type(e).__name__}: {e}"
        return m
    m.shapes, m.cells = shapes, cells
    return m


_DEF_COMPONENTS_RE = re.compile(r"^\s*COMPONENTS\s+(\d+)\s*;", re.M)
_DEF_NETS_RE = re.compile(r"^\s*(?:SPECIAL)?NETS\s+(\d+)\s*;", re.M)


def count_def_geometry(path: Path) -> LayoutMeasure:
    """DEF geometry = placed components (+ nets), read from DEF's own structured
    `COMPONENTS <N> ;` / `NETS <N> ;` section headers — numeric fields, not prose."""
    m = LayoutMeasure(file=str(path), fmt="def", method="def_section_header")
    try:
        text = _read_input_text(path, errors="replace")
    except _semantic_progress.ProgressProtocolError:
        raise
    except Exception as e:
        m.error = f"{type(e).__name__}: {e}"
        return m
    comp = _DEF_COMPONENTS_RE.search(text)
    nets = _DEF_NETS_RE.search(text)
    if comp is None and nets is None:
        m.error = "no COMPONENTS/NETS section header"
        return m
    m.cells = int(comp.group(1)) if comp else 0
    m.shapes = (m.cells or 0) + (int(nets.group(1)) if nets else 0)
    return m


def _count_via_klayout(path: Path) -> Optional[LayoutMeasure]:
    """Measure with klayout.db when the module is importable (it handles OASIS
    and every dialect the record walk does not). Returns None when unavailable,
    so the pure-Python path stays authoritative in a bare environment."""
    try:
        import klayout.db as kdb          # type: ignore
    except Exception:
        return None
    m = LayoutMeasure(file=str(path), fmt=path.suffix.lstrip("."),
                      method="klayout.db")
    try:
        ly = kdb.Layout()
        ly.read(str(path))
        shapes = 0
        for ci in ly.each_cell():
            for li in ly.layer_indexes():
                shapes += ci.shapes(li).size()
        m.shapes, m.cells = shapes, ly.cells()
    except Exception as e:
        m.error = f"{type(e).__name__}: {e}"
    return m


def measure_layout(path: Path) -> LayoutMeasure:
    """Measure ONE layout artifact's geometry. Unknown/unreadable formats come
    back with `shapes is None` — never silently treated as populated."""
    name = path.name.lower()
    if name.endswith((".gds", ".gds.gz", ".gdsii")):
        m = count_gds_geometry(path)
        if m.shapes is None:
            if _ACTIVE_INPUT_PLAN is not None:
                raise _semantic_progress.ProgressProtocolError(
                    "semantic routed receipt cannot bind a fallback GDS "
                    "parser that reopens the pathname outside the verified "
                    "input descriptor")
            return _count_via_klayout(path) or m
        return m
    if name.endswith((".def",)):
        return count_def_geometry(path)
    if name.endswith((".oas", ".oasis")):
        if _ACTIVE_INPUT_PLAN is not None:
            raise _semantic_progress.ProgressProtocolError(
                "semantic routed receipt cannot bind an OASIS parser that "
                "reopens the pathname outside the verified input descriptor")
        return (_count_via_klayout(path)
                or LayoutMeasure(file=str(path), fmt="oasis",
                                 method="none",
                                 error="OASIS needs klayout.db (not importable)"))
    return LayoutMeasure(file=str(path), fmt=path.suffix.lstrip("."),
                         method="none", error="unrecognised layout format")


def _discover_layouts(path: Path) -> List[Path]:
    """Layout artifacts near the DRC report: under the project dir, or beside a
    single log file (its own directory, then its parent)."""
    if _ACTIVE_INPUT_PLAN is not None:
        return _ACTIVE_INPUT_PLAN.paths("layout")
    roots: List[Path] = []
    if path.is_dir():
        roots = [path]
    elif path.is_file():
        roots = [path.parent, path.parent.parent]
    out: List[Path] = []
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for g in _LAYOUT_GLOBS:
            it = root.rglob(g) if root == path else root.glob(g)
            for fp in sorted(it):
                rp = fp.resolve()
                if rp not in seen and fp.is_file():
                    seen.add(rp)
                    out.append(fp)
        if out:
            break                    # nearest directory that has any layout wins
    return out


def _cite_matcher(name: str) -> "re.Pattern":
    """The token-boundary matcher for one candidate filename — the SAME regex
    the whole-file binder used inline, factored out so the streaming pass builds
    it once per candidate and tests it per line."""
    return re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])")


def _bind_layouts(cands: List[Path], cited: set) -> Tuple[List[Path], bool]:
    """Bind the layout(s) the report actually names.

    `cited` is the set of candidate filenames the report text actually names,
    computed in ONE streaming pass by `_scan_chunks` (the whole-file version used
    to `re.search` each name over the fully-materialised report text; the set is
    the identical membership, decided the same way — see `_cite_matcher`).

    CITATION IS A FILENAME, NOT A DESIGN NAME (vibe-ic#693). This used to also
    match `p.stem.split(".")[0]`, i.e. the bare design name. A KLayout sign-off
    database opens with `<top-cell>spm</top-cell>`, so on a real run EVERY file
    called `spm.*` bound — the sign-off GDS, the router's scratch DEF, a
    snapshot copy — and the decisive `any(shapes == 0)` rule below then let ANY
    one of them condemn the run.

    MEASURED, reproduced on a passing published run (9050 shapes, rc=0): adding
    one 0-component `spm.def` under a `phase3/stage3/pnr_d8/` scratch directory
    flipped it to rc=1 with the message "the layout the run consumed holds 0
    shapes" — a statement that was factually false about the layout the run
    consumed. `pnr_d8/`, `pnr_d8s/` and `_snapshot_orig_rtl_*/` already exist in
    published trees, so the trigger is not hypothetical.

    So a citation is the FILENAME. And a filename that resolves to several
    distinct paths is not a citation of one artifact, so it does not license
    the decisive rule either: `bound` is True only when exactly one path is
    named. Everything else falls back to unanimity over all candidates, where a
    single stray empty file cannot condemn and a genuinely empty tree still can.
    """
    named = [p for p in cands if p.name in cited]
    if len(named) == 1:
        return named, True
    if named:
        return named, False       # ambiguous citation — unanimity, not decision
    return cands, False


# Compiled once so the STREAMING pass can test it per line without recompiling
# (the whole-file `_is_drc_log` below keeps its own call for the reference path).
_IS_DRC_RE = re.compile(r"\bdrc\b|\bviolation|\berror", re.I)


def _is_drc_log(text: str) -> bool:
    """Heuristic: does this look like a DRC report at all?"""
    return bool(_IS_DRC_RE.search(text))


def _discover(path: Path, under: Optional[List[str]] = None) -> List[Path]:
    """Return DRC log files. If `path` is a file, use it directly.

    `under` restricts discovery to project-relative subtrees or FILES, the same
    mechanism and the same flag name `eda_report_audit` uses (#584). Without it
    discovery is a project-wide `rglob` — which at step 31 sweeps in step 21's
    `reports/phase3/drc_router.rpt`, the pre-signoff `phase3/reports/drc.rpt`,
    the router's `phase3/stage3/pnr/routed.drc.rpt` and every `_snapshot_*`
    copy. The flow's own comment at step 31 records that exactly this
    project-wide rglob produced a 3x miscount in a sibling gate, and that
    `--under` exists to stop step 21's evidence reaching step 31.
    """
    if _ACTIVE_INPUT_PLAN is not None:
        if under:
            raise _semantic_progress.ProgressProtocolError(
                "routed parent progress does not cover --under discovery")
        return _ACTIVE_INPUT_PLAN.paths("drc-report")
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    roots: List[Path] = ([path / rel for rel in under] if under else [path])
    out: List[Path] = []
    seen = set()
    for root in roots:
        if root.is_file():
            rp = root.resolve()
            if rp not in seen:
                seen.add(rp)
                out.append(root)
            continue
        if not root.is_dir():
            continue
        for g in _DRC_GLOBS:
            for fp in sorted(root.rglob(g)):
                rp = fp.resolve()
                if rp not in seen and fp.is_file():
                    seen.add(rp)
                    out.append(fp)
    return out


# ---------------------------------------------------------------------------
# A NUMBER LIFTED OUT OF PROSE IS ONLY A DECLARATION IF THE SENTENCE AFFIRMS IT
# ---------------------------------------------------------------------------
# vibe-ic#712: an extractor that greps a value out of a sentence and publishes
# it as a declared fact republishes the values the sentence DENIES. Measured
# twice in one day, in two fields — "This block is NOT targeted at <PDK>."
# became a pdk_target, and a die the document said was "REMOVED, not
# translated" became a die mandate.
#
# This checker has the same shape in TWO places. Both are numbers taken out of
# report prose and written in as declarations:
#
#   * `nonzero_count` — "the 3 violations reported by the previous run are NOT
#     present here" would publish 3 as this run's violation count. That number
#     then does two relaxing things: it satisfies (C) `violations_prove_geometry`
#     and it routes the file to "not a vacuous PASS, defer to the violation-count
#     gate".
#   * `reported_geometry_counts` — (B), the checker's own claim that it looked at
#     geometry. A denied count is not evidence that anything was checked.
#
# Refusing a denied number moves the gate in the CONSERVATIVE direction in both
# cases: fewer ways to establish geometry, fewer files that skip the vacuous
# check. That is the right direction for a gate whose entire purpose is to
# refuse a clean it cannot earn.
#
# `zero_count` is deliberately NOT polarity-filtered, and that is not an
# oversight: it is a boolean over a pattern's PRESENCE, not a value lifted out
# of prose, and its own canonical spelling — `\bno\s+(?:drc\s+)?violations?\s+
# found\b` — IS a negation. Running the denial vocabulary over "no DRC
# violations found" would make the cleanest statement in the corpus deny
# itself.
#
# ONE HELPER OWNS THE CONSULT, so the whole-file reference path
# (`_classify_one`) and the streaming path (`_scan_chunks`) cannot diverge on
# it: both call `_declared_count`, so both inherit the same answer.
from _prose_polarity import (  # type: ignore  # noqa: E402
    NEGATION_RE as _DENIAL_RE,
    is_denied as _is_denied,
    sentence_scope as _sentence_scope,
)

#: Necessary-substring gate for the polarity consult, in the same spirit as the
#: `_present` gates the window scanner already uses: every alternative in
#: `_prose_polarity.NEGATION_RE` contains one of these lowercase literals, so a
#: text holding none of them cannot contain a denial and the consult can be
#: skipped outright. `no` covers not/no/none/non/no longer/does not apply.
#:
#: It is a SPEED gate only — `is_denied` still decides every span it lets
#: through. Running `NEGATION_RE` itself as the pre-scan was measured at ~66 s
#: added to a 256 MiB report (27.1 s -> 93.9 s, destroying this rewrite's whole
#: speed-up); the substring scan is memchr-fast and costs nothing measurable.
#: `test_the_denial_substring_gate_is_sound` proves the necessary-condition
#: claim against `NEGATION_RE` itself, so the two cannot drift apart silently.
_DENIAL_TRIG = ("no", "without", "exclud", "never", "removed", "obsolete",
                "supersed", "n/a", "inapplicable", "deprecated",
                "非", "无", "無", "不", "否")


def _denial_possible(low: str) -> bool:
    """True when `low` (already lower-cased) MIGHT contain a denial word."""
    return any(t in low for t in _DENIAL_TRIG)

#: The window `_sentence_scope` reads around a match. Passed EXPLICITLY rather
#: than left to the default because `_scan_chunks` must retain exactly this
#: much context on each side of an accepted match for its window answer to
#: equal the whole-file answer — a default that drifted would silently break
#: that equality. Changing either number requires changing nothing else.
_POLARITY_BEFORE = 240
_POLARITY_AFTER = 120


#: What ends a RECORD in a DRC report. `_sentence_scope` was written for prose
#: documents: it reaches 240 characters back (stopping at a sentence break) and
#: 120 forward (stopping at nothing), because #711's denial sat in an earlier
#: SENTENCE. A DRC report is not prose — consecutive lines are unrelated
#: records, and a plain `\n` does not end a sentence — so those reaches walk
#: into neighbouring records and let one record's denial retract another
#: record's number. MEASURED on the equivalence fuzz: `cells: 87` suppressed by
#: a `no drc errors found` printed two lines away, and `4211 shapes` by one two
#: lines below. The span is therefore clamped to the record on BOTH sides,
#: inside the bounds the helper returns. Bounding it HERE, in the one caller
#: whose input is machine-generated, is deliberate: `_sentence_scope` is shared
#: with gates whose input really is prose.
_RECORD_STOPS = ("\n", ". ", "; ")

# ...AND THE CLEAN VERDICT IS NOT A DENIAL OF ANYTHING ELSE ON ITS LINE.
#
# Clamping to the RECORD still let a denial in one part of a line retract
# another part's number, on the two most ordinary lines a DRC tool prints.
# MEASURED, whole-file, against `origin/main`, which has no consult at all:
#
#   A: "cell top: checked 4211 shapes<SEP>no drc violations found"
#          base PASS/DRC_CLEAN_EARNED geom=[4211.0] -> here geom=[] FABRICATED
#   B: "13 DRC errors found<SEP>none waived"
#          base PASS/DRC_NONZERO_COUNT nonzero=13   -> here None    FABRICATED
#
# The FIRST fix for this clamped the forward reach at a comma. That closed the
# two witnesses and generalised to exactly the two witnesses: holding the
# assertion fixed and varying only <SEP>, 8 of 11 separators still fabricated —
# TAB and double space among them, i.e. any column-formatted report. A fix
# shaped like its examples is not a fix, and this repo has paid for that shape
# repeatedly. The comma clamp is REMOVED rather than extended into a longer
# list of separators, because the separator was never the point.
#
# THE POINT IS FAMILY A's DENIAL WORD IS NOT A RETRACTION AT ALL. `no ...
# violations found` IS the clean verdict — the very statement `_ZERO_COUNT_RE`
# recognises, and the one this consult ALREADY exempts for `zero_count` on the
# grounds that "running the denial vocabulary over it would make the cleanest
# statement in the corpus deny itself". That exemption was written for the
# boolean and not applied to the span, so the identical phrase went on denying
# the geometry evidence beside it. Blanking those spans before asking
# `is_denied` — exactly as `blank_bracketed` blanks parentheticals — closes
# family A for EVERY separator, because it never looks at the separator.
# MEASURED over the 11-separator sweep: family A 3/11 -> 11/11 kept, controls
# broken 0.
#
# FAMILY B IS NOT CLOSED BY THIS AND IS NOT CLAIMED TO BE. "none waived" is a
# denial about WAIVERS, and nothing structural separates it from a real
# retraction without enumerating separators again — which is the move just
# rejected. It is left DENIED, uniformly across every separator rather than for
# some and not others, and DISCLOSED: the refusal is recorded in the summary
# and the verdict says a count was found and retracted instead of the false
# "no parseable violation verdict". Its direction is the safe one — it drops
# evidence and moves the verdict to INCONCLUSIVE, so it can lose a PASS the
# report earned but can never make a failure go quiet.


def _blank_clean_verdicts(span: str) -> str:
    """`span` with every CLEAN-VERDICT statement replaced by spaces.

    Length-preserving, like `blank_bracketed`, so a caller's offsets stay
    valid. `_ZERO_COUNT_RE`'s canonical spelling IS a negation, so leaving it
    in the span makes a correct clean run deny its own evidence. chip-AGNOSTIC:
    the checker's own verdict vocabulary, no design literal."""
    out = span
    for r in _ZERO_COUNT_RE:
        out = r.sub(lambda mm: " " * len(mm.group(0)), out)
    return out


def _record_span(text: str, m: "re.Match") -> Tuple[int, int]:
    """The span whose polarity governs this match.

    SCOPE IS THE HELPER'S JOB AND THIS DELEGATES TO IT. `_record_span` used to
    re-clamp `_sentence_scope`'s window here, in this file, because the helper
    bounded its reach BACKWARD only and a DRC report's consecutive lines are
    unrelated RECORDS, not one sentence. That was a second private copy of
    scoping in a module written to end private copies of scoping, and it was
    the caller's copy that the helper's own docstring named as the reason to
    fix the reach centrally.

    `070aea3e8` (v1.9.78) did fix it, symmetrically, and gave callers
    `extra_breaks` for the one thing that genuinely is per-caller: what ends a
    RECORD in input that is not prose. So the clamps are GONE and
    `_RECORD_STOPS` is passed in. MEASURED before deleting them, over every
    span the polarity corpus drives (11 separators x both families, plus the
    cross-line and cross-sentence cases): 56 spans compared, 56 identical, 0
    verdict-changing differences. The two invariants the old code asserted for
    itself — that the span contains the match at both ends — are now
    guarantees of the helper's own loop, so asserting them again here would be
    a guard that only looks protective."""
    return _sentence_scope(text, m.start(), m.end(),
                           before=_POLARITY_BEFORE, after=_POLARITY_AFTER,
                           extra_breaks=_RECORD_STOPS)


def _declared_count(text: str, m: "re.Match", denial_possible: bool = True
                    ) -> Optional[float]:
    """The captured number, or None when the sentence around it DENIES it.

    `denial_possible` is a sound fast reject, not a policy: when the caller has
    already established that the whole text carries no denial word at all, no
    span of it can be denied (`is_denied` blanks bracketed spans, which can only
    REMOVE candidate matches, never add one), so the scope+denial work is
    skipped. It changes speed only."""
    if denial_possible:
        lo, hi = _record_span(text, m)
        if _is_denied(_blank_clean_verdicts(text[lo:hi])):
            return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _is_polarity_refusal(m: "re.Match", v: Optional[float]) -> bool:
    """True when `_declared_count` returned None because the span DENIED the
    number, rather than because the number would not parse.

    A REFUSAL IS A FACT ABOUT THE REPORT AND HAS TO BE COUNTED. Refusing a
    denied number is right, but a run whose only violation count was retracted
    is not the same thing as a run that printed no count at all, and the
    verdict said the second about the first ("No parseable violation
    verdict"). That is exactly the class of false statement this whole change
    exists to remove."""
    if v is not None:
        return False
    try:
        float(m.group(1))
        return True
    except (ValueError, IndexError):
        return False


def _first_declared_count(text: str, r: "re.Pattern",
                          denial_possible: bool = True
                          ) -> Tuple[Optional[float], int]:
    """The first match of `r` whose sentence does not deny it, and HOW MANY
    matches were refused on the way. A pattern all of whose matches are denied
    has declared nothing, so the caller moves on to the next pattern rather
    than publishing a retracted number — and records that it did."""
    refused = 0
    for m in r.finditer(text):
        v = _declared_count(text, m, denial_possible)
        if v is not None:
            return v, refused
        refused += _is_polarity_refusal(m, v)
    return None, refused


def _reported_counts(text: str, denial_possible: bool = True
                     ) -> Tuple[List[float], int]:
    """Every NUMERIC geometry count the checker reported, in any word order —
    minus the ones its own prose retracts, plus how many those were."""
    out: List[float] = []
    refused = 0
    for r in _REPORTED_COUNT_RE:
        for m in r.finditer(text):
            v = _declared_count(text, m, denial_possible)
            if v is not None:
                out.append(v)
            else:
                refused += _is_polarity_refusal(m, v)
    return out, refused


def _wording_hints(text: str) -> List[str]:
    """Phrases that merely EXPLAIN a verdict. Never used to decide one."""
    return [name for name, r in _WORDING_HINT_RE if r.search(text)]


def _classify_one(text: str) -> dict:
    """Classify a single DRC log's verdict + REPORTED numeric geometry counts.
    Prose is harvested only as `wording_hints` — it decides nothing."""
    zero = any(r.search(text) for r in _ZERO_COUNT_RE)
    denial_possible = _denial_possible(text.lower())
    nonzero = None
    refused = 0
    for r in _NONZERO_COUNT_RE:
        v, n = _first_declared_count(text, r, denial_possible)
        refused += n
        if v is not None:
            nonzero = int(v)
            break
    counts, n = _reported_counts(text, denial_possible)
    refused += n
    return {
        "zero_count": zero,
        "nonzero_count": nonzero,
        # (B) a POSITIVE reported count is evidence; a reported 0 is not.
        "reported_geometry_counts": counts,
        "reported_geometry_max": max(counts) if counts else None,
        # How many numbers the polarity consult REFUSED. Not a decision input —
        # a disclosure, so a verdict can never say "no count was printed" about
        # a report that printed one and retracted it.
        "polarity_refused": refused,
        "wording_hints": _wording_hints(text),   # explanation only
    }


# ---------------------------------------------------------------------------
# STREAMING read — never materialise the report.
#
# `_classify_one`/`_is_drc_log`/`_bind_layouts` above are the REFERENCE
# semantics, expressed over a fully-materialised string. On a real sign-off
# report that string is enormous — a measured run produced a multi-gigabyte,
# ~10^8-line DRC report, and `Path.read_text` on it plus the several whole-file
# regex passes ran past the flow's per-gate budget and were killed, so a step
# that should get a verdict never got one.
#
# `_scan_chunks` derives the SAME four facts `audit` needs — (nonempty, is_drc,
# classification, cited) — from a FIXED-SIZE SLIDING WINDOW over the report, so
# peak memory is bounded by (one block + one carry + the trim's bounded search
# for a cut point) plus the geometry-summary counts / wording hints / cited
# names the report declares. The window bound holds for ANY input, including a
# report with no newline in it — see the trim's three-way cut choice below,
# which is what makes that unconditional. It is NOT a bound on the RETAINED
# counts: `reported_geometry_counts` still accumulates one float per matched
# geometry summary, so a report that prints millions of them still costs
# proportionally (unchanged by this rewrite; a 1 GB report yielded 10.88 M
# entries and a 174 MB JSON, which is a separate defect and a separate fix).
# THAT CAVEAT IS NOT THEORETICAL, and stating it abstractly let the change's own
# headline read as an unconditional memory win. MEASURED, 64 MiB report,
# `/usr/bin/time -v`, whole-file vs this:
#     newline-free      143.8 MiB / 12.99 s  ->  46.5 MiB / 1.49 s
#     newline-delimited 144.0 MiB / 17.55 s  ->  46.6 MiB / 6.91 s
#     counts-printing   349.7 MiB / 17.44 s  -> 350.4 MiB / 7.36 s   <-- MORE
# On a body that prints a geometry count on every record the retained list IS
# the peak, and streaming buys time only. The WINDOW is what is bounded.
# It reuses the identical compiled pattern tables and
# reproduces the whole-file `re.search`/`finditer` results EXACTLY — not merely
# per line — because the window carries an overlap and a match is COUNTED only
# once it ends before the window's right margin (an "accept-once" watermark),
# so a match up to `_CARRY_OVERLAP` chars long that straddles a block boundary
# is still seen whole and counted a single time, in file order:
#   * zero_count / is_drc / nonempty — search over each window (completeness;
#     a boolean needs no dedup)                == any(search over whole text)
#   * nonzero    — first accepted match, by pattern priority
#                                              == the whole-text pattern priority
#   * reported   — per-pattern accepted matches, pattern0..patternN, file order
#                                              == `_reported_counts` grouping
#   * wording    — names in table order        == `_wording_hints`
#   * cited      — candidate-name membership    == `_bind_layouts`'s inline search
# The one construct outside this equivalence is a decisive token separated from
# its number by more than `_CARRY_OVERLAP` (256 KiB) of whitespace — orders of
# magnitude larger than any real DRC-report record. The equivalence tests (the
# window scanner vs `_classify_one` under a deliberately tiny window that forces
# a boundary between almost every token, and the pre-fix program vs this one on
# a real corpus report) pin it.
# ---------------------------------------------------------------------------
_READ_BLOCK = 1 << 22       # 4 MiB read granularity
_CARRY_OVERLAP = 1 << 18    # 256 KiB — the max match length equivalence covers
#: How far back the trim looks for a safe cut point when the retained prefix
#: holds no newline. Bounded so the search costs O(1) per window rather than
#: O(window); past it the trim takes a hard cut (see `_scan_chunks`).
_SAFE_CUT_SCAN = 1 << 16    # 64 KiB
#: The trailing run of characters a cut must not land inside: `\w` is what
#: `\b` is defined against and `[\w.-]` is what the citation look-behind
#: rejects, so a cut just before this run leaves both reading as they do
#: whole-file.
_UNSAFE_TAIL_RE = re.compile(r"[\w.\-]*\Z")
#: One token character — the class `_UNSAFE_TAIL_RE` is built from. Used to ask
#: whether a chosen cut point landed INSIDE a token.
_TOKEN_CHAR_RE = re.compile(r"[\w.\-]")


def _cut_is_mid_token(buf: str, cut: int) -> bool:
    """True when trimming `buf` at `cut` would split a `[\\w.-]` token.

    The next window then opens on a token FRAGMENT, and at index 0 the regex
    engine sees a start-of-string: `\\b` fires where the file has no boundary
    and `(?<![\\w.-])` succeeds where the file refuses. Exactly ONE index is
    affected — from index 1 on, the look-behind reads `buf[0]`, which IS the
    real preceding character. Chip-AGNOSTIC: lexical."""
    return (0 < cut < len(buf)
            and _TOKEN_CHAR_RE.match(buf[cut - 1]) is not None
            and _TOKEN_CHAR_RE.match(buf[cut]) is not None)

# Necessary-substring gates: a pattern CANNOT match a window that contains none
# of these lowercase literals (each is a literal every match of the pattern must
# contain — an alternation contributes one literal per branch). Skipping the
# regex on a window that lacks them is a SOUND fast reject: it makes the scan a
# near-single-pass on a real sign-off report (whose body is millions of geometry
# records and rule-name categories, with no "error"/"violation"/"clean"/verb
# text at all) while changing SPEED only, never the verdict. These stay in
# lock-step with the pattern tables above and are pinned by the equivalence
# fuzz. Parallel by index to the pattern lists they gate.
_IS_DRC_TRIG = ("drc", "violation", "error")
_ZERO_TRIG = (("violation", "error", "issue"),
              ("violation", "error", "issue"),
              ("clean", "clear"),
              ("found",))
_NONZERO_TRIG = (("violation", "error", "issue"),
                 ("violation", "error", "issue"))
_GEOM_KW = ("rectangle", "polygon", "shape", "geometr", "cell")
_REPORTED_TRIG = (_GEOM_KW, _GEOM_KW, _GEOM_KW, ("area",))
_WORDING_TRIG = (("loading", "reading"),        # loading_reading
                 ("loaded",),                    # cell_loaded
                 ("layout",),                    # layout_read
                 ("checking",),                  # checking
                 ("geometr", "empty", "nothing", "(?)", "couldn"))  # empty_diagnostic


def _present(triggers, low: str) -> bool:
    """True if any necessary-substring trigger is in the lower-cased window."""
    return any(t in low for t in triggers)


def _safe_cut_point(buf: str, keep_from: int) -> int:
    """Where the sliding window may be trimmed, at or before `keep_from`.

    The cut has to land on a real left boundary, so the next window's first
    character reads to the regex exactly as it does whole-file: `\\b` and the
    `(?<![\\w.-])` citation look-behind at start-of-string must not be able to
    invent a boundary that a mid-token cut would create. THREE cut points, best
    first:

      1. just after a newline — the case every real DRC report is in;
      2. just after any other character that is neither a word char nor
         `.`/`-`, which is the property that made the newline safe in the first
         place (a space, `)`, `;`, `,` … all serve);
      3. failing both, a HARD cut at `keep_from`.

    The first revision had only (1) and fell back to `0` — i.e. NO trim at all.
    A report with no newline in it was therefore never trimmed: the buffer grew
    to the whole file, with a `buf.lower()` copy of it per window on top.
    MEASURED on a 256 MiB single-line report: 802 MiB peak / 142.7 s, against
    527 MiB / 91.3 s for the whole-file `read_text` this rewrite replaces — 1.5x
    the memory and 1.6x the time of the code it was supposed to bound, and the
    gap grew super-linearly with size. (2) fixes that outright for any report
    containing a space, a bracket or a semicolon, which is all of them; the same
    report now measures 48.7 MiB / 27.4 s.

    (3) exists so the bound holds with no "unless" at all, and it is RATIONED:
    reached only once the reclaimable prefix is itself `_SAFE_CUT_SCAN` long.
    Below that there is nothing worth reclaiming, so the no-trim behaviour is
    kept.

    RATIONING IS NOT A FIX FOR (3)'s HAZARD, only a cap on how often it is hit,
    and the first revision of this comment claimed otherwise. A cut inside a
    token leaves the next window starting mid-token, where `\\b` and the
    citation look-behind see a start-of-string the whole file never had —
    MEASURED as `top.gds` harvested out of `xtop.gds`, and re-MEASURED at
    exactly the rationed cut (a >= 64 KiB `[\\w.-]` run, cut=65547, next window
    opening on `top.gds rest`), where it still happened. What actually fixes it
    is the caller: `_scan_chunks` notices the cut landed mid-token and starts
    the next window's scans at index 1 instead of 0, so every regex reads the
    REAL preceding character (`buf[0]`) exactly as it does whole-file, and the
    one position whose left context the file never had is the only one skipped.

    Chip-AGNOSTIC: pure lexical boundary arithmetic on the read window."""
    nl = buf.rfind("\n", 0, keep_from)
    if nl != -1:
        return nl + 1
    lo = max(0, keep_from - _SAFE_CUT_SCAN)
    m_cut = _UNSAFE_TAIL_RE.search(buf, lo, keep_from)
    cut = m_cut.start() if m_cut is not None else keep_from
    # `cut == lo` means the token run reaches the LEFT EDGE of the bounded
    # search, which on its own says nothing about whether `lo` is a boundary —
    # only that the search could not see past it. Ask the character before it.
    # `cut > lo` alone threw away a perfectly safe cut whenever the run began
    # exactly at `lo`, and hard-cut mid-token instead: for
    # `"a"*50 + " " + "b"*(64 KiB + 100)` at keep_from = 51 + 64 KiB the
    # boundary is at 51 and the old test returned the mid-token 65587.
    if cut > lo or lo == 0 or _TOKEN_CHAR_RE.match(buf[lo - 1]) is None:
        return cut                  # (2) a real boundary inside the search
    # (3) The searched span is one unbroken token AND it continues past the
    # search's left edge, so there is no honest cut anywhere in reach: hard-cut
    # and let `_scan_chunks` skip index 0 of the next window.
    #
    # THE RATION IS THE `lo == 0` ARM ABOVE, not a separate test. `lo` is
    # `keep_from - _SAFE_CUT_SCAN` clamped at 0, so `keep_from < _SAFE_CUT_SCAN`
    # is EXACTLY `lo == 0`, and that arm already returns `cut` — which is 0 when
    # the whole prefix is one token, i.e. no trim, which is what the ration
    # said. A separate `if keep_from < _SAFE_CUT_SCAN: return 0` below the
    # search was therefore unreachable: mutating it away changed no answer,
    # which is the definition of a branch that only looks protective. It is
    # deleted rather than left to be re-justified by the next reader.
    return keep_from                # rationed HARD cut, mid-token by definition


def _scan_chunks(read, layout_cands=(), block: int = _READ_BLOCK,
                 overlap: int = _CARRY_OVERLAP) -> Tuple[bool, bool, dict, set]:
    """Stream a decoded text source via ``read(n) -> str`` ("" at EOF) in fixed
    sliding windows and return (nonempty, is_drc, classification, cited). See the
    module comment above for the byte-identity argument. ``block``/``overlap``
    are parameters only so a test can shrink the window to stress boundaries.

    Each COUNTING pattern (the nonzero-count and geometry-count families) carries
    its own absolute resume cursor. ``Pattern.finditer(buf, pos)`` resumes the
    non-overlapping left-to-right walk at ``pos`` — stateless beyond position —
    so resuming at the end of that pattern's last accepted match reproduces the
    whole-text ``finditer`` walk EXACTLY, split across reads. A match is accepted
    only once it ends at/before the window's right margin (``horizon``); anything
    past it is deferred and re-found next read from the same cursor, so a match
    up to ``overlap`` long that straddles a block boundary is counted once and
    whole. Booleans (zero / is_drc / nonempty / wording / cited) need only
    completeness, so they test the whole retained window each read."""
    nonempty = False
    is_drc = False
    zero = False
    nz_first: List[Optional[int]] = [None] * len(_NONZERO_COUNT_RE)
    nz_cur = [0] * len(_NONZERO_COUNT_RE)        # absolute resume cursor / pattern
    geom: List[List[float]] = [[] for _ in _REPORTED_COUNT_RE]
    geom_cur = [0] * len(_REPORTED_COUNT_RE)     # absolute resume cursor / pattern
    hint_seen: set = set()
    cited: set = set()
    # How many numbers the polarity consult REFUSED, accumulated exactly as
    # the whole-file paths accumulate it: once per ACCEPTED match that was
    # denied, never for a deferred one (those are re-found next window).
    refused = 0
    # Build each candidate's token matcher once; the cheap `name in window`
    # substring reject keeps the per-window cost near zero when nothing is cited.
    cand = [(p.name, _cite_matcher(p.name)) for p in layout_cands]

    buf = ""
    buf_base = 0            # absolute offset of buf[0] in the decoded stream
    # Where a scan of this window may START. 0 normally. 1 after a trim that
    # had to cut INSIDE a token (`_safe_cut_point`'s rationed hard cut), because
    # index 0 is then the only index whose left context the file never had: the
    # regex sees a start-of-string where the file has a `[\w.-]` character, so
    # `\b` fires and `(?<![\w.-])` succeeds when neither does whole-file.
    # MEASURED with this at 0: a `top.gds` citation harvested out of `xtop.gds`
    # at the rationed cut. From index 1 on, the look-behind reads `buf[0]` —
    # the REAL preceding character — so those indices are already exact.
    #
    # Nothing real is lost. A match the whole file has that starts at that
    # index would have to have started EARLIER there (its left context is a
    # token character), and everything earlier was already scanned in a
    # previous window: the trim only ever discards a prefix that lies at least
    # `overlap + _POLARITY_BEFORE` before this window's horizon, which is the
    # `_CARRY_OVERLAP` bound the equivalence is already stated under.
    scan_from = 0
    while True:
        chunk = read(block)
        final = (chunk == "")
        if chunk:
            buf += chunk
        if not buf and final:
            break
        # Matches ending at/before `horizon` (local index) are safe to accept;
        # anything past it may still extend into the next read, so defer it. On
        # the final window, accept to the very end.
        # The right margin must also cover `_sentence_scope`'s FORWARD reach,
        # or a match accepted near the window's edge would see a truncated
        # sentence and could read as undenied where the whole file denies it.
        horizon = (len(buf) if final
                   else max(0, len(buf) - max(overlap, _POLARITY_AFTER)))
        low = buf.lower()          # one lowercase pass drives every substring gate
        # Sound fast reject for the polarity consult: no denial word anywhere
        # in this window => no span of it can be denied. One extra pass per
        # window, never per match — on a real sign-off report, whose body is
        # millions of geometry records, this is False for nearly every window.
        denial_possible = _denial_possible(low)

        # A boolean pattern is only HONOURED when its leftmost match ends at or
        # before the horizon: that guarantees the match had real right context
        # (buf extends `overlap` further, or this is EOF), so the window's right
        # edge cannot fake a `\b`/`$` the whole file never had. Left context is
        # real too — buf[0] is the file start or, after a trim, snapped to just
        # after a newline. A match deferred past the horizon reappears whole in
        # the next window, and the leftmost real match in the file is always
        # accepted in the window where it sits interior — so existence (all a
        # boolean needs) is decided exactly as the whole-file `search` decides.
        #
        # The local is `bm` (boolean match), NOT `m`: the counting loops below
        # bind their own `m` per accepted match, and one name meaning two
        # different match objects in two scopes of one function is how a reader
        # — and any analysis that walks this function as a whole — comes to
        # believe the boolean probe's match is the one being written into a
        # count.
        def _hit(r):
            bm = r.search(buf, scan_from)
            return bm is not None and bm.end() <= horizon

        if not nonempty and buf.strip():
            nonempty = True
        if not is_drc and _present(_IS_DRC_TRIG, low) and _hit(_IS_DRC_RE):
            is_drc = True
        if not zero:
            for i, r in enumerate(_ZERO_COUNT_RE):
                if _present(_ZERO_TRIG[i], low) and _hit(r):
                    zero = True
                    break
        for i, r in enumerate(_NONZERO_COUNT_RE):
            if nz_first[i] is not None:
                continue
            if not _present(_NONZERO_TRIG[i], low):
                nz_cur[i] = max(nz_cur[i], buf_base + horizon)   # no match here
                continue
            deferred = False
            for m in r.finditer(buf, max(scan_from, nz_cur[i] - buf_base)):
                if m.end() > horizon:
                    deferred = True
                    break                          # defer; keep cursor, retry next read
                v = _declared_count(buf, m, denial_possible)
                if v is not None:
                    nz_first[i] = int(v)
                    break                          # first match wins; pattern done
                refused += _is_polarity_refusal(m, v)
                # Denied: this match declared nothing. Advance past it and keep
                # looking, exactly as `_first_declared_count` does whole-file.
                nz_cur[i] = buf_base + m.end()
            if nz_first[i] is None and not deferred:
                nz_cur[i] = max(nz_cur[i], buf_base + horizon)
        for i, r in enumerate(_REPORTED_COUNT_RE):
            if not _present(_REPORTED_TRIG[i], low):
                geom_cur[i] = max(geom_cur[i], buf_base + horizon)  # no match here
                continue
            deferred = False
            for m in r.finditer(buf, max(scan_from, geom_cur[i] - buf_base)):
                if m.end() <= horizon:
                    v = _declared_count(buf, m, denial_possible)
                    if v is not None:
                        geom[i].append(v)
                    else:
                        refused += _is_polarity_refusal(m, v)
                    geom_cur[i] = buf_base + m.end()
                else:
                    deferred = True
                    break
            if not deferred:
                geom_cur[i] = max(geom_cur[i], buf_base + horizon)
        for j, (name, r) in enumerate(_WORDING_HINT_RE):
            if name not in hint_seen and _present(_WORDING_TRIG[j], low) and _hit(r):
                hint_seen.add(name)
        for name, r in cand:
            if name not in cited and name in buf and _hit(r):
                cited.add(name)

        if final:
            break
        # Retain the tail any still-active consumer could still need:
        #   * each counting cursor's resume position (exact finditer walk), and
        #   * `overlap` chars before the horizon, so a BOOLEAN match up to
        #     `overlap` long that straddles this read's right edge is still whole
        #     in the next window (booleans scan the whole window, no cursor).
        # Everything before the minimum of those is decided for good.
        #   * `_POLARITY_BEFORE` chars BEFORE the earliest of those, so an
        #     accepted match's `_sentence_scope` lookback is as complete in the
        #     window as it is in the whole file.
        active = list(geom_cur) + [nz_cur[i] for i in range(len(_NONZERO_COUNT_RE))
                                   if nz_first[i] is None]
        active.append(buf_base + max(0, horizon - overlap))
        keep_from = max(0, min(active) - buf_base - _POLARITY_BEFORE)
        keep_from = _safe_cut_point(buf, keep_from)
        # Recomputed at EVERY trim, never accumulated: it describes only the
        # buffer this trim produces.
        scan_from = 1 if _cut_is_mid_token(buf, keep_from) else 0
        buf_base += keep_from
        buf = buf[keep_from:]

    nonzero = next((v for v in nz_first if v is not None), None)
    counts = [c for lst in geom for c in lst]
    classification = {
        "zero_count": zero,
        "nonzero_count": nonzero,
        "reported_geometry_counts": counts,
        "reported_geometry_max": max(counts) if counts else None,
        "polarity_refused": refused,
        "wording_hints": [name for name, _ in _WORDING_HINT_RE
                          if name in hint_seen],
    }
    return nonempty, is_drc, classification, cited


def _scan_report_file(fp: Path,
                      layout_cands=()) -> Tuple[bool, bool, dict, set]:
    """Stream one DRC report file. Opens with the SAME locale-default encoding +
    `errors='replace'` that `Path.read_text(errors='replace')` used, so the
    decoded stream — and therefore every regex result — is identical to the
    whole-file path, without ever holding the file in memory. OSError propagates
    to the caller, which treats it exactly as the old read failure did."""
    if _ACTIVE_INPUT_PLAN is not None:
        text = _read_input_text(fp, errors="replace")
        return _scan_chunks(io.StringIO(text).read, layout_cands)
    with open(fp, "r", errors="replace") as fh:
        return _scan_chunks(fh.read, layout_cands)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def audit(path: Path, layout: Optional[Path] = None,
          under: Optional[List[str]] = None) -> AuditResult:
    result = AuditResult()
    files = _discover(path, under)
    scope = {"scoped_under": list(under)} if under else {}
    if under:
        # WHICH declared scopes do not exist. Without this a typo'd `--under`
        # is byte-identical to a genuinely absent report.
        scope["scoped_under_missing"] = [rel for rel in under
                                         if not (path / rel).exists()]
    if not files:
        result.verdict = "SKIP"
        result.passed = False
        result.findings.append(Finding(
            rule="DRC_LOG_EXISTS", severity="ERROR",
            message="No DRC log found — nothing to vet (SKIP, never a PASS)."
                    + (f" Scope: {under}." if under else "")))
        result.summary = {"files_found": 0, **scope}
        return result

    per_file = []
    any_empty_with_clean = False
    any_real_check = False
    any_drc_log = False
    any_empty_report = False
    # A verdict this checker actually PARSED, anywhere in scope -- a violation
    # count, zero or non-zero. `any_real_check` is NOT that: it is also set by
    # `DRC_NO_VERDICT_TOKEN`, which fires when nothing was parsed at all.
    any_parsed_verdict = False
    # A step that offers no proof its checker examined anything. Decisive, and
    # it must not be maskable by another step's verdict -- see the branch below.
    any_step_never_reported = False
    layout_cands = [layout] if layout else _discover_layouts(path)

    for fp in files:
        # STREAMED, never materialised — a real sign-off report is multi-GB and
        # `read_text` + whole-file regex on it overran the flow's per-gate
        # budget and was killed, so the step never got a verdict. `_scan_chunks`
        # derives the identical facts from a fixed window (see its module note).
        try:
            nonempty, is_drc, c, cited = _scan_report_file(fp, layout_cands)
        except OSError:
            result.findings.append(Finding(
                rule="DRC_LOG_READABLE", severity="ERROR",
                message="DRC log could not be read.", file=str(fp)))
            continue
        if not nonempty:
            # A ZERO-BYTE REPORT IS THE RUN SAYING IT PRODUCED NOTHING.
            #
            # This branch used to write the finding and then drop out of the
            # verdict entirely: `any_empty_report` did not exist, so a run
            # whose report was 0 bytes contributed an ERROR line and no
            # consequence. If any OTHER discovered file looked like a DRC log
            # and geometry was established behind it, the rollup reached
            # `PASS` — and the empty report, the strongest tell in the
            # directory, was the one thing the verdict did not read.
            #
            # MEASURED (gf180mcuD, 16-stage non-CoB precheck, step 12): Magic
            # ran 14:47 at 99.95 % CPU and ended without writing —
            # `drc.magic.rpt` 0 bytes, `magic-drc.log` stopping at "Loading DRC
            # CIF style." before the checker's own output, `drc.magic.lyrdb`
            # naming its top cell `UNKNOWN`. The image's checker printed "Check
            # for Magic DRC errors clear." and THIS GATE, handed the same
            # directory and the design's 4 556 379-shape GDS, returned PASS.
            # A completed run of the same deck on the same design writes 102
            # bytes: the top cell, `[INFO] COUNT: 0`. Nothing distinguishes the
            # two except that one file has contents.
            #
            # So the empty report is decisive, in the same direction as every
            # other rule here: a clean must be EARNED, and a checker that wrote
            # no report has not reported zero violations — it has not reported.
            any_empty_report = True
            result.findings.append(Finding(
                rule="DRC_REPORT_EMPTY", severity="ERROR",
                message="DRC report file is 0 bytes — the run produced no "
                        "result. That is NOT zero violations; it is no "
                        "measurement. INCONCLUSIVE.", file=str(fp)))
            per_file.append({"file": str(fp), "empty_file": True})
            continue
        if not is_drc:
            # Not actually a DRC report; ignore it.
            continue
        any_drc_log = True
        c["file"] = str(fp)

        # --- establish geometry from OBSERVABLES, in decreasing authority ---
        bound, is_bound = _bind_layouts(layout_cands, cited)
        measures = [measure_layout(p) for p in bound]
        c["layout_measures"] = [asdict(m) for m in measures]
        c["layout_bound_by_name"] = is_bound
        measured = [m.shapes for m in measures if m.shapes is not None]
        # A MEASURED empty layout is decisive: it beats anything the log claims.
        # Bound by name -> any zero condemns. Unbound -> demand unanimity, so an
        # unrelated stray empty file cannot condemn a real run.
        measured_empty = (any(s == 0 for s in measured) if is_bound
                          else bool(measured) and all(s == 0 for s in measured))
        measured_geometry = bool(measured) and not measured_empty and max(measured) > 0
        reported_geometry = (c["reported_geometry_max"] or 0) > 0
        violations_prove_geometry = bool(c["nonzero_count"])

        if measured_empty:
            evidence = "MEASURED: the layout the run consumed holds 0 shapes"
            geometry_ok = False
        else:
            geometry_ok = (measured_geometry or reported_geometry
                           or violations_prove_geometry)
            evidence = ("MEASURED: {} shape(s) in the layout".format(max(measured))
                        if measured_geometry else
                        "REPORTED: checker counted {:g} geometry object(s)".format(
                            c["reported_geometry_max"]) if reported_geometry else
                        "IMPLIED: a non-zero violation count needs geometry"
                        if violations_prove_geometry else
                        "NONE: no measured layout, no positive reported count")
        c["geometry_established"] = geometry_ok
        c["geometry_evidence"] = evidence
        per_file.append(c)

        # Wording is carried ONLY to explain the verdict, never to reach it.
        hint = (" [wording hints (non-deciding): "
                + ", ".join(c["wording_hints"]) + "]") if c["wording_hints"] else ""
        # A number this checker REFUSED as retracted is not a number the report
        # never printed, and every message below used to say the second about
        # the first. The refusal travels with the verdict so a reader can see
        # that a count WAS there and why it was not used.
        if c.get("polarity_refused"):
            hint += (f" [polarity: {c['polarity_refused']} count(s) found and "
                     f"REFUSED as retracted by the report's own prose — this "
                     f"run did print numbers; they were not used]")

        if measured_empty:
            # Decisive, regardless of the verdict token or the tool's phrasing.
            any_empty_with_clean = True
            result.findings.append(Finding(
                rule="DRC_VACUOUS_PASS", severity="ERROR",
                message=f"DRC ran on an EMPTY layout — {evidence}. Any verdict "
                        f"from this run is vacuous, INCONCLUSIVE.{hint}",
                file=str(fp)))
            continue

        if c["nonzero_count"] and c["nonzero_count"] > 0:
            # Real violations reported — not vacuous (a real count gate handles it).
            any_real_check = True
            any_parsed_verdict = True
            result.findings.append(Finding(
                rule="DRC_NONZERO_COUNT", severity="INFO",
                message=f"DRC log reports {c['nonzero_count']} violation(s) — "
                        "not a vacuous PASS (defer to the violation-count gate).",
                file=str(fp)))
            continue

        if c["zero_count"]:
            any_parsed_verdict = True
            if not geometry_ok:
                any_empty_with_clean = True
                result.findings.append(Finding(
                    rule="DRC_VACUOUS_PASS", severity="ERROR",
                    message=f"0-violation verdict with geometry NOT positively "
                            f"established ({evidence}) — INCONCLUSIVE, not "
                            f"DRC-clean.{hint}",
                    file=str(fp)))
            else:
                any_real_check = True
                # SAY WHAT THIS GATE ESTABLISHED, AND NOTHING MORE.
                #
                # This gate answers exactly one question: is the 0 vacuous
                # because the layout is empty? Here it is not — there IS
                # geometry. That is the whole of the finding.
                #
                # The phrase it used to carry, "earned DRC-clean", claims a
                # different and much larger thing: that a DRC adequate to the
                # design ran and found nothing. This gate never looks at WHICH
                # deck produced the 0 and cannot tell a foundry sign-off deck
                # from the router's own in-loop pass.
                #
                # OBSERVED on a full run: the sign-off DRC was killed at its
                # wall-clock cap and wrote no report; the surviving
                # `drc_signoff.rpt` was the ROUTER's in-loop projection
                # (antenna + via only, no spacing, no width, no min-area); and
                # this line then stamped PASS / "earned DRC-clean" over a
                # layout independently measured to carry ~1,968 unpatchable
                # min-area shapes. `drc_signoff.json` correctly recorded
                # `passed=false, is_signoff_deck=false` and even warned that
                # the spacing and width categories were absent — so the truth
                # was on disk, and this sentence contradicted it.
                #
                # The verdict is unchanged (still INFO, still not vacuous). The
                # CLAIM is narrowed to what was measured, and the reader is
                # pointed at the artefact that owns deck adequacy.
                result.findings.append(Finding(
                    rule="DRC_CLEAN_EARNED", severity="INFO",
                    message=f"0-violation verdict on a layout proven to contain "
                            f"geometry ({evidence}) — the zero is NOT vacuous. "
                            f"This gate does NOT establish that the deck behind "
                            f"that zero is adequate for sign-off: it never reads "
                            f"which deck produced it, so a router in-loop pass "
                            f"and a foundry sign-off deck are indistinguishable "
                            f"here. For deck adequacy read "
                            f"`drc_signoff.json` (`is_signoff_deck`, `passed`) — "
                            f"do not quote this line as a clean DRC.{hint}",
                    file=str(fp)))
        elif geometry_ok:
            # BEFORE DEFERRING, ASK THE CHECKER WHAT IT EXAMINED.
            #
            # `DRC_NO_VERDICT_IN_SCOPE` (below) refuses a scope in which
            # NOTHING was parsed. It cannot help when a scope holds two steps
            # and only one of them ran: the finished step supplies a count, the
            # scope has a verdict in it, and the step that never started is
            # deferred over in silence.
            #
            # MEASURED at the scope the hygiene loop actually uses -- the whole
            # cell, no `--under` (`repo_hygiene_gates.sh` passes "$_cell") --
            # on the real run: Magic's 0-byte report deleted, KLayout's 53 273
            # left in place. Result: **PASS, exit 0**, with Magic having never
            # loaded a cell. That is the masking case, and this is where it is
            # caught: the step's own database names no cell, which is the
            # checker stating it examined nothing.
            #
            # Decisive, like a measured-empty layout, and for the same reason:
            # it is the run's own artefact contradicting the deferral, not a
            # phrasing this gate chose to trust.
            proof = completion_proof(fp)
            if proof is None:
                any_step_never_reported = True
                result.findings.append(Finding(
                    rule="DRC_STEP_NEVER_REPORTED", severity="ERROR",
                    message="No verdict parsed here, and nothing in this step "
                            "proves its checker examined a cell — no "
                            "report-database naming one. A finished checker "
                            "elsewhere in this scope does not speak for this "
                            "one. INCONCLUSIVE." + hint,
                    file=str(fp)))
                continue
            # No verdict token parsed, but the run demonstrably examined
            # geometry: not vacuous. The violation-count gate reads the count.
            any_real_check = True
            result.findings.append(Finding(
                rule="DRC_NO_VERDICT_TOKEN", severity="INFO",
                message=f"No 0-count clean verdict parsed, but geometry was "
                        f"established ({evidence}) — not vacuous by this gate "
                        f"(defer to violation-count gate).{hint}",
                file=str(fp)))
        else:
            # FAIL-SAFE: unrecognised/garbled report AND nothing measurable
            # behind it. We cannot show the run examined anything, so we do not
            # let it stand as a clean.
            any_empty_with_clean = True
            result.findings.append(Finding(
                rule="DRC_UNVERIFIABLE_RUN", severity="ERROR",
                message=(("No violation verdict this checker will USE "
                          "(every count it found was retracted by the "
                          "report's own prose)"
                          if c.get("polarity_refused")
                          else "No parseable violation verdict")
                         + f" and geometry NOT established ({evidence}) — "
                         f"INCONCLUSIVE; a clean requires positive "
                         f"evidence.{hint}"),
                file=str(fp)))

    result.summary = {"files_found": len(files), "per_file": per_file, **scope}

    # OUTRANKS the no-log SKIP below: a 0-byte report is not an absence of
    # evidence ("nothing to vet"), it is evidence of a run that terminated
    # without reporting. SKIP is exit 2 and callers are entitled to treat it as
    # non-blocking; this must block.
    if any_empty_report or any_step_never_reported:
        result.verdict = "INCONCLUSIVE"
        result.passed = False
        return result

    if not any_drc_log:
        result.verdict = "SKIP"
        result.passed = False
        if not any(f.rule in ("DRC_LOG_READABLE", "DRC_REPORT_EMPTY")
                   for f in result.findings):
            result.findings.append(Finding(
                rule="DRC_LOG_RECOGNISED", severity="ERROR",
                message="File(s) found but none look like a DRC report (SKIP)."))
        return result

    if any_empty_with_clean:
        result.verdict = "INCONCLUSIVE"
        result.passed = False
        return result

    # NOTHING IN SCOPE EVER REPORTED A VIOLATION COUNT.
    #
    # `DRC_NO_VERDICT_TOKEN` defers -- "no verdict parsed, but geometry was
    # established, so this is not vacuous BY THIS GATE; the violation-count
    # gate reads the count". That deferral is sound only while some other file
    # in scope actually carries a count. When NO file does, the deferral has
    # nowhere to defer TO, and exit 0 says "a clean was earned" over a scope in
    # which no checker ever stated a result.
    #
    # This is the same defect one layer up from the empty-report rule above,
    # and it survives that rule trivially: `rm` the 0-byte report and the only
    # thing left is the truncated log, which lands here.
    #
    # MEASURED (gf180mcuD, 16-stage non-CoB precheck, step 12, sha256 LOWUTIL):
    # Magic ran 14:47 at 99.95 % CPU and stopped at "Loading DRC CIF style." --
    # before its own checker output -- writing a 0-byte `drc.magic.rpt` and a
    # `drc.magic.lyrdb` whose top cell is `UNKNOWN`. With the report present
    # this returns INCONCLUSIVE. With that one empty file DELETED, the same
    # unfinished run returned **PASS**, on the strength of the 4 556 379 shapes
    # in the GDS -- geometry the checker demonstrably never got to.
    #
    # So geometry is not enough. Geometry proves the LAYOUT was worth checking;
    # it says nothing about whether the CHECKER ran. A clean must be earned by
    # a verdict, not by the existence of something to have a verdict about.
    #
    # SCOPE-LEVEL, deliberately: one unparsed report beside a report that DID
    # state a count still defers, exactly as before. Only a scope in which
    # nothing at all was parsed is refused. Measured on the published corpus
    # cell, which carries two unparsed reports and one real count: unchanged,
    # still PASS.
    if not any_parsed_verdict:
        result.verdict = "INCONCLUSIVE"
        result.passed = False
        result.findings.append(Finding(
            rule="DRC_NO_VERDICT_IN_SCOPE", severity="ERROR",
            message="DRC log(s) present and geometry established, but NO file "
                    "in scope reported a violation count — not zero, not "
                    "non-zero, none. A run that never stated a result has not "
                    "reported a clean, so there is no verdict here to call "
                    "vacuous or earned. INCONCLUSIVE."))
        return result

    result.verdict = "PASS"
    result.passed = True
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_EXIT = {"PASS": 0, "INCONCLUSIVE": 1, "SKIP": 2}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject a vacuous '0 DRC violations' PASS on an empty layout")
    parser.add_argument("path", help="Project directory or a single DRC log file")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    parser.add_argument("--layout", default=None,
                        help="The layout the DRC ran on (.gds/.gds.gz/.oas/.def). "
                             "Overrides discovery — measure THIS artifact.")
    parser.add_argument("--under", action="append", default=None, metavar="REL",
                        help="restrict DRC-report discovery to this "
                             "project-relative subtree or FILE (repeatable). "
                             "Omitted, discovery is project-wide. Use it to "
                             "scope a step's gate to the artefact that step "
                             "declares, so another step's DRC report cannot "
                             "carry — or condemn — this one.")
    args = parser.parse_args(argv)

    global _ACTIVE_INPUT_PLAN
    with _semantic_progress.child_progress(PROGRESS_SCOPE) as progress:
        try:
            if progress.enabled:
                path = Path(args.path)
                if (not path.is_dir() or args.json is not None
                        or args.layout is not None or args.under is not None):
                    raise _semantic_progress.ProgressProtocolError(
                        "routed parent progress covers the default project-dir "
                        "DRC invocation only")
                _ACTIVE_INPUT_PLAN = _input_plan(path)
                _ACTIVE_INPUT_PLAN.materialize(progress)
            rc = _main_parsed(args)
            if _ACTIVE_INPUT_PLAN is not None:
                _ACTIVE_INPUT_PLAN.checkpoint_decision(
                    fresh_plan=_input_plan(Path(args.path)))
            return rc
        finally:
            _ACTIVE_INPUT_PLAN = None


def _main_parsed(args) -> int:

    result = audit(Path(args.path),
                   Path(args.layout) if args.layout else None,
                   args.under)
    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    if result.verdict == "SKIP":
        # NOT CHECKED, disclosed at line start so the flow's verdict tier reads
        # it rather than inferring a pass from a bare rc.
        print(f"VACUOUS_PASS: drc_vacuous_pass_check examined "
              f"{result.summary.get('files_found', 0)} DRC report(s)"
              + (f" under {args.under}" if args.under else "")
              + " — nothing was vetted.")
    return _EXIT.get(result.verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
