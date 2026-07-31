#!/usr/bin/env python3
"""analog_lef_gds_outline_check.py — A8 LEF-vs-GDS outline gate.

Codifies the EXTRACT-NEW spot-check in
`skills/analog-output-verify/SKILL.md`:

    A8 hardmacro_gen:  "LEF matches GDS outline"
    Spot-check:        "Cross-check A8 LEF outline width × height vs
                        A5 layout extents"

`analog_hardmacro_check.py` only proves the LEF *contains* a MACRO/PIN
keyword and that the GDS is non-empty — it never reads the numeric
`SIZE w BY h ;` line nor the GDS bounding box, so a LEF that claims a
100x100 abstract over a GDS whose real polygons span 250x80 sails
through every existing gate. That mismatch is a real, silicon-relevant
defect (the digital PnR floorplan reserves the LEF outline; if the GDS
is wider the macro overlaps its neighbours / the seal ring).

This gate, per hardmacro block:
  1. parses `SIZE <w> BY <h> ;` from the macro's `.lef`
     (microns; LEF SIZE is always in microns).
  2. parses the GDS bounding box from the *binary* GDSII stream
     (UNITS record → user-unit-in-microns; BOUNDARY / PATH / BOX
     XY records → coordinate extents in database units → microns).
  3. compares LEF width/height against GDS width/height; FAIL when
     either differs by more than `--tol-pct` (default 2.0 %).

Honest FAIL / SKIP contract (NO FABRICATION):
  * no `analog/analog_block_list.json` (or empty) → VACUOUS_PASS
    (digital-only project, gate inapplicable).
  * a hardmacro block dir with NEITHER a .lef NOR a .gds → that
    block is not yet packaged; reported INFO, not a violation
    (A8-presence is `analog_a8_hardmacro_gen_check`'s job, not ours).
  * a block that has a .lef but no .gds (or vice-versa), or a .lef
    with no parseable SIZE line, or a .gds with no extractable
    boundary → HONEST FAIL for that block (you cannot prove the
    outlines match, and the spot-check's whole point is that the
    pair exists and agrees).
  * a DETERMINISTIC-STUB hardmacro (LEF/LIB/V carrying the
    `extraction_strategy=deterministic_stub` marker) that ships NO
    .gds at all → `STUB_NOT_PACKAGED`: a NAMED, disclosed skip, not a
    pass and not a FAIL. The A7 stub tier deliberately omits the .gds
    (replacing it with a real one is A5's job) and
    `analog_hardmacro_check` already credits it at the PASS_WITH_STUB
    tier; this gate must not contradict that when it is wired into the
    same A8 all_of. The exemption is narrow ON PURPOSE: a stub-marked
    LEF that DOES ship a .gds is compared like any other, so no block
    buys a free pass on an outline it actually claims.
  * garbage / truncated GDS, unreadable LEF → HONEST FAIL.
  Never a vacuous PASS on absent / garbage input.

Usage:
    python3 analog_lef_gds_outline_check.py <project_dir> [--json <out>]
                                            [--block <name>] [--tol-pct 2.0]

Exit codes:
    0 = PASS / VACUOUS_PASS
    1 = FAIL (outline mismatch / missing-half / unparseable pair)
    2 = argument or fatal I/O error

chip-AGNOSTIC. No vendor / IC / pin / byte / block-name string.
"""
from __future__ import annotations

import argparse
import json
import re
import math
import struct
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover - allow direct import in tests
    _pl = None

try:
    from _analog_stub_marker import is_stub_text
except ImportError:  # pragma: no cover - allow direct import in tests
    def is_stub_text(text):  # type: ignore[misc]
        """Fallback that recognises NOTHING as a stub. Failing closed is the
        safe direction here: an unrecognised stub is FAILed, never passed."""
        return False


GATE = "analog_lef_gds_outline_check"
DEFAULT_TOL_PCT = 2.0

# LEF SIZE line:  SIZE 100 BY 100 ;   /  SIZE 12.5 BY 8.0 ;
_LEF_SIZE_RE = re.compile(
    r"\bSIZE\s+([0-9]*\.?[0-9]+)\s+BY\s+([0-9]*\.?[0-9]+)\s*;",
    re.IGNORECASE,
)

