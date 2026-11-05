#!/usr/bin/env python3
"""kspm43 — the cell a streamout is asked for must be one the DEF contains.

Every physical step in `phase3_one_shot_runner` is handed ONE `top` string and
uses it for two different things: to build `<top>.def` / `<top>.gds` /
`<top>_pnr.v`, and as the CELL NAME it hands a tool. On the chip path those
stop being the same word. Step 15.5ic's `io_pad_chip_top_gen` writes a
pad-carrying chip top and `_inject_padring_chip_top` retargets `link_design`
to it, so the DEF leaving PnR says `DESIGN chip_top ;` while the FILE stays
`<core>.def` — deliberately, because every downstream lookup is keyed on the
file name. `effective_top` is resolved once from `rtl/` before the flow starts
and is never told about the substitution.

MEASURED, spm x gf180mcuD, a 36-pad chip top, plugin 1.17.4, the run as
shipped. `phase3/stage3/pnr/spm.def` carries `DESIGN chip_top ;`; the Magic
streamout was invoked with `TOP=spm`; Magic said so, in the transcript the
caller assigned to a local and never read:

    Cell spm couldn't be read
    No such file or directory
    Cannot rename; cell "spm" already exists!

`load spm` on a database with no `spm` CREATES an empty cell of that name,
`select top cell` selects it, and `gds write` writes it — `spm.gds`, 106
bytes, one empty structure. `step_drc` then reported `violations=0` on it,
`pad_ring_route_evidence` reported PADRING_GDS_REFERENCES_LOST for 35
references of `gf180mcu_fd_io__in_c`, and `digital_hardmacro_gen` refused
because "spm.gds carries no geometry record".

A/B ON THE SHIPPED DEF — same deck, same libraries, only the cell name
changed:

    TOP=spm       ->        106 bytes
    TOP=chip_top  -> 16,941,056 bytes

AND IT IS NOT A LIBRARY SHORTAGE. The same probe with the PDK IO library's
LEF and GDS views ADDED to the Magic invocation, still `TOP=spm`, still writes
106 bytes — Magic had already resolved those masters by itself:
`Cell gf180mcu_fd_io__in_c read from path
/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/mag`.
"""
from __future__ import annotations
import sys
from pathlib import Path
_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402




def _def(path: Path, design: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "VERSION 5.8 ;\n"
        "DIVIDERCHAR \"/\" ;\n"
        f"DESIGN {design} ;\n"
        "UNITS DISTANCE MICRONS 1000 ;\n"
        "COMPONENTS 1 ;\n    - u_0 STD_CELL_A + FIXED ( 0 0 ) N ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    return path


# --- the reader ------------------------------------------------------------

def test_the_def_names_itself(tmp_path):
    assert p3._def_design_name(_def(tmp_path / "spm.def", "chip_top")) == "chip_top"


def test_an_unreadable_or_headerless_def_is_none_never_an_exception(tmp_path):
    """Best-effort: this must never be the thing that takes a step down."""
    assert p3._def_design_name(tmp_path / "absent.def") is None
    bare = tmp_path / "bare.def"
    bare.write_text("VERSION 5.8 ;\n")
    assert p3._def_design_name(bare) is None








# --- the two engines: what the tool is actually told to load ---------------















# --- the same seam, one step later: LVS extraction -------------------------
