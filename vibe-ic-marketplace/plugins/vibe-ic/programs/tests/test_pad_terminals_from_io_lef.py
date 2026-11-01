import os
from pathlib import Path

import pytest

import test_pad_ring as T

GEN, PR = T.GEN, T.PR
OUTWARD = (5.0, 0.0, 70.0, 3.0)
INTERIOR = (5.0, 40.0, 70.0, 120.0)


def _library(root, pins):
    path = root / "pdk/proc/libs.ref/proc_io/lef/io.lef"
    path.write_text(T._io_lef_with_terminal(pins))
    return path


def _explicit(root, mapping):
    path = root / "pdk/proc/libs.tech/someflow/proc_io/config.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('set ::env(PAD_PLACE_IO_TERMINALS) "' + " ".join(
        f"{master}/{pin}" for master, pin in mapping.items()) + '"\n')


def _moves(root):
    return T._report(root)["bterms"]["terminal_moves"]


def _assert_refused(root, rule, *names):
    assert T._gen(root) == 1
    report = T._report(root)
    assert report["verdict"] == "FAIL"
    findings = [f for f in report["findings"] if f["rule"] == rule]
    assert findings and all(f["severity"] == "ERROR" for f in findings)
    for name in names:
        assert name in " ".join(f["message"] for f in findings)
    assert not T._ring_def(root).exists()


def test_empty_map_places_bterms_on_only_outward_pin_rectangles(tmp_path):
    root = T._project(tmp_path)
    source = _library(root, [
        ("bond", [("edge_metal", OUTWARD), ("rail_metal", INTERIOR)]),
        ("core", [("core_metal", (20.0, 330.0, 30.0, 350.0))]),
    ])
    assert T._gen(root) == 0
    assert T._report(root)["bterms"]["kept_at_the_die_edge"] == []
    moves = _moves(root)
    assert len(moves) == 16
    by_instance = {p["instance"]: p for p in T._report(root)["pads"]}
    for move in moves:
        pad = by_instance[move["instance"]]
        assert move["terminal"] == "bond"
        assert move["layer"] == "edge_metal"
        oriented = PR.orient_rect(OUTWARD, pad["orient"], (75.0, 350.0))
        assert move["rect_dbu"] == [
            pad["x"] + round(oriented[0] * T.UNITS),
            pad["y"] + round(oriented[1] * T.UNITS),
            pad["x"] + round(oriented[2] * T.UNITS),
            pad["y"] + round(oriented[3] * T.UNITS),
        ]
        provenance = move["terminal_provenance"]
        assert provenance["basis"] == "unique_outward_lef_pin"
        assert provenance["master"] == "pad_bidir"
        assert provenance["pin"] == "bond"
        assert provenance["source_paths"] == [str(source)]
        assert provenance["layer"] == "edge_metal"
        assert provenance["rect_um"] == list(OUTWARD)
    assert T._bterm_port_rect(root, "ssig0") == (
        "+ PORT + LAYER edge_metal ( 5000 0 ) ( 70000 3000 )")


def test_empty_map_refuses_two_outward_pins(tmp_path):
    root = T._project(tmp_path)
    _library(root, [("first", [("metal", OUTWARD)]),
                    ("second", [("metal", (10.0, 0.0, 30.0, 2.0))])])
    _assert_refused(root, "PAD_TERMINAL_PIN_AMBIGUOUS", "pad_bidir",
                    "first", "second")


@pytest.mark.parametrize("pins", [[], [
    ("buried", [("metal", INTERIOR)]),
    ("overhang", [("metal", (-1.0, 0.0, 20.0, 3.0))]),
    ("zero", [("metal", (5.0, 0.0, 5.0, 3.0))]),
]])
def test_empty_map_refuses_no_valid_outward_terminal(tmp_path, pins):
    root = T._project(tmp_path)
    _library(root, pins)
    _assert_refused(root, "PAD_TERMINAL_PIN_UNDECLARED", "pad_bidir")


def test_explicit_terminal_keeps_existing_largest_rectangle_choice(tmp_path):
    root = T._project(tmp_path)
    _library(root, [("bond", [("edge", OUTWARD)]),
                    ("chosen", [("interior", INTERIOR)])])
    _explicit(root, {"pad_bidir": "chosen"})
    assert T._gen(root) == 0
    assert T._bterm_port_rect(root, "ssig0") == (
        "+ PORT + LAYER interior ( 5000 40000 ) ( 70000 120000 )")
    assert "terminal_moves" not in T._report(root)["bterms"]


def test_nonempty_map_does_not_infer_unlisted_used_master(tmp_path):
    root = T._project(tmp_path)
    _library(root, [("bond", [("edge", OUTWARD)])])
    _explicit(root, {"another_master": "its_pin"})
    assert T._gen(root) == 0
    report = T._report(root)
    assert report["bterms"]["placed_on_pad_terminal"] == []
    assert report["bterms"]["kept_at_the_die_edge"] == sorted(T.ALL_SIGNALS)
    assert "terminal_moves" not in report["bterms"]


