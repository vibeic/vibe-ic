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
import sys
from pathlib import Path


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
