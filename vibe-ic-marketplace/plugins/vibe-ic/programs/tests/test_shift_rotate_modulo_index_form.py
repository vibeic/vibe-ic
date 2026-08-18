"""ORGANIC (RTLLM barrel_shifter) — the `shift-implemented-as-rotate` emit-block
MISSED the generate/for MODULO-ARITHMETIC rotate form `x[(i +/- k) % W]`.

The RTLLM barrel_shifter sample builds the shifter as per-bit muxes whose source
index is `in[(i+4)%8]`, `s4[(i+2)%8]`, `s2[(i+1)%8]`. The `% 8` WRAPS the index
around the word — the defining behaviour of a ROTATE — but idioms (1)-(3) of
`_rtl_rotate_signatures` (OR-of-opposite-shifts / concat-partition / doubled-
vector-shift) all miss it because it is neither a shift-operator OR nor a concat.
Signature (4) adds the modulo/mask index-wrap form.

§4.05: a genuine logical shift never wraps the index (it uses a shift operator,
a zero-fill concat, or a guarded `i+k < W ? x[i+k] : 0`), so the presence of
`% W` / `& (W-1)` on an offset bit index is unambiguous — zero false fire.
"""
import subprocess
import sys
from pathlib import Path

_P = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_P))
import spec_conformance_check as SC  # noqa: E402

_PC = _P / "spec_conformance_check.py"
_SHIFT_SPEC = ("A barrel shifter performing a logical shift of the input by the "
               "control amount; vacated bits are filled with zero.\n")


def _conf(tmp_path, rtl, spec=_SHIFT_SPEC):
    (tmp_path / "d.sv").write_text(rtl)
    (tmp_path / "spec.txt").write_text(spec)
    return subprocess.run(
        [sys.executable, str(_PC), "--rtl-dir", str(tmp_path), "--spec",
         str(tmp_path / "spec.txt"), "--top", "barrel_shifter"],
        capture_output=True, text=True)


# The RTLLM barrel_shifter modulo-rotate sample.
_MODROT = (
    "module mux2X1(input a, input b, input sel, output out);\n"
    "  assign out = sel ? b : a;\n"
    "endmodule\n"
    "module barrel_shifter(input [7:0] in, input [2:0] ctrl, output [7:0] out);\n"
    "  wire [7:0] s4, s2; genvar i;\n"
    "  generate\n"
    "    for (i=0;i<8;i=i+1) begin: g4\n"
    "      mux2X1 m(.a(in[i]), .b(in[(i+4)%8]), .sel(ctrl[2]), .out(s4[i]));\n"
    "    end\n"
    "    for (i=0;i<8;i=i+1) begin: g2\n"
    "      mux2X1 m(.a(s4[i]), .b(s4[(i+2)%8]), .sel(ctrl[1]), .out(s2[i]));\n"
    "    end\n"
    "    for (i=0;i<8;i=i+1) begin: g1\n"
    "      mux2X1 m(.a(s2[i]), .b(s2[(i+1)%8]), .sel(ctrl[0]), .out(out[i]));\n"
    "    end\n"
    "  endgenerate\n"
    "endmodule\n"
)

# A CORRECT logical barrel shifter: zero-fill concat, NO index wrap.
_LOGICAL_OK = (
    "module barrel_shifter(input [7:0] in, input [2:0] ctrl, output [7:0] out);\n"
    "  wire [7:0] s4 = ctrl[2] ? {in[3:0], 4'b0000} : in;\n"
    "  wire [7:0] s2 = ctrl[1] ? {s4[5:0], 2'b00}   : s4;\n"
    "  assign out    = ctrl[0] ? {s2[6:0], 1'b0}    : s2;\n"
    "endmodule\n"
)


def test_modulo_index_signature_detected_by_function():
    sigs = SC._rtl_rotate_signatures(_MODROT)
    assert any("%" in s for s in sigs), sigs


def test_modulo_rotate_blocks_under_shifter_spec(tmp_path):
    r = _conf(tmp_path, _MODROT)
    assert r.returncode == 1
    assert "shift-implemented-as-rotate" in (r.stdout + r.stderr)


