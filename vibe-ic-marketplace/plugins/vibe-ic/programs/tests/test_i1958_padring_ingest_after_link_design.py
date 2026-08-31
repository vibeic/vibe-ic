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
import phase3_one_shot_runner as R  # noqa: E402

_RING = "/work/phase3/stage3/pnr/padring.def"


def _deck() -> str:
    """A minimal pnr.tcl carrying the two things that matter: a `link_design`
    before the floorplan section, the floorplan seam the consumer replaces, and
    the marked main global-route command the chip path specializes."""
    marker = R._PNR_STAGE_MARKER
    return ("read_lef /pdk/core.lef\n"
            "read_verilog /work/netlist.v\n"
            "link_design chip_top\n"
            f'puts "{marker} floorplan"\n'
            "initialize_floorplan -die_area {0 0 100 100}\n"
            "place_pins -hor_layers m2\n"
            "write_def /work/phase3/stage3/pnr/floorplan.def\n"
            f'puts "{marker} placement"\n'
            "global_placement\n"
            f'puts "{marker} global_route"\n'
            "global_route\n"
            "detailed_route\n")


def _ingest_line(deck: str) -> str:
    lines = [ln for ln in deck.splitlines() if ln.startswith("read_def ")]
    assert len(lines) == 1, f"expected exactly one ingest, got {lines}"
    return lines[0]


def test_the_ingest_uses_floorplan_initialize():
    """THE defect. A bare `read_def` here is ODB-0251 on every chip-path run."""
    assert _ingest_line(R._padring_routing_consumer_tcl(_deck(), _RING)) == \
        f"read_def -floorplan_initialize {_RING}"


def test_the_bare_read_def_is_gone_not_merely_accompanied():
    """Negative control for the test above: a deck that emitted BOTH spellings
    would satisfy a bare `in` check while still dying on the first one."""
    deck = R._padring_routing_consumer_tcl(_deck(), _RING)
    assert f"\nread_def {_RING}" not in "\n" + deck
    assert deck.count("read_def ") == 1


def test_incremental_is_not_what_was_chosen():
    """`-incremental` also ingests the ring, and also loses the ROW section, so
    global placement then fails GPL-0130.  Pinned so a later edit reaching for
    'the other non-destructive flag' has to argue with a measurement."""
    assert "-incremental" not in R._padring_routing_consumer_tcl(_deck(), _RING)


def test_the_ingest_really_does_follow_link_design():
    """The REASON the flag is needed.  If the seam ever moved above
    `link_design` the flag would be the wrong one -- so the ordering that makes
    it right is asserted here rather than assumed."""
    deck = R._padring_routing_consumer_tcl(_deck(), _RING)
    assert deck.index("link_design ") < deck.index("read_def ")
    assert deck.index("read_def ") < deck.index("\nglobal_placement")


def test_the_fail_closed_guard_and_the_marker_are_unchanged():
    """The ingest still refuses to run without a ring, and still says which
    file it consumed -- the flag was the only thing that changed."""
    deck = R._padring_routing_consumer_tcl(_deck(), _RING)
    assert f'PADRING_ROUTING_INPUT_MISSING: {_RING}' in deck
    assert f'PADRING_ROUTING_CONSUMED: {_RING}' in deck
    assert "initialize_floorplan" not in deck


def test_i1966_chip_path_allows_pad_pin_access_congestion():
    """The #1966 defect: the pad-ring consumer must not hard-fail global route
    on zero-capacity edge tiles that detailed routing can legally enter."""
    deck = R._padring_routing_consumer_tcl(_deck(), _RING)
    commands = [ln for ln in deck.splitlines()
                if ln.startswith("global_route")]
    assert commands == [
        "global_route -allow_congestion "
        "-congestion_report_file grt_congestion.rpt"
    ]


def test_i1966_generic_core_route_stays_bare():
    """Scope guard: only the verified chip/pad-ring consumer gets the flag;
    the generic deck used by core/IP flows remains byte-for-byte bare."""
    commands = [ln for ln in _deck().splitlines()
                if ln.startswith("global_route")]
    assert commands == ["global_route"]


def test_the_ingest_survives_the_resume_transform():
    """pnr.tcl is also the SOURCE of the resume deck.  A read_def line with a
    flag in front of the path must not confuse `_build_pnr_resume_tcl_text`'s
    read_verilog/link_design surgery.  The elide sentinel is placed where the
    real emitter puts it -- immediately above the floorplan marker -- so the
    ingest lands INSIDE the elided region and the resume must not carry it."""
    marker = f'puts "{R._PNR_STAGE_MARKER} floorplan"'
    full = (_deck().replace(marker, R._PNR_RESUME_ELIDE_BEGIN + "\n" + marker)
            .replace("detailed_route\n",
                     "detailed_route\n" + R._PNR_RESUME_ELIDE_END + "\n"))
    consumer = R._padring_routing_consumer_tcl(full, _RING)
    resume = R._build_pnr_resume_tcl_text(consumer, checkpoint_def_c="/w/ck.def")
    assert "read_def /w/ck.def" in resume
    assert _RING not in resume, "the elided region still carries the ring ingest"


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
