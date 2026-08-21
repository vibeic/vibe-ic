"""slot_pad_budget_check — the chip path's pad-budget front door.

Captured from the gf180mcuD chip-path campaign (2026-08-20): five of nine
benchmark ICs cannot be bonded out on any purchasable slot, and each was
discovered by building until it hit a wall instead of by arithmetic on files
step 0.5ic had already ingested.

TWO OF THESE TESTS PIN DEFECTS THIS PROGRAM ITSELF SHIPPED IN ITS FIRST DRAFT,
both of the same shape — an unmeasured thing becoming a measured number — and
both in the direction that produces a FALSE PASS:

  1. reading only the operator's RAW `PAD_<SIDE>` keys against a real INGESTED
     project counted zero pads and returned DOES_NOT_FIT with
     "largest slot digital signal pads: 0".
  2. a port whose width is parameterised was dropped from the sum, so a design
     with 120 real interface bits summed to 31 and the verdict was **FITS**.
"""
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import slot_pad_budget_check as S  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures — a slot in BOTH shapes, built from the same pad list
# --------------------------------------------------------------------------- #
def _pads(n_bidir=40, n_input=12, n_analog=2, n_power=18, n_corner=4):
    e = []
    e += [f"bidir\\[{i}\\].pad" for i in range(n_bidir)]
    e += [f"inputs\\[{i}\\].pad" for i in range(n_input)]
    e += [f"analog\\[{i}\\].pad" for i in range(n_analog)]
    e += [f"dvdd_pads\\[{i}\\].pad" for i in range(n_power // 2)]
    e += [f"dvss_pads\\[{i}\\].pad" for i in range(n_power - n_power // 2)]
    e += [f"corner\\[{i}\\].pad" for i in range(n_corner)]
    e += ["clk_pad", "rst_n_pad"]
    return e


def _slot_raw(**kw):
    """The shape the shuttle operator's own template file has."""
    e = _pads(**kw)
    q = len(e) // 4 + 1
    return {"DIE_AREA": [0, 0, 3932, 5122],
            "PAD_SOUTH": e[:q], "PAD_EAST": e[q:2 * q],
            "PAD_NORTH": e[2 * q:3 * q], "PAD_WEST": e[3 * q:]}


def _slot_ingested(**kw):
    """The shape `submission_template_ingest` writes into the project."""
    raw = _slot_raw(**kw)
    return {"slot": "slot_1x1", "die_area": {"width": "3932"},
            "pads": {"pattern": "^PAD.*$",
                     "lists": [{"key": k, "raw": raw[k], "count": len(raw[k])}
                               for k in ("PAD_SOUTH", "PAD_EAST",
                                         "PAD_NORTH", "PAD_WEST")]}}


_RTL_FITS = """
module chip_top (
    input wire clk, input wire rst_n,
    input wire [7:0] address, input wire cs,
    output wire [7:0] status, output wire error
);
endmodule
"""

_RTL_FOLDABLE = """
module chip_top (
    input  wire        clk,
    input  wire        reset_n,
    input  wire        cs,
    input  wire        we,
    input  wire [7:0]  address,
    input  wire [31:0] write_data,
    output [31:0] read_data,
    output error
);
endmodule
"""

_RTL_PARAMETERISED = """
module accel #(parameter BAW = 11, parameter BDW = 39) (
    input  wire clk, input wire rst_n,
    input  wire [BAW-1:0] host_addr,
    input  wire [BDW-1:0] host_wdata,
    output reg  [BDW-1:0] host_rdata,
    output reg done
);
endmodule
"""


# --------------------------------------------------------------------------- #
# pad inventory
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("shape", ["raw", "ingested"])
def test_both_slot_shapes_count_the_same_pads(shape):
    """DEFECT 1 REGRESSION. The gate must read the INGESTED shape, which is the
    only shape a real chip-path project has; reading only the raw shape counted
    zero and the verdict looked authoritative."""
    obj = _slot_raw() if shape == "raw" else _slot_ingested()
    inv = S.slot_pad_inventory(obj)
    assert inv["digital_signal_pads"] == 52, inv
    assert inv["analog_pads"] == 2
    assert inv["by_role"]["bidir"] == 40
    assert inv["by_role"]["input"] == 12
    assert inv["unclassified_examples"] == []


def test_unclassified_pads_are_reported_not_dropped():
    obj = _slot_ingested()
    obj["pads"]["lists"][0]["raw"].append("mystery_thing\\[0\\].pad")
    inv = S.slot_pad_inventory(obj)
    assert inv["by_role"]["unclassified"] == 1
    assert "mystery_thing\\[0\\].pad" in inv["unclassified_examples"]


def test_zero_pads_is_UNDECIDED_never_DOES_NOT_FIT():
    """DEFECT 1, the verdict half: 0 pads is a parse that found nothing."""
    ports = S.parse_top_ports(_RTL_FITS, "chip_top")
    rep = S.evaluate({"empty": {"PAD_SOUTH": []}}, ports)
    assert rep["verdict"] == "UNDECIDED", rep
    assert rep["rc"] == 2
    assert "0 pads is not a slot" in rep["reason"]


# --------------------------------------------------------------------------- #
# widths
# --------------------------------------------------------------------------- #
def test_parameterised_width_without_a_value_is_UNDECIDED_not_a_pass():
    """DEFECT 2 REGRESSION — the false-PASS direction.

    Before the fix these three ports were dropped and the design summed to 31
    against a 52-pad slot, so the gate answered FITS for a 120-bit interface.
    """
    ports = S.parse_top_ports(_RTL_PARAMETERISED, "accel")
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert rep["verdict"] == "UNDECIDED", rep
    assert rep["rc"] == 2
    for name in ("host_addr", "host_wdata", "host_rdata"):
        assert name in rep["reason"]
    assert "partial_signal_bits_EXCLUDING_UNRESOLVED" in rep
    assert rep["partial_signal_bits_EXCLUDING_UNRESOLVED"] != 120


def test_parameterised_width_WITH_supplied_values_measures_the_real_interface():
    ports = S.parse_top_ports(_RTL_PARAMETERISED, "accel",
                              {"BAW": 11, "BDW": 39})
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert rep["declared_signal_bits"] == 11 + 39 + 39 + 1, rep
    assert rep["over_by_ratio"] == pytest.approx(90 / 52, rel=1e-3)
    # 90 declared bits against 52 pads, BUT host_wdata/host_rdata are a
    # same-width 39-bit pair: 90 - 39 = 51 <= 52. The gate is right and my
    # first draft of this test was wrong — I asserted DOES_NOT_FIT from the
    # raw ratio and the program had already done the arithmetic properly.
    assert rep["verdict"] == "FITS_AFTER_FOLD"
    assert rep["rc"] == 0
    assert rep["signal_bits_after_folding_every_candidate"] == 51


def test_clk_and_rst_ride_dedicated_pads_and_cost_no_budget():
    ports = S.parse_top_ports(_RTL_FITS, "chip_top")
    b = S.interface_budget(ports)
    assert b["signal_bits"] == 8 + 1 + 8 + 1
    assert set(b["on_dedicated_pads"]) == {"clk", "rst_n"}


# --------------------------------------------------------------------------- #
# verdicts
# --------------------------------------------------------------------------- #
def test_a_design_that_fits_is_rc0_FITS():
    ports = S.parse_top_ports(_RTL_FITS, "chip_top")
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert (rep["verdict"], rep["rc"]) == ("FITS", 0)
    assert rep["slot_that_fits_as_declared"] == "slot_1x1"


def test_over_budget_but_foldable_is_FITS_AFTER_FOLD_and_names_the_fold():
    """The `sha256` case: 75 declared bits against 52 pads, which fits only
    because a 32-bit input bus and a 32-bit output bus can share one
    bidirectional group."""
    ports = S.parse_top_ports(_RTL_FOLDABLE, "chip_top")
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert rep["declared_signal_bits"] == 75
    assert (rep["verdict"], rep["rc"]) == ("FITS_AFTER_FOLD", 0)
    assert rep["signal_bits_after_folding_every_candidate"] == 43
    f = rep["fold_candidates"]
    assert len(f) == 1
    assert f[0]["input_bus"] == "write_data"
    assert f[0]["output_bus"] == "read_data"
    assert f[0]["width"] == 32
    assert set(f[0]["possible_direction_controls"]) >= {"cs", "we"}


def test_the_fold_is_proposed_never_applied_and_says_so():
    """The gate must NOT claim a fold is safe — that is a protocol fact about
    the design, and a gate that asserted it would be inventing a pin-out."""
    ports = S.parse_top_ports(_RTL_FOLDABLE, "chip_top")
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert "NOT DECIDED HERE" in rep["fold_candidates"][0]["safety"]
    assert any("protocol-safe" in s for s in rep["does_not_decide"])
    # the DECLARED count is reported unchanged; the fold does not rewrite it
    assert rep["declared_signal_bits"] == 75


def test_hopeless_design_is_rc1_with_the_ratio_named():
    rtl = ("module chip_top (input wire clk, input wire rst_ni,\n"
           "  input wire [127:0] a, input wire [255:0] k,\n"
           "  output wire [127:0] y, output wire alert);\nendmodule\n")
    ports = S.parse_top_ports(rtl, "chip_top")
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert rep["declared_signal_bits"] == 128 + 256 + 128 + 1
    assert (rep["verdict"], rep["rc"]) == ("DOES_NOT_FIT", 1)
    assert rep["over_by_ratio"] > 9
    # even folding the one same-width pair is not enough, and it says so
    assert rep["over_by_ratio_after_fold"] > 7


def test_missing_top_module_is_UNDECIDED_not_a_verdict():
    assert S.parse_top_ports(_RTL_FITS, "not_a_module") is None


def test_cli_writes_json_and_returns_the_verdict_rc(tmp_path):
    proj = tmp_path / "proj"
    slots = proj / "input" / "submission_template" / "slots"
    slots.mkdir(parents=True)
    (slots / "slot_1x1.json").write_text(json.dumps(_slot_ingested()))
    rtl = tmp_path / "chip_top.v"
    rtl.write_text(_RTL_FITS)
    out = tmp_path / "rep.json"
    rc = S.main([str(proj), "--rtl", str(rtl), "--top", "chip_top",
                 "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FITS"
    assert rep["slots"]["slot_1x1"]["digital_signal_pads"] == 52


def test_cli_without_ingested_slots_is_UNDECIDED(tmp_path):
    rtl = tmp_path / "chip_top.v"
    rtl.write_text(_RTL_FITS)
    rc = S.main([str(tmp_path), "--rtl", str(rtl), "--top", "chip_top"])
    assert rc == 2


# --------------------------------------------------------------------------- #
# comments must never mint or destroy a port  (vibe-ic#731)
# --------------------------------------------------------------------------- #
# `parse_top_ports` stripped comments with TWO independent substitutions --
# `//` first, then `/* */`. Verilog has one rule instead: whichever introducer
# opens FIRST owns what follows. The `//` pass runs blind to an open block
# comment, so a `*/` sitting behind a `//` is deleted with its line, and the
# block comment it terminated survives into the text `_DIR_RE` scans.
#
# Both directions below are the SAME orphaned block; which one fires depends
# only on where the commas fall. The dropping direction is the dangerous one:
# a smaller interface is how a design that cannot be bonded out reads as FITS.

# Real ports are exactly clk and done. `phantom` is inside the block comment.
_RTL_COMMENT_MINTS = """
module chip_top (
    input wire clk,   /* disabled,
    output wire phantom,
    // end of the disabled block */
    output wire done
);
endmodule
"""

# Real ports are clk, done and io -- the block comment holds no port at all.
_RTL_COMMENT_DROPS = """
module chip_top (
    input wire clk,
    /* legacy block
    // was here */
    output wire done,
    inout wire [7:0] io
);
endmodule
"""


def test_a_comment_does_not_mint_a_port_that_does_not_exist():
    ports = S.parse_top_ports(_RTL_COMMENT_MINTS, "chip_top")
    assert [p["name"] for p in ports] == ["clk", "done"]


def test_a_comment_does_not_swallow_the_real_port_that_follows_it():
    ports = S.parse_top_ports(_RTL_COMMENT_DROPS, "chip_top")
    assert [p["name"] for p in ports] == ["clk", "done", "io"]


def test_the_founding_case_a_comment_sentence_naming_a_direction():
    """The shape the gate exists for: prose that matches the declaration
    pattern. Neither commented port is real."""
    rtl = ("module chip_top (\n"
           "    input  wire clk,     // output wire commented_out,\n"
           "    output wire done     /* inout wire also_not_real, */\n"
           ");\nendmodule\n")
    ports = S.parse_top_ports(rtl, "chip_top")
    assert [p["name"] for p in ports] == ["clk", "done"]


def test_stripping_preserves_line_geometry_so_ifdef_nesting_still_counts():
    """A block comment is replaced by the newlines it spanned. The
    conditional-compilation scan is line-oriented and counts `ifdef`/`endif`
    nesting by line, so collapsing those lines would mis-attribute which
    ports were conditional."""
    rtl = ("module chip_top (\n"
           "`ifdef USE_PWR\n"
           "    /* a power-only pad,\n"
           "       spanning lines */\n"
           "    inout wire vdda1,\n"
           "`endif\n"
           "    input wire clk,\n"
           "    output wire done\n"
           ");\nendmodule\n")
    ports = S.parse_top_ports(rtl, "chip_top")
    assert [p["name"] for p in ports] == ["vdda1", "clk", "done"]
    assert [p["name"] for p in ports if p["conditional"]] == ["vdda1"]


def test_a_phantom_port_does_not_reach_the_budget_verdict():
    """The defect is only interesting because it lands on the number the
    verdict is computed from. `_RTL_FITS` plus a commented-out 256-bit bus
    must still be the same interface it was without the comment."""
    clean = S.evaluate({"slot_1x1": _slot_ingested()},
                       S.parse_top_ports(_RTL_FITS, "chip_top"))
    commented = _RTL_FITS.replace(
        "    output wire [7:0] status, output wire error\n",
        "    output wire [7:0] status, output wire error\n"
        "    /* removed for this tape-out,\n"
        "    , input wire [255:0] wide_key\n"
        "    // end */\n")
    rep = S.evaluate({"slot_1x1": _slot_ingested()},
                     S.parse_top_ports(commented, "chip_top"))
    assert rep["declared_signal_bits"] == clean["declared_signal_bits"]
    assert (rep["verdict"], rep["rc"]) == ("FITS", 0)


# --------------------------------------------------------------------------- #
# an ATTRIBUTE is not a comment, and it dropped a real port
# --------------------------------------------------------------------------- #
# PRE-EXISTING, and measured identical on the commit before the comment repair.
# `(* keep = "true" *)` is live source a synthesiser reads, but it is not part
# of a port declaration and `_DIR_RE` anchors with `^`. A port carrying one
# reached the scan as a chunk beginning `(*`, matched no direction keyword, and
# was discarded as an unparsable continuation.
#
# Same failure direction as the orphaned block comment above: a real port
# DROPPED, a smaller interface than the design has, and a false FITS.

def test_an_attribute_on_a_port_does_not_drop_it():
    rtl = ('module chip_top (\n'
           '    (* keep = "true" *) input wire clk,\n'
           '    output wire done\n'
           ');\nendmodule\n')
    assert [p["name"] for p in S.parse_top_ports(rtl, "chip_top")] == ["clk", "done"]


def test_an_attribute_spanning_lines_keeps_the_conditional_attribution():
    """Attributes are replaced by the newlines they spanned, for the same
    reason comments are: the conditional scan counts `ifdef` nesting by line."""
    rtl = ('module chip_top (\n'
           '`ifdef USE_PWR\n'
           '    (* mark_debug = "true",\n'
           '       keep = "true" *) inout wire vdda1,\n'
           '`endif\n'
           '    input wire clk\n'
           ');\nendmodule\n')
    ports = S.parse_top_ports(rtl, "chip_top")
    assert [p["name"] for p in ports] == ["vdda1", "clk"]
    assert [p["name"] for p in ports if p["conditional"]] == ["vdda1"]


def test_a_comment_that_contains_an_attribute_opener_is_still_a_comment():
    """Order matters: comments are stripped first, so `(*` inside a block
    comment never reaches the attribute pass. Real ports are clk and done."""
    rtl = ('module chip_top (\n'
           '    input wire clk,   /* (* not really an attribute *)\n'
           '    output wire phantom,\n'
           '    // end */\n'
           '    output wire done\n'
           ');\nendmodule\n')
    assert [p["name"] for p in S.parse_top_ports(rtl, "chip_top")] == ["clk", "done"]


def test_multiplication_inside_parentheses_is_not_an_attribute():
    """`(*` begins an attribute; `( 2 * 4 )` does not. A stripper that ate the
    latter would silently rewrite a parameter expression."""
    rtl = ('module chip_top #(parameter W = (2 * 4)) (\n'
           '    input wire [W-1:0] bus,\n'
           '    output wire done\n'
           ');\nendmodule\n')
    assert [p["name"] for p in S.parse_top_ports(rtl, "chip_top")] == ["bus", "done"]


def test_the_founding_shape_a_comment_naming_the_top_module():
    """The defect the GATE was written for -- `\\bmodule\\s+(\\w+)` matching a
    comment -- reaching this program's own inline module search. That regex is
    written inline rather than as a module-level `re.compile`, so the gate's
    detector cannot see it and never named it; it is covered here because the
    defect class is what matters, not the finding string."""
    rtl = ('// This module chip_top is described in section 4.\n'
           '/* module chip_top (input wire decoy_a, output wire decoy_b); */\n'
           'module chip_top (\n'
           '    input wire clk,\n'
           '    output wire done\n'
           ');\nendmodule\n')
    assert [p["name"] for p in S.parse_top_ports(rtl, "chip_top")] == ["clk", "done"]


def test_a_block_comment_is_not_nested_and_ends_at_the_first_terminator():
    """Verilog block comments do not nest. `/* outer /* inner */` ends at the
    FIRST `*/`, so `done` is a real port."""
    rtl = ('module chip_top (\n'
           '    input wire clk,\n'
           '    /* outer /* inner */\n'
           '    output wire done\n'
           ');\nendmodule\n')
    assert [p["name"] for p in S.parse_top_ports(rtl, "chip_top")] == ["clk", "done"]


# --------------------------------------------------------------------------- #
# driven by a REAL checked-in artefact, not a fixture authored alongside it
# --------------------------------------------------------------------------- #
# vibe-ic#400: "a change whose tests are all fixtures authored alongside it
# cannot distinguish itself from its own absence". Every test above this line
# is synthetic. These two read RTL that was in the repository before this
# change existed.

import _hostpaths  # noqa: E402


def _real_rtl_files():
    root = _hostpaths.repo_path(".")
    files = sorted(p for p in root.rglob("*.v") if ".git" not in p.parts)
    files += sorted(p for p in root.rglob("*.sv") if ".git" not in p.parts)
    if not files:
        pytest.skip("no checked-in RTL in this tree")
    return files


def test_real_in_repo_rtl_still_parses_to_a_port_list():
    """The stripper runs over real RTL, not only over pathological fixtures.
    At least one checked-in module header must yield ports — a rewrite that
    silently returned None everywhere would pass every synthetic test above
    that asserts a specific list, but not this."""
    import re
    mod = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)
    parsed = 0
    for f in _real_rtl_files():
        txt = f.read_text(errors="replace")
        for top in sorted(set(mod.findall(txt))):
            ports = S.parse_top_ports(txt, top)
            if ports:
                parsed += 1
                assert all(p["dir"] in ("input", "output", "inout")
                           for p in ports)
                assert all(p["name"] and not p["name"].startswith(("/", "("))
                           for p in ports), (
                    f"{f.name}::{top} minted a port out of comment or "
                    f"attribute text: {[p['name'] for p in ports]}")
    assert parsed > 0, "no checked-in module header parsed to any port"


def test_no_real_in_repo_module_gains_or_loses_a_port_from_the_comment_fix():
    """A stripper is only safe if it is inert on text that has nothing to
    strip. Re-parsing each real module with its comments ALREADY removed must
    give the identical port list — if the two disagree, the stripper is
    changing something other than comments."""
    import re
    mod = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)
    checked = 0
    for f in _real_rtl_files():
        txt = f.read_text(errors="replace")
        pre = S._strip_hdl_attributes(S._strip_hdl_comments(txt))
        for top in sorted(set(mod.findall(txt))):
            a = S.parse_top_ports(txt, top)
            b = S.parse_top_ports(pre, top)
            ka = [(p["dir"], p["name"], p["width"]) for p in (a or [])]
            kb = [(p["dir"], p["name"], p["width"]) for p in (b or [])]
            assert ka == kb, f"{f.name}::{top}: {ka} != {kb}"
            checked += 1
    assert checked > 0


# --------------------------------------------------------------------------- #
# the site-level strip is a DATAFLOW guarantee, and it needs its own test
# --------------------------------------------------------------------------- #
# Found by a mutation run, and it is the honest reason this test exists:
# deleting either site-level `_strip_hdl_comments(...)` call changed NO
# observable behaviour and every test above still passed. The whole-text pass
# had already cleared the text, so the local calls were doing nothing a fixture
# could see — a guarantee no test defended.
#
# They are not decoration. `decl` and `s` are `for`-loop targets, so no
# assignment carries the whole-text strip to them, and a later change to where
# `rest` or `raw_no_comment` comes from would re-open the hole silently. That
# is a property of the DATAFLOW, not of any input, so it is pinned with the
# repo gate's own scanner rather than with another Verilog fixture — this is
# `hdl_declaration_scan_strips_comments_check`'s question, asked locally
# instead of only in a 300-second suite.

def test_no_declaration_regex_in_this_file_scans_unstripped_text():
    import hdl_declaration_scan_strips_comments_check as H
    src = Path(S.__file__).read_text(encoding="utf-8")
    findings = H.scan_source(src, "slot_pad_budget_check")
    assert findings == [], (
        "a declaration regex here scans a local no stripper touched: "
        f"{findings}. Strip on the value that REACHES the scan — stripping a "
        "sibling does not make this one safe.")


# --------------------------------------------------------------------------- #
# line geometry is load-bearing, and a mutation run is what proved it
# --------------------------------------------------------------------------- #
# Both strippers replace a multi-line region with the NEWLINES IT SPANNED. The
# two tests further up assert conditional attribution survives, and a mutation
# run showed neither of them dies when the newlines are dropped — their
# comments and attributes sit on their own lines, so fusing changes nothing.
#
# The case that bites is a region spanning FROM the `ifdef line INTO the port
# line. Collapse its newlines and the two fuse; the fused line now begins with
# `ifdef, which is exactly what the directive-removal regex is anchored to
# (`^[ \t]*`(?:ifdef|...)\b[^\n]*$`), so the whole line is deleted — REAL PORT
# INCLUDED. Measured: `vdda1` disappears from the port list entirely, not
# merely from the conditional set. A dropped port is a smaller interface, and a
# smaller interface is a false FITS.

def test_a_comment_spanning_from_the_ifdef_line_into_a_port_line_keeps_the_port():
    rtl = ("module chip_top (\n"
           "`ifdef USE_PWR /* a note that\n"
           "   spans lines */ inout wire vdda1,\n"
           "`endif\n"
           "    input wire clk\n"
           ");\nendmodule\n")
    ports = S.parse_top_ports(rtl, "chip_top")
    assert [p["name"] for p in ports] == ["vdda1", "clk"]
    assert [p["name"] for p in ports if p["conditional"]] == ["vdda1"]


def test_an_attribute_spanning_from_the_ifdef_line_into_a_port_line_keeps_the_port():
    """Same geometry rule, the attribute stripper's copy of it."""
    rtl = ("module chip_top (\n"
           "`ifdef USE_PWR (* mark_debug = \"true\",\n"
           "   keep = \"true\" *) inout wire vdda1,\n"
           "`endif\n"
           "    input wire clk\n"
           ");\nendmodule\n")
    ports = S.parse_top_ports(rtl, "chip_top")
    assert [p["name"] for p in ports] == ["vdda1", "clk"]
    assert [p["name"] for p in ports if p["conditional"]] == ["vdda1"]


def test_an_unterminated_block_comment_keeps_the_lines_it_swallowed():
    """The unterminated branch preserves geometry too. Everything after the
    opener is comment body, so no port survives it — but the lines it spanned
    must still be there, or a directive on a LATER line fuses with the text
    before it."""
    for text in ("a\n/* x\ny\nz\n",            # unterminated block comment
                 "a\n/* x\ny */\nz\n",         # terminated, multi-line
                 "a\n(* x\ny *)\nb\n",         # attribute, multi-line
                 "a\n// x\nb\n"):               # line comment keeps its own
        for strip in (S._strip_hdl_comments, S._strip_hdl_attributes):
            assert strip(text).count("\n") == text.count("\n"), (
                f"{strip.__name__} changed the line count of {text!r}")


# --------------------------------------------------------------------------- #
# `always @(*)` is not an attribute, and the guard that says so was untested
# --------------------------------------------------------------------------- #
# Found by mutation: deleting the `!= "(*)"` guard from `_strip_hdl_attributes`
# left all 31 tests green. It is not defensive decoration.
#
# An implicit sensitivity list `always @(*)` CONTAINS the attribute opener
# `(*`. Without the guard the stripper looks for the next `*)` — which is not
# the `)` two characters along, because the search starts past it — and finds
# the closer of some LATER construct, deleting everything in between.
#
# MEASURED on a file whose first module carries `always @(*)` and whose second
# is the top: the whole intervening region goes, `parse_top_ports` finds no
# port list, and the program returns None -> rc 2 UNDECIDED. That is the
# DISCLOSED-SKIP tier, so the gate does not go red — it quietly stops asking
# the question, on a shape that is ordinary Verilog.

_RTL_IMPLICIT_SENSITIVITY = """
module helper (input wire a, output reg b);
  always @(*) b = a;
endmodule

module chip_top (
    input  wire clk,
    output wire done,
    inout  wire [7:0] io
);
  always @(*) done = clk;
endmodule
"""


def test_an_implicit_sensitivity_list_is_not_read_as_an_attribute():
    ports = S.parse_top_ports(_RTL_IMPLICIT_SENSITIVITY, "chip_top")
    assert ports is not None, (
        "the port list was swallowed: `always @(*)` was read as an attribute "
        "opener and the stripper ran to some later `*)`")
    assert [p["name"] for p in ports] == ["clk", "done", "io"]


def test_that_failure_would_have_been_a_SILENT_SKIP_not_a_red_gate():
    """Why the case above is worth a test of its own: losing the port list
    does not fail the gate, it makes it UNDECIDED — the tier that reads as a
    disclosed skip. A gate that stops asking is worse than one that answers
    wrongly, because nothing looks broken."""
    ports = S.parse_top_ports(_RTL_IMPLICIT_SENSITIVITY, "chip_top")
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert rep["rc"] in (0, 1) and rep["verdict"] != "UNDECIDED"


# --------------------------------------------------------------------------- #
# what sits AFTER the port name — unpacked arrays and initialisers
# --------------------------------------------------------------------------- #
# Found by sweeping the PUBLISHED corpus: 174 of 31,873 real ports came back
# named `1'b0`, `64'd0` or `[PMPNumRegions]`. Both causes sit after the name,
# where a last-token read finds them instead of it.
#
# The unpacked case moves a NUMBER, and it moves it the dangerous way:
# `input logic [33:0] csr_pmp_addr_i [PMPNumRegions]` is 4 x 34 bits and the
# packed range alone reports 34. A smaller interface than the design has is how
# a design that cannot be bonded out reads as FITS.
#
# `ibex` is one of the five ICs in this program's own docstring table, so this
# was mis-measuring a design the file cites as evidence.

_RTL_UNPACKED = """
module chip_top #(parameter int unsigned NREG = 4) (
    input  logic          clk,
    input  logic [33:0]   addr_i [NREG],
    output reg            done = 1'b0,
    output reg   [63:0]   order = 64'd0
);
endmodule
"""


def test_an_unpacked_array_port_is_named_by_its_NAME_not_its_dimension():
    ports = S.parse_top_ports(_RTL_UNPACKED, "chip_top", {"NREG": 4})
    assert [p["name"] for p in ports] == ["clk", "addr_i", "done", "order"]


def test_an_unpacked_array_multiplies_the_bit_count():
    ports = S.parse_top_ports(_RTL_UNPACKED, "chip_top", {"NREG": 4})
    w = {p["name"]: p["width"] for p in ports}
    assert w["addr_i"] == 34 * 4, "the packed range alone was reported"
    assert w["order"] == 64 and w["done"] == 1


def test_an_unresolvable_array_length_is_UNDECIDED_never_a_guess():
    """Same rule the packed range already follows: a length nobody supplied is
    not a pad count this program may invent. None reaches the verdict as
    UNDECIDED, which REFUSES rather than passes."""
    ports = S.parse_top_ports(_RTL_UNPACKED, "chip_top")      # no params
    w = {p["name"]: p["width"] for p in ports}
    assert w["addr_i"] is None
    rep = S.evaluate({"slot_1x1": _slot_ingested()}, ports)
    assert rep["verdict"] == "UNDECIDED" and rep["rc"] == 2
    assert "addr_i" in rep["unresolved_width_ports"]


def test_a_port_initialiser_is_not_mistaken_for_the_port_name():
    ports = S.parse_top_ports(_RTL_UNPACKED, "chip_top", {"NREG": 4})
    names = [p["name"] for p in ports]
    assert "1'b0" not in names and "64'd0" not in names


def test_a_PACKED_range_is_not_read_as_an_unpacked_dimension():
    """The regression guard: a packed range sits BEFORE the name, so nothing
    trailing may be stripped. If this broke, every ordinary bus would lose its
    width."""
    rtl = ("module chip_top (input wire [7:0] bus, output wire done);\n"
           "endmodule\n")
    ports = S.parse_top_ports(rtl, "chip_top")
    assert [(p["name"], p["width"]) for p in ports] == [("bus", 8), ("done", 1)]


def test_multiple_unpacked_dimensions_multiply_together():
    rtl = ("module chip_top (input wire [7:0] mem [2][3], output wire d);\n"
           "endmodule\n")
    w = {p["name"]: p["width"] for p in S.parse_top_ports(rtl, "chip_top")}
    assert w["mem"] == 8 * 2 * 3 and w["d"] == 1


def test_the_undercount_would_have_been_a_FALSE_FITS():
    """Why this is worth a test and not just a tidier name: the whole point of
    the program is refusing a design that cannot be bonded out, and an
    under-counted array is how one slips through."""
    ports = S.parse_top_ports(_RTL_UNPACKED, "chip_top", {"NREG": 4})
    bits = S.interface_budget(ports)["signal_bits"]
    assert bits == 34 * 4 + 64 + 1        # clk rides a dedicated pad


# --------------------------------------------------------------------------- #
# a packed range with no whitespace around it  (the third and fourth shapes)
# --------------------------------------------------------------------------- #
# `output reg [3:0]one` and `input wire[7:0]bus` are both legal: whitespace
# around a packed range is optional. The range then arrives glued to the
# identifier as ONE token, so a last-token read returns `[3:0]one` as the name.
#
# The WIDTH is unaffected — the range reader searches rather than tokenising —
# so this is a name-only defect. It still matters: the clk/rst exclusion and
# the fold-candidate match both key on the NAME, so a glued clock would be
# counted against the signal budget instead of riding its dedicated pad.
#
# Four real ports in the published corpus carried it. Measured after the fix:
# malformed names 174 -> 0, and zero widths moved.

def test_a_packed_range_glued_to_the_name_still_yields_the_name():
    """Verbatim shape from the corpus."""
    rtl = ("module Binary2BCD(input [7:0] num, output reg [3:0]thousand,\n"
           "  output reg [3:0]hundred, output reg [3:0]ten, output reg [3:0]one);\n"
           "endmodule\n")
    ports = S.parse_top_ports(rtl, "Binary2BCD")
    assert [p["name"] for p in ports] == ["num", "thousand", "hundred", "ten", "one"]
    assert all(p["width"] == 4 for p in ports if p["name"] != "num")


def test_a_type_glued_to_the_range_too_still_yields_the_name():
    rtl = "module chip_top(input wire[7:0]bus, output wire done);\nendmodule\n"
    assert [(p["name"], p["width"]) for p in S.parse_top_ports(rtl, "chip_top")] \
        == [("bus", 8), ("done", 1)]


def test_a_glued_clock_still_rides_its_dedicated_pad():
    """The reason a name-only defect is not cosmetic: `_CLK_RST_RE` matches on
    the NAME, so a mis-named clock is charged to the signal budget."""
    rtl = "module chip_top(input wire[0:0]clk_i, output wire done);\nendmodule\n"
    b = S.interface_budget(S.parse_top_ports(rtl, "chip_top"))
    assert b["on_dedicated_pads"] == ["clk_i"]
    assert b["signal_bits"] == 1          # `done` only


def test_ordinary_spacing_and_qualified_types_are_untouched():
    """The regression guard for the glued-name rule: it must fire only when a
    bracket group actually precedes the identifier."""
    rtl = ("module chip_top(input wire [7:0] bus, input pkg::cfg_t c,\n"
           "  output wire done);\nendmodule\n")
    assert [(p["name"], p["width"]) for p in S.parse_top_ports(rtl, "chip_top")] \
        == [("bus", 8), ("c", 1), ("done", 1)]
