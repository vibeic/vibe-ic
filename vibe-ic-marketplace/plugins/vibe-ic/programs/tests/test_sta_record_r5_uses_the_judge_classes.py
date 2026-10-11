"""sta_record R5 blocks on std-cell DRV only; bond-pad port rows are listed.

MEASURED on the routed spm DIE (lane spmdrv run2, tree main+padin+U1 fixes):
Step 32 closed with final_drv 0, and the pre-stream gate still FAILed on
`sta_record` R5 -- `sta_spef_multicorner.rpt` and `sta_mcorner_ocv.rpt` each
"max_capacitance x73": 70 bond-pad PORT rows (2 corners x 35 inputs, the pad's
own 2.9 pF PAD pin against the std-cell 0.2 pF margin) and 3 IO-cell pins
within their IO Liberty limit. R-0928-DRV-IC / root audit U1: those are not
std-cell DRV. R5 now counts the DRV standard's classes (the same classifier as
Step 32's census), lists the rest, and keeps every other row blocking.
"""
from __future__ import annotations

import json
import sys
import pytest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import test_sta_corner_record_completeness as T  # noqa: E402
from _drv_class_fixture import write_witness

_IO_LIB = """library (io) {
  time_unit : "1ns";
  capacitive_load_unit (1, pf);
  default_max_capacitance : 999;
  default_max_fanout : 1;
  cell (PADIN) { pad_cell : true;
    pin (PAD) { max_transition : 1; direction : input; }
    pin (Y) { direction : output; } }
  cell (BUF) { pin (A) { direction : input; } pin (Z) { direction : output; } }
}
"""
_NETLIST = """module chip (a, n);
  input a;
  input n;
  PADIN u_pad_a (.PAD(a),
    .Y(a_core));
  BUF \\u_core/u1  (.A(a_core),
    .Z(z1));
  BUF u2 (.A(n),
    .Z(z2));
endmodule
"""


def _cap_table(rows):
    body = "".join(f"{pin:<40}{lim:>9} {val:>11} {float(lim) - float(val):>11.6f} (VIOLATED)\n\n"
                   for pin, lim, val in rows)
    return ("max capacitance\n\nPin" + " " * 40 + "Limit         Cap       Slack\n"
            + "-" * 72 + "\n" + body)


def _stage(tmp_path, rows, *, with_deck=True):
    run = T._run(tmp_path, "r5classes")
    T._declare(run)
    sta = run / "phase3/stage3/sta"
    host_pdk = tmp_path / "pdkcache" / "mypdk"
    T._write(host_pdk / "libs.ref/io/io.lib", _IO_LIB)
    T._write(run / "phase3/librelane_pdk_root.provenance.json", json.dumps(
        {"derivation": {"pdk": "mypdk", "host_path": str(host_pdk)}}))
    T._write(run / "phase3/stage3/pnr/chip_pnr.v", _NETLIST)
    if with_deck:
        T._write(sta / "sta_mcorner_ocv_setup.tcl",
                 "read_liberty /foss/pdks/vendor/v1/mypdk/libs.ref/io/io.lib\n"
                 f"read_verilog {run}/phase3/stage3/pnr/chip_pnr.v\n"
                 "link_design chip\n"
                 f"read_sdc {run}/phase3/stage3/pnr/signoff.sdc\n")
        T._write(run / "phase3/stage3/pnr/signoff.sdc",
                 "set_max_capacitance 0.2 [current_design]\n")
        write_witness(run, run / "phase3/stage3/pnr/chip_pnr.v",
                      run / "phase3/stage3/pnr/signoff.sdc", host_pdk / "libs.ref/io/io.lib",
                      [("a", "", "", "a", True), ("n", "", "", "n", True),
                       ("u_pad_a/PAD", "PADIN", "PAD", "a", False),
                       ("u_pad_a/Y", "PADIN", "Y", "a_core", True),
                       ("u_core/u1/A", "BUF", "A", "a_core", False),
                       ("u_core/u1/Z", "BUF", "Z", "z1", True),
                       ("u2/A", "BUF", "A", "n", False), ("u2/Z", "BUF", "Z", "z2", True)])
        # A sibling deck on another netlist (the real run's power deck reads the
        # synthesis netlist): only the deck on the report's own netlist counts.
        T._write(run / "phase2/stage2/synth/chip_synth.v", "module chip (a); endmodule\n")
        T._write(sta / "power_chip.tcl",
                 f"read_verilog {run}/phase2/stage2/synth/chip_synth.v\nlink_design chip\n")
    T._write(sta / "sta_spef_multicorner.rpt", T._multicorner(0.41, 0.08))
    T._write(sta / "sta_mcorner_ocv.rpt",
             "STA_BASIS_NETLIST: chip_pnr.v\n" + T._mcorner_ocv(2.68, 0.33)
             + _cap_table(rows))
    T._write(sta / "sta_spef_based.rpt", T._nominal(0.05))
    return run


