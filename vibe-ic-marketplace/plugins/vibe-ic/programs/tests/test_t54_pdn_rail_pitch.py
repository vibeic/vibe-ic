"""A measured hot fixed cell rail must change the perpendicular strap plan."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _ppa import power as P  # noqa: E402




def test_ring_current_that_cannot_fit_gap_is_named_refusal():
    def_text = ("UNITS DISTANCE MICRONS 1000 ;\nSPECIALNETS 1 ;\n"
                "- SUP + ROUTED M4 1600 + SHAPE RING "
                "( 10000 0 ) ( 10000 20000 ) ;\n"
                "END SPECIALNETS\n")
    segments = [{"layer0": "M4", "layer1": "M4",
                 "current_A": 0.01136,
                 "points_um": ((10, 5), (10, 8))}]
    peaks = P.pdn_ring_segment_peaks(def_text, segments)
    cfg = {"layers": ["M4", "M5"], "widths": [1.6, 1.6],
           "spacings": [1.7, 1.7], "connect_to_pad_layers": ["M2"],
           "connects": [["M2", "M4"]], "core_offset_um": 6,
           "min_clearance_um": 0.46}
    plan = P.pdn_ring_capacity_plan(
        cfg, gap_um=17.44, peaks_A=peaks,
        jmax_A_per_um={"m4": 0.00067, "m5": 0.0015},
        margin=0.1, grid_um=0.005)
    assert peaks == {"m4": 0.01136}
    assert plan["code"] == "PDN_EM_RING_CAPACITY_UNREACHABLE"
    assert plan["required_widths_um"][0] > 18.83
    assert plan["required_footprint_um"] > plan["available_footprint_um"]




def test_pad_entry_current_needs_measured_width_not_recipe_assumption():
    rows = P.pdn_pad_entry_plan(
        [{"layer0": "M2", "layer1": "M2", "current_A": 0.01704}],
        pad_layers=["M2"], drawn_widths_um={"m2": 9.45},
        jmax_A_per_um={"m2": 0.00067}, margin=0.1, grid_um=0.005)
    assert rows[0]["status"] == "CAPACITY_NOT_PROVEN"
    assert rows[0]["required_width_um"] == 28.26
