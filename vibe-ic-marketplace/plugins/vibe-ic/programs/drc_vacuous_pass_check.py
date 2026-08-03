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

This is a *structural* check on the DRC run — it does NOT re-run DRC and does
NOT replace the violation-count gate; it sits in front of it.

Honest-failure contract
------------------------
  - No DRC log found             -> SKIP (exit 2)  -- nothing to vet, never PASS
  - Unreadable / empty log file  -> INCONCLUSIVE (exit 1)
  - measured layout has 0 shapes -> INCONCLUSIVE (exit 1)  -- the bug, decisive
  - 0-count, geometry NOT established -> INCONCLUSIVE (exit 1)  -- the bug
  - unparseable verdict, geometry NOT established -> INCONCLUSIVE (exit 1)
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
import json
import re
import struct
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple


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

_LAYOUT_GLOBS = ["*.gds", "*.gds.gz", "*.gdsii", "*.GDS",
                 "*.oas", "*.oasis", "*.def", "*.DEF"]


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
        with _open_maybe_gz(path) as fh:
            while True:
                head = fh.read(4)
                if len(head) < 4:
                    break
                length, rtype = struct.unpack(">H", head[:2])[0], head[2]
                if length < 4:
                    break                      # malformed record — stop honestly
                body = fh.read(length - 4)
                if len(body) < length - 4:
                    break
                if rtype in _GDS_SHAPE_RECS:
                    shapes += 1
                elif rtype == _GDS_REC_BGNSTR:
                    cells += 1
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
        text = path.read_text(errors="replace")
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
            return _count_via_klayout(path) or m
        return m
    if name.endswith((".def",)):
        return count_def_geometry(path)
    if name.endswith((".oas", ".oasis")):
        return (_count_via_klayout(path)
                or LayoutMeasure(file=str(path), fmt="oasis",
                                 method="none",
                                 error="OASIS needs klayout.db (not importable)"))
    return LayoutMeasure(file=str(path), fmt=path.suffix.lstrip("."),
                         method="none", error="unrecognised layout format")


def _discover_layouts(path: Path) -> List[Path]:
    """Layout artifacts near the DRC report: under the project dir, or beside a
    single log file (its own directory, then its parent)."""
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


def _bind_layouts(cands: List[Path], log_text: str) -> Tuple[List[Path], bool]:
    """Bind the layout(s) the report actually names.

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
    named = [p for p in cands
             if re.search(r"(?<![\w.-])" + re.escape(p.name) + r"(?![\w-])",
                          log_text)]
    if len(named) == 1:
        return named, True
    if named:
        return named, False       # ambiguous citation — unanimity, not decision
    return cands, False


def _is_drc_log(text: str) -> bool:
    """Heuristic: does this look like a DRC report at all?"""
    return bool(re.search(r"\bdrc\b|\bviolation|\berror", text, re.I))


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


def _reported_counts(text: str) -> List[float]:
    """Every NUMERIC geometry count the checker reported, in any word order."""
    out: List[float] = []
    for r in _REPORTED_COUNT_RE:
        for m in r.finditer(text):
            try:
                out.append(float(m.group(1)))
            except ValueError:
                pass
    return out


def _wording_hints(text: str) -> List[str]:
    """Phrases that merely EXPLAIN a verdict. Never used to decide one."""
    return [name for name, r in _WORDING_HINT_RE if r.search(text)]


def _classify_one(text: str) -> dict:
    """Classify a single DRC log's verdict + REPORTED numeric geometry counts.
    Prose is harvested only as `wording_hints` — it decides nothing."""
    zero = any(r.search(text) for r in _ZERO_COUNT_RE)
    nonzero = None
    for r in _NONZERO_COUNT_RE:
        m = r.search(text)
        if m:
            nonzero = int(m.group(1))
            break
    counts = _reported_counts(text)
    return {
        "zero_count": zero,
        "nonzero_count": nonzero,
        # (B) a POSITIVE reported count is evidence; a reported 0 is not.
        "reported_geometry_counts": counts,
        "reported_geometry_max": max(counts) if counts else None,
        "wording_hints": _wording_hints(text),   # explanation only
    }


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
    layout_cands = [layout] if layout else _discover_layouts(path)

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            result.findings.append(Finding(
                rule="DRC_LOG_READABLE", severity="ERROR",
                message="DRC log could not be read.", file=str(fp)))
            continue
        if not text.strip():
            result.findings.append(Finding(
                rule="DRC_LOG_NONEMPTY", severity="ERROR",
                message="DRC log is empty.", file=str(fp)))
            per_file.append({"file": str(fp), "empty_file": True})
            continue
        if not _is_drc_log(text):
            # Not actually a DRC report; ignore it.
            continue
        any_drc_log = True
        c = _classify_one(text)
        c["file"] = str(fp)

        # --- establish geometry from OBSERVABLES, in decreasing authority ---
        bound, is_bound = _bind_layouts(layout_cands, text)
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
            result.findings.append(Finding(
                rule="DRC_NONZERO_COUNT", severity="INFO",
                message=f"DRC log reports {c['nonzero_count']} violation(s) — "
                        "not a vacuous PASS (defer to the violation-count gate).",
                file=str(fp)))
            continue

        if c["zero_count"]:
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
                result.findings.append(Finding(
                    rule="DRC_CLEAN_EARNED", severity="INFO",
                    message=f"0-violation verdict on a layout proven to contain "
                            f"geometry ({evidence}) — earned DRC-clean.{hint}",
                    file=str(fp)))
        elif geometry_ok:
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
                message=f"No parseable violation verdict and geometry NOT "
                        f"established ({evidence}) — INCONCLUSIVE; a clean "
                        f"requires positive evidence.{hint}",
                file=str(fp)))

    result.summary = {"files_found": len(files), "per_file": per_file, **scope}

    if not any_drc_log:
        result.verdict = "SKIP"
        result.passed = False
        if not any(f.rule in ("DRC_LOG_READABLE", "DRC_LOG_NONEMPTY")
                   for f in result.findings):
            result.findings.append(Finding(
                rule="DRC_LOG_RECOGNISED", severity="ERROR",
                message="File(s) found but none look like a DRC report (SKIP)."))
        return result

    if any_empty_with_clean:
        result.verdict = "INCONCLUSIVE"
        result.passed = False
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