_PORT = ("a", "0.200000", "2.989206")
_IO = ("u_pad_a/Y", "0.200000", "0.211182")
_CORE = ("u_core/u1/Z", "0.200000", "0.246000")
_PORT_INTO_CORE = ("n", "0.200000", "0.250000")


def test_port_to_pad_and_io_margin_rows_do_not_block(tmp_path):
    rc, res = T._judge(_stage(tmp_path, [_PORT, _IO]), tmp_path)
    assert "R5_DRV_VIOLATION" not in res["rules_violated"], res["reasons"]
    blob = " ".join(res["reasons"])
    assert "OFFCHIP_PORT_TO_PAD_NET max_capacitance x1" in blob, blob
    assert "IO_STD_CELL_MARGIN_DISCLOSURE max_capacitance x1" in blob, blob
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")
    assert proc["drv"]["total"] == 2          # the tool's own count, unchanged


def test_unrelated_physical_pin_preserves_the_complete_connectivity_witness(tmp_path):
    from _drv_row_class import Classifier, OFFCHIP_PORT
    from drv_signoff_judge import _sha
    run = _stage(tmp_path, [_PORT, _IO])
    source = run / 'reports/phase3/sta/drv_signoff_bundle.json'
    doc = json.loads(source.read_text())
    scene = doc['scenes'][0]
    lef = tmp_path / 'physical.lef'
    lef_body = ('MACRO physical\n CLASS PAD SPACER ;\n PIN BUS\n'
                ' DIRECTION INOUT ;\n USE SIGNAL ;\n END BUS\nEND physical\n')
    lef.write_text(lef_body)
    scene['linked_lefs'] = [{'path': str(lef), 'sha256': _sha(lef)}]
    pins, nets = (Path(scene[key]['path']) for key in ('pin_census_report', 'net_census_report'))
    with pins.open('a') as stream:
        stream.write('spacer/BUS\tpin\tunknown\t0\tspacer\tphysical\tBUS\tbus\tinput\t0\t0\t0\tX\t0\n')
    with nets.open('a') as stream:
        stream.write('\nNet bus\n Total capacitance: 0\n Number of drivers: 0\n'
                     ' Number of loads: 1\n Number of pins: 1\n\n'
                     'Load pins\n spacer/BUS unknown\n\n')
    for key in ('pin_census_report', 'net_census_report'):
        scene[key]['sha256'] = _sha(Path(scene[key]['path']))
    source.write_text(json.dumps(doc))
    netlist = Path(doc['identity']['artifacts']['sta_netlist']['path'])
    sdc = Path(doc['current']['sources']['signoff_sdc']['path'])
    lib = Path(scene['linked_liberties'][0]['path'])
    def classify():
        return Classifier(netlist, {'*': [lib]}, .2, project=run, sdc=sdc)
    classifier = classify()
    assert classifier.connectivity_evidence['state'] == 'SOURCE_BOUND', classifier.connectivity_evidence
    assert classifier.classify('*', 'max_capacitance', 'a', .2, 2.989206) == OFFCHIP_PORT
    _, result = T._judge(run, tmp_path)
    assert 'R5_DRV_VIOLATION' not in result['rules_violated'], result
    # Missing models on real logic still make the witness unavailable.
    lef.write_text(lef_body.replace('PAD SPACER', 'CORE'))
    scene['linked_lefs'][0]['sha256'] = _sha(lef)
    source.write_text(json.dumps(doc))
    assert classify().connectivity_evidence['state'] == 'UNAVAILABLE'
    _, result = T._judge(run, tmp_path)
    assert 'R5_DRV_VIOLATION' in result['rules_violated']


def test_a_core_row_beside_them_still_blocks(tmp_path):
    rc, res = T._judge(_stage(tmp_path, [_PORT, _IO, _CORE]), tmp_path)
    assert rc == 1 and "R5_DRV_VIOLATION" in res["rules_violated"]
    blob = " ".join(res["reasons"])
    assert "reports 1 DRV violation (of 3 tool rows" in blob, blob


def test_a_port_into_a_std_cell_still_blocks(tmp_path):
    rc, res = T._judge(_stage(tmp_path, [_PORT_INTO_CORE]), tmp_path)
    assert "R5_DRV_VIOLATION" in res["rules_violated"], res["reasons"]


def test_without_the_deck_every_row_counts_as_before(tmp_path):
    """Control: no resolvable netlist/IO Liberty -> classes UNAVAILABLE."""
    rc, res = T._judge(_stage(tmp_path, [_PORT], with_deck=False), tmp_path)
    assert rc == 1 and "R5_DRV_VIOLATION" in res["rules_violated"]


