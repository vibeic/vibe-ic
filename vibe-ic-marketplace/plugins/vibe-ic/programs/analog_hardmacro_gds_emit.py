#!/usr/bin/env python3
"""analog_hardmacro_gds_emit.py — the A8 GDS PRODUCER that was missing.

WHAT WAS BROKEN
===============
Flow step A8 ("Hardmacro Generation (LEF + Liberty + GDS + Verilog)")
declares four `required_outputs`, one of which is
`phase3/analog/hardmacro/*/*.gds`. Three of the four are emitted by the
`analog-hardmacro-gen` skill. The `.gds` was emitted by NOTHING:

  * `programs/magic_port_extract_emit.build_gds_write_tcl()` has existed,
    documented and unit-tested, for many releases — and was referenced only
    by its own unit test and by the skill's prose. No gate, no runner and no
    MCP tool ever called it. (The emitter's own module docstring dates it.)
  * `analog_one_shot_runner._emit_deterministic_stub("A8_hardmacro_gen")`
    writes `<block>.lef`, `<block>.lib` and `<block>.v` — and no `.gds`.
  * `analog_a8_hardmacro_gen_check` verifies the LEF/LIB/V TRIPLE only, so
    nothing downstream noticed the fourth declared artefact never appeared.

So A8 declared a physical layout it never produced, and step M1 — whose
merge consumes `phase3/analog/hardmacro/**/*.gds` — could never find one.

WHAT THIS PROGRAM DOES
======================
For every declared analog block it streams the A5 Magic layout out to GDS:

    phase3/analog/<block>/layout.mag   ->   phase3/analog/hardmacro/<block>/<block>.gds

using the flow's own deterministic TCL emitter
(`magic_port_extract_emit.build_gds_write_tcl`) and the PDK technology the
LAYOUT ITSELF names on its `tech <name>` line — never a hard-coded PDK. The
staged copy is named `<block>.mag` so Magic's cell name is the block name,
which is what the LEF `MACRO <block>` and the Verilog `module <block>` already
use.

CONTAINER STAGING, AND WHY IT IS NOT A HOST-PATH ASSUMPTION
===========================================================
The EDA tools live in a container. Sibling programs pass HOST paths straight
into `docker exec` (`mixed_signal_top_lvs_run._to_container_path` returns its
argument unchanged), which silently requires the project to sit under a
bind-mounted directory: on a checkout anywhere else Magic reports "no such
file" and the caller reads it as a tool failure. This program instead stages
through `docker cp` into a container-side temporary directory and copies the
result back, so it works from ANY host path, mounted or not.

HONEST RC CONTRACT — a skip is never a success and never a failure
==================================================================
    rc 0  at least one block produced a real GDS, or every block was
          skipped for a NAMED, disclosed reason (no layout, stub layout,
          already present).
    rc 1  Magic RAN and the result is not a layout: no file, zero bytes, or
          zero BOUNDARY/PATH/SREF/AREF/BOX records. A hollow GDS is worse
          than none — `analog_hardmacro_check` used to accept 500 bytes of
          noise — so it is deleted and reported, never left on disk.
    rc 2  the capability itself is absent (no container/Magic reachable, or
          the layout's technology has no magicrc under the PDK root). A
          disclosed capability gap, reported with the tool and tech names.

DELIBERATE NON-BEHAVIOURS
=========================
  * A deterministic-stub `layout.mag` (`_analog_stub_marker.is_stub_text`) is
    SKIPPED, not streamed. The stub tier ships without a `.gds` on purpose and
    `analog_lef_gds_outline_check` credits that as `STUB_NOT_PACKAGED`;
    emitting a geometry-free GDS from stub padding would convert that
    disclosed skip into a mismatch FAIL.
  * An existing `<block>.gds` is never overwritten. Re-running the flow must
    not silently replace a signoff artefact.

ENFORCEMENT: none — this is a PRODUCER, and it is deliberately NOT a gate
clause. Corrected 2026-07-28; this paragraph previously said the opposite.
  It is invoked by `analog_one_shot_runner.step_for_block` at
  `A8_hardmacro_gen` and declared in A8's `programs:` list. It was ALSO wired
  into A8's gate as `advisory_program_exit_zero` for one day, and that clause
  was WITHDRAWN: `flow_compliance_check` is the sole phase-2+3 acceptance
  auditor, `phase3/analog/hardmacro/*/*.gds` is one of A8's declared
  `required_outputs`, and a gate clause that MAKES a declared output leaves the
  same audit reporting the artefact it just created. Measured on a copy of the
  analog reference run: with the clause, an audit that started with 0 `.gds`
  ended with 2 that it had written itself; without it, 0.
  Producing is not a verdict either way: the blocking verdicts stay with
  `analog_hardmacro_check` (presence + real geometry) and
  `analog_lef_gds_outline_check` (LEF SIZE vs GDS bounding box), both of which
  READ what this writes — and they must read a tree the audit did not touch.

chip-AGNOSTIC: block names come from `analog_block_list.json`, the technology
comes from the layout header, and no PDK SKU, vendor or cell literal appears
below.

Usage:
    python3 analog_hardmacro_gds_emit.py <project> [--json <out>]
        [--container vibeic-eda] [--pdk-root /foss/pdks] [--block <name>]
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import struct as _struct
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _path_layout as _pl  # noqa: E402
from _analog_a_check_common import load_block_list  # noqa: E402
from _analog_stub_marker import is_stub_text  # noqa: E402
from magic_port_extract_emit import build_gds_write_tcl  # noqa: E402

# ONE parser for "does this GDS carry geometry", shared with the A5 layout gate
# and with analog_hardmacro_check so the producer cannot accept a file its own
# consumers reject.
from analog_a5_layout_check import _gds_geometry_count  # noqa: E402

# vibe-ic#595. The SAME parsers the A8 outline GATE judges this file with, so
# the producer cannot align to a frame its own gate measures differently. If
# these ever disagree the gate is right by construction and the producer is
# broken — importing them makes that impossible rather than unlikely.
from analog_lef_gds_outline_check import (  # noqa: E402
    DEFAULT_TOL_UM,
    offset_on_grid,
    parse_gds_bbox_extent,
    parse_lef_frame_ll,
    _parse_structures,
    _GDS_ENDSTR,
    _GDS_STRNAME,
    _GDS_XY,
)

PROGRAM = "analog_hardmacro_gds_emit"

DEFAULT_CONTAINER = "vibeic-eda"
DEFAULT_PDK_ROOT = "/foss/pdks"

#: Magic writes the technology it was built against on the second line of a
#: `.mag`: `tech <name>`. The magicrc is then
#: `<pdk_root>/<name>/libs.tech/magic/<name>.magicrc`.
_MAG_TECH_RE = re.compile(r"^\s*tech\s+(\S+)\s*$", re.MULTILINE)
_MAGICRC_REL = "{tech}/libs.tech/magic/{tech}.magicrc"


# ──────────────────────────────────────────────────────────────────────
# Container plumbing
# ──────────────────────────────────────────────────────────────────────

# `use <cellname> <instance-id>` — a Magic .mag subcell reference.
_MAG_USE_RE = re.compile(r"(?im)^\s*use\s+(\S+)")


def _stage_layout_subtree(stage, layout: Path, block: str):
    """Stage `layout` as `<block>.mag` PLUS every `.mag` it references,
    transitively, from the layout's own directory.

    A Magic layout is a CELL HIERARCHY: the top `.mag` carries `use <cell>`
    lines and each of those cells lives in its own sibling `.mag`. Staging only
    the top file leaves Magic unable to resolve them, and `gds write` then
    reports `Failure to read entire subtree of the cell` / `I/O error in writing
    file` and produces NOTHING. Measured on a real device-level layout: the
    write failed on the last referenced device cell and no GDS came back at all.
    Only a single flat cell ever worked, and essentially no real analog layout
    is flat (hierarchy is how matched/arrayed devices are expressed).

    The top cell is staged under `<block>.mag` so Magic's cell name is the block
    name; subcells keep their own names because that is what the `use` lines
    reference. Bounded depth + visited set. Returns (ok, detail)."""
    ok, why = stage.put(layout, f"{block}.mag")
    if not ok:
        return False, f"could not stage {layout.name}: {why}"
    src_dir = layout.parent
    seen = set()
    pending = [layout]
    staged = []
    depth = 0
    while pending and depth < 16:
        nxt = []
        for f in pending:
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for cell in _MAG_USE_RE.findall(text):
                if cell in seen:
                    continue
                seen.add(cell)
                child = src_dir / f"{cell}.mag"
                if not child.is_file():
                    # Not an error here: the cell may come from a PDK library on
                    # Magic's own search path. Magic reports it if it cannot be
                    # resolved, and that surfaces in the FAIL detail.
                    continue
                cok, cwhy = stage.put(child, child.name)
                if not cok:
                    return False, f"could not stage subcell {child.name}: {cwhy}"
                staged.append(cell)
                nxt.append(child)
        pending = nxt
        depth += 1
    return True, (f"staged {len(staged)} subcell(s): {sorted(staged)}"
                  if staged else "flat layout (no subcells)")



def _run(argv: List[str], timeout: int = 900) -> Tuple[int, str, str]:
    """Bounded subprocess. Monkeypatch surface for the unit tests."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller verbatim
        return 1, "", str(exc)


