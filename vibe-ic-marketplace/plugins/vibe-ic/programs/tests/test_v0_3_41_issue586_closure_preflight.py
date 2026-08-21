"""ORGANIC #586 — staged vendor RTL whose parameter DEFAULT selects a
deliberately-excluded implementation variant kills yosys elaboration of
uninstantiated generate branches ("Module `X' referenced ... is not part
of the design") with no hint that a default-vs-closure mismatch is the
cause (live: 8 modules declared the excluded default; the glue agent had
to sed all 8 before synth passed).

Fix: new staged_rtl_closure_preflight.py scans the staged set for module
references resolving to no staged module and, when the dangling ref sits
in a generate branch, names the guard label, the selecting parameter
default(s), and the in-closure alternative — the precise diagnosis the
raw yosys abort lacks.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import staged_rtl_closure_preflight as P  # noqa: E402

# The issue's exact shape: two-variant generate where the declared
# DEFAULT names the variant excluded from staging.
_SBOX_USER = """\
module aes_sbox #(
  parameter sbox_impl_e SecSBoxImpl = SBoxImplMasked
) (
  input  logic [7:0] data_i,
  output logic [7:0] data_o
);
  generate
    case (SecSBoxImpl)
      SBoxImplMasked: begin : gen_masked
        aes_sbox_masked u_sbox (.data_i(data_i), .data_o(data_o));
      end
      SBoxImplLut: begin : gen_lut
        aes_sbox_lut u_sbox (.data_i(data_i), .data_o(data_o));
      end
    endcase
  endgenerate
endmodule
"""

_SBOX_LUT = """\
module aes_sbox_lut (
  input  logic [7:0] data_i,
  output logic [7:0] data_o
);
  assign data_o = ~data_i;
endmodule
"""


def _stage(tmp_path, *files):
    for name, text in files:
        (tmp_path / name).write_text(text)
    return tmp_path


def test_default_selected_excluded_variant_diagnosed(tmp_path):
    """The issue's exact 現象: masked variant NOT staged, default points
    at it → FAIL with rule generate_branch_default naming the guard, the
    selecting default, and the in-closure alternative."""
    proj = _stage(tmp_path, ("aes_sbox.sv", _SBOX_USER),
                  ("aes_sbox_lut.sv", _SBOX_LUT))
    report = P.audit([str(proj)])
    assert report["verdict"] == "FAIL"
    f = next(x for x in report["findings"]
             if x["module_ref"] == "aes_sbox_masked")
    assert f["rule"] == "generate_branch_default"
    assert "SBoxImplMasked" in f["guard_label"]
    assert any("SecSBoxImpl" in s for s in f["selecting_param_defaults"])
    assert "aes_sbox_lut" in f["in_closure_alternatives"]
    assert "Rewrite the default" in f["message"]


def test_full_closure_passes(tmp_path):
    proj = _stage(
        tmp_path, ("aes_sbox.sv", _SBOX_USER),
        ("aes_sbox_lut.sv", _SBOX_LUT),
        ("aes_sbox_masked.sv",
         "module aes_sbox_masked (input logic [7:0] data_i,\n"
         "                        output logic [7:0] data_o);\n"
         "  assign data_o = data_i;\nendmodule\n"))
    report = P.audit([str(proj)])
    assert report["verdict"] == "PASS", report["findings"]


def test_unconditional_dangling_ref_reported(tmp_path):
    """NEGATIVE half: a dangling ref OUTSIDE any generate conditional is
    a genuine hole — different rule, no rewrite advice."""
    proj = _stage(tmp_path, ("top.sv",
        "module top (input logic clk);\n"
        "  missing_core u_core (.clk(clk));\n"
        "endmodule\n"))
    report = P.audit([str(proj)])
    assert report["verdict"] == "FAIL"
    f = report["findings"][0]
    assert f["rule"] == "unconditional_dangling_ref"
    assert f["module_ref"] == "missing_core"


def test_keywords_not_mistaken_for_instantiations(tmp_path):
    proj = _stage(tmp_path, ("clean.sv",
        "module clean (input logic clk, input logic rst_n,\n"
        "              output logic q);\n"
        "  logic d;\n"
        "  always_ff @(posedge clk or negedge rst_n)\n"
        "    if (!rst_n) q <= 1'b0;\n"
        "    else q <= d;\n"
        "  assign d = ~q;\n"
        "endmodule\n"))
    report = P.audit([str(proj)])
    assert report["verdict"] == "PASS", report["findings"]


def test_cli_end_state(tmp_path):
    """End-state via the real CLI: the issue shape exits 1 with the
    diagnosis; the completed closure exits 0."""
    proj = _stage(tmp_path, ("aes_sbox.sv", _SBOX_USER),
                  ("aes_sbox_lut.sv", _SBOX_LUT))
    r = subprocess.run(
        [sys.executable, str(PROG / "staged_rtl_closure_preflight.py"),
         str(proj)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "generate_branch_default" in r.stdout
    assert "aes_sbox_masked" in r.stdout
