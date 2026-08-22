#!/usr/bin/env python3
"""
gds_substance_check.py — the shipped chip GDS must be a structurally valid
GDSII stream carrying layout substance proportional to the design's own
placed-instance count.

Why this gate exists
--------------------
`gds_size_check` (v1.1.0) is a *size* gate: it compares the file against a
flow-wide constant (`--min-size-kb`, default 100) and downgrades a bad GDSII
header to a WARNING. Two fake tape-out artefacts therefore sign off clean:

  1. 150 KB of `os.urandom()` prefixed by a 4-byte HEADER record
     → `pass: true`, 0 errors, 0 warnings, Step 37 PASS.
  2. A structurally valid GDSII library containing ZERO structures
     (no cells, no geometry), zero-padded to 150 KB
     → `pass: true`, 0 errors, 0 warnings, Step 37 PASS.

Neither file is a layout. Both would ship. The 100 KB constant is also
unrelated to the design: a 200k-instance SoC streaming out a 120 KB stub
clears it just as easily as a 350-instance test chip.

What this gate checks (chip-AGNOSTIC — no per-design numbers)
-------------------------------------------------------------
A. STRUCTURE — a full record-stream walk of the GDSII file:
     - first record is HEADER, last record is ENDLIB
     - every record length is >= 4, even, and inside the file
     - no trailing bytes after ENDLIB
     - BGNLIB / LIBNAME / UNITS present; BGNSTR/ENDSTR balanced
   Any violation is a hard ERROR. A file that does not parse is not a GDS,
   regardless of how many bytes it has.

B. SUBSTANCE — the stream must actually contain layout:
     - at least one structure (BGNSTR)
     - at least one geometry/placement element
       (BOUNDARY / PATH / SREF / AREF / TEXT / BOX)
     - at least one drawn layer

C. DESIGN-DERIVED FLOOR — the floor comes from the design's OWN artefacts,
   never from a table of per-design constants. The placed-instance count is
   read from the design's routed DEF (`COMPONENTS <n> ;`); the GDS must then
   carry at least `--elements-per-instance` (default 1.0) layout elements per
   placed instance. A real stream-out emits at least one placement or polygon
   per placed cell — a stub cannot fake this without actually containing the
   layout. When no DEF is available the floor is skipped and reported as such
   (the structure + substance checks still apply).

Calibration (why the default ratio is 1.0)
------------------------------------------
Measured on the three committed converged spm cells (elements / placed
instances):

    v1.5.58_ihp-sg13g2   11583 / 1826 =  6.34
    v1.5.65_sky130A       8848 /  558 = 15.86
    v1.5.66_gf180mcuD    13337 / 2007 =  6.65

The 1.0 default sits 6.3x below the tightest real point, so the gate flags
substance-less artefacts without policing legitimate hierarchy vs flattening
style differences between PDKs. Note the placement records alone already
match the DEF almost exactly (SREF 1826/1826, 558/558, and 2145 SREF + 170
AREF for gf180's 2007) — the ratio's headroom comes from BOUNDARY geometry.

VACUOUS_PASS: no GDS at any canonical chip path → the project has not reached
stream-out. Gate inapplicable.

ENFORCEMENT: blocking — a GDS that is not a layout must not reach hand-off.
NOTE: currently wired AUDIT_ONLY (see flow_gate_enforcement_audit.py). The
declaration states the INTENT; the contradiction is real and deliberate to
surface, not a claim that it already blocks.

Usage:
    python3 gds_substance_check.py <project_dir> [--json <out>]
    python3 gds_substance_check.py --gds-file <f> [--def-file <f>] [--json <out>]

Exit codes:
    0  PASS / VACUOUS_PASS
    1  FAIL — not a valid GDSII stream, or no layout substance
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# GDSII record types we care about (SPEC: Calma GDSII Stream Format)
# ---------------------------------------------------------------------------
RT_HEADER = 0x0002
RT_BGNLIB = 0x0102
RT_LIBNAME = 0x0206
RT_UNITS = 0x0305
RT_ENDLIB = 0x0400
RT_BGNSTR = 0x0502
RT_STRNAME = 0x0606
RT_ENDSTR = 0x0700
RT_BOUNDARY = 0x0800
RT_PATH = 0x0900
RT_SREF = 0x0A00
RT_AREF = 0x0B00
RT_TEXT = 0x0C00
RT_LAYER = 0x0D02
RT_SNAME = 0x1206
RT_STRING = 0x1906
RT_TEXTTYPE = 0x1602
RT_BOX = 0x2D00

# Elements that constitute actual layout content.
_ELEMENT_RECORDS = {
    RT_BOUNDARY: "BOUNDARY",
    RT_PATH: "PATH",
    RT_SREF: "SREF",
    RT_AREF: "AREF",
    RT_TEXT: "TEXT",
    RT_BOX: "BOX",
}

# The canonical chip-GDS locations, shared with
# chip_gds_canonical_real_file_check.
_CANONICAL_GDS_GLOBS = (
    "phase3/stage4/gds/**/*.gds",
    "phase3/mixed_signal/**/*.gds",
)

# Where the design's own placed-instance count comes from. Ordered by
# preference: the routed DEF is the post-PnR truth.
_DEF_GLOBS = (
    "phase3/stage3/pnr/routed.def",
    "phase3/stage3/pnr/*.def",
)


@dataclass
class Finding:
    severity: str          # ERROR only — this gate has no advisory tier
    category: str
    message: str
    details: str = ""


@dataclass
class GdsStats:
    file_size_bytes: int = 0
    records: int = 0
    structures: int = 0
    elements: int = 0
    element_breakdown: Dict[str, int] = field(default_factory=dict)
    layers: List[int] = field(default_factory=list)
    libname: str = ""
    top_structures: List[str] = field(default_factory=list)
    parsed_to_endlib: bool = False
    trailing_bytes: int = 0


# ---------------------------------------------------------------------------
# A. Structure — full record-stream walk
# ---------------------------------------------------------------------------
def parse_gds(data: bytes) -> Tuple[List[Finding], GdsStats]:
    """Walk the GDSII record stream. Returns (findings, stats).

    Every structural violation is an ERROR: a file that does not parse as a
    record stream is not a GDSII file, no matter its size.
    """
    findings: List[Finding] = []
    st = GdsStats(file_size_bytes=len(data))
    layers: set = set()

    if len(data) < 4:
        findings.append(Finding(
            "ERROR", "NOT_GDSII",
            "File is shorter than a single GDSII record header (4 bytes)",
            f"size={len(data)} bytes"))
        return findings, st

    pos = 0
    saw_header = saw_bgnlib = saw_units = False
    open_structs = 0
    while pos + 4 <= len(data):
        rec_len, rec_type = struct.unpack_from('>HH', data, pos)

        if rec_len < 4:
            findings.append(Finding(
                "ERROR", "MALFORMED_RECORD",
                f"Record at offset {pos} declares length {rec_len} (< 4); "
                "the stream is not a valid GDSII record chain",
                f"record_type=0x{rec_type:04x}"))
            return findings, st
        if rec_len % 2:
            findings.append(Finding(
                "ERROR", "MALFORMED_RECORD",
                f"Record at offset {pos} has odd length {rec_len}; GDSII "
                "record lengths are always even",
                f"record_type=0x{rec_type:04x}"))
            return findings, st
        if pos + rec_len > len(data):
            findings.append(Finding(
                "ERROR", "TRUNCATED_RECORD",
                f"Record at offset {pos} declares length {rec_len} but only "
                f"{len(data) - pos} bytes remain; stream is truncated",
                f"record_type=0x{rec_type:04x}"))
            return findings, st

        payload = data[pos + 4:pos + rec_len]
        st.records += 1

        if st.records == 1 and rec_type != RT_HEADER:
            findings.append(Finding(
                "ERROR", "NOT_GDSII",
                "First record is not HEADER (0x0002); the file is not a "
                "GDSII stream",
                f"first record type=0x{rec_type:04x}"))
            return findings, st

        if rec_type == RT_HEADER:
            saw_header = True
        elif rec_type == RT_BGNLIB:
            saw_bgnlib = True
        elif rec_type == RT_UNITS:
            saw_units = True
        elif rec_type == RT_LIBNAME:
            st.libname = payload.rstrip(b'\x00').decode('ascii', 'replace')
        elif rec_type == RT_BGNSTR:
            open_structs += 1
            st.structures += 1
        elif rec_type == RT_STRNAME:
            name = payload.rstrip(b'\x00').decode('ascii', 'replace')
            if len(st.top_structures) < 20:
                st.top_structures.append(name)
        elif rec_type == RT_ENDSTR:
            open_structs -= 1
            if open_structs < 0:
                findings.append(Finding(
                    "ERROR", "UNBALANCED_STRUCTURE",
                    f"ENDSTR at offset {pos} without a matching BGNSTR"))
                return findings, st
        elif rec_type == RT_LAYER:
            if len(payload) >= 2:
                layers.add(struct.unpack_from('>h', payload, 0)[0])
        elif rec_type in _ELEMENT_RECORDS:
            st.elements += 1
            nm = _ELEMENT_RECORDS[rec_type]
            st.element_breakdown[nm] = st.element_breakdown.get(nm, 0) + 1
        elif rec_type == RT_ENDLIB:
            st.parsed_to_endlib = True
            pos += rec_len
            st.trailing_bytes = len(data) - pos
            break

        pos += rec_len

    st.layers = sorted(layers)

    if not st.parsed_to_endlib:
        findings.append(Finding(
            "ERROR", "NO_ENDLIB",
            "Stream ended without an ENDLIB (0x0400) record; the GDS is "
            "incomplete or truncated",
            f"records_parsed={st.records}"))
        return findings, st

    if st.trailing_bytes:
        findings.append(Finding(
            "ERROR", "TRAILING_GARBAGE",
            f"{st.trailing_bytes} bytes follow ENDLIB; a stream-out writes "
            "nothing after ENDLIB (padding to inflate file size is the "
            "signature of a fabricated artefact)",
            f"file_size={st.file_size_bytes}"))

    if open_structs:
        findings.append(Finding(
            "ERROR", "UNBALANCED_STRUCTURE",
            f"{open_structs} structure(s) opened with BGNSTR but never "
            "closed with ENDSTR"))

    for ok, name, rt in ((saw_header, "HEADER", RT_HEADER),
                         (saw_bgnlib, "BGNLIB", RT_BGNLIB),
                         (saw_units, "UNITS", RT_UNITS)):
        if not ok:
            findings.append(Finding(
                "ERROR", "MISSING_LIBRARY_RECORD",
                f"Mandatory library record {name} (0x{rt:04x}) is absent"))

    return findings, st


# ---------------------------------------------------------------------------
# A2. Per-structure content census (vibe-ic#613)
# ---------------------------------------------------------------------------
def iter_records(data: bytes):
    """Yield ``(offset, record_type, payload)`` over a GDSII record stream.

    THE CONTENT reader, and deliberately not the same walk as `parse_gds`:
    that one is the VALIDITY authority and must keep its own byte-exact pass so
    it can say WHERE a stream is malformed and return findings from the middle
    of it. This one assumes validity and stops silently at the first impossible
    record or at ENDLIB.

    A caller must establish validity with `parse_gds` FIRST — counting labels
    in a truncated file counts an artefact of the truncation, and reporting
    "0 labels" for a file that is not a GDS at all is a statement about the
    wrong thing.
    """
    pos, n = 0, len(data)
    while pos + 4 <= n:
        rec_len, rec_type = struct.unpack_from('>HH', data, pos)
        if rec_len < 4 or rec_len % 2 or pos + rec_len > n:
            return
        yield pos, rec_type, data[pos + 4:pos + rec_len]
        if rec_type == RT_ENDLIB:
            return
        pos += rec_len


@dataclass
class StructureCensus:
    """What each structure in a GDS library CONTAINS, and which are referenced.

    `text_per_structure` is per-STRUCTURE on purpose. A library GDS carries the
    std cells' own pin texts, so a GLOBAL text count is non-zero for a chip
    whose TOP cell has no label at all — the exact defect #613 measures.
    """
    structures: List[str] = field(default_factory=list)
    text_per_structure: Dict[str, int] = field(default_factory=dict)
    labels_per_structure: Dict[str, List[str]] = field(default_factory=dict)
    #: (gds_layer, texttype) per TEXT, in the same order as the strings.
    #: vibe-ic#631 — a label's LAYER decides whether an extractor can read it,
    #: and the string alone cannot say.
    label_layers_per_structure: Dict[str, List] = field(default_factory=dict)
    referenced: List[str] = field(default_factory=list)

    def top_structures(self) -> List[str]:
        """Structures no SREF/AREF references — the library's top cells."""
        refd = set(self.referenced)
        return [s for s in self.structures if s not in refd]


