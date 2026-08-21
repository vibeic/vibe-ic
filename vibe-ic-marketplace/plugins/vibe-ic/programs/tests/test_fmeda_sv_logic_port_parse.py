"""FMEDA — a SystemVerilog `output logic [W:0] name` port was parsed as
name=`logic`, width=1, hiding a genuine SEC-DED ECC decoder.

`_module_ports` skipped only the `reg|wire` net-type keyword between a port's
direction and its packed dimension. SystemVerilog's ANSI default type is
`logic`, so the lowRISC / OpenTitan house-style header

    module prim_secded_inv_64_57_dec (
      input        [63:0] data_i,
      output logic [56:0] data_o,
      output logic [6:0]  syndrome_o,
      output logic [1:0]  err_o
    );

parsed as four ports all named `logic` (except the plain `data_i`), each width
1. With no detect port and no corrected-data output visible,
`detect_safety_mechanism` found NO decoder-shaped module, returned None →
NOT_APPLICABLE, and Step FS1 (ISO-26262 FMEDA) VACUOUSLY passed on a design
that ships a real SEC-DED ECC and DECLARES it (`SECDED` matches the strong
safety-declaration regex). A vacuous pass that should have been a real graded
FMEDA verdict — the input was applicable and simply was not examined.

The fix skips a run of SV net/var-type + signedness keywords
(`logic|bit|var|signed|unsigned|reg|wire`) before the optional dimension.
"""
from __future__ import annotations

import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import fmeda_fault_injection_coverage as F  # noqa: E402

_SECDED_DEC = """\
// SECDED SEC-DED decoder (single error correct, double error detect)
module prim_secded_inv_64_57_dec (
  input        [63:0] data_i,
  output logic [56:0] data_o,
  output logic [6:0]  syndrome_o,
  output logic [1:0]  err_o
);
endmodule : prim_secded_inv_64_57_dec
"""


def test_sv_logic_output_port_keeps_its_name_and_width():
    """The defect, stated as a property of the parsed port tuple."""
    ports = dict((n, (d, w)) for n, d, w in
                 F._module_ports(_SECDED_DEC, "prim_secded_inv_64_57_dec"))
    # pre-fix these were all ('logic', 'output', 1)
    assert "data_o" in ports, "the SV `output logic` port lost its name"
    assert ports["data_o"] == ("output", 57)
    assert ports["syndrome_o"] == ("output", 7)
    assert ports["err_o"] == ("output", 2)
    assert "logic" not in ports, "the net-type keyword was captured as a port"


def test_plain_verilog_and_reg_wire_ports_still_parse():
    """The fix is additive: pre-existing `input [W:0]` and `output reg/wire`
    forms must be unchanged."""
    src = ("module m (input [7:0] a, output reg [3:0] b, "
           "output wire c, inout [1:0] d);\nendmodule")
    ports = dict((n, (dr, w)) for n, dr, w in F._module_ports(src, "m"))
    assert ports["a"] == ("input", 8)
    assert ports["b"] == ("output", 4)
    assert ports["c"] == ("output", 1)
    assert ports["d"] == ("inout", 2)


def test_signed_type_run_is_skipped():
    """`output wire signed [7:0] x` — multiple type/sign keywords before the
    dimension must all be skipped."""
    src = "module m (output wire signed [7:0] x, input logic y);\nendmodule"
    ports = dict((n, (dr, w)) for n, dr, w in F._module_ports(src, "m"))
    assert ports["x"] == ("output", 8)
    assert ports["y"] == ("input", 1)
    assert "signed" not in ports and "logic" not in ports and "wire" not in ports


def test_secded_decoder_is_now_a_detected_safety_mechanism(tmp_path):
    """End-to-end: a declared SEC-DED decoder must make FMEDA APPLICABLE
    (detect_safety_mechanism returns a spec), not NOT_APPLICABLE."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "prim_secded_inv_64_57_dec.sv").write_text(_SECDED_DEC)
    # an encoder so the enc/dec pairing has a partner (input 57 -> output 64)
    (rtl / "prim_secded_inv_64_57_enc.sv").write_text(
        "module prim_secded_inv_64_57_enc (\n"
        "  input  [56:0] data_i,\n"
        "  output logic [63:0] data_o\n"
        ");\nendmodule\n")
    spec = F.detect_safety_mechanism(rtl, "")
    assert spec is not None, (
        "a declared SEC-DED ECC decoder was still classified NOT_APPLICABLE — "
        "FS1 would vacuously pass on a real safety design")
