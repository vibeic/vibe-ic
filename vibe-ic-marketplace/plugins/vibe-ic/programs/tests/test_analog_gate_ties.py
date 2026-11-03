"""Antenna ties on nets without diffusion."""
import pytest

import analog_gate_ties as ties

ROW = {"name": "antenna_tie", "net": "nref", "w_um": 4.0, "l_um": 1.0}


def _ir():
    return {"rails": {"vdd": "vdd", "vss": "vss"},
            "devices": [{"name": "m", "role": "nmos", "nets": ["x", "nref", "vss", "vss"]}]}


def test_no_row_means_no_tie():
    assert ties.declared({"specs": [{"name": "order", "target": 3}]}) == []
    ir = _ir()
    assert ties.apply(ir, []) is ir


@pytest.mark.parametrize("rows", [
    [{**ROW, "w_um": -1}], [{**ROW, "l_um": True}], [{**ROW, "net": ""}], [ROW, ROW],
])
def test_a_bad_row_is_refused(rows):
    with pytest.raises(ties.TieRefused):
        ties.declared({"specs": rows})


def test_the_tie_is_an_off_device_with_its_drain_on_the_net():
    ir = ties.apply(_ir(), ties.declared({"specs": [ROW]}))
    tie = next(d for d in ir["devices"] if d["name"] == "mn_tie_nref")
    assert tie["nets"] == ["nref", "vss", "vss", "vss"] and (tie["w"], tie["l"]) == (4.0, 1.0)


def test_a_net_not_in_the_block_is_refused():
    with pytest.raises(ties.TieRefused):
        ties.apply(_ir(), [("other", 4.0, 1.0)])
