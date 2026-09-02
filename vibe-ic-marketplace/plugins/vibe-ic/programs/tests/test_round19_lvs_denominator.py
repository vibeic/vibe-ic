"""ROUND 19 — an LVS verdict is published with its denominators.

MEASURED (u_hawaii_adc / ihp-sg13g2, round 18's 256-device delta_sigma block):
A6 wrote

    {"result": "mismatch", "method": "klayout_lvs_runset",
     "layout_devices": null, "source_devices": null}

A `mismatch` with both counts absent cannot tell the next reader whether 256
layout devices met 256 source devices with one net wrong, or met nothing at
all. Only one of those is a design problem, and the artefact was the same
either way — which is why round 17's and round 18's A6 mismatch could not be
triaged from the evidence it left.

The cause was narrow: `_write_lvs_report` reads the counts out of the runner's
meta, and only ONE of the two LVS runners collects them. The runset runner —
whose own docstring promises "the verdict plus device counts" — returned
neither. The source side was free the whole time: it is the comparison-side
netlist that runner had just written.

These tests pin both directions: the count that IS available is reported, and
the one that is NOT is reported as absent WITH ITS REASON rather than as a
bare null.
"""
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
mod = importlib.import_module("analog_a6_native_pv")


_SRC = """\
* a block
.subckt demo vdd vss vin vout
xm1 vout vin vss vss nmos_dev w=1u l=0.15u
mp1 vout vin vdd vdd pmos_dev w=2u l=0.15u
r1 vout vss 1k
c1 vout vss 1p
* a comment is not a device
.ends demo
.subckt other a b
m9 a b 0 0 nmos_dev
.ends other
"""


def test_the_source_side_count_is_the_blocks_own_element_cards():
    assert mod.source_device_count(_SRC, "demo") == 4


def test_a_sibling_subcircuits_devices_are_not_counted_into_this_block():
    # `other` carries one device; counting it into `demo` would inflate the
    # denominator of a block it is not part of.
    assert mod.source_device_count(_SRC, "other") == 1


def test_a_block_the_netlist_does_not_declare_counts_as_ABSENT_not_zero():
    # The whole point of the fix: absent must not read as a measurement.
    assert mod.source_device_count(_SRC, "missing") is None


def test_a_block_that_really_has_no_devices_counts_zero_not_absent():
    empty = ".subckt hollow a b\n.ends hollow\n"
    assert mod.source_device_count(empty, "hollow") == 0


def test_case_does_not_change_which_subcircuit_is_counted():
    assert mod.source_device_count(_SRC.replace(".subckt demo", ".SUBCKT DEMO"),
                                   "demo") == 4


def test_the_report_carries_the_count_the_runner_supplied(tmp_path):
    mod._write_lvs_report(tmp_path, "demo", "MISMATCH",
                          {"method": "klayout_pdk_lvs",
                           "layout_devices": 255, "source_devices": 256})
    d = json.loads((tmp_path / "comp.json").read_text())
    assert d["result"] == "mismatch"
    assert (d["layout_devices"], d["source_devices"]) == (255, 256)
    # Both counts are present, so there is nothing to explain away.
    assert "counts_absent_because" not in d


def test_an_absent_count_is_published_with_its_reason(tmp_path):
    mod._write_lvs_report(tmp_path, "demo", "MISMATCH",
                          {"method": "klayout_lvs_runset",
                           "layout_devices": None, "source_devices": 256,
                           "layout_devices_absent_because": "engine has no tally"})
    d = json.loads((tmp_path / "comp.json").read_text())
    assert d["source_devices"] == 256
    assert d["layout_devices"] is None
    assert d["counts_absent_because"] == "engine has no tally"


def test_a_null_with_no_reason_is_still_a_null_and_says_so(tmp_path):
    # The negative control for the field above: a runner that supplies neither
    # the count nor a reason must not have one invented for it.
    mod._write_lvs_report(tmp_path, "demo", "MATCH", {"method": "x"})
    d = json.loads((tmp_path / "comp.json").read_text())
    assert d["layout_devices"] is None and "counts_absent_because" not in d


def test_the_gate_still_reads_the_verdict_it_always_read(tmp_path):
    # Adding fields must not move the A6 gate's own verdict, in either
    # direction.
    gate = importlib.import_module("analog_a6_block_pv_check")
    for verdict, expected in (("MATCH", True), ("MISMATCH", False)):
        b = tmp_path / verdict
        b.mkdir()
        mod._write_lvs_report(b, "demo", verdict,
                              {"method": "klayout_lvs_runset",
                               "source_devices": 256, "layout_devices": None,
                               "layout_devices_absent_because": "r"})
        assert gate._lvs_match(b)[0] is expected