def test_mask_form_index_wrap_detected():
    # x[(i+k) & (W-1)] is the power-of-two mask equivalent of % W
    rtl = ("module s(input [7:0] in, input [2:0] c, output [7:0] o);\n"
           "  genvar i; generate for (i=0;i<8;i=i+1) begin: g\n"
           "    assign o[i] = in[(i+c) & (8-1)];\n"
           "  end endgenerate endmodule\n")
    assert SC._rtl_rotate_signatures(rtl)


def test_correct_logical_shifter_not_blocked(tmp_path):
    r = _conf(tmp_path, _LOGICAL_OK)
    assert "shift-implemented-as-rotate" not in (r.stdout + r.stderr)


def test_bare_index_no_offset_not_flagged():
    # x[i] and x[i % 8] with NO offset are identity, not a rotate → must not match.
    rtl = ("module s(input [7:0] in, output [7:0] o);\n"
           "  genvar i; generate for (i=0;i<8;i=i+1) begin: g\n"
           "    assign o[i] = in[i];\n"
           "  end endgenerate endmodule\n")
    assert not [s for s in SC._rtl_rotate_signatures(rtl) if "%" in s or "&" in s]


# ── folded in at merge: a COMMENT is not RTL ───────────────────────────────
#
# Found by sweeping the corpus with the pre-PR and post-PR detectors and diffing
# the hit sets. Every idiom here matches a STRING, so a comment that DESCRIBES a
# wrap arms the detector as surely as code that performs one:
#
#   Prob094_gatesv / Prob092_gatesv100   // out_different[i] = in[i] ^ in[(i+1)%4]
#
# Measured across 6255 RTL files: 5 of 172 signatures existed only inside a
# comment. Two are this rule's new modulo form; the other three are the
# PRE-EXISTING idioms (parallel2serial's concat, ibex_alu's OR-of-shifts twice),
# so the exposure is older than the form that surfaced it. Stripping leaves 167,
# and the five that vanish are exactly those five.
#
# It matters because the finding EMIT-BLOCKS: a design whose spec says shift and
# whose RTL merely comments a wrap would be blocked on the strength of prose —
# this file's own failure mode, arriving through its own input.
import importlib.util as _ilu
import pathlib as _pl
import sys as _sys

_S_SPEC = _ilu.spec_from_file_location(
    "_scc_cmt", _pl.Path(__file__).resolve().parents[1] / "spec_conformance_check.py")
_SCC = _ilu.module_from_spec(_S_SPEC)
_sys.modules["_scc_cmt"] = _SCC
try:
    _S_SPEC.loader.exec_module(_SCC)
except SystemExit:
    pass

_ROT_CODE = ("module z(input [7:0] a, output [7:0] y);\n"
             "genvar i;\ngenerate for(i=0;i<8;i=i+1) begin\n"
             "  assign y[i]=a[(i+3)%8];\nend endgenerate\nendmodule\n")


def test_a_wrap_in_a_LINE_comment_does_not_arm_the_detector():
    rtl = ("module z(input [7:0] a, output [7:0] y);\n"
           "// y[i] = a[(i+1)%8] wrap-around\n"
           "assign y = a >> 1;\nendmodule\n")
    assert _SCC._rtl_rotate_signatures(rtl) == []


def test_a_wrap_in_a_BLOCK_comment_does_not_arm_the_detector():
    rtl = ("module z(input [7:0] a, output [7:0] y);\n"
           "/* y[i] = a[(i+1)%8] */\nassign y = a >> 1;\nendmodule\n")
    assert _SCC._rtl_rotate_signatures(rtl) == []


def test_the_real_rotate_in_CODE_still_fires():
    """THE ACCEPT CASE. Stripping comments must not blind the rule to the thing
    it exists to catch."""
    assert _SCC._rtl_rotate_signatures(_ROT_CODE) == ["a[(i+3)%8]"]


def test_a_commented_wrap_beside_a_REAL_one_still_fires():
    """The half a naive strip could get wrong: a file carrying both must still
    report the code one."""
    rtl = _ROT_CODE.replace("genvar i;",
                            "// see a[(i+9)%8] in the note above\ngenvar i;")
    assert _SCC._rtl_rotate_signatures(rtl) == ["a[(i+3)%8]"]
