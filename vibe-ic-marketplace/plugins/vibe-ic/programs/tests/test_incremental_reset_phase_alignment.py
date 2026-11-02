"""Incremental reset must qualify physical charge paths and stored decisions."""
import itertools
import re

import pytest

from test_declared_load_bias_branches import _emit


def devices(ir):
    return {d["name"]: d for d in ir["devices"]}


def fanin(rows, node, visited=None):
    visited = set() if visited is None else visited
    if node in visited or node in {"vdd", "vss"}:
        return visited
    visited.add(node)
    for d in rows.values():
        if d.get("role") not in {"nmos", "pmos"}:
            continue
        drain, gate, source, _ = d["nets"]
        if node in {drain, source}:
            for other in (gate, source if drain == node else drain):
                fanin(rows, other, visited)
    return visited


def logic(rows, node, inputs, active=None):
    if node in inputs:
        return int(inputs[node])
    if node in {"vdd", "vss"}:
        return int(node == "vdd")
    active = set() if active is None else active
    if node in active:
        return None
    active = active | {node}
    driven = set()
    for d in rows.values():
        if d.get("role") not in {"nmos", "pmos"} or d["nets"][0] != node:
            continue
        gate = logic(rows, d["nets"][1], inputs, active)
        if gate is None or gate != int(d["role"] == "nmos"):
            continue
        value = logic(rows, d["nets"][2], inputs, active)
        if value is not None:
            driven.add(value)
    assert len(driven) <= 1, (node, "conflicting CMOS rail paths", driven)
    return next(iter(driven)) if driven else None


def transfer_pairs(ir):
    rows = devices(ir)
    plates = {n for d in rows.values() if d.get("role") == "cap"
              and re.fullmatch(r"(?:cs|cf|czero)\d+(?:_u\d+)?", d["name"])
              for n in d["nets"]}
    result = []
    for d in rows.values():
        if d.get("role") != "nmos":
            continue
        ends = {d["nets"][0], d["nets"][2]}
        if not ends & plates or not any(re.fullmatch(r"vsum\d+", n) for n in ends):
            continue
        p = rows["mp_" + d["name"][3:]]
        assert {p["nets"][0], p["nets"][2]} == ends
        result.append((d, p))
    return result


def assert_qualified(ir, extra=()):
    rows = devices(ir)
    pairs = transfer_pairs(ir) + list(extra)
    assert pairs, "No physical SC transfer paths were inspected"
    for n, _ in pairs:
        assert fanin(rows, n["nets"][1]) & {"nall", "nrstb"}, (
            n["name"], "physical transfer is independent of conversion reset")
    control = ir.get("incremental_startup")
    assert control, "Physical conversion-control record is absent"
    valid = control["decision_valid_net"]
    ready = control["transfer_ready_net"]
    for n, p in pairs:
        assert valid in fanin(rows, n["nets"][1]), (n["name"], "no fresh-decision eligibility")
        for reset, accepted in ((1, 1), (1, 0), (0, 0), (0, 1)):
            known = {"nall": reset, "nrstb": 1-reset, valid: accepted, ready: accepted,
                     "clk": 0, "nclkb": 1, "nph1": 0, "nph1b": 1,
                     "nph1d": 0, "nph1db": 1, "nph2": 1, "nph2b": 0}
            expected = int(not reset and accepted)
            assert logic(rows, n["nets"][1], known) == expected, (n["name"], known)
            assert logic(rows, p["nets"][1], known) == 1-expected, (p["name"], known)


@pytest.mark.parametrize("family,order", itertools.product(("CIFF", "CIFB"), (1, 2, 3)))
def test_every_stage_transfer_blocks_reset_and_invalid_decision(tmp_path, family, order):
    ir, *_ = _emit(tmp_path, family, order)
    assert_qualified(ir)


def test_shared_input_dac_bottom_transfer_has_the_same_qualification(tmp_path):
    ir, *_ = _emit(tmp_path, "CIFF", 3, values={"shared_input_dac": 1., "cf1_ff": 60.})
    rows = devices(ir)
    assert rows["mn_smpb1"]["nets"][2] == "ndacb"
    assert_qualified(ir, [(rows["mn_smpb1"], rows["mp_smpb1"])])


