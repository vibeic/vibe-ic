"""ORGANIC #650 — phase3 `step_pnr` always auto-assigned I/O pins with the
bare `place_pins -hor_layers M3 -ver_layers M2` and NEVER consumed a
`pin_order.cfg` even when one was present. The wrapper / fixed-die pin-order
contract was DETECTED (`_v1_6_599_check_wrapper_pin_order_cfg` only rglob'd
for the file's PRESENCE and returned a FAIL string — a dead-end gate) but
never HONORED: `grep set_io_pin_constraint|place_pins -group|FP_PIN_ORDER`
in phase3 returned 0 hits.

Fix: when a `pin_order.cfg` is found, INGEST it — parse the common
io-placer format (edge sections `#N` / `#S` / `#E` / `#W` followed by
pin-name lines / regexes) and emit OpenROAD `set_io_pin_constraint
-pin_names {<pin>} -region <edge>:*` directives so each pin lands on its
required die edge, then `place_pins` auto-assigns only the still-
unconstrained pins. `_v1_0_38_pin_placement_block` is the ENTRY to
ingestion; `_v1_6_599` remains the no-cfg wrapper-class pre-flight.

Acceptance (this file):
  * a project WITH a pin_order.cfg → the emitted PnR TCL references the
    cfg-derived pin constraints (`set_io_pin_constraint`, with the right
    -region per edge), NOT only the bare `place_pins -hor_layers ...`.
  * NO-LEAK: a project WITHOUT pin_order.cfg → the emitted PnR TCL keeps
    the bare auto-assign UNCHANGED, with zero `set_io_pin_constraint`.

These exercise the PURE TCL-builder helpers (no openroad / docker), which
is the right scope: #650 is source-verified (a phase2 blocker upstream
prevents a full benchmark reproduction).
"""
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# A representative pin_order.cfg in the common io-placer format: edge
# headers (#N/#S/#E/#W) each followed by pin-name tokens / regexes.
_SAMPLE_CFG = """\
# Pin order contract for the fixed-die wrapper
#N
clk
resetn
#E
gpio_out\\[.*\\]
#S
data_in
#W
spi_csb
spi_sck
"""


def _bare(metal="met"):
    return f"place_pins -hor_layers {metal}3 -ver_layers {metal}2"


# ── parser ─────────────────────────────────────────────────────────────────

def test_parse_pin_order_cfg_edge_sections():
    secs = R._v1_0_38_parse_pin_order_cfg(_SAMPLE_CFG)
    # ordered list of (edge_letter, [pins])
    assert [e for e, _ in secs] == ["N", "E", "S", "W"]
    by_edge = dict(secs)
    assert by_edge["N"] == ["clk", "resetn"]
    assert by_edge["E"] == ["gpio_out\\[.*\\]"]
    assert by_edge["S"] == ["data_in"]
    assert by_edge["W"] == ["spi_csb", "spi_sck"]


def test_parse_pin_order_cfg_word_headers_and_comments():
    """`#NORTH` resolves to N; a `#` comment line is not a pin; pins before
    the first edge header are ignored."""
    cfg = (
        "orphan_pin_before_any_edge\n"
        "#NORTH\n"
        "  a  extra_token_ignored\n"   # only first token is the pin name
        "# this is a comment, not a pin\n"
        "b\n"
        "# SOUTH\n"
        "c\n"
    )
    secs = R._v1_0_38_parse_pin_order_cfg(cfg)
    assert secs == [("N", ["a", "b"]), ("S", ["c"])]


def test_parse_pin_order_cfg_empty_or_no_edges():
    assert R._v1_0_38_parse_pin_order_cfg("") == []
    assert R._v1_0_38_parse_pin_order_cfg("   \n\n") == []
    # `#X` is not a compass edge → ignored, and its pins have no section.
    assert R._v1_0_38_parse_pin_order_cfg("#X\nfoo\nbar\n") == []


# ── TCL builder ─────────────────────────────────────────────────────────────

def test_build_pin_placement_tcl_emits_constraints_per_edge():
    secs = R._v1_0_38_parse_pin_order_cfg(_SAMPLE_CFG)
    tcl = R._v1_0_38_build_pin_placement_tcl(secs, _bare())
    assert "set_io_pin_constraint" in tcl
    # Each cfg entry pinned to its compass region (N=top, E=right, S=bottom,
    # W=left). The cfg entry is a REGEX, so it is resolved against the
    # design's own BTerm names first and the matched LITERAL names are what
    # reaches `-pin_names`; the entry->region binding is asserted on the
    # emitted resolve + report pair rather than on a raw `-pin_names {<pat>}`
    # string, which is the form that made OpenROAD answer PPL-0061.
    for pat, region in [("clk", "top"), ("resetn", "top"),
                        ("gpio_out\\[.*\\]", "right"),
                        ("data_in", "bottom"),
                        ("spi_csb", "left"), ("spi_sck", "left")]:
        assert ("set _poc_pins [vibeic_pin_names_matching {%s}]" % pat) in tcl
        assert ("PIN_ORDER_CONSTRAINT_APPLIED: %s -> %s:" % (pat, region)) in tcl
    # Every constraint goes through the resolver — no cfg entry is handed to
    # `-pin_names` as a raw pattern.
    assert "-pin_names $_poc_pins -region" in tcl
    assert "-pin_names {gpio_out\\[.*\\]}" not in tcl
    # Bare auto-assign still present (placing pins NOT named in the cfg).
    assert _bare() in tcl
    # NONFATAL-guarded so a build lacking the command falls through.
    assert "PIN_ORDER_CONSTRAINT_NONFATAL" in tcl
    # An entry matching no pin in the design stays LOUD rather than reading
    # as applied.
    assert "PIN_ORDER_CONSTRAINT_UNMATCHED" in tcl