class Stage:
    """A working directory the EDA tools can actually see.

    ``container`` empty or ``"host"`` runs the tools directly and the stage is
    a plain host directory. Otherwise the stage lives INSIDE the container and
    files move across with ``docker cp``, so the project may sit at any host
    path — mounted, unmounted, or a pytest ``tmp_path``.
    """

    def __init__(self, container: str, host_tmp: Path):
        self.container = (container or "").strip()
        self.in_container = self.container not in ("", "host")
        self.host_tmp = host_tmp
        self.path: Optional[str] = None

    def open(self) -> Tuple[bool, str]:
        if not self.in_container:
            self.host_tmp.mkdir(parents=True, exist_ok=True)
            self.path = str(self.host_tmp)
            return True, ""
        rc, out, err = _run(
            ["docker", "exec", self.container, "mktemp", "-d"], timeout=60)
        if rc != 0 or not out.strip():
            return False, (f"cannot open a staging dir in container "
                           f"{self.container!r}: {(err or out).strip()[:200]}")
        self.path = out.strip()
        return True, ""

    def put(self, src: Path, name: str) -> Tuple[bool, str]:
        assert self.path is not None
        dst = f"{self.path}/{name}"
        if not self.in_container:
            try:
                Path(dst).write_bytes(src.read_bytes())
                return True, ""
            except OSError as exc:
                return False, str(exc)
        rc, out, err = _run(
            ["docker", "cp", str(src), f"{self.container}:{dst}"], timeout=120)
        return (rc == 0), (err or out).strip()[:200]

    def put_text(self, text: str, name: str) -> Tuple[bool, str]:
        assert self.path is not None
        tmp = self.host_tmp / f".stage_{name}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        return self.put(tmp, name)

    def get(self, name: str, dst: Path) -> Tuple[bool, str]:
        assert self.path is not None
        src = f"{self.path}/{name}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not self.in_container:
            try:
                dst.write_bytes(Path(src).read_bytes())
                return True, ""
            except OSError as exc:
                return False, str(exc)
        rc, out, err = _run(
            ["docker", "cp", f"{self.container}:{src}", str(dst)], timeout=120)
        return (rc == 0 and dst.is_file()), (err or out).strip()[:200]

    def sh(self, cmd: str, timeout: int = 900) -> Tuple[int, str, str]:
        if not self.in_container:
            return _run(["bash", "-lc", cmd], timeout=timeout)
        return _run(["docker", "exec", self.container, "bash", "-lc", cmd],
                    timeout=timeout)

    def exists(self, path: str) -> bool:
        return self.sh(f"test -e {shlex.quote(path)}", timeout=60)[0] == 0

    def close(self) -> None:
        if self.path and self.in_container:
            _run(["docker", "exec", self.container, "rm", "-rf", self.path],
                 timeout=60)


