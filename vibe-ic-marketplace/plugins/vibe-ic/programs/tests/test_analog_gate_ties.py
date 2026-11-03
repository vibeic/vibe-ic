"""Tie devices for gates on a rail."""
import pytest

import analog_gate_ties as ties


def _ir(*devices):
    return {"rails": {"vdd": "vdd", "vss": "vss"}, "internal_nets": ["x"], "devices": list(devices)}


def _mos(name, gate, role="nmos"):
    return {"name": name, "role": role, "nets": ["x", gate, "vss", "vss"]}


def test_no_declaration_means_no_tie():
    assert ties.declared_size({"specs": [{"name": "order", "target": 3}]}) is None


@pytest.mark.parametrize("rows", [
    [{"name": "gate_tie_w_um", "target": 1.0}],
    [{"name": "gate_tie_w_um", "target": -1}, {"name": "gate_tie_l_um", "target": 1}],
    [{"name": "gate_tie_w_um", "target": True}, {"name": "gate_tie_l_um", "target": 1}],
    [{"name": "gate_tie_w_um", "target": 1}, {"name": "gate_tie_w_um", "target": 2},
     {"name": "gate_tie_l_um", "target": 1}],
])
def test_a_bad_declaration_is_refused(rows):
    with pytest.raises(ties.TieRefused):
        ties.declared_size({"specs": rows})


def test_no_gate_stays_on_a_rail_including_the_ties_own():
    ir = ties.apply(_ir(_mos("a", "vdd"), _mos("b", "vss"), _mos("c", "x")), 1.0, .5)
    mos = [d for d in ir["devices"] if d["role"] in ("nmos", "pmos")]
    assert not [d["name"] for d in mos if d["nets"][1] in ("vdd", "vss")]
    assert {"ntie_hi", "ntie_hi_bias", "ntie_lo", "ntie_lo_bias"} <= set(ir["internal_nets"])
    assert next(d for d in mos if d["name"] == "c")["nets"][1] == "x"


def test_the_high_tie_is_a_diode_biasing_a_pmos_from_the_rail():
    ir = ties.apply(_ir(_mos("a", "vdd")), 1.0, .5)
    by_name = {d["name"]: d for d in ir["devices"]}
    assert by_name["a"]["nets"][1] == "ntie_hi"
    assert by_name["mn_tie_hi_bias"]["nets"] == ["ntie_hi_bias", "ntie_hi_bias", "vss", "vss"]
    assert by_name["mp_tie_hi"]["nets"] == ["ntie_hi", "ntie_hi_bias", "vdd", "vdd"]
    assert "mn_tie_lo" not in by_name


def test_a_block_with_no_rail_gate_is_unchanged():
    ir = _ir(_mos("c", "x"))
    assert ties.apply(ir, 1.0, .5) is ir
