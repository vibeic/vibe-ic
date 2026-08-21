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
