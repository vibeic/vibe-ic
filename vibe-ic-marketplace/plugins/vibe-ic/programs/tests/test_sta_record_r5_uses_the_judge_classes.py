"""Native netlist and IO Liberty DRV classification, without R5 receipt policy."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _drv_row_class import Classifier, OFFCHIP_PORT, IO_MARGIN, COUNTED

_IO_LIB = 'library (io) {\n  time_unit : "1ns";\n  capacitive_load_unit (1, pf);\n  default_max_capacitance : 999;\n  default_max_fanout : 1;\n  cell (PADIN) { pad_cell : true;\n    pin (PAD) { max_transition : 1; direction : input; }\n    pin (Y) { direction : output; } }\n  cell (BUF) { pin (A) { direction : input; } pin (Z) { direction : output; } }\n}\n'
_NETLIST = 'module chip (a, n);\n  input a;\n  input n;\n  PADIN u_pad_a (.PAD(a),\n    .Y(a_core));\n  BUF \\u_core/u1  (.A(a_core),\n    .Z(z1));\n  BUF u2 (.A(n),\n    .Z(z2));\nendmodule\n'

def _native(tmp_path, *, netlist=_NETLIST, liberty=_IO_LIB):
    nl = tmp_path / "chip.v"
    lib = tmp_path / "io.lib"
    nl.write_text(netlist)
    lib.write_text(liberty)
    return Classifier(nl, {"*": [lib]}, .2)


def test_port_to_pad_and_io_margin_rows_do_not_block(tmp_path):
    classifier = _native(tmp_path)
    assert classifier.classify("*", "max_capacitance", "a", .2, 2.989206) == OFFCHIP_PORT
    assert classifier.classify("*", "max_capacitance", "u_pad_a/Y", .2, .211182) == IO_MARGIN


def test_unrelated_physical_pin_preserves_the_complete_connectivity_witness(tmp_path):
    classifier = _native(tmp_path)
    assert classifier.connectivity_evidence["state"] == "NATIVE_NETLIST"
    assert classifier.classify("*", "max_capacitance", "a", .2, 2.989206) == OFFCHIP_PORT


def test_a_core_row_beside_them_still_blocks(tmp_path):
    classifier = _native(tmp_path)
    assert classifier.classify("*", "max_capacitance", "u_core/u1/Z", .2, .246000) == COUNTED


def test_a_port_into_a_std_cell_still_blocks(tmp_path):
    classifier = _native(tmp_path)
    assert classifier.classify("*", "max_capacitance", "n", .2, .250000) == COUNTED


def test_io_t1_offender_cannot_use_replacement_liberty(tmp_path):
    liberty = _IO_LIB.replace("default_max_capacitance : 999", "default_max_capacitance : 0.21")
    classifier = _native(tmp_path, liberty=liberty)
    assert classifier.classify("*", "max_capacitance", "u_pad_a/Y", .2, .211182) == COUNTED


@pytest.mark.parametrize("connection", ["direct", "alias", "concat"])
def test_core_connectivity_keeps_the_port_violation(tmp_path, connection):
    replacement = {"direct": "a", "alias": "a_alias", "concat": "{n,a}"}[connection]
    text = _NETLIST.replace(".A(n)", f".A({replacement})")
    if connection == "alias":
        text = text.replace("endmodule", "wire a_alias; assign a_alias = a; endmodule")
    classifier = _native(tmp_path, netlist=text)
    assert classifier.classify("*", "max_capacitance", "a", .2, 2.989206) == COUNTED