# ──────────────────────────────────────────────────────────────────────
# Layout discovery
# ──────────────────────────────────────────────────────────────────────
def layout_for(project: Path, block: str) -> Optional[Path]:
    """The A5 Magic layout for *block*, or None."""
    for cand in (_pl.analog_dir(project) / block / "layout.mag",
                 _pl.analog_dir(project) / block / f"{block}.mag"):
        if cand.is_file():
            return cand
    return None


def tech_of(layout: Path) -> Optional[str]:
    """The technology the LAYOUT names, never a default.

    A `.mag` with no `tech` line cannot be streamed reproducibly: guessing one
    would silently write a GDS against the wrong layer map, which is exactly
    the kind of plausible-but-wrong artefact this campaign removes.
    """
    m = _MAG_TECH_RE.search(layout.read_text(errors="replace"))
    return m.group(1) if m else None


def discover_blocks(project: Path) -> List[str]:
    declared = load_block_list(project)
    if declared:
        return list(declared)
    root = _pl.analog_dir(project)
    if not root.is_dir():
        return []
    return sorted(p.parent.name for p in root.glob("*/layout.mag"))


# ──────────────────────────────────────────────────────────────────────
# The producer
# ──────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────
# vibe-ic#595 — the abstract and the body must leave A8 in ONE frame
# ──────────────────────────────────────────────────────────────────────
#
# A8 ships two views of the same block, written by two different Magic
# writers: `lef write` NORMALISES the abstract to the cell bounding box, and
# `gds write` PRESERVES the `.mag`'s own coordinates. Any A5 layout whose
# bounding box does not already start at the origin therefore leaves A8 with
# its outline and its metal in DIFFERENT coordinate frames — the LEF reserves
# the area where the body is not, and every PIN rect names metal that is not
# there. Measured on this repo's own analog reference blocks: every Metal3
# signal pin hit 0 shapes at its stated LEF coordinate and exactly 1 when
# shifted by the GDS bounding box lower-left, on both blocks.
#
# #594 made that VISIBLE (the outline gate had been comparing width and
# height — the two numbers a misregistered pair agrees on). This closes it at
# the PRODUCER, which is the only place it can be closed without a human:
# downstream every consumer has already inherited the wrong frame.
#
# WHICH REMEDY, AND WHY IT IS NOT A CHOICE MADE HERE
# ---------------------------------------------------
# #595 named two remedies and was right that they are NOT equivalent:
#
#   * translate the stream into the LEF's frame — a RIGID move. DRC and LVS
#     are translation-invariant, so it cannot change either verdict. What it
#     CAN do is put every coordinate off the manufacturing grid, and this
#     repo has already paid for an off-grid streamout once.
#   * declare `FOREIGN <cell> <llx> <lly> ;` — moves nothing, but depends on a
#     sign convention and OpenROAD's stream-out does not honour FOREIGN
#     uniformly.
#
# v1.9.21 measured the fact that separates them — WHETHER THE OFFSET IS A
# WHOLE NUMBER OF GRID STEPS — and deliberately stopped there. It is measured
# again here, from the PDK the layout's own `tech` line names, and the
# translation is applied ONLY when it is provably grid-preserving. When the
# offset is not an exact multiple, or the grid cannot be read, or the grid is
# contradictory, or the stream has no single top structure, NOTHING is
# touched: the file is left exactly as Magic wrote it and the record says so,
# so the outline gate still FAILs and a human picks FOREIGN. A guessed grid
# would decide the question, so it is never guessed and there is no default.
#
# The translation itself is exact INTEGER database-unit arithmetic on the
# GDSII XY records — no floating point reaches the coordinates, so a
# grid-preserving move cannot introduce a grid error of its own.


