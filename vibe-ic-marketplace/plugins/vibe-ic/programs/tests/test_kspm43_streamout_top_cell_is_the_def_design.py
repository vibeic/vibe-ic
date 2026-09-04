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


class _Pdk:
    """The PdkConfig surface the two streamout engines read."""
    def __init__(self):
        self.macro_lefs, self.macro_gds = [], []
        self.tech_lef, self.cell_lef, self.cell_gds = "/t.tlef", "/c.lef", "/c.gds"
        self.lefdef_layermap = None
        self.calibre_drc = self.drc_deck = None
        self.stdcell_marker_layer = self.dummy_fill = None
        self.same_net_heal = self.port_label_restore = None


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


def test_a_def_that_agrees_is_a_byte_for_byte_no_op(tmp_path):
    """THE NO-OP CONTROL. Off the chip path the DEF's DESIGN *is* the runner's
    top, so every caller below reproduces its current behaviour exactly and
    the disclosure is empty — this cannot perturb a design it is not for."""
    d = _def(tmp_path / "spm.def", "spm")
    assert p3._streamout_top(d, "spm") == ("spm", "")


def test_a_def_that_disagrees_substitutes_and_says_so(tmp_path):
    """The substitution is NAMED. A run that silently streams a different cell
    than the one its record says is the shape that hid this for a release."""
    d = _def(tmp_path / "spm.def", "chip_top")
    cell, note = p3._streamout_top(d, "spm")
    assert cell == "chip_top"
    assert "chip_top" in note and "spm" in note, note


def test_an_absent_def_falls_back_to_the_callers_top(tmp_path):
    cell, note = p3._streamout_top(tmp_path / "absent.def", "spm")
    assert (cell, note) == ("spm", "")


# --- the two engines: what the tool is actually told to load ---------------

def _capture(monkeypatch):
    seen = {}

    def _exec(container, cmd, *a, **kw):
        seen["cmd"] = cmd
        return 0, "", ""
    monkeypatch.setattr(p3, "_docker_exec", _exec)
    monkeypatch.setattr(p3, "_tool_in_path", lambda c, t: True)
    monkeypatch.setattr(p3, "_to_container_path", lambda p, c: str(p))
    return seen


def _project(tmp_path, design):
    pnr = p3._pl.pnr_dir(tmp_path)
    _def(pnr / "spm.def", design)
    return tmp_path, pnr


def test_the_magic_engine_loads_the_cell_the_def_contains(tmp_path, monkeypatch):
    """`load <a cell this database does not have>` CREATES an empty cell and
    streams it — Magic does not refuse, it invents. So the name has to be
    right BEFORE the tool runs; there is no failure to catch afterwards."""
    project, pnr = _project(tmp_path, "chip_top")
    seen = _capture(monkeypatch)
    p3._magic_def_to_gds(project, "spm", _Pdk(), "cnt", pnr / "spm.gds")
    assert "TOP=chip_top " in seen["cmd"], seen["cmd"][:300]
    assert "GDS_OUT=" + str(pnr / "spm.gds") in seen["cmd"], (
        "the FILE name must not follow the cell name — every downstream "
        "lookup in this runner is keyed on it")


def test_the_klayout_engine_loads_the_cell_the_def_contains(tmp_path, monkeypatch):
    """The other engine, same seam. KLayout fails differently — `ly.cell(top)`
    returns None and a fallback guesses a top cell — but a guess is not a
    resolution and the two engines must not disagree about what the top is."""
    project, pnr = _project(tmp_path, "chip_top")
    seen = _capture(monkeypatch)
    monkeypatch.setattr(p3, "_vacuous_on_unrouted", lambda *a, **k: None)
    monkeypatch.setattr(p3, "_magic_def_to_gds", lambda *a, **k: (False, "forced"))
    p3.step_gds(project, "spm", _Pdk(), "cnt")
    assert "TOP=chip_top " in seen["cmd"], seen["cmd"][:300]


def test_an_agreeing_def_leaves_both_engines_argv_unchanged(tmp_path, monkeypatch):
    """The other half of the no-op control, on the argv the tools receive."""
    project, pnr = _project(tmp_path, "spm")
    seen = _capture(monkeypatch)
    p3._magic_def_to_gds(project, "spm", _Pdk(), "cnt", pnr / "spm.gds")
    assert "TOP=spm " in seen["cmd"], seen["cmd"][:300]