def structure_text_census(data: bytes) -> StructureCensus:
    """Count TEXT records per structure, capture their STRINGs, and collect
    SREF/AREF targets.

    The STRINGs are what make an answer actionable: a COUNT can only say how
    many labels are missing, and the names say WHICH port has nothing to name
    it. A STRING record occurs only inside a TEXT element, so collecting them
    per structure needs no element-state machine.
    """
    cen = StructureCensus()
    cur: Optional[str] = None
    _pend = None          # (layer, texttype) accumulating for the open TEXT
    for _off, rt, payload in iter_records(data):
        if rt == RT_STRNAME:
            cur = payload.rstrip(b'\x00').decode('ascii', 'replace')
            if cur not in cen.text_per_structure:
                cen.structures.append(cur)
                cen.text_per_structure[cur] = 0
                cen.labels_per_structure[cur] = []
                cen.label_layers_per_structure[cur] = []
        elif rt == RT_TEXT and cur is not None:
            cen.text_per_structure[cur] = cen.text_per_structure.get(cur, 0) + 1
            _pend = [None, 0]
        elif rt == RT_LAYER and cur is not None and _pend is not None:
            if len(payload) >= 2:
                _pend[0] = struct.unpack_from('>h', payload, 0)[0]
        elif rt == RT_TEXTTYPE and cur is not None and _pend is not None:
            if len(payload) >= 2:
                _pend[1] = struct.unpack_from('>h', payload, 0)[0]
        elif rt == RT_STRING and cur is not None:
            cen.labels_per_structure.setdefault(cur, []).append(
                payload.rstrip(b'\x00').decode('ascii', 'replace'))
            if _pend is not None and _pend[0] is not None:
                cen.label_layers_per_structure.setdefault(cur, []).append(
                    (int(_pend[0]), int(_pend[1])))
            _pend = None
        elif rt == RT_SNAME:
            nm = payload.rstrip(b'\x00').decode('ascii', 'replace')
            if nm not in cen.referenced:
                cen.referenced.append(nm)
        elif rt == RT_ENDSTR:
            cur = None
    return cen