# GDSII record types we care about.
_GDS_HEADER = 0x0002
_GDS_UNITS = 0x0305
_GDS_BOUNDARY = 0x0800
_GDS_PATH = 0x0900
_GDS_BOX = 0x2D00
_GDS_XY = 0x1003


# ───────────────────────── block discovery ─────────────────────────

def _analog_root(project: Path) -> Path:
    if _pl is not None:
        return _pl.analog_dir(project)
    # fallback mirrors _path_layout.analog_dir
    return project / "phase3/analog"


def _hardmacro_root(project: Path) -> Path:
    if _pl is not None:
        return _pl.hardmacro_dir(project)
    return project / "phase3/analog/hardmacro"


def _load_block_list(project: Path) -> Optional[List[str]]:
    """Return declared block names, or None when no analog block list
    exists at all (→ VACUOUS_PASS)."""
    bl = _analog_root(project) / "analog_block_list.json"
    if not bl.is_file():
        return None
    try:
        data = json.loads(bl.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list):
        return []
    out: List[str] = []
    for entry in blocks:
        if isinstance(entry, str) and entry:
            out.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("block")
            if isinstance(name, str) and name:
                out.append(name)
    return out


# ───────────────────────── LEF SIZE parse ──────────────────────────

def parse_lef_size(lef_text: str) -> Optional[Tuple[float, float]]:
    """Return (width_um, height_um) from the first LEF `SIZE w BY h ;`
    line, or None when no such line exists."""
    m = _LEF_SIZE_RE.search(lef_text)
    if not m:
        return None
    try:
        return (float(m.group(1)), float(m.group(2)))
    except ValueError:  # pragma: no cover - regex already constrains
        return None


# ───────────────────────── GDS bbox parse ──────────────────────────

# Structure / reference records needed to resolve a HIERARCHICAL stream.
_GDS_BGNSTR = 0x0502
_GDS_STRNAME = 0x0606
_GDS_ENDSTR = 0x0700
_GDS_SREF = 0x0A00
_GDS_AREF = 0x0B00
_GDS_BOX = 0x2D00
_GDS_TEXT = 0x0C00
_GDS_ENDEL = 0x1100
_GDS_SNAME = 0x1206
_GDS_STRANS = 0x1A01
_GDS_MAG = 0x1B05
_GDS_ANGLE = 0x1C05
_GDS_COLROW = 0x1302


def _xy_points(data: bytes):
    cnt = len(data) // 4
    cnt -= cnt % 2
    return [(struct.unpack(">i", data[i * 4:(i + 1) * 4])[0],
             struct.unpack(">i", data[(i + 1) * 4:(i + 2) * 4])[0])
            for i in range(0, cnt, 2)]