@pytest.mark.parametrize("population", ["drivers", "loads", "pins"])
@pytest.mark.parametrize("missing", [False, True])
def test_inconsistent_native_population_keeps_port_counted(tmp_path, population, missing):
    """A digest-bound truncated report cannot prove the port has only IO pins."""
    from drv_signoff_judge import _sha
    run = _stage(tmp_path, [_PORT])
    source = run / "reports/phase3/sta/drv_signoff_bundle.json"
    doc = json.loads(source.read_text())
    ref = doc["scenes"][0]["net_census_report"]
    path = Path(ref["path"])
    count = 2 if population == "pins" else 1
    line = f" Number of {population}: {count}\n"
    path.write_text(path.read_text().replace(
        line, "" if missing else f" Number of {population}: {count + 1}\n", 1))
    ref["sha256"] = _sha(path)
    source.write_text(json.dumps(doc))
    rc, res = T._judge(run, tmp_path)
    assert rc == 1 and "R5_DRV_VIOLATION" in res["rules_violated"], res
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")
    assert proc["drv"]["classes"]["counted"] == {"max_capacitance": 1}
    assert proc["drv"]["classes"]["connectivity"]["state"] == "UNAVAILABLE"


@pytest.mark.parametrize("stale", [False, True], ids=["captured_limit", "replaced_library"])
def test_io_t1_offender_cannot_use_replacement_liberty(tmp_path, stale):
    """The measured IO exceeds its captured .21 limit even after replacement."""
    from drv_signoff_judge import _sha
    run = _stage(tmp_path, [_IO])
    source = run / "reports/phase3/sta/drv_signoff_bundle.json"
    doc = json.loads(source.read_text())
    ref = doc["scenes"][0]["linked_liberties"][0]
    lib = Path(ref["path"])
    lib.write_text(lib.read_text().replace("default_max_capacitance : 999",
                                          "default_max_capacitance : 0.21"))
    ref["sha256"] = _sha(lib)
    source.write_text(json.dumps(doc))
    if stale:
        lib.write_text(lib.read_text().replace("default_max_capacitance : 0.21",
                                              "default_max_capacitance : 999"))
    rc, res = T._judge(run, tmp_path)
    assert rc == 1 and "R5_DRV_VIOLATION" in res["rules_violated"], res
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")
    assert proc["drv"]["classes"]["counted"] == {"max_capacitance": 1}
    assert proc["drv"]["classes"]["connectivity"]["state"] == ("UNAVAILABLE" if stale else "SOURCE_BOUND")


@pytest.mark.parametrize("connection", ["direct", "alias", "concat"])
@pytest.mark.parametrize("fresh", [False, True])
def test_core_connectivity_keeps_the_port_violation(tmp_path, connection, fresh):
    run = _stage(tmp_path, [_PORT])
    netlist = run / "phase3/stage3/pnr/chip_pnr.v"
    replacement = {"direct": "a", "alias": "a_alias", "concat": "{n,a}"}[connection]
    text = netlist.read_text().replace(".A(n)", f".A({replacement})")
    if connection == "alias":
        text = text.replace("endmodule", "wire a_alias; assign a_alias = a; endmodule")
    netlist.write_text(text)
    if fresh:
        from drv_signoff_judge import _sha
        source = run / "reports/phase3/sta/drv_signoff_bundle.json"
        doc = json.loads(source.read_text())
        doc["identity"]["artifacts"]["sta_netlist"]["sha256"] = _sha(netlist)
        scene = doc["scenes"][0]
        pins = Path(scene["pin_census_report"]["path"])
        nets = Path(scene["net_census_report"]["path"])
        pins.write_text(pins.read_text().replace("\tA\tn\t", "\tA\ta\t"))
        # Explicit native-format endpoints, no Verilog reader in the fixture.
        nets.write_text(nets.read_text().replace(" Number of loads: 1\n Number of pins: 2\n\nDriver pins\n a input",
                                                " Number of loads: 2\n Number of pins: 3\n\nDriver pins\n a input")
                       .replace(" u_pad_a/PAD input\n", " u_pad_a/PAD input\n u2/A input\n")
                       .replace(" Number of loads: 1\n Number of pins: 2\n\nDriver pins\n n input",
                                " Number of loads: 0\n Number of pins: 1\n\nDriver pins\n n input")
                       .replace("Load pins\n u2/A input\n", "Load pins\n"))
        for field, path in (("pin_census_report", pins), ("net_census_report", nets)):
            scene[field]["sha256"] = _sha(path)
        source.write_text(json.dumps(doc))
    rc, res = T._judge(run, tmp_path)
    assert rc == 1 and "R5_DRV_VIOLATION" in res["rules_violated"], res
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")
    assert proc["drv"]["classes"]["counted"] == {"max_capacitance": 1}
    assert proc["drv"]["classes"]["connectivity"]["state"] == ("SOURCE_BOUND" if fresh else "UNAVAILABLE")