def test_empty_map_refuses_conflicting_used_master_lefs(tmp_path):
    root = T._project(tmp_path)
    first = _library(root, [("bond", [("edge", OUTWARD)])])
    second = first.with_name("second.lef")
    second.write_text(T._io_lef_with_terminal([
        ("bond", [("edge", (10.0, 0.0, 60.0, 2.0))])]))
    _assert_refused(root, "PAD_TERMINAL_PIN_AMBIGUOUS", "pad_bidir",
                    str(first), str(second))


def test_real_io_lef_maps_all_signal_and_supply_masters(tmp_path):
    source = os.environ.get("VIBEIC_PAD_TERMINAL_LEF")
    if not source:
        pytest.skip("set VIBEIC_PAD_TERMINAL_LEF to the real IO LEF")
    source = Path(source)
    expected = {
        "sg13g2_IOPadIn": "pad", "sg13g2_IOPadOut4mA": "pad",
        "sg13g2_IOPadOut16mA": "pad", "sg13g2_IOPadOut30mA": "pad",
        "sg13g2_IOPadTriOut4mA": "pad", "sg13g2_IOPadTriOut16mA": "pad",
        "sg13g2_IOPadTriOut30mA": "pad", "sg13g2_IOPadInOut4mA": "pad",
        "sg13g2_IOPadInOut16mA": "pad", "sg13g2_IOPadInOut30mA": "pad",
        "sg13g2_IOPadAnalog": "pad", "sg13g2_IOPadIOVss": "iovss",
        "sg13g2_IOPadIOVdd": "iovdd", "sg13g2_IOPadVss": "vss",
        "sg13g2_IOPadVdd": "vdd",
    }
    masters = list(expected) + ["sg13g2_IOPadIOVdd"]
    floorplan = T._floorplan()
    for signal, master in zip(T.ALL_SIGNALS, masters):
        floorplan = floorplan.replace(
            f"- {T.PADS[signal]} pad_bidir ", f"- {T.PADS[signal]} {master} ")
    root = T._project(tmp_path, floorplan=floorplan,
                      config=T._config(PAD_FILLERS=["pad_fill1"]),
                      corner_w=180.0)
    support = root / "pdk/proc/libs.ref/proc_io/lef/io.lef"
    support.write_text(support.read_text().replace("350", "180"))
    assert T._gen(root, "--io-lef", str(support),
                  "--io-lef", str(source)) == 0
    assert T._report(root)["bterms"]["kept_at_the_die_edge"] == []
    moves = _moves(root)
    assert {move["master"] for move in moves} == set(expected)
    by_instance = {p["instance"]: p for p in T._report(root)["pads"]}
    for move in moves:
        assert move["terminal"] == expected[move["master"]]
        assert move["layer"] == "TopMetal2"
        provenance = move["terminal_provenance"]
        assert provenance["source_paths"] == [str(source)]
        assert provenance["rect_um"] == [5.0, 0.0, 75.0, 3.0]
        pad = by_instance[move["instance"]]
        oriented = PR.orient_rect((5.0, 0.0, 75.0, 3.0), pad["orient"],
                                   (80.0, 180.0))
        assert move["rect_dbu"] == [
            pad["x"] + round(oriented[0] * T.UNITS),
            pad["y"] + round(oriented[1] * T.UNITS),
            pad["x"] + round(oriented[2] * T.UNITS),
            pad["y"] + round(oriented[3] * T.UNITS),
        ]


def test_no_pad_population_is_named_not_applicable(tmp_path):
    config = T._config(**{T.PR.SIDE_VAR[side]: [] for side in T.PR.SIDES},
                       SIGNAL_MAP={})
    root = T._project(tmp_path, config=config,
                      floorplan=T._floorplan(pins=[], instances=[]))
    assert T._gen(root) == 0
    report = T._report(root)
    assert report["verdict"] == "NOT_APPLICABLE"
    assert "PAD_RING_NOT_APPLICABLE" in T._rules(root)
    assert report["pads"] == [] and report["padring_def"] is None
    assert not T._ring_def(root).exists()


@pytest.mark.parametrize("source_pads,source_ports", [(True, False), (False, True)])
def test_an_incomplete_pad_assignment_is_not_an_empty_design(tmp_path, source_pads, source_ports):
    config = T._config(**{T.PR.SIDE_VAR[side]: [] for side in T.PR.SIDES},
                       SIGNAL_MAP={})
    root = T._project(tmp_path, config=config, floorplan=T._floorplan(
        pins=T.ALL_SIGNALS if source_ports else [],
        instances=list(T.PADS.values()) if source_pads else []))
    assert T._gen(root) == 1
    assert T._report(root)["verdict"] == "FAIL"
    assert "PAD_RING_NOT_APPLICABLE" not in T._rules(root)
    assert not T._ring_def(root).exists()