def _parse_structures(raw: bytes):
    """{struct_name: {"geom": [pts...], "refs": [(sname, placement)]}} plus the
    dbu size in metres. Pure GDSII record walk."""
    structs = {}
    meters_per_dbu = None
    seen_header = False
    cur = None
    el = None          # current element context
    pos, n = 0, len(raw)
    while pos + 4 <= n:
        rec_len = (raw[pos] << 8) | raw[pos + 1]
        rec_type = (raw[pos + 2] << 8) | raw[pos + 3]
        if rec_len < 4 or pos + rec_len > n:
            break
        data = raw[pos + 4: pos + rec_len]
        pos += rec_len
        if rec_type == _GDS_HEADER:
            seen_header = True
        elif rec_type == _GDS_UNITS:
            if len(data) >= 16:
                meters_per_dbu = _gds_real8(data[8:16])
        elif rec_type == _GDS_BGNSTR:
            cur = None
        elif rec_type == _GDS_STRNAME:
            cur = data.split(b"\x00")[0].decode("ascii", "replace")
            structs.setdefault(cur, {"geom": [], "refs": []})
        elif rec_type == _GDS_ENDSTR:
            cur = None
        elif rec_type in (_GDS_BOUNDARY, _GDS_PATH, _GDS_BOX):
            el = {"kind": "geom"}
        elif rec_type in (_GDS_SREF, _GDS_AREF):
            el = {"kind": "ref", "aref": rec_type == _GDS_AREF,
                  "sname": None, "mag": 1.0, "angle": 0.0, "reflect": False,
                  "cols": 1, "rows": 1}
        elif rec_type == _GDS_TEXT:
            el = {"kind": "text"}          # TEXT XY is a label origin, not extent
        elif rec_type == _GDS_SNAME and el is not None:
            el["sname"] = data.split(b"\x00")[0].decode("ascii", "replace")
        elif rec_type == _GDS_STRANS and el is not None and len(data) >= 2:
            el["reflect"] = bool(data[0] & 0x80)
        elif rec_type == _GDS_MAG and el is not None and len(data) >= 8:
            el["mag"] = _gds_real8(data[0:8])
        elif rec_type == _GDS_ANGLE and el is not None and len(data) >= 8:
            el["angle"] = _gds_real8(data[0:8])
        elif rec_type == _GDS_COLROW and el is not None and len(data) >= 4:
            el["cols"] = struct.unpack(">h", data[0:2])[0] or 1
            el["rows"] = struct.unpack(">h", data[2:4])[0] or 1
        elif rec_type == _GDS_XY and el is not None and cur is not None:
            pts = _xy_points(data)
            if el["kind"] == "geom":
                structs[cur]["geom"].extend(pts)
            elif el["kind"] == "ref" and el.get("sname") and pts:
                el["pts"] = pts
                structs[cur]["refs"].append((el["sname"], dict(el)))
        elif rec_type == _GDS_ENDEL:
            el = None
    return structs, meters_per_dbu, seen_header


def _struct_bbox(name, structs, memo, stack):
    """(minx, miny, maxx, maxy) of a structure in ITS OWN coordinates, with all
    references resolved through their placement transforms. Cycle-guarded."""
    if name in memo:
        return memo[name]
    if name in stack or name not in structs:
        return None
    stack.add(name)
    xs, ys = [], []
    st = structs[name]
    for (x, y) in st["geom"]:
        xs.append(x)
        ys.append(y)
    for sname, ref in st["refs"]:
        child = _struct_bbox(sname, structs, memo, stack)
        if child is None:
            continue
        cx0, cy0, cx1, cy1 = child
        mag = ref.get("mag") or 1.0
        ang = math.radians(ref.get("angle") or 0.0)
        refl = ref.get("reflect")
        ca, sa = math.cos(ang), math.sin(ang)
        corners = [(cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1)]
        origins = list(ref.get("pts") or [])
        if ref.get("aref") and len(origins) >= 3:
            # AREF: origin + column-ref + row-ref define the lattice.
            (ox, oy), (colx, coly), (rowx, rowy) = origins[0], origins[1], origins[2]
            cols = max(1, ref.get("cols", 1))
            rows = max(1, ref.get("rows", 1))
            dcx, dcy = (colx - ox) / cols, (coly - oy) / cols
            drx, dry = (rowx - ox) / rows, (rowy - oy) / rows
            origins = [(ox + dcx * i + drx * j, oy + dcy * i + dry * j)
                       for i in (0, cols - 1) for j in (0, rows - 1)]
        else:
            origins = origins[:1]
        for (ox, oy) in origins:
            for (px, py) in corners:
                sx, sy = px * mag, py * mag
                if refl:
                    sy = -sy
                rx = sx * ca - sy * sa
                ry = sx * sa + sy * ca
                xs.append(ox + rx)
                ys.append(oy + ry)
    stack.discard(name)
    bb = (min(xs), min(ys), max(xs), max(ys)) if xs else None
    memo[name] = bb
    return bb