@pytest.mark.parametrize("family", ("CIFF", "CIFB"))
def test_reset_dominates_both_latch_inputs_for_every_comparator_history(tmp_path, family):
    ir, *_ = _emit(tmp_path, family, 2)
    rows = devices(ir)
    for nq_n, nq_p in itertools.product((0, 1), repeat=2):
        known = {"nall": 1, "nrstb": 0, "nq_n": nq_n, "nq_p": nq_p}
        for stem, expected in (("n1a", 1), ("n2a", 0)):
            for prefix in ("mn_", "mp_"):
                gate = rows[prefix+stem]["nets"][1]
                assert logic(rows, gate, known) == expected, (prefix+stem, known)
    assert rows["mn_obuf"]["nets"][:3] == ["bit_out", "nsrqb", "vss"]
    assert rows["mn_bbuf"]["nets"][:3] == ["nqb", "bit_out", "vss"]


@pytest.mark.parametrize("por", (0., 1.))
def test_reset_has_a_high_phase_slave_after_its_low_phase_master(tmp_path, por):
    ir, *_ = _emit(tmp_path, values={"startup_reset": por})
    rows = devices(ir)
    storage = rows["mn_rout"]["nets"][1]
    assert storage != "nrmb", "A LOW-transparent latch still releases reset at phi2"
    links = [d for d in rows.values() if d.get("role") == "nmos"
             and {d["nets"][0], d["nets"][2]} == {"nrmb", storage}]
    assert len(links) == 1
    assert links[0]["nets"][1] in {"clk", "npor_clk"}
    if por:
        control = ir["incremental_startup"]
        assert control["bootstrap_net"] in fanin(rows, "nall")
        assert any(d.get("role") == "pmos" and d["nets"][:3] ==
                   [storage, "npor_run", "vdd"] for d in rows.values())


@pytest.mark.parametrize("family", ("CIFF", "CIFB"))
def test_declared_feedback_delay_is_preserved(tmp_path, family):
    ir, *_ = _emit(tmp_path, family, 2, values={"feedback_delay": 1.})
    assert ir["loop_declaration"]["D"] == 1
    control = ir.get("incremental_startup")
    assert control and control["mode"] == 1
    assert control["decision_valid_net"] != control["transfer_ready_net"]


def test_qualification_check_rejects_one_real_unqualified_path(tmp_path):
    ir, *_ = _emit(tmp_path)
    assert_qualified(ir)
    rows = devices(ir)
    rows["mn_cstv2"]["nets"][1] = "nph2"
    with pytest.raises(AssertionError, match="independent of conversion reset|no fresh-decision eligibility"):
        assert_qualified(ir)


@pytest.mark.parametrize("family", ("CIFF", "CIFB"))
def test_reset_clears_valid_and_ready_for_both_clock_levels(tmp_path, family):
    ir, *_ = _emit(tmp_path, family, 2)
    rows = devices(ir)
    control = ir.get("incremental_startup")
    assert control, "No physical fresh-window storage is emitted"
    for phase, nq_n, nq_p in itertools.product((0, 1), repeat=3):
        known = {"nall": 1, "nrstb": 0, "clk": phase, "nclkb": 1-phase,
                 "nph1": phase, "nph1b": 1-phase, "nph2": 1-phase,
                 "nph2b": phase, "nq_n": nq_n, "nq_p": nq_p}
        for key in ("decision_valid_net", "transfer_ready_net"):
            assert logic(rows, control[key], known) == 0, (key, known)


def test_chopped_first_stage_is_not_lost_by_virtual_node_discovery(tmp_path):
    from test_analog_ota1_options import _case
    _, ir = _case(tmp_path, 1, 1, phase=1, ratio=2, stages=3, remove_cc=1)
    assert any(n["name"] == "mn_cstv1" for n, _ in transfer_pairs(ir))
    assert_qualified(ir)
