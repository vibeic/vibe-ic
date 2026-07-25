#!/usr/bin/env python3
"""
gds_deliverable_plausibility_check.py — the sign-off GDS must be a
PLAUSIBLE LAYOUT, not merely a file of adequate size.

Doctrine
--------
"An empty artefact is not a passing artefact." A 0-byte / near-0-byte /
structurally-vacuous GDS is equally consistent with "the layout is clean"
and "the streamer wrote nothing". A sign-off flow must never emit
PASS / PASS_WITH_WAIVERS while its GDS deliverable cannot possibly be a
real layout of THIS design.

The gap this closes
-------------------
`gds_size_check` (the wired Step-37 gate) reduced "is this a layout?" to
two questions:

  * is the file >= a HARDCODED 100 KB floor?   (ERROR)
  * do bytes 2-3 look like a GDSII HEADER?     (WARNING — not fatal)

Both are unsound:

  1. The format check was a WARNING, so any >=100 KB blob passed as a
     sign-off GDS — measured, pre-fix: 150 KB of 0x00 -> exit 0; a
     renamed error log -> exit 0; 4 valid header bytes + 150 KB of
     garbage -> exit 0 with ZERO findings.
  2. A single hardcoded byte floor cannot be right for two designs of
     different size. It is simultaneously too high for a small design
     (false FAIL) and far too low for a large one: a 200,000-instance
     design shipping a 120 KB stub passes a 100 KB floor.

This gate replaces "big enough" with "structurally a layout, and big
enough FOR THIS DESIGN" — where the size expectation is derived from the
design's OWN placement data, never from a per-design constant.

What it checks (all chip-AGNOSTIC — no vendor / SKU / IC / PDK literal
appears in any decision)
------------------------------------------------------------------
Structural (applied to EVERY canonical GDS deliverable; hard FAIL):
  NOT_A_GDS           first record is not a GDSII HEADER record
  GDS_MALFORMED       record walk hit an impossible record length
  GDS_TRUNCATED       record walk overran EOF, or trailing bytes remain
  GDS_NO_ENDLIB       stream never terminates with ENDLIB
  GDS_NO_STRUCTURE    zero structure definitions (BGNSTR)
  GDS_NO_GEOMETRY     zero geometry/placement elements
  GDS_NO_LAYER        no element declares a layer number

Design-derived (applied to the top-level chip deliverable only; hard FAIL):
  DEF_ZERO_COMPONENTS  the placement the GDS claims to represent is empty
  GDS_PLACEMENT_SHORTFALL
                       the GDS accounts for fewer than
                       `--min-placement-coverage` (default 0.5) of the
                       instances the design's own DEF places
  GDS_BELOW_DESIGN_FLOOR
                       size < instances x `--min-bytes-per-instance`
                       (default 16)

Informational:
  DELIVERABLE_IS_SYMLINK
                       the deliverable path is a symlink. `ls -l` on a
                       symlink prints the length of the TARGET PATH
                       STRING, not the layout — an 86-character target
                       path reads as "86 bytes". Both the apparent
                       (lstat) and resolved (stat) sizes are reported so
                       a reviewer can never mistake one for the other.
                       Whether a symlink is ALLOWED at a canonical path
                       is `chip_gds_canonical_real_file_check`'s job,
                       not this gate's.

Why these constants are not per-design numbers
----------------------------------------------
`--min-bytes-per-instance 16` is a property of the GDSII RECORD FORMAT,
not of any design: the cheapest possible per-instance encoding is an
SREF (4) + SNAME (>=6) + XY (12) + ENDEL (4) ~= 28 bytes, so 16 leaves a
>1.7x margin below the format's own floor. Measured against the three
converged reference layouts in this repo the observed ratios are 450 /
588 / 1309 bytes per instance — a 28x-82x margin over the constant. It
can only fire on a stream that is physically incapable of carrying the
design's instances.

`--min-placement-coverage 0.5` compares the GDS's own placement count
(SREF + every AREF's cols x rows, or BOUNDARY count for a flattened
stream) against the DEF's COMPONENTS count. Measured on the same three
reference layouts the coverage is 1.00 / 1.00 / 1.07 — the 0.5 threshold
is a 2x margin. Array-dominated streams are handled by expanding AREF
COLROW, so a legitimately array-heavy layout is not penalised; for such
a stream the byte floor is reported as not-applicable rather than
enforced, because an AREF can place many instances in a few bytes.

Scope
-----
Full guard (structural + design-derived):
    phase3/stage4/gds/*.gds        (top level only — the chip deliverable)
Structural only (may legitimately be a partial / scribe / macro stream):
    phase3/stage4/gds/**/*.gds     (sub-cells)
    phase3/stage4/foundry_handoff/**/*.gds
    phase3/mixed_signal/**/*.gds

VACUOUS_PASS (exit 2): no canonical GDS exists yet — the project has not
reached stream-out, so the gate is inapplicable. It never passes
vacuously once a GDS is present.

Usage:
    python3 gds_deliverable_plausibility_check.py <project_dir> [--json <out>]
    python3 gds_deliverable_plausibility_check.py --gds-file <f> [--instances N]

Exit codes:
    0  PASS
    1  FAIL — at least one ERROR finding
    2  VACUOUS_PASS (no GDS yet) / usage error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# GDSII record types (SPEC constants — format-level, design-independent)
# --------------------------------------------------------------------------
_R_HEADER = 0x0002
_R_BGNLIB = 0x0102
_R_LIBNAME = 0x0206
_R_UNITS = 0x0305
_R_ENDLIB = 0x0400
_R_BGNSTR = 0x0502
_R_ENDSTR = 0x0700
_R_BOUNDARY = 0x0800
_R_PATH = 0x0900
_R_SREF = 0x0A00
_R_AREF = 0x0B00
_R_TEXT = 0x0C00
_R_BOX = 0x2D00
_R_LAYER = 0x0D02
_R_COLROW = 0x1302

_ELEMENT_RECORDS = (_R_BOUNDARY, _R_PATH, _R_SREF, _R_AREF, _R_TEXT, _R_BOX)

# Canonical deliverable locations. Chip-AGNOSTIC: directory layout only,
# never a design / vendor / PDK name.
_CHIP_GDS_GLOB = "phase3/stage4/gds/*.gds"
_SECONDARY_GDS_GLOBS = (
    "phase3/stage4/gds/*/**/*.gds",
    "phase3/stage4/foundry_handoff/**/*.gds",
    "phase3/mixed_signal/**/*.gds",
)

# DEF search order for the design's own instance count. Most-final first.
_DEF_GLOBS = (
    "phase3/**/routed.def",
    "phase3/**/filled.def",
    "phase3/**/*.def",
)

# Format-level floor (see module docstring): the cheapest legal GDSII
# per-instance encoding is ~28 bytes; 16 keeps a margin below that.
DEFAULT_MIN_BYTES_PER_INSTANCE = 16
# The GDS must account for at least this fraction of the DEF's instances.
DEFAULT_MIN_PLACEMENT_COVERAGE = 0.5

# Bound the record walk so a hostile/garbage file cannot spin forever.
_MAX_RECORDS = 200_000_000


@dataclass
class Finding:
    severity: str          # ERROR | INFO
    rule: str
    path: str
    message: str


@dataclass
class GdsStats:
    parsed: bool = False
    header_ok: bool = False
    endlib: bool = False
    walk_complete: bool = False
    parse_error: Optional[str] = None
    size_bytes: int = 0
    apparent_size_bytes: int = 0
    is_symlink: bool = False
    structures: int = 0
    boundaries: int = 0
    paths: int = 0
    srefs: int = 0
    arefs: int = 0
    aref_placements: int = 0
    texts: int = 0
    boxes: int = 0
    layers: List[int] = field(default_factory=list)

    @property
    def elements(self) -> int:
        return (self.boundaries + self.paths + self.srefs
                + self.arefs + self.texts + self.boxes)

    @property
    def placements(self) -> int:
        """Instances the stream actually places.

        Hierarchical stream: one SREF per instance, plus every AREF's
        full cols x rows expansion. Flattened stream (no SREF/AREF at
        all): each instance must contribute at least one BOUNDARY, so
        the boundary count is the placement proxy.
        """
        if self.srefs or self.arefs:
            return self.srefs + self.aref_placements
        return self.boundaries


# --------------------------------------------------------------------------
# GDSII record-stream walk (pure Python, streaming, bounded memory)
# --------------------------------------------------------------------------
def parse_gds(path: Path) -> GdsStats:
    st = GdsStats()
    try:
        st.is_symlink = path.is_symlink()
        st.apparent_size_bytes = path.lstat().st_size
        st.size_bytes = path.stat().st_size
    except OSError as exc:
        st.parse_error = f"stat failed: {exc}"
        return st

    size = st.size_bytes
    if size < 4:
        st.parse_error = f"file is {size} bytes — too short to hold one GDSII record"
        return st

    try:
        with open(path, "rb") as fh:
            pos = 0
            first = True
            records = 0
            while pos + 4 <= size:
                head = fh.read(4)
                if len(head) < 4:
                    st.parse_error = f"unexpected EOF reading record header at byte {pos}"
                    return st
                rec_len = (head[0] << 8) | head[1]
                rec_type = (head[2] << 8) | head[3]

                if first:
                    first = False
                    st.header_ok = (rec_type == _R_HEADER)
                    if not st.header_ok:
                        st.parse_error = (
                            f"first record type is 0x{rec_type:04x}, "
                            f"expected 0x{_R_HEADER:04x} (HEADER)")
                        return st

                if rec_len < 4:
                    st.parse_error = (
                        f"impossible record length {rec_len} at byte {pos} "
                        f"(record type 0x{rec_type:04x})")
                    return st
                if pos + rec_len > size:
                    st.parse_error = (
                        f"record at byte {pos} declares length {rec_len} but "
                        f"only {size - pos} bytes remain — stream is truncated")
                    return st

                payload = rec_len - 4
                if rec_type == _R_LAYER and payload >= 2:
                    body = fh.read(2)
                    if len(body) == 2:
                        layer = int.from_bytes(body, "big", signed=True)
                        if layer not in st.layers:
                            st.layers.append(layer)
                    fh.seek(payload - 2, os.SEEK_CUR)
                elif rec_type == _R_COLROW and payload >= 4:
                    body = fh.read(4)
                    if len(body) == 4:
                        cols = int.from_bytes(body[0:2], "big", signed=True)
                        rows = int.from_bytes(body[2:4], "big", signed=True)
                        if cols > 0 and rows > 0:
                            # An AREF already counted itself once via the
                            # AREF record; add the remaining placements.
                            st.aref_placements += cols * rows
                    fh.seek(payload - 4, os.SEEK_CUR)
                elif payload:
                    fh.seek(payload, os.SEEK_CUR)

                if rec_type == _R_BGNSTR:
                    st.structures += 1
                elif rec_type == _R_BOUNDARY:
                    st.boundaries += 1
                elif rec_type == _R_PATH:
                    st.paths += 1
                elif rec_type == _R_SREF:
                    st.srefs += 1
                elif rec_type == _R_AREF:
                    st.arefs += 1
                elif rec_type == _R_TEXT:
                    st.texts += 1
                elif rec_type == _R_BOX:
                    st.boxes += 1
                elif rec_type == _R_ENDLIB:
                    st.endlib = True

                pos += rec_len
                records += 1
                if records > _MAX_RECORDS:
                    st.parse_error = "record count exceeded sanity bound"
                    return st

            st.walk_complete = (pos == size)
            if not st.walk_complete:
                st.parse_error = (
                    f"{size - pos} trailing byte(s) after the last complete "
                    f"record — stream is truncated or corrupt")
                return st
            st.parsed = True
    except OSError as exc:
        st.parse_error = f"read failed: {exc}"
    return st


# --------------------------------------------------------------------------
# Design-side instance count (the design's OWN data — never a constant)
# --------------------------------------------------------------------------
_COMPONENTS_RE = re.compile(rb"^COMPONENTS\s+(\d+)\s*;", re.MULTILINE)
_DESIGN_RE = re.compile(rb"^DESIGN\s+(\S+)\s*;", re.MULTILINE)


def read_def_placement(def_path: Path) -> Tuple[Optional[int], Optional[str]]:
    """Return (components, design_name) declared by a DEF file."""
    try:
        blob = def_path.read_bytes()
    except OSError:
        return None, None
    m = _COMPONENTS_RE.search(blob)
    d = _DESIGN_RE.search(blob)
    return (int(m.group(1)) if m else None,
            d.group(1).decode("ascii", "replace") if d else None)


def discover_design_placement(project: Path,
                              top_hint: Optional[str] = None) -> Dict[str, object]:
    """Find the design's own instance count from its own DEF artefacts.

    `top_hint` is the chip GDS's file stem. When a candidate DEF declares
    `DESIGN <top_hint>`, that DEF is the authoritative placement for THIS
    deliverable and wins outright — otherwise a macro's or sub-block's DEF
    sorting earlier could supply an instance count belonging to a
    different design. Without a match the most-final-first order applies.
    """
    ordered: List[Tuple[Path, int, Optional[str]]] = []
    seen: set = set()
    for pat in _DEF_GLOBS:
        for cand in sorted(project.glob(pat)):
            key = str(cand.resolve())
            if key in seen or not cand.is_file():
                continue
            seen.add(key)
            comps, design = read_def_placement(cand)
            if comps is None:
                continue
            ordered.append((cand, comps, design))

    if not ordered:
        return {"source": None, "instances": None, "design": None}

    chosen = ordered[0]
    if top_hint:
        for entry in ordered:
            if entry[2] == top_hint:
                chosen = entry
                break
    cand, comps, design = chosen
    return {
        "source": str(cand.relative_to(project)),
        "instances": comps,
        "design": design,
        "matched_top": bool(top_hint and design == top_hint),
    }


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------
def _structural_findings(rel: str, st: GdsStats) -> List[Finding]:
    out: List[Finding] = []
    if st.is_symlink:
        out.append(Finding(
            "INFO", "DELIVERABLE_IS_SYMLINK", rel,
            f"path is a symlink: `ls -l` reports {st.apparent_size_bytes} "
            f"bytes (the length of the target path string), the resolved "
            f"layout is {st.size_bytes} bytes — do not read the apparent "
            f"size as the GDS size"))
    if not st.parsed:
        rule = "NOT_A_GDS" if not st.header_ok else "GDS_TRUNCATED"
        err = (st.parse_error or "unparseable").lower()
        if st.header_ok and ("impossible record length" in err):
            rule = "GDS_MALFORMED"
        out.append(Finding(
            "ERROR", rule, rel,
            f"file is not a well-formed GDSII stream: {st.parse_error}"))
        return out
    if not st.endlib:
        out.append(Finding(
            "ERROR", "GDS_NO_ENDLIB", rel,
            "stream never terminates with an ENDLIB record — a streamer "
            "that died mid-write leaves exactly this"))
    if st.structures == 0:
        out.append(Finding(
            "ERROR", "GDS_NO_STRUCTURE", rel,
            "stream defines zero structures (BGNSTR) — it contains no cell"))
    if st.elements == 0:
        out.append(Finding(
            "ERROR", "GDS_NO_GEOMETRY", rel,
            "stream contains zero geometry or placement elements — an "
            "empty artefact is not a passing artefact"))
    if not st.layers and st.elements:
        out.append(Finding(
            "ERROR", "GDS_NO_LAYER", rel,
            "no element declares a layer number — the stream carries no "
            "mask geometry"))
    return out


def _design_findings(rel: str, st: GdsStats, instances: Optional[int],
                     def_source: Optional[str],
                     min_bpi: int, min_cov: float) -> List[Finding]:
    out: List[Finding] = []
    if instances is None:
        out.append(Finding(
            "INFO", "DESIGN_FLOOR_NOT_DERIVABLE", rel,
            "no DEF with a COMPONENTS count was found, so no design-derived "
            "size floor could be computed; structural checks still applied"))
        return out
    if instances == 0:
        out.append(Finding(
            "ERROR", "DEF_ZERO_COMPONENTS", rel,
            f"the design's own placement ({def_source}) declares COMPONENTS 0 "
            f"— there is nothing to lay out, so no GDS can back a PASS"))
        return out

    coverage = st.placements / instances if instances else 0.0
    if coverage < min_cov:
        out.append(Finding(
            "ERROR", "GDS_PLACEMENT_SHORTFALL", rel,
            f"GDS accounts for {st.placements} placement(s) but the design's "
            f"own DEF ({def_source}) places {instances} instance(s) — "
            f"coverage {coverage:.3f} < required {min_cov}"))

    # An AREF can place many instances in a handful of bytes, so the byte
    # floor is only meaningful for a stream that is not array-dominated.
    array_dominated = st.aref_placements > st.srefs
    floor = instances * min_bpi
    if array_dominated:
        out.append(Finding(
            "INFO", "DESIGN_BYTE_FLOOR_NOT_APPLICABLE", rel,
            f"stream is array-dominated ({st.aref_placements} AREF "
            f"placement(s) vs {st.srefs} SREF(s)); the per-instance byte "
            f"floor does not apply, placement coverage governs"))
    elif st.size_bytes < floor:
        out.append(Finding(
            "ERROR", "GDS_BELOW_DESIGN_FLOOR", rel,
            f"GDS is {st.size_bytes} bytes but the design's own DEF "
            f"({def_source}) places {instances} instance(s); the GDSII "
            f"record format cannot encode them in fewer than "
            f"{instances} x {min_bpi} = {floor} bytes"))
    return out


def audit(project: Path, min_bpi: int = DEFAULT_MIN_BYTES_PER_INSTANCE,
          min_cov: float = DEFAULT_MIN_PLACEMENT_COVERAGE) -> dict:
    # `is_symlink()` is part of the predicate on purpose: a BROKEN symlink
    # is not `is_file()`, and silently dropping it would let a dangling
    # deliverable reach VACUOUS_PASS — the worst possible outcome for a
    # gate whose whole subject is missing substance.
    def _candidate(p: Path) -> bool:
        return p.is_file() or p.is_symlink()

    chip = sorted(p for p in project.glob(_CHIP_GDS_GLOB) if _candidate(p))
    secondary: List[Path] = []
    seen = {str(p) for p in chip}
    for pat in _SECONDARY_GDS_GLOBS:
        for p in sorted(project.glob(pat)):
            if _candidate(p) and str(p) not in seen:
                seen.add(str(p))
                secondary.append(p)

    if not chip and not secondary:
        return {
            "gate": "gds_deliverable_plausibility_check",
            "verdict": "VACUOUS_PASS",
            "project": str(project),
            "reason": ("no .gds at any canonical deliverable path — the "
                       "project has not reached GDS stream-out yet"),
            "findings": [],
            "artefacts": [],
        }

    placement = discover_design_placement(
        project, top_hint=(chip[0].stem if chip else None))
    instances = placement["instances"]
    def_source = placement["source"]

    findings: List[Finding] = []
    artefacts: List[dict] = []

    for p, full in [(c, True) for c in chip] + [(s, False) for s in secondary]:
        rel = str(p.relative_to(project))
        st = parse_gds(p)
        f = _structural_findings(rel, st)
        if full and st.parsed:
            f += _design_findings(rel, st, instances, def_source,
                                  min_bpi, min_cov)
        findings += f
        artefacts.append({
            "path": rel,
            "scope": "chip_deliverable" if full else "secondary",
            "size_bytes": st.size_bytes,
            "apparent_size_bytes": st.apparent_size_bytes,
            "is_symlink": st.is_symlink,
            "well_formed": st.parsed,
            "endlib": st.endlib,
            "structures": st.structures,
            "elements": st.elements,
            "placements": st.placements,
            "srefs": st.srefs,
            "arefs": st.arefs,
            "aref_placements": st.aref_placements,
            "boundaries": st.boundaries,
            "layers": len(st.layers),
            "parse_error": st.parse_error,
            "bytes_per_instance": (round(st.size_bytes / instances, 1)
                                   if full and instances else None),
        })

    errors = [x for x in findings if x.severity == "ERROR"]
    return {
        "gate": "gds_deliverable_plausibility_check",
        "verdict": "FAIL" if errors else "PASS",
        "project": str(project),
        "design_placement": placement,
        "thresholds": {
            "min_bytes_per_instance": min_bpi,
            "min_placement_coverage": min_cov,
        },
        "errors_count": len(errors),
        "findings": [asdict(x) for x in findings],
        "artefacts": artefacts,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify the sign-off GDS is a plausible layout of "
                    "this design, not merely a file of adequate size.")
    ap.add_argument("project_dir", nargs="?",
                    help="project root (canonical-path mode)")
    ap.add_argument("--gds-file", help="audit a single GDS (standalone mode)")
    ap.add_argument("--instances", type=int, default=None,
                    help="instance count for standalone mode; without it "
                         "only the structural checks apply")
    ap.add_argument("--min-bytes-per-instance", type=int,
                    default=DEFAULT_MIN_BYTES_PER_INSTANCE)
    ap.add_argument("--min-placement-coverage", type=float,
                    default=DEFAULT_MIN_PLACEMENT_COVERAGE)
    ap.add_argument("--json", help="write the JSON report here")
    args = ap.parse_args(argv)

    if args.gds_file:
        p = Path(args.gds_file)
        if not p.exists():
            print(f"FAIL: GDS not found: {p}", file=sys.stderr)
            report = {
                "gate": "gds_deliverable_plausibility_check",
                "verdict": "FAIL",
                "findings": [asdict(Finding(
                    "ERROR", "MISSING_GDS", str(p),
                    "GDS deliverable does not exist"))],
                "artefacts": [],
            }
        else:
            st = parse_gds(p)
            f = _structural_findings(str(p), st)
            if st.parsed:
                f += _design_findings(
                    str(p), st, args.instances, "--instances",
                    args.min_bytes_per_instance, args.min_placement_coverage)
            errs = [x for x in f if x.severity == "ERROR"]
            report = {
                "gate": "gds_deliverable_plausibility_check",
                "verdict": "FAIL" if errs else "PASS",
                "errors_count": len(errs),
                "findings": [asdict(x) for x in f],
                "artefacts": [{
                    "path": str(p),
                    "scope": "chip_deliverable",
                    "size_bytes": st.size_bytes,
                    "apparent_size_bytes": st.apparent_size_bytes,
                    "is_symlink": st.is_symlink,
                    "well_formed": st.parsed,
                    "structures": st.structures,
                    "elements": st.elements,
                    "placements": st.placements,
                    "parse_error": st.parse_error,
                }],
            }
    else:
        if not args.project_dir:
            ap.error("either <project_dir> or --gds-file is required")
        project = Path(args.project_dir).resolve()
        if not project.is_dir():
            print(f"error: project dir not found: {project}", file=sys.stderr)
            return 2
        report = audit(project, args.min_bytes_per_instance,
                       args.min_placement_coverage)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    verdict = report["verdict"]
    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 2
    if verdict == "PASS":
        n = len(report.get("artefacts", []))
        print(f"PASS: {n} GDS deliverable(s) are well-formed GDSII and "
              f"plausible for this design's own placement.")
        for f in report["findings"]:
            print(f"  INFO {f['rule']}: {f['path']} — {f['message']}")
        return 0

    print("FAIL: the GDS deliverable cannot be a real layout of this design:",
          file=sys.stderr)
    for f in report["findings"]:
        if f["severity"] == "ERROR":
            print(f"  {f['rule']}: {f['path']} — {f['message']}",
                  file=sys.stderr)
    print("  -> An empty artefact is not a passing artefact. A sign-off "
          "verdict must not be issued over this file.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
