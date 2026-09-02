"""The pad ring's physical-only population must survive the routing ingest.

MEASURED on spm x gf180mcuD, 2026-09-02, `phase3/stage3/pnr/openroad.log`:

    padring.def   757 IO-library instances   (36 pads + 4 corners + 717 fill)
    placed.def     36                        and every DEF after it, 36

The 721 are not dropped downstream. They are never ingested, and OpenROAD says
so 721 times -- 4 corners, 717 fillers, ZERO signal pads:

    [WARNING ODB-0248] skipping undefined comp gf180mcu_fd_io__cor_SW
                       encountered in FLOORPLAN DEF

`read_def -floorplan_initialize` lays a floorplan ONTO an already-linked design,
so a COMPONENT naming an instance the design does not own is undefined and is
skipped. The read still succeeds. `pad_ring_route_evidence` then reports
PADRING_POPULATION_LOST, and it is right.

These tests are about the DECK the runner builds, which is what decides whether
the instances exist when the DEF is read. They need no EDA tool.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as P  # noqa: E402


PADRING_DEF = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 2000 ;
COMPONENTS 5 ;
- u_pad_clk gf180mcu_fd_io__in_c + PLACED ( 100 200 ) N ;
- gf180mcu_fd_io__cor_SW gf180mcu_fd_io__cor + PLACED ( 0 0 ) N ;
- gf180mcu_fd_io__cor_NE gf180mcu_fd_io__cor + PLACED ( 900 900 ) S ;
- vibeic_iofill_S_0_0 gf180mcu_fd_io__fill5 + PLACED ( 300 0 ) N ;
- vibeic_iofill_S_0_1 gf180mcu_fd_io__fill1 + PLACED ( 400 0 ) N ;
END COMPONENTS
END DESIGN
"""

#: The seam the consumer replaces, in the shape the real deck has.
FLOORPLAN_TCL = (
    f'puts "{P._PNR_STAGE_MARKER} floorplan"\n'
    "initialize_floorplan -die_area {0 0 900 900} -site mysite\n"
    "write_def /w/floorplan.def\n"
    f'puts "{P._PNR_STAGE_MARKER} global_route"\n'
    "global_route\n"
)


def test_every_component_of_the_ring_def_is_parsed_with_its_master():
    got = P._padring_def_components(PADRING_DEF)
    assert got == [
        ("u_pad_clk", "gf180mcu_fd_io__in_c"),
        ("gf180mcu_fd_io__cor_SW", "gf180mcu_fd_io__cor"),
        ("gf180mcu_fd_io__cor_NE", "gf180mcu_fd_io__cor"),
        ("vibeic_iofill_S_0_0", "gf180mcu_fd_io__fill5"),
        ("vibeic_iofill_S_0_1", "gf180mcu_fd_io__fill1"),
    ], got


def test_nothing_outside_the_components_section_is_parsed():
    """A NETS or PINS section also uses ``- name ...`` entries."""
    noisy = PADRING_DEF.replace("END DESIGN", (
        "NETS 1 ;\n- some_net ( u_pad_clk PAD ) ;\nEND NETS\nEND DESIGN"))
    assert P._padring_def_components(noisy) == P._padring_def_components(
        PADRING_DEF)


def test_the_physical_only_instances_are_created_and_the_pads_are_not_touched():
    """Every ring component gets a guarded creation; none is unguarded.

    The guard is what keeps this from shadowing an instance the netlist owns:
    the pad is in the deck too, behind `findInst`, so the deck does not need to
    know which components the producer emitted -- odb answers at run time.
    """
    tcl = P._padring_physical_only_instance_tcl(PADRING_DEF)
    for inst in ("gf180mcu_fd_io__cor_SW", "gf180mcu_fd_io__cor_NE",
                 "vibeic_iofill_S_0_0", "vibeic_iofill_S_0_1", "u_pad_clk"):
        assert f'findInst "{inst}"' in tcl, f"{inst} is not guarded by findInst"
        assert f'dbInst_create $_pr_block $_pr_master "{inst}"' in tcl, inst
    # every creation sits inside a findInst guard
    assert tcl.count("dbInst_create") == tcl.count("findInst") == 5, tcl


def test_a_created_instance_is_marked_physical_so_it_is_not_read_as_logic():
    assert 'setSourceType "DIST"' in P._padring_physical_only_instance_tcl(
        PADRING_DEF)


def test_the_creations_run_BEFORE_the_def_is_read():
    """This is the whole fix. ODB-0248 skips and does not record: a component
    whose instance is absent at read time is gone, so a repair after the read
    has nothing to repair.
    """
    deck = P._padring_routing_consumer_tcl(
        FLOORPLAN_TCL, "/w/padring.def",
        P._padring_physical_only_instance_tcl(PADRING_DEF))
    create = deck.index("dbInst_create")
    read = deck.index("read_def -floorplan_initialize")
    assert create < read, (
        "the physical-only instances are created AFTER the ring is read, so "
        "odb skips them as undefined components and the creations land on a "
        "population that is already lost")


def test_the_ingest_still_happens_and_still_aborts_on_a_missing_ring():
    deck = P._padring_routing_consumer_tcl(
        FLOORPLAN_TCL, "/w/padring.def",
        P._padring_physical_only_instance_tcl(PADRING_DEF))
    assert "read_def -floorplan_initialize /w/padring.def" in deck
    assert "PADRING_ROUTING_INPUT_MISSING" in deck
    assert "write_def /w/floorplan.def" not in deck, (
        "the floorplan seam must still be REPLACED, not merely preceded")


def test_a_ring_wholly_present_in_the_netlist_creates_nothing_unguarded():
    """Degrade quietly in the one direction that is safe: the deck is emitted
    either way, and `findInst` decides. A ring with no components at all yields
    a deck with no creations."""
    empty = PADRING_DEF.replace(
        PADRING_DEF[PADRING_DEF.index("- u_pad_clk"):
                    PADRING_DEF.index("END COMPONENTS")], "")
    tcl = P._padring_physical_only_instance_tcl(empty)
    assert "dbInst_create" not in tcl
    assert "PADRING_PHYSICAL_INSTANCES_CREATED" in tcl, (
        "the marker must be printed even when nothing was created, or a run "
        "that created nothing is indistinguishable from one that never tried")


def test_the_count_is_reported_so_a_silent_zero_is_visible():
    tcl = P._padring_physical_only_instance_tcl(PADRING_DEF)
    assert "PADRING_PHYSICAL_INSTANCES_CREATED: $_pr_created" in tcl


def test_no_pdk_or_design_literal_is_baked_into_the_deck_builder():
    """The masters and instance names come from the DEF, never from here."""
    src = Path(P.__file__).read_text(encoding="utf-8")
    fn = src[src.index("def _padring_physical_only_instance_tcl"):]
    fn = fn[:fn.index("\ndef ")]
    body = fn[fn.index('"""', fn.index('"""') + 3) + 3:]
    for literal in ("gf180mcu", "sky130", "vibeic_iofill", "__cor"):
        assert literal not in body, (
            f"{literal!r} is a design/PDK literal in the deck builder's LOGIC; "
            f"the population must come from the ring DEF")