# ---------------------------------------------------------------------------
# B/C. Substance + design-derived floor
# ---------------------------------------------------------------------------
def read_def_component_count(def_path: Path) -> Optional[int]:
    """Placed-instance count from the design's own DEF (`COMPONENTS <n> ;`)."""
    try:
        with open(def_path, 'r', errors='replace') as f:
            for line in f:
                s = line.strip()
                if s.startswith("COMPONENTS "):
                    parts = s.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        return int(parts[1])
    except OSError:
        return None
    return None


# Mask-stack floor (#298). The element-count floor below counts ELEMENTS, so it
# is defeated by degenerate geometry: 2,600 10x10 nm squares on ONE layer clears
# a 1,826-instance floor, is structurally valid, has structures/elements/LAYER,
# and is 166 KB — it passed every other check. A real full-chip stream-out draws
# device AND contact AND interconnect AND via layers; padding draws one.
#
# The threshold is MEASURED, not guessed: parsing all 62 real chip GDS on this
# host (6 designs x 4 PDKs, 8,762-1,555,181 elements, incl. foundry_handoff/ and
# .magic_merged.gds) gives distinct-layer counts of min 17 / max 19 with 0 parse
# errors. A floor of 4 leaves >4x headroom under the smallest real layout while
# the padded fake sits at 1. Structural constant, not per-design or per-PDK.
MIN_DISTINCT_LAYERS = 4