# ── ingestion entry point ────────────────────────────────────────────────────

def _mk_project_with_cfg(tmp_path: Path, subdir="openlane",
                         body=_SAMPLE_CFG) -> Path:
    proj = tmp_path / "proj"
    d = proj / subdir
    d.mkdir(parents=True)
    (d / "pin_order.cfg").write_text(body)
    return proj


def test_pin_placement_block_ingests_when_cfg_present(tmp_path):
    proj = _mk_project_with_cfg(tmp_path)
    block, note = R._v1_0_38_pin_placement_block(proj, _bare())
    assert "set_io_pin_constraint" in block
    assert _bare() in block
    assert "pin_order.cfg ingested" in note
    assert "6 pin" in note  # clk, resetn, gpio, data_in, spi_csb, spi_sck


def test_pin_placement_block_finds_cfg_under_pnr_and_constraints(tmp_path):
    for sub in ("pnr", "constraints"):
        proj = _mk_project_with_cfg(tmp_path / sub, subdir=sub)
        block, note = R._v1_0_38_pin_placement_block(proj, _bare())
        assert "set_io_pin_constraint" in block, sub
        assert note, sub


def test_pin_placement_block_noleak_without_cfg(tmp_path):
    """NO-LEAK: no pin_order.cfg anywhere → bare auto-assign UNCHANGED."""
    proj = tmp_path / "proj_nocfg"
    (proj / "pnr").mkdir(parents=True)
    block, note = R._v1_0_38_pin_placement_block(proj, _bare())
    assert block == _bare()
    assert note == ""
    assert "set_io_pin_constraint" not in block


def test_pin_placement_block_cfg_with_no_edges_falls_back(tmp_path):
    """A cfg that parses to zero edge pins → bare auto-assign kept."""
    proj = _mk_project_with_cfg(tmp_path, body="#X\nfoo\n")
    block, note = R._v1_0_38_pin_placement_block(proj, _bare())
    assert block == _bare()
    assert "no edge pins" in note
    assert "set_io_pin_constraint" not in block


# ── full builder plumbing (the named defect surface) ─────────────────────────

def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        pnr_exclude_cell_file="/pdk/drc_exclude.cells",
    )


def _full_pnr_tcl(out_dir_c: str, place_pins_block):
    pdk = _pdk()
    plan = R._build_spare_cells_plan(
        2000, 0.02, (10, 10, 290, 290), liberty_path="", container="")
    return R._build_pnr_tcl_text(
        tech_lef_c="/pdk/tech.lef", cell_lef_c="/pdk/cells.lef",
        macro_lefs_tcl="", liberty_c="/pdk/lib.lib",
        macro_libs_tcl="", netlist_c="/work/netlist.v", top="chip_top",
        sdc_c="/work/chip_top.sdc",
        dont_use_block=R._dont_use_tcl(pdk),
        metal_prefix=pdk.metal_prefix, die_w=300, die_h=300,
        core_pad=10, core_w=280, core_h=280, site=pdk.site,
        out_dir_c=out_dir_c,
        tapcell_block=R._build_tapcell_tcl(pdk),
        pdn_block=R._build_pdn_tcl(pdk),
        util=0.45,
        spare_protection_tcl=R._build_spare_protection_tcl(plan, out_dir_c),
        spare_postfix_tcl=R._build_spare_postfix_tcl(
            plan, tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO"),
        clk_buf="sky130_fd_sc_hd__clkbuf_4",
        clk_buf_root="sky130_fd_sc_hd__clkbuf_16",
        routing_constraint_tcl="",
        pg_cleanup_block=R._pg_net_cleanup_tcl(),
        spef_repair_block=R._post_route_spef_repair_tcl(out_dir_c, "/x.lef"),
        antenna_repair_block=R._antenna_repair_tcl(pdk),
        filler_block="",
        place_pins_block=place_pins_block,
    )


def test_full_pnr_tcl_references_cfg_constraints_when_supplied(tmp_path):
    """The named acceptance: emitted PnR TCL references the cfg-derived pin
    constraints (set_io_pin_constraint), NOT only the bare place_pins."""
    secs = R._v1_0_38_parse_pin_order_cfg(_SAMPLE_CFG)
    block = R._v1_0_38_build_pin_placement_tcl(secs, _bare())
    tcl = _full_pnr_tcl(str(tmp_path / "out"), block)
    assert "set_io_pin_constraint" in tcl
    assert "-region top:*" in tcl and "-region left:*" in tcl
    # The auto-assign for unconstrained pins is still in the emitted TCL.
    assert _bare() in tcl


def test_full_pnr_tcl_default_is_bare_autoassign(tmp_path):
    """NO-LEAK: default (place_pins_block=None) emits ONLY the bare
    auto-assign — zero set_io_pin_constraint, exactly the legacy line."""
    tcl = _full_pnr_tcl(str(tmp_path / "out"), None)
    assert "set_io_pin_constraint" not in tcl
    assert _bare() in tcl
    assert "PIN_ORDER_CONSTRAINT_NONFATAL" not in tcl


def test_full_pnr_tcl_noleak_matches_pre650_line(tmp_path):
    """The default-None path produces the IDENTICAL make_tracks → place_pins
    → write_def sequence that shipped before #650 (regression guard)."""
    tcl = _full_pnr_tcl(str(tmp_path / "out"), None)
    assert ("make_tracks\n"
            "place_pins -hor_layers met3 -ver_layers met2\n"
            "write_def") in tcl