def parse_gds_bbox(raw: bytes) -> Optional[Tuple[float, float]]:
    """Return (width_um, height_um) of the TOP-LEVEL bounding box of a GDSII
    stream, resolving cell references through their placement transforms.

    A GDS layout is a CELL HIERARCHY. The previous implementation unioned every
    XY record in the whole file into ONE flat coordinate space, which mixes a
    child's LOCAL coordinates with its parent's PLACEMENT coordinates and also
    swallows SREF/AREF placement origins as if they were geometry. That is
    exactly right for a single flat structure and wrong for everything else.
    Measured on one layout streamed both ways:
        FLAT         gate 123.260 x 34.000 um   klayout 123.260 x 34.000 um  (0.00%)
        HIERARCHICAL gate 132.650 x 30.000 um   klayout 123.260 x 34.000 um  (7.6% / 11.8%)
    So the outline gate silently published a wrong number for any hierarchical
    macro -- and hierarchy is how real analog layouts express matched/arrayed
    devices.

    Resolves BOUNDARY/PATH/BOX geometry plus SREF/AREF references with
    STRANS reflection, MAG and ANGLE. TEXT origins are excluded (a label is not
    physical extent). The top cell is the structure no other structure
    references; several tops union. Returns None when the stream is not a
    parseable GDS with at least one geometry record."""
    if len(raw) < 4:
        return None
    structs, meters_per_dbu, seen_header = _parse_structures(raw)
    if not seen_header or not structs:
        return None
    referenced = {sn for st in structs.values() for sn, _ in st["refs"]}
    tops = [n for n in structs if n not in referenced] or list(structs)
    memo, boxes = {}, []
    for t in tops:
        bb = _struct_bbox(t, structs, memo, set())
        if bb:
            boxes.append(bb)
    if not boxes:
        return None
    min_x = min(b[0] for b in boxes)
    min_y = min(b[1] for b in boxes)
    max_x = max(b[2] for b in boxes)
    max_y = max(b[3] for b in boxes)
    if meters_per_dbu is None or meters_per_dbu <= 0:
        return None
    um_per_dbu = meters_per_dbu * 1e6
    width = (max_x - min_x) * um_per_dbu
    height = (max_y - min_y) * um_per_dbu
    if width <= 0 or height <= 0:
        return None
    return (width, height)

def _gds_real8(b: bytes) -> float:
    """Decode an 8-byte GDSII real (excess-64 hex exponent)."""
    if len(b) < 8:
        return 0.0
    sign = -1.0 if (b[0] & 0x80) else 1.0
    exponent = (b[0] & 0x7F) - 64
    mantissa = 0
    for byte in b[1:8]:
        mantissa = (mantissa << 8) | byte
    return sign * mantissa * (16.0 ** (exponent - 14))


def encode_gds_real8(value: float) -> bytes:
    """Encode a Python float as an 8-byte GDSII real (test helper +
    used nowhere in production parsing). Inverse of _gds_real8."""
    if value == 0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0x00
    v = abs(value)
    exponent = 64
    while v >= 1.0:
        v /= 16.0
        exponent += 1
    while v < 1.0 / 16.0:
        v *= 16.0
        exponent -= 1
    mantissa = int(round(v * (1 << 56)))
    if mantissa >= (1 << 56):
        mantissa >>= 4
        exponent += 1
    out = bytes([sign | (exponent & 0x7F)])
    out += mantissa.to_bytes(7, "big")
    return out


# ───────────────────────── per-block check ─────────────────────────

def _find_lef(hm_dir: Path, block: str) -> Optional[Path]:
    cand = hm_dir / block / f"{block}.lef"
    if cand.is_file():
        return cand
    matches = sorted((hm_dir / block).glob("*.lef")) if (hm_dir / block).is_dir() else []
    return matches[0] if matches else None


def _find_gds(project: Path, hm_dir: Path, block: str) -> Optional[Path]:
    # prefer the packaged hardmacro GDS, fall back to the A5 block GDS.
    cands = [
        hm_dir / block / f"{block}.gds",
        _analog_root(project) / block / f"{block}.gds",
    ]
    for c in cands:
        if c.is_file() and c.stat().st_size > 0:
            return c
    bdir = hm_dir / block
    if bdir.is_dir():
        g = sorted(bdir.glob("*.gds"))
        if g:
            return g[0]
    return None