def audit_gds(data: bytes, instance_count: Optional[int],
              elements_per_instance: float,
              min_distinct_layers: int = MIN_DISTINCT_LAYERS,
              ) -> Tuple[List[Finding], GdsStats, dict]:
    findings, st = parse_gds(data)
    floor = {
        "instance_count": instance_count,
        "elements_per_instance": elements_per_instance,
        "required_elements": None,
        "actual_elements": st.elements,
        "min_distinct_layers": min_distinct_layers,
        "actual_distinct_layers": len(set(st.layers)),
        "applied": False,
    }

    # A structural failure already means "not a GDS" — substance checks on a
    # stream we could not parse would only add noise.
    if any(f.category in ("NOT_GDSII", "MALFORMED_RECORD", "TRUNCATED_RECORD",
                          "NO_ENDLIB") for f in findings):
        return findings, st, floor

    if st.structures == 0:
        findings.append(Finding(
            "ERROR", "NO_STRUCTURES",
            "GDS library contains zero structures (BGNSTR); it is an empty "
            "library, not a layout"))
    if st.elements == 0:
        findings.append(Finding(
            "ERROR", "NO_GEOMETRY",
            "GDS contains no layout elements (BOUNDARY / PATH / SREF / AREF "
            "/ TEXT / BOX); nothing was streamed out"))
    if not st.layers and st.elements:
        findings.append(Finding(
            "ERROR", "NO_LAYERS",
            "GDS contains elements but no LAYER record; no mask layer was "
            "drawn"))
    elif st.elements and min_distinct_layers > 0 \
            and len(set(st.layers)) < min_distinct_layers:
        findings.append(Finding(
            "ERROR", "MASK_STACK_TOO_THIN",
            f"GDS draws on only {len(set(st.layers))} distinct mask layer(s); "
            f"a real full-chip stream-out draws device + contact + "
            f"interconnect + via layers (>= {min_distinct_layers}). An "
            f"element count alone is satisfiable with degenerate geometry on a "
            f"single layer, so this is the check that catches padding",
            f"distinct_layers={len(set(st.layers))} "
            f"required={min_distinct_layers} elements={st.elements}"))

    if instance_count and instance_count > 0:
        required = int(instance_count * elements_per_instance)
        floor["required_elements"] = required
        floor["applied"] = True
        if st.elements < required:
            findings.append(Finding(
                "ERROR", "SUBSTANCE_BELOW_DESIGN_FLOOR",
                f"GDS carries {st.elements} layout elements but the design "
                f"places {instance_count} instances; a real stream-out emits "
                f"at least {required} "
                f"({elements_per_instance} x placed instances)",
                f"elements={st.elements} required={required} "
                f"instances={instance_count}"))

    return findings, st, floor


