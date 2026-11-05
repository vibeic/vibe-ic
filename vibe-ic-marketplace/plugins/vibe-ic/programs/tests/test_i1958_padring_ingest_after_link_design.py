#!/usr/bin/env python3
"""vibe-ic#1958 (1/3) — the pad-ring ingest ran `read_def` on a linked design.

`_padring_routing_consumer_tcl` replaces the floorplan section of the emitted
pnr.tcl with an ingest of the verified `padring.def`.  The section it replaces
sits AFTER `read_verilog` + `link_design`, so the chip already owns a block by
the time the ring is read, and a BARE `read_def` asks odb for a second one:

    [INFO  ORD-0048] Loading an additional DEF.
    [ERROR ODB-0251] Chip already has a block

MEASURED on OpenROAD 26Q3-1165-g58dbde489f (vibeic-eda:0.2.70), sky130A, a
two-cell design, the same three-rung ladder the issue reporter's probe walked:

    read_def <def>                      -> ODB-0251, dead before placement
    read_def -incremental <def>         -> ingests, but 0 rows and 0 tracks, so
                                           the next command dies (GPL-0130 with a
                                           bare global_placement, PPL-0021 when
                                           place_pins runs first)
    read_def -floorplan_initialize <def>-> 14 rows, place_pins + global_placement OK

So the flag is not a preference between two working spellings: two of the three
kill the run, in two different places, and only the third gets a floorplan onto
a linked design.

Every assertion below is against the deck the emitter RETURNED.  The one test
that runs OpenROAD is skipped when no image is present, and is the reproduction
rather than the specification -- the source-level tests stand alone.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

_RING = "/work/phase3/stage3/pnr/padring.def"






















# ── the reproduction ────────────────────────────────────────────────────────
_IMAGE = "vibeic-eda:0.2.70"
_DOCKER = shutil.which("docker")


def _image_present() -> bool:
    if _DOCKER is None:
        return False
    r = subprocess.run([_DOCKER, "image", "inspect", _IMAGE],
                       capture_output=True, text=True)
    return r.returncode == 0


@pytest.mark.skipif(not _image_present(),
                    reason=f"{_IMAGE} not available on this host")
def test_openroad_agrees_which_of_the_three_spellings_works(tmp_path):
    """Run the ladder.  This is the measurement the flag was chosen from, and
    it fails in BOTH directions: the bare and `-incremental` decks must die,
    and the chosen one must reach a completed global placement."""
    pdk = "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd"
    (tmp_path / "top.v").write_text(
        "module top (input a, input clk, output z);\n"
        "  wire n1;\n"
        "  sky130_fd_sc_hd__clkbuf_4 u0 (.A(a), .X(n1));\n"
        "  sky130_fd_sc_hd__clkbuf_4 u1 (.A(n1), .X(z));\n"
        "endmodule\n")
    common = (f"read_lef {pdk}/techlef/sky130_fd_sc_hd__nom.tlef\n"
              f"read_lef {pdk}/lef/sky130_fd_sc_hd.lef\n"
              f"read_liberty {pdk}/lib/sky130_fd_sc_hd__tt_025C_1v80.lib\n"
              "read_verilog /work/top.v\n"
              "link_design top\n")
    (tmp_path / "common.tcl").write_text(common)
    (tmp_path / "mk.tcl").write_text(
        "source /work/common.tcl\n"
        "initialize_floorplan -die_area {0 0 60 60} "
        "-core_area {10 10 50 50} -site unithd\n"
        "make_tracks\nwrite_def /work/fp.def\nputs MK_OK\nexit\n")
    for name, ingest in (("bare", "read_def /work/fp.def"),
                         ("incremental", "read_def -incremental /work/fp.def"),
                         ("floorplan_initialize",
                          "read_def -floorplan_initialize /work/fp.def")):
        (tmp_path / f"{name}.tcl").write_text(
            "source /work/common.tcl\n" + ingest + "\n"
            'puts "ROWS: [llength [[ord::get_db_block] getRows]]"\n'
            "place_pins -hor_layers met3 -ver_layers met2\n"
            "global_placement -density 0.5\n"
            f'puts "REACHED_PLACEMENT: {name}"\nexit\n')

    def _run(script: str) -> str:
        r = subprocess.run(
            [_DOCKER, "run", "--rm", "--entrypoint", "bash",
             "-v", f"{tmp_path}:/work", _IMAGE, "-lc",
             f"openroad -no_init -exit /work/{script}"],
            capture_output=True, text=True, timeout=900)
        return r.stdout + r.stderr

    assert "MK_OK" in _run("mk.tcl")
    bare = _run("bare.tcl")
    assert "ODB-0251" in bare, bare[-2000:]
    assert "REACHED_PLACEMENT" not in bare
    incr = _run("incremental.tcl")
    # `-incremental` drops the whole ROW/TRACK section. Which command dies of
    # that depends on which one runs first -- `place_pins` (PPL-0021, no
    # routing tracks) in this deck, `global_placement` (GPL-0130, no rows) in
    # a deck without one. The DEFECT is the empty row list; the error code is
    # downstream of it, so the row count is what is asserted.
    assert "ROWS: 0" in incr, incr[-2000:]
    assert ("GPL-0130" in incr or "PPL-0021" in incr), incr[-2000:]
    assert "REACHED_PLACEMENT" not in incr
    good = _run("floorplan_initialize.tcl")
    assert "ODB-0251" not in good and "GPL-0130" not in good, good[-2000:]
    assert "ROWS: 0" not in good
    assert "REACHED_PLACEMENT: floorplan_initialize" in good