def _hardmacro_is_stub(hm_dir: Path, block: str) -> bool:
    """True iff any of the block's textual hardmacro artefacts carries the
    deterministic-stub marker — the same predicate analog_hardmacro_check
    uses to award the PASS_WITH_STUB tier."""
    bdir = hm_dir / block
    for suffix in (".lef", ".lib", ".v"):
        cand = bdir / f"{block}{suffix}"
        try:
            if cand.is_file() and is_stub_text(
                    cand.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def check_block(project: Path, block: str, tol_pct: float) -> dict:
    """Return a verdict dict for one block:
      status ∈ {PASS, FAIL, NOT_PACKAGED, STUB_NOT_PACKAGED}
    Only FAIL is a violation; NOT_PACKAGED and STUB_NOT_PACKAGED are DISCLOSED
    non-comparisons (both are reported by name in the JSON and on stdout).
    """
    hm_dir = _hardmacro_root(project)
    lef_path = _find_lef(hm_dir, block)
    gds_path = _find_gds(project, hm_dir, block)

    # Neither half present → block simply not packaged yet.
    if lef_path is None and gds_path is None:
        return {"block": block, "status": "NOT_PACKAGED",
                "detail": "no .lef and no .gds in hardmacro dir"}

    findings = []
    # Missing-half is an HONEST FAIL — the spot-check needs BOTH.
    if lef_path is None:
        findings.append({
            "rule": "A8_LEF_MISSING_FOR_GDS",
            "detail": f"GDS present ({gds_path.name}) but no .lef to "
                      f"compare its outline against",
        })
        return {"block": block, "status": "FAIL", "findings": findings}
    if gds_path is None:
        # A DETERMINISTIC-STUB hardmacro deliberately ships without a .gds and
        # is credited at the PASS_WITH_STUB tier by analog_hardmacro_check.
        # Disclose it by name instead of contradicting that tier — but ONLY
        # when there is no .gds at all; a stub-marked LEF that ships a .gds is
        # compared like any other below.
        if _hardmacro_is_stub(hm_dir, block):
            return {"block": block, "status": "STUB_NOT_PACKAGED",
                    "findings": [{
                        "rule": "A8_STUB_HARDMACRO_NO_GDS",
                        "detail": (f"{lef_path.name} carries the "
                                   f"deterministic_stub marker and the block "
                                   f"ships no .gds; outline comparison is "
                                   f"not applicable at the PASS_WITH_STUB "
                                   f"tier (a real GDS is A5's deliverable)"),
                    }]}
        findings.append({
            "rule": "A8_GDS_MISSING_FOR_LEF",
            "detail": f"LEF present ({lef_path.name}) but no .gds to "
                      f"verify its SIZE against",
        })
        return {"block": block, "status": "FAIL", "findings": findings}

    try:
        lef_text = lef_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"block": block, "status": "FAIL", "findings": [{
            "rule": "A8_LEF_UNREADABLE", "detail": str(e)}]}
    lef_size = parse_lef_size(lef_text)
    if lef_size is None:
        return {"block": block, "status": "FAIL", "findings": [{
            "rule": "A8_LEF_NO_SIZE",
            "detail": f"{lef_path.name} has no `SIZE w BY h ;` line"}]}

    try:
        raw = gds_path.read_bytes()
    except OSError as e:
        return {"block": block, "status": "FAIL", "findings": [{
            "rule": "A8_GDS_UNREADABLE", "detail": str(e)}]}
    gds_bbox = parse_gds_bbox(raw)
    if gds_bbox is None:
        return {"block": block, "status": "FAIL", "findings": [{
            "rule": "A8_GDS_NO_GEOMETRY",
            "detail": f"{gds_path.name} carries no parseable GDS "
                      f"boundary/box geometry (stub or truncated)"}]}

    lw, lh = lef_size
    gw, gh = gds_bbox
    dw = abs(lw - gw) / gw * 100.0 if gw else float("inf")
    dh = abs(lh - gh) / gh * 100.0 if gh else float("inf")

    rec = {
        "block": block,
        "lef": str(lef_path),
        "gds": str(gds_path),
        "lef_size_um": [round(lw, 4), round(lh, 4)],
        "gds_bbox_um": [round(gw, 4), round(gh, 4)],
        "width_delta_pct": round(dw, 3),
        "height_delta_pct": round(dh, 3),
        "tol_pct": tol_pct,
    }
    if dw > tol_pct or dh > tol_pct:
        rec["status"] = "FAIL"
        rec["findings"] = [{
            "rule": "A8_LEF_GDS_OUTLINE_MISMATCH",
            "detail": (f"LEF SIZE {lw:g}x{lh:g}um vs GDS bbox "
                       f"{gw:.3f}x{gh:.3f}um: Δw={dw:.2f}% Δh={dh:.2f}% "
                       f"(tol {tol_pct}%)"),
        }]
    else:
        rec["status"] = "PASS"
    return rec


