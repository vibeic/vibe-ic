"""F23 -- the LibreLane 15..18 seam: the pad ring and the pad-control ties.

With steps 15, 15.5ic and 17 on LibreLane (T97) the routing session loads the
tool's placed DEF (`librelane_contract.placement_consumer_tcl`), and the
combined chain LL15 -> LL17+18 -> LL19/20 -> direct tail ended rc=1 on two
defects, both measured on spm x gf180mcuD (vibeic-eda 0.3.79):

1. `pad_ring_route_evidence` -> PADRING_CONSUMER_MISSING. The gate looked for
   the direct deck's `read_def -floorplan_initialize` marker, which the seam
   removes, although the ring IS in the consumed DEF (731/731 ring instances
   unmoved, 148/148 ring pins connected, 36/36 port-to-pad connections).
   The gate now judges that evidence on the LibreLane path.
2. post-layout LEC: `u_pad_clk/PD` on a net named `net` from placed.def on.
   LibreLane's RepairDesignPostGPL runs `repair_tie_fanout`, which replaced all
   76 declared `_vibeic_aux_tie_*` ties. The contract now declares them in
   RSZ_DONT_TOUCH_LIST (measured: the same call then inserts 0 ties).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import librelane_contract as contract  # noqa: E402
import phase3_one_shot_runner as p3  # noqa: E402


def put(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


# --------------------------------------------------------------------------
# defect 2: the declared pad-control ties survive LibreLane's repair_tie_fanout
# --------------------------------------------------------------------------

def _design(tmp_path: Path, chip_top_record: dict | None) -> Path:
    p = tmp_path / "design"
    put(p / "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{"role": "primary", "pdk_scoped_target": "processA",
                           "period_ns": 12, "source_pin": "clk"}]})
    put(p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {"top_module": "block"})
    put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {"fields": {"pdk_target": "processA"}})
    put(p / "input/submission_template/tapeout_declaration.json", {"answers": {
        "top_cell": "chip_top", "die_area_um": [0, 0, 100, 100],
        "core_area_um": [10, 10, 90, 90]}})
    if chip_top_record is not None:
        put(p / "reports/phase3/io_pad_chip_top.json", chip_top_record)
    return p


_AUX = [
    {"instance": "u_pad_a", "pin": "PD", "net": "_aux_tie_0",
     "tie_instance": "_aux_tie_cell_0", "tie_master": "TIELO", "tie_pin": "ZN"},
    {"instance": "u_pad_a", "pin": "PU", "net": "_aux_tie_1",
     "tie_instance": "_aux_tie_cell_1", "tie_master": "TIELO", "tie_pin": "ZN"},
]


def test_declared_pad_control_ties_reach_rsz_dont_touch_list(tmp_path):
    p = _design(tmp_path, {"verdict": "WROTE", "aux_pin_signal_connections": _AUX})
    out = p / "phase3/librelane/config.json"
    result = contract.emit_config(p, "processA", out)
    assert result["RSZ_DONT_TOUCH_LIST"] == [
        "_aux_tie_cell_0", "_aux_tie_0", "_aux_tie_cell_1", "_aux_tie_1"]
    written = json.loads(out.read_text())
    assert written["RSZ_DONT_TOUCH_LIST"] == result["RSZ_DONT_TOUCH_LIST"]
    provenance = json.loads(out.with_suffix(".provenance.json").read_text())
    assert "io_pad_chip_top.json.aux_pin_signal_connections" in provenance[
        "RSZ_DONT_TOUCH_LIST"]


@pytest.mark.parametrize("record", [None, {"verdict": "WROTE"},
                                    {"aux_pin_signal_connections": []}])
def test_no_declared_tie_means_no_dont_touch_list(tmp_path, record):
    p = _design(tmp_path, record)
    result = contract.emit_config(p, "processA", p / "phase3/librelane/config.json")
    assert "RSZ_DONT_TOUCH_LIST" not in result


def test_pad_local_tie_protects_its_net_without_freezing_the_entire_pad(tmp_path):
    rows = _AUX + [{"instance": "u_pad_q", "pin": "ENABLE_H",
                    "net": "_local_tie_hi", "tie_instance": "u_pad_q",
                    "tie_master": "GPIO", "tie_pin": "TIE_HI_ESD"}]
    p = _design(tmp_path, {"verdict": "WROTE", "aux_pin_signal_connections": rows})
    result = contract.emit_config(p, "processA", p / "phase3/librelane/config.json")
    protected = result["RSZ_DONT_TOUCH_LIST"]
    assert "_local_tie_hi" in protected
    assert "u_pad_q" not in protected
    assert all(row[key] in protected for row in _AUX
               for key in ("tie_instance", "net"))


@pytest.mark.parametrize("rows", [
    "not-a-list",
    [{"instance": "u_pad_a", "pin": "PD", "net": "_aux_tie_0"}],
    [{"instance": "u_pad_a", "pin": "PD", "net": "", "tie_instance": "t"}],
], ids=["not-a-list", "no-tie-instance", "empty-net"])
def test_an_unreadable_tie_record_is_refused_not_skipped(tmp_path, rows):
    p = _design(tmp_path, {"aux_pin_signal_connections": rows})
    with pytest.raises(contract.Refusal) as exc:
        contract.emit_config(p, "processA", p / "phase3/librelane/config.json")
    assert exc.value.code == "LL_AUX_TIE_RECORD_INVALID"


# --------------------------------------------------------------------------
# defect 1: the pad-ring gate judges the ring in the DEF the route consumed
# --------------------------------------------------------------------------

_RING = "IO_PAD_A"
_CORNER = "IO_CORNER"
_CELL = "STD_CELL_A"


def _def(*, pad_xy=(0, 50000), pad_net="clk", core_net="clk__core",
         pd_net="_aux_tie_0", pad_driver="( PIN clk )", extra_nets=()) -> str:
    """A chip-top DEF shaped as OpenROAD writes it after LibreLane's PadRing:
    the port-to-pad net in SPECIALNETS, the core-side and tie nets in NETS."""
    nets = [f"- {core_net} ( u_pad_clk Y ) ( u_core/_1_ CLK ) + USE SIGNAL ;",
            f"- {pd_net} ( u_pad_clk PD ) ( _aux_tie_cell_0 ZN ) + USE SIGNAL ;",
            *extra_nets]
    special = [f"- {pad_net} {pad_driver} ( u_pad_clk PAD ) + USE SIGNAL ;",
               "- VDD ( PIN VDD ) ( * VDD ) + USE POWER ;"]
    return (
        "VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
        "COMPONENTS 4 ;\n"
        f"- u_pad_clk {_RING} + FIXED ( {pad_xy[0]} {pad_xy[1]} ) W ;\n"
        f"- u_corner_sw {_CORNER} + FIXED ( 0 0 ) N ;\n"
        f"- _aux_tie_cell_0 {_CELL} + PLACED ( 20000 20000 ) N ;\n"
        f"- u_core/_1_ {_CELL} + PLACED ( 30000 30000 ) N ;\n"
        "END COMPONENTS\n"
        "PINS 2 ;\n- clk + NET clk + DIRECTION INPUT + USE SIGNAL ;\n"
        "- VDD + NET VDD + SPECIAL + DIRECTION INOUT + USE POWER ;\nEND PINS\n"
        f"SPECIALNETS {len(special)} ;\n" + "\n".join(special) + "\nEND SPECIALNETS\n"
        f"NETS {len(nets)} ;\n" + "\n".join(nets) + "\nEND NETS\n"
        "END DESIGN\n")








#: A direct deck in the shape `placement_consumer_tcl` transforms (the load,
#: the resume sentinel, the region up to CTS, and the route after it).
_DIRECT_DECK = """read_lef tech.lef
read_verilog chip_top_io.v
link_design chip_top
# <<<PNR_RESUME_ELIDE_BEGIN>>>
puts "PNR_STAGE: padring_ingest"
read_def -floorplan_initialize {floorplan}
puts "PADRING_ROUTING_CONSUMED: {floorplan}"
global_placement -density 0.3
detailed_placement
puts "PNR_STAGE: cts"
clock_tree_synthesis
if {{[catch {{detailed_route -output_drc x.rpt}} dr_err]}} {{ puts $dr_err }}
"""




























def test_def_net_members_reads_port_nets_from_specialnets():
    members = p3._def_net_members(_def())
    assert members["clk"] == [("PIN", "clk"), ("u_pad_clk", "PAD")]
    assert members["VDD"] == [("PIN", "VDD")]
    assert ("u_pad_clk", "PD") in members["_aux_tie_0"]