def test_magic_keeps_its_transcript(tmp_path, monkeypatch):
    """It was the only evidence of WHAT went into the GDS, and it was thrown
    away at the point of capture: both call sites assign it to a local they
    never read. Keyed on the OUTPUT, because this same function also streams
    the DRC re-stream's `<top>.magic_merged.gds` and one fixed name would let
    the second run erase the first run's evidence."""
    project, pnr = _project(tmp_path, "spm")
    monkeypatch.setattr(p3, "_tool_in_path", lambda c, t: True)
    monkeypatch.setattr(p3, "_to_container_path", lambda p, c: str(p))
    monkeypatch.setattr(
        p3, "_docker_exec",
        lambda container, cmd, *a, **kw: (1, "Cell spm couldn't be read", ""))
    p3._magic_def_to_gds(project, "spm", _Pdk(), "cnt", pnr / "spm.gds")
    log = pnr / "spm.magic_stream_out.log"
    assert log.is_file(), sorted(p.name for p in pnr.iterdir())
    assert "couldn't be read" in log.read_text()
    p3._magic_def_to_gds(project, "spm", _Pdk(), "cnt",
                         pnr / "spm.magic_merged.gds")
    assert (pnr / "spm.magic_merged.magic_stream_out.log").is_file()
    assert "couldn't be read" in log.read_text(), (
        "the re-stream erased the stream-out's own transcript")


def test_the_prefix_tree_can_run_this_and_answers_wrongly(tmp_path, monkeypatch):
    """THE BIDIRECTIONAL CONTROL, written so the PRE-FIX tree can execute it.

    It uses no symbol the pre-fix tree lacks — only the shipped engine and the
    command it builds — so that tree produces an argv and the assertion judges
    THAT argv: `TOP=spm` against a DEF whose DESIGN is `chip_top`, which is the
    defect stated as an answer rather than a crash.

    The live half of the control is not a stub: the shipped run's own
    `spm.gds` is 106 bytes, and the same DEF streamed with `TOP=chip_top` is
    16,941,056."""
    project, pnr = _project(tmp_path, "chip_top")
    seen = _capture(monkeypatch)
    p3._magic_def_to_gds(project, "spm", _Pdk(), "cnt", pnr / "spm.gds")
    assert "TOP=chip_top " in seen["cmd"], (
        "the streamout is told to load `spm`, a cell this DEF does not "
        "contain; Magic creates an empty cell of that name and streams it, "
        "and the 106-byte result reaches sign-off DRC, LVS and the hand-off "
        "pack as the layout")


# --- the same seam, one step later: LVS extraction -------------------------

def test_the_extraction_recipe_loads_the_cell_the_def_contains(tmp_path,
                                                               monkeypatch):
    """LVS reads the SAME DEF with the SAME `load $env(TOP)` and lost the
    design the same way. MEASURED on the shipped run
    (phase3/stage3/extracted/ext2spice.log):

        Cell spm couldn't be read
        No such file or directory
        PORTS_PROMOTED -1..-1
        Warning:  There is nothing here to extract.

    and the step reported LVS_EXTRACTION_NO_NETLIST, "magic completed the
    recipe but wrote no file". Pinned beside the stream-out so the family
    cannot be half-fixed: leaving this one would extract the layout as
    `chip_top` and point netgen's schematic side at `spm`, turning a loud
    refusal into a compare over the wrong pair."""
    pnr = p3._pl.pnr_dir(tmp_path)
    def_file = _def(pnr / "spm.def", "chip_top")
    netlist = pnr / "spm_pnr.v"
    netlist.write_text("module chip_top(); endmodule\n")
    seen = _capture(monkeypatch)
    p3._run_extraction_lvs(tmp_path, "spm", _Pdk(), "cnt", def_file, netlist,
                           "/dev/null", "/dev/null", 0.0)
    assert "TOP=chip_top " in seen["cmd"], seen["cmd"][-400:]


def test_an_agreeing_def_leaves_the_extraction_argv_unchanged(tmp_path,
                                                              monkeypatch):
    """The no-op control on the LVS side."""
    pnr = p3._pl.pnr_dir(tmp_path)
    def_file = _def(pnr / "spm.def", "spm")
    netlist = pnr / "spm_pnr.v"
    netlist.write_text("module spm(); endmodule\n")
    seen = _capture(monkeypatch)
    p3._run_extraction_lvs(tmp_path, "spm", _Pdk(), "cnt", def_file, netlist,
                           "/dev/null", "/dev/null", 0.0)
    assert "TOP=spm " in seen["cmd"], seen["cmd"][-400:]