# ───────────────────────────── main ────────────────────────────────

def build_report(project: Path, block_filter: Optional[str],
                 tol_pct: float) -> Tuple[int, dict]:
    blocks = _load_block_list(project)
    if blocks is None:
        # A PROJECT THAT IS NOT THERE IS NOT A DIGITAL PROJECT. Measured:
        #
        #   $ analog_lef_gds_outline_check /nonexistent/path
        #   VACUOUS_PASS: no analog_block_list.json — digital-only project
        #
        # The VERDICT was right — nothing was checked, and it says so. The
        # REASON was a conclusion about a design nobody looked at, and it is
        # the reason that lands in the sign-off report: a reader of that line
        # records "digital-only", which reads as an examined fact rather than
        # as a path typo. Absence of the manifest is evidence of exactly one
        # thing, so that is now all it claims.
        return 0, {
            "gate": GATE, "verdict": "VACUOUS_PASS",
            "reason": ("no analog_block_list.json under "
                       f"{project} — nothing was examined; this is not a "
                       "finding that the design is digital-only"),
            "blocks": [],
        }
    if not blocks:
        return 0, {
            "gate": GATE, "verdict": "VACUOUS_PASS",
            "reason": "analog_block_list.json declares no blocks",
            "blocks": [],
        }
    if block_filter:
        blocks = [block_filter]

    results = [check_block(project, b, tol_pct) for b in blocks]
    failed = [r for r in results if r["status"] == "FAIL"]
    passed = [r for r in results if r["status"] == "PASS"]
    not_pkg = [r for r in results if r["status"] == "NOT_PACKAGED"]
    stub = [r for r in results if r["status"] == "STUB_NOT_PACKAGED"]

    verdict = "FAIL" if failed else "PASS"
    report = {
        "gate": GATE,
        "verdict": verdict,
        "tol_pct": tol_pct,
        "blocks_checked": len(results),
        "blocks_pass": len(passed),
        "blocks_fail": len(failed),
        "blocks_not_packaged": len(not_pkg),
        # DISCLOSED, not silent: blocks whose outline was not compared because
        # the hardmacro is a deterministic stub with no .gds.
        "blocks_stub_not_packaged": len(stub),
        "blocks": results,
    }
    return (1 if failed else 0), report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=GATE, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path,
                    help="project root (holds phase3/analog/...)")
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    ap.add_argument("--block", default=None,
                    help="restrict to a single block")
    ap.add_argument("--tol-pct", type=float, default=DEFAULT_TOL_PCT,
                    help=f"max LEF-vs-GDS outline delta %% (default {DEFAULT_TOL_PCT})")
    args = ap.parse_args(argv)

    try:
        rc, report = build_report(args.project_dir, args.block, args.tol_pct)
    except Exception as e:  # truly fatal (programming error)
        print(f"ERROR: {GATE}: {e}", file=sys.stderr)
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
    elif verdict == "PASS":
        print(f"PASS: {GATE} — {report['blocks_pass']}/"
              f"{report['blocks_checked']} block(s) LEF outline matches GDS")
        # Disclose every block that was NOT compared, by name and reason —
        # a PASS that quietly skipped blocks is the failure mode this gate
        # was written to end.
        for r in report["blocks"]:
            if r["status"] in ("STUB_NOT_PACKAGED", "NOT_PACKAGED"):
                for f in r.get("findings", []) or [{"rule": r["status"],
                                                    "detail": r.get("detail",
                                                                    "")}]:
                    print(f"  [SKIP {r['block']}] {f['rule']}: {f['detail']}")
    else:
        print(f"FAIL: {GATE} — {report['blocks_fail']} block(s) mismatch:",
              file=sys.stderr)
        for r in report["blocks"]:
            if r["status"] == "FAIL":
                for f in r.get("findings", []):
                    print(f"  [{r['block']}] {f['rule']}: {f['detail']}",
                          file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