def top_structure_name(raw: bytes) -> Optional[str]:
    """The one structure no other structure references, or None.

    None when the stream is unparseable, has no structures, or has SEVERAL
    tops — a multi-top stream has no single body to move and guessing which
    one the abstract describes would move the wrong geometry."""
    structs, _meters, seen_header = _parse_structures(raw)
    if not seen_header or not structs:
        return None
    referenced = {sn for st in structs.values() for sn, _ in st["refs"]}
    tops = [n for n in structs if n not in referenced]
    return tops[0] if len(tops) == 1 else None


def um_per_dbu(raw: bytes) -> Optional[float]:
    """The stream's own database unit in um, or None when it declares none."""
    _structs, meters_per_dbu, seen_header = _parse_structures(raw)
    if not seen_header or not meters_per_dbu or meters_per_dbu <= 0:
        return None
    return meters_per_dbu * 1e6


def translate_structure(raw: bytes, sname: str, dx: int, dy: int) -> bytes:
    """Rigidly move ONE structure by (dx, dy) DATABASE UNITS.

    Only the named structure's own records are rewritten. Its geometry XY
    records move the shapes; its SREF/AREF XY records are PLACEMENT origins,
    so moving those moves the referenced children with it. Child structures
    keep their local coordinates untouched — translating those too would move
    every instanced cell twice.

    Byte-exact everywhere else: record lengths and types are preserved and
    every non-XY record is copied verbatim, so this cannot perturb layers,
    datatypes, properties or the cell hierarchy."""
    out = bytearray()
    pos, n = 0, len(raw)
    cur = None
    while pos + 4 <= n:
        rec_len = (raw[pos] << 8) | raw[pos + 1]
        rec_type = (raw[pos + 2] << 8) | raw[pos + 3]
        if rec_len < 4 or pos + rec_len > n:
            out += raw[pos:]          # truncated tail — copied, never guessed
            return bytes(out)
        rec = raw[pos:pos + rec_len]
        data = raw[pos + 4:pos + rec_len]
        if rec_type == _GDS_STRNAME:
            cur = data.split(b"\0")[0].decode("ascii", "replace")
        elif rec_type == _GDS_ENDSTR:
            cur = None
        elif rec_type == _GDS_XY and cur == sname:
            cnt = (len(data) // 4) & ~1        # whole (x, y) pairs only
            if cnt:
                vals = list(_struct.unpack(f">{cnt}i", data[:cnt * 4]))
                for i in range(0, cnt, 2):
                    vals[i] += dx
                    vals[i + 1] += dy
                rec = (rec[:4] + _struct.pack(f">{cnt}i", *vals)
                       + data[cnt * 4:])
        out += rec
        pos += rec_len
    return bytes(out)


def pdk_manufacturing_grid_um(stage: "Stage", pdk_root: str,
                              tech: str) -> Optional[float]:
    """MANUFACTURINGGRID (um) declared by the PDK the layout's own `tech` line
    names, or None.

    Read from the real PDK, container-side, where the PDK actually is — the
    outline GATE runs on the host, where the PDK root does not exist, which is
    exactly why it reports the grid as unknown and can recommend neither
    remedy. There is NO fallback and NO default: absent, unreadable and
    CONTRADICTORY (two different values under one PDK) all return None, and
    None never authorises a translation."""
    root = f"{pdk_root.rstrip('/')}/{tech}"
    rc, out, _err = stage.sh(
        f"grep -rhoiE 'MANUFACTURINGGRID[[:space:]]+[0-9.]+' "
        f"{shlex.quote(root)} 2>/dev/null | head -32", timeout=120)
    vals = {float(m.group(1)) for m in
            re.finditer(r"MANUFACTURINGGRID\s+([0-9.]+)", out or "", re.I)}
    return vals.pop() if len(vals) == 1 else None


def align_to_lef_frame(project: Path, block: str, gds_path: Path,
                       stage: "Stage", pdk_root: str, tech: str) -> Dict:
    """Put the streamed body into the frame the sibling LEF abstract declares,
    when — and only when — that move is provably grid-preserving."""
    lef = _pl.hardmacro_dir(project) / block / f"{block}.lef"
    if not lef.is_file():
        return {"status": "NO_LEF", "rule": "A8GDS_FRAME_NO_LEF",
                "detail": (f"no sibling {block}.lef, so there is no declared "
                           f"abstract frame to align the body to")}

    fx, fy, src = parse_lef_frame_ll(lef.read_text(errors="replace"))
    raw = gds_path.read_bytes()
    ext = parse_gds_bbox_extent(raw)
    upd = um_per_dbu(raw)
    if ext is None or upd is None:
        return {"status": "UNMEASURED", "rule": "A8GDS_FRAME_UNMEASURED",
                "detail": (f"{gds_path.name} carries geometry but its "
                           f"top-level bounding box / database unit could not "
                           f"be parsed, so the frame offset is unknown")}

    llx, lly = ext[0], ext[1]
    dx_um, dy_um = fx - llx, fy - lly
    base = {"lef_frame_ll_um": [fx, fy], "lef_frame_source": src,
            "gds_bbox_ll_um": [round(llx, 6), round(lly, 6)],
            "offset_um": [round(dx_um, 6), round(dy_um, 6)]}

    if abs(dx_um) <= DEFAULT_TOL_UM and abs(dy_um) <= DEFAULT_TOL_UM:
        return {**base, "status": "ALREADY_ALIGNED",
                "rule": "A8GDS_FRAME_ALREADY_ALIGNED",
                "detail": (f"body lower-left ({llx:.3f},{lly:.3f})um already "
                           f"sits on the {src} frame ({fx:.3f},{fy:.3f})um "
                           f"within {DEFAULT_TOL_UM}um; nothing moved")}

    grid = pdk_manufacturing_grid_um(stage, pdk_root, tech)
    on_grid, grid_detail = offset_on_grid(dx_um, dy_um, grid)
    base["manufacturing_grid_um"] = grid
    base["offset_is_grid_multiple"] = on_grid
    if on_grid is not True:
        return {**base, "status": "NOT_ALIGNED",
                "rule": "A8GDS_FRAME_NOT_ALIGNED",
                "detail": (
                    f"body lower-left ({llx:.3f},{lly:.3f})um is "
                    f"({dx_um:.3f},{dy_um:.3f})um off the {src} frame "
                    f"({fx:.3f},{fy:.3f})um, but {grid_detail} — translating "
                    f"would trade a registration defect for an off-grid "
                    f"streamout, so NOTHING was moved and the file is exactly "
                    f"as Magic wrote it. `FOREIGN {block} {llx:g} {lly:g} ;` "
                    f"is the remedy that moves nothing, and choosing it is an "
                    f"owner decision this producer does not make.")}

    sname = top_structure_name(raw)
    if sname is None:
        return {**base, "status": "NOT_ALIGNED",
                "rule": "A8GDS_FRAME_NO_SINGLE_TOP",
                "detail": (f"{gds_path.name} has no single top structure, so "
                           f"there is no one body the abstract describes; "
                           f"nothing was moved")}

    dx_dbu = int(round(dx_um / upd))
    dy_dbu = int(round(dy_um / upd))
    moved = translate_structure(raw, sname, dx_dbu, dy_dbu)

    # Re-MEASURE rather than assume. A translation that did not land on the
    # declared frame is not a fix, and the unmoved file is better than a file
    # moved somewhere nobody predicted.
    ext2 = parse_gds_bbox_extent(moved)
    if ext2 is None or abs(ext2[0] - fx) > DEFAULT_TOL_UM \
            or abs(ext2[1] - fy) > DEFAULT_TOL_UM:
        return {**base, "status": "NOT_ALIGNED",
                "rule": "A8GDS_FRAME_MOVE_DID_NOT_LAND",
                "detail": (f"translating top structure {sname!r} by "
                           f"({dx_dbu},{dy_dbu}) dbu did not land the bounding "
                           f"box on the {src} frame; the original stream was "
                           f"kept unmodified")}

    gds_path.write_bytes(moved)
    return {**base, "status": "ALIGNED", "rule": "A8GDS_FRAME_ALIGNED",
            "top_structure": sname, "moved_dbu": [dx_dbu, dy_dbu],
            "gds_bbox_ll_um_after": [round(ext2[0], 6), round(ext2[1], 6)],
            "detail": (
                f"body lower-left was ({llx:.3f},{lly:.3f})um against a {src} "
                f"frame of ({fx:.3f},{fy:.3f})um; {grid_detail}, so top "
                f"structure {sname!r} was rigidly moved by ({dx_dbu},{dy_dbu}) "
                f"dbu = ({dx_um:.3f},{dy_um:.3f})um and now starts at "
                f"({ext2[0]:.3f},{ext2[1]:.3f})um. DRC and LVS are invariant "
                f"under a rigid translation and the move is a whole number of "
                f"grid steps, so neither verdict can change.")}


def emit_block(project: Path, block: str, stage: Stage,
               pdk_root: str) -> Dict:
    """Stream one block's layout to GDS. Returns a per-block record."""
    out_gds = _pl.hardmacro_dir(project) / block / f"{block}.gds"
    rec: Dict = {"block": block, "gds": str(out_gds.relative_to(project))}

    if out_gds.is_file() and out_gds.stat().st_size > 0:
        rec.update(status="SKIP", rule="A8GDS_ALREADY_PRESENT",
                   detail=f"{out_gds.name} already present "
                          f"({out_gds.stat().st_size} B); not overwritten")
        return rec

    layout = layout_for(project, block)
    if layout is None:
        rec.update(status="SKIP", rule="A8GDS_NO_LAYOUT",
                   detail=(f"no A5 Magic layout for block {block!r} "
                           f"(looked for layout.mag / {block}.mag under "
                           f"{_pl.analog_dir(project).relative_to(project)}/"
                           f"{block}/)"))
        return rec

    text = layout.read_text(errors="replace")
    if is_stub_text(text):
        rec.update(status="SKIP", rule="A8GDS_STUB_LAYOUT",
                   detail=(f"{layout.name} carries the deterministic-stub "
                           f"marker; the stub tier ships without a .gds on "
                           f"purpose and streaming padding would turn a "
                           f"disclosed skip into an outline mismatch"))
        return rec

    tech = tech_of(layout)
    if not tech:
        rec.update(status="SKIP", rule="A8GDS_NO_TECH_LINE",
                   detail=(f"{layout.name} declares no `tech <name>` line, so "
                           f"the layer map to stream against is unknown; "
                           f"guessing one would write a wrong-layer GDS"))
        return rec
    rec["tech"] = tech

    magicrc = f"{pdk_root.rstrip('/')}/{_MAGICRC_REL.format(tech=tech)}"
    if not stage.exists(magicrc):
        rec.update(status="UNAVAILABLE", rule="A8GDS_NO_TECH",
                   detail=(f"technology {tech!r} named by {layout.name} has no "
                           f"magicrc at {magicrc}"))
        return rec

    ok, why = _stage_layout_subtree(stage, layout, block)
    if not ok:
        rec.update(status="UNAVAILABLE", rule="A8GDS_STAGE_FAILED",
                   detail=why)
        return rec
    rec["staged_subtree"] = why

    tcl_name = f"{block}_gds_write.tcl"
    tcl = build_gds_write_tcl(top_cell=block, layout_mag=block,
                              out_gds=f"{block}.gds")
    ok, why = stage.put_text(tcl, tcl_name)
    if not ok:
        rec.update(status="UNAVAILABLE", rule="A8GDS_STAGE_FAILED",
                   detail=f"could not stage {tcl_name}: {why}")
        return rec

    cmd = (f"export PDK={shlex.quote(tech)} "
           f"PDK_ROOT={shlex.quote(pdk_root)} && "
           f"cd {shlex.quote(stage.path or '.')} && "
           f"magic -noconsole -dnull -rcfile {shlex.quote(magicrc)} "
           f"{shlex.quote(tcl_name)}")
    rc, out, err = stage.sh(cmd)
    tail = ((out or "") + (err or "")).strip().splitlines()[-4:]

    landed = _pl.hardmacro_dir(project) / block / f"{block}.gds"
    got, why = stage.get(f"{block}.gds", landed)
    if not got or not landed.is_file() or landed.stat().st_size == 0:
        if landed.is_file():
            landed.unlink()
        rec.update(status="FAIL", rule="A8GDS_NOT_WRITTEN",
                   detail=(f"magic -rcfile {magicrc} {tcl_name} returned "
                           f"rc={rc} and no non-empty {block}.gds came back "
                           f"({why}); last output: {tail}"))
        return rec

    records = _gds_geometry_count(landed.read_bytes())
    if records <= 0:
        landed.unlink()
        rec.update(status="FAIL", rule="A8GDS_NO_GEOMETRY",
                   detail=(f"magic wrote {block}.gds but it carries no "
                           f"BOUNDARY/PATH/SREF/AREF/BOX record — a layout "
                           f"with no geometry is not a layout; the file was "
                           f"removed rather than left to read as produced. "
                           f"last output: {tail}"))
        return rec

    # vibe-ic#595 — the abstract and the body must leave A8 in ONE frame.
    # Done HERE, before the record is finalised, so the reported size is the
    # size of the file that actually ships.
    frame = align_to_lef_frame(project, block, landed, stage, pdk_root, tech)

    rec.update(status="PRODUCED", rule="A8GDS_PRODUCED",
               size_bytes=landed.stat().st_size,
               geometry_records=records,
               source=str(layout.relative_to(project)),
               frame=frame,
               detail=(f"magic streamed {layout.name} ({tech}) to "
                       f"{block}.gds: {landed.stat().st_size} B, "
                       f"{records} geometry records; "
                       f"frame {frame['status']}: {frame['detail']}"))
    return rec


def run(project: Path, container: str, pdk_root: str,
        only: Optional[str], host_tmp: Path) -> Tuple[Dict, int]:
    blocks = discover_blocks(project)
    if only:
        blocks = [b for b in blocks if b == only]
    # No absolute path and no timestamp on purpose: the record lives INSIDE the
    # project it describes, and a re-run on the same inputs must be
    # byte-identical so a reviewer can regenerate it and diff.
    report: Dict = {
        "program": PROGRAM,
        "tool": "magic (gds write) via magic_port_extract_emit"
                ".build_gds_write_tcl",
        "container": container,
        "pdk_root": pdk_root,
        "blocks": blocks,
        "results": [],
    }
    if not blocks:
        report["verdict"] = "VACUOUS_PASS"
        report["reason"] = (
            "no analog block declares a layout to stream; A8 GDS emission is "
            "inapplicable to this project")
        return report, 0

    stage = Stage(container, host_tmp)
    ok, why = stage.open()
    if not ok:
        report["verdict"] = "UNAVAILABLE"
        report["reason"] = why
        report["results"] = [
            {"block": b, "status": "UNAVAILABLE", "rule": "A8GDS_NO_STAGE",
             "detail": why} for b in blocks]
        return report, 2
    try:
        if stage.sh("command -v magic >/dev/null 2>&1", timeout=60)[0] != 0:
            report["verdict"] = "UNAVAILABLE"
            report["reason"] = (
                f"magic is not on PATH in "
                f"{container!r}; the A8 GDS streamout has no producer here")
            report["results"] = [
                {"block": b, "status": "UNAVAILABLE", "rule": "A8GDS_NO_MAGIC",
                 "detail": report["reason"]} for b in blocks]
            return report, 2
        for block in blocks:
            report["results"].append(
                emit_block(project, block, stage, pdk_root))
    finally:
        stage.close()

    failed = [r for r in report["results"] if r["status"] == "FAIL"]
    unavailable = [r for r in report["results"]
                   if r["status"] == "UNAVAILABLE"]
    produced = [r for r in report["results"] if r["status"] == "PRODUCED"]
    report["summary"] = {
        "produced": len(produced),
        "skipped": len(report["results"]) - len(produced) - len(failed)
                   - len(unavailable),
        "unavailable": len(unavailable),
        "failed": len(failed),
    }
    if failed:
        report["verdict"] = "FAIL"
        return report, 1
    if unavailable and not produced:
        report["verdict"] = "UNAVAILABLE"
        return report, 2
    report["verdict"] = "PASS"
    return report, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--pdk-root", default=DEFAULT_PDK_ROOT)
    ap.add_argument("--block", default=None)
    args = ap.parse_args(argv)

    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 2

    project = args.project.resolve()
    import tempfile
    with tempfile.TemporaryDirectory(prefix="a8gds_") as td:
        report, rc = run(project, args.container, args.pdk_root,
                         args.block, Path(td))

    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out + "\n", encoding="utf-8")
    print(f"[{report['verdict']}] {PROGRAM}")
    for r in report["results"]:
        print(f"  [{r['status']}] {r['rule']}: {r['detail']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
