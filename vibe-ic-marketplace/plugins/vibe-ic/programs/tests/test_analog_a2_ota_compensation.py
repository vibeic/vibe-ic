"""Explicit compensation sizing reaches A3 without changing noise/loop ratios."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3

SPEC = {"order": 2.0, "osr": 64.0, "enob": 10.0, "vref": 1.0,
        "vdd": 1.2, "vindiff": 1.0, "fclk": 1.0, "fclk_max": 1.0}
MEASURED = {"cap_area_ff_per_um2": 1.5, "cap_perim_ff_per_um": 0.04,
            "rsheet_ohm_per_sq": 260.0, "k_prime_n_ua_per_v2": 328.0,
            "vth_n_extracted_v": 0.197}


def _ir(project, lib=None, scale=None):
    if scale is not None:
        path = project / "phase3/analog/converter/sizing_inputs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"knobs": {"ota_compensation_scale": scale}}))
    return a2.build_ir("converter", "delta_sigma", {"name": "converter"},
        lib or a2.LIBRARY["delta_sigma"], SPEC, None, project, None, {},
        measured_params=MEASURED)


def _old_library():
    lib = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    lib["spec_knobs"] = []
    lib.pop("input_drain_cascodes", None)
    lib["loop_probe"]["follows_integrating"]["cc{i}"] = "miller_fraction_of_load"
    for group in lib["stage"]:
        group.pop("input_drain_cascodes", None)
        for row in group.get("param_exprs", []):
            for key in ("expr", "ff_expr"):
                if key in row:
                    row[key] = row[key].replace(" * ota_compensation_scale", "")
    return lib


def test_default_one_preserves_all_existing_device_values(tmp_path):
    old = _ir(tmp_path / "old", _old_library())
    default = _ir(tmp_path / "new")
    assert default["knobs"]["ota_compensation_scale"] == 1
    assert default["knob_sources"]["ota_compensation_scale"] == "library_default"
    assert a3._resolve_params(default, SPEC)[0] == a3._resolve_params(old, SPEC)[0]


def test_explicit_scale_changes_only_miller_capacitances(tmp_path):
    old, sized = _ir(tmp_path / "old"), _ir(tmp_path / "new", scale=3)
    before, after = a3._resolve_params(old, SPEC)[0], a3._resolve_params(sized, SPEC)[0]
    assert {name for name in after if after[name] != before.get(name)} == {"cc1", "cc2"}
    for name in ("cc1", "cc2"):
        before_ff = a2._safe_eval(next(e["ff_expr"] for e in old["device_param_exprs"] if e["device"] == name),
                                 a3._resolve_params(old, SPEC)[3])
        after_ff = a2._safe_eval(next(e["ff_expr"] for e in sized["device_param_exprs"] if e["device"] == name),
                                a3._resolve_params(sized, SPEC)[3])
        assert after_ff == pytest.approx(3 * before_ff)
    assert sized["knob_sources"]["ota_compensation_scale"] == "explicit_design_sizing"
    assert "ota_compensation_scale" not in sized["_provenance"]["fields_defaulted"]


@pytest.mark.parametrize("scale", [0, -1, "large", True])
def test_invalid_compensation_cannot_reach_a3(tmp_path, scale):
    with pytest.raises(a2.SizingInputsInvalid, match="finite positive"):
        _ir(tmp_path, scale=scale)