# ---------------------------------------------------------------------------
# Project-mode discovery
# ---------------------------------------------------------------------------
def find_canonical_gds(project: Path) -> List[Path]:
    out: List[Path] = []
    seen: set = set()
    for pat in _CANONICAL_GDS_GLOBS:
        for p in sorted(project.glob(pat)):
            if str(p) in seen:
                continue
            seen.add(str(p))
            out.append(p)
    return out


def find_def(project: Path) -> Optional[Path]:
    for pat in _DEF_GLOBS:
        for p in sorted(project.glob(pat)):
            if p.is_file():
                return p
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify the shipped chip GDS is a structurally valid "
                    "GDSII stream with layout substance matching the "
                    "design's own placed-instance count.")
    ap.add_argument("project_dir", nargs="?",
                    help="project directory (scans canonical chip-GDS paths)")
    ap.add_argument("--gds-file", help="audit a single GDS file instead")
    ap.add_argument("--def-file",
                    help="DEF supplying the placed-instance count "
                         "(single-file mode)")
    ap.add_argument("--elements-per-instance", type=float, default=1.0,
                    help="layout elements required per placed instance "
                         "(default: 1.0)")
    ap.add_argument("--min-distinct-layers", type=int,
                    default=MIN_DISTINCT_LAYERS,
                    help="mask-stack floor: minimum distinct GDS layers a real "
                         "full-chip stream-out must draw (#298). 0 disables the "
                         "check, which reproduces the pre-fix code path and is "
                         "used by the two-sided negative control.")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    if not args.project_dir and not args.gds_file:
        print("error: give a project_dir or --gds-file", file=sys.stderr)
        return 2

    targets: List[Tuple[Path, Optional[Path]]] = []
    project: Optional[Path] = None
    if args.gds_file:
        gp = Path(args.gds_file)
        if not gp.is_file():
            print(f"error: GDS not found: {gp}", file=sys.stderr)
            return 2
        targets.append((gp, Path(args.def_file) if args.def_file else None))
    else:
        project = Path(args.project_dir).resolve()
        if not project.is_dir():
            print(f"error: project dir not found: {project}", file=sys.stderr)
            return 2
        def_path = find_def(project)
        for g in find_canonical_gds(project):
            targets.append((g, def_path))

    if not targets:
        report = {
            "gate": "gds_substance_check",
            "version": "1.0.0",
            "verdict": "VACUOUS_PASS",
            "project": str(project) if project else None,
            "checked_globs": list(_CANONICAL_GDS_GLOBS),
            "reason": "no .gds at any canonical chip-GDS path; project has "
                      "not reached GDS stream-out yet.",
            "files": [],
        }
        _emit(report, args.json)
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0

    file_reports = []
    any_fail = False
    for gds_path, def_path in targets:
        try:
            data = gds_path.read_bytes()
        except OSError as e:
            print(f"error: cannot read {gds_path}: {e}", file=sys.stderr)
            return 2
        inst = read_def_component_count(def_path) if def_path else None
        findings, st, floor = audit_gds(data, inst,
                                        args.elements_per_instance,
                                        args.min_distinct_layers)
        ok = not findings
        any_fail = any_fail or not ok
        file_reports.append({
            "gds_file": (str(gds_path.relative_to(project))
                         if project else str(gds_path)),
            "def_file": (str(def_path.relative_to(project))
                         if project and def_path else
                         (str(def_path) if def_path else None)),
            "verdict": "PASS" if ok else "FAIL",
            "stats": asdict(st),
            "design_floor": floor,
            "findings": [asdict(f) for f in findings],
        })

    report = {
        "gate": "gds_substance_check",
        "version": "1.0.0",
        "verdict": "FAIL" if any_fail else "PASS",
        "project": str(project) if project else None,
        "elements_per_instance": args.elements_per_instance,
        "min_distinct_layers": args.min_distinct_layers,
        "files_checked": len(file_reports),
        "files": file_reports,
    }
    _emit(report, args.json)

    if any_fail:
        print("FAIL: chip GDS failed structure/substance audit:",
              file=sys.stderr)
        for fr in file_reports:
            for f in fr["findings"]:
                print(f"  {fr['gds_file']}: [{f['category']}] {f['message']}",
                      file=sys.stderr)
        return 1
    for fr in file_reports:
        s = fr["stats"]
        print(f"PASS: {fr['gds_file']} — {s['structures']} structures, "
              f"{s['elements']} elements, {len(s['layers'])} layers"
              + (f", floor {fr['design_floor']['required_elements']} "
                 f"(from {fr['design_floor']['instance_count']} placed "
                 f"instances)" if fr["design_floor"]["applied"] else
                 ", design floor N/A (no DEF)"))
    return 0


def _emit(report: dict, json_path: Optional[str]) -> None:
    if json_path:
        out = Path(json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
