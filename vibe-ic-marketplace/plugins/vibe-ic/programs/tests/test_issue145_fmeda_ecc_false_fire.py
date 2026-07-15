"""#145 — fmeda detect_safety_mechanism must NOT false-fire ECC on a non-safety
register-mapped design (generic `error` port + the runner's `<top>` /
`<top>__rcvar_inner` wrapper-inner rename) → forced ASIL-D FMEDA → spurious FS1.

The tightened gate requires POSITIVE ECC structure (a real corrected-DATA output
narrower than the codeword) OR an explicit safety declaration; a bare 1-bit
`error`/detect status flag is no longer sufficient. §4.05 no-leak: a genuine ECC
(corrected output) OR a declared ASIL/parity design still fires FS1.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import fmeda_fault_injection_coverage as fi  # noqa: E402


def _rtl(tmp: Path) -> Path:
    d = tmp / "rtl"
    d.mkdir(parents=True)
    return d


def test_sha256_wrapper_inner_error_not_ecc(tmp_path):
    # register-mapped crypto: `<top>` wrapper + `<top>__rcvar_inner` inner, a
    # generic 1-bit `error` status, a data bus — and NO safety declaration.
    d = _rtl(tmp_path)
    (d / "sha256.v").write_text(
        "module sha256(input clk, reset_n, cs, we, input [7:0] address,"
        " input [31:0] write_data, output [31:0] read_data, output error);\n"
        " sha256__rcvar_inner u(.clk(clk), .write_data(write_data),"
        " .read_data(read_data), .error(error));\nendmodule\n")
    (d / "inner.v").write_text(
        "module sha256__rcvar_inner(input clk, input [31:0] write_data,"
        " output [31:0] read_data, output error);\n"
        " assign error = 1'b0;\nendmodule\n")
    assert fi.detect_safety_mechanism(d) is None   # NOT_APPLICABLE, never fake


def test_rcvar_base_pairs_wrapper_and_inner():
    assert fi._rcvar_base("sha256__rcvar_inner") == "sha256"
    assert fi._rcvar_base("sha256") == "sha256"
    # so an encoder loop never pairs a module with its own reset/clock variant
    assert fi._rcvar_base("aes") != fi._rcvar_base("sha256__rcvar_inner")


# ── §4.05 no-leak: genuine safety designs STILL fire ──────────────────────
def test_genuine_ecc_corrected_output_still_fires(tmp_path):
    d = _rtl(tmp_path)
    (d / "enc.v").write_text(
        "module ham_enc(input [3:0] data_in, output [6:0] code_out);\n"
        " assign code_out = 7'b0;\nendmodule\n")
    (d / "dec.v").write_text(
        "module ham_dec(input [6:0] code_in, output [3:0] data_out,"
        " output syndrome_err);\n"
        " assign data_out = code_in[3:0]; assign syndrome_err = 1'b0;\n"
        "endmodule\n")
    spec = fi.detect_safety_mechanism(d)
    assert spec is not None
    assert spec.dec_out == "data_out"          # positive corrected-data output
    assert spec.detect_port == "syndrome_err"


def test_declared_parity_detect_only_still_fires(tmp_path):
    # a detect-only parity mechanism (no corrected output) fires ONLY because
    # the L-docs/RTL DECLARE a safety intent (ISO-26262 / ASIL / parity-protect)
    d = _rtl(tmp_path)
    (d / "p.v").write_text(
        "// ISO-26262 ASIL-D parity-protected register file\n"
        "module par_enc(input [7:0] data_in, output [8:0] code_out);"
        " assign code_out = 9'b0; endmodule\n"
        "module par_dec(input [8:0] code_in, output parity_err);"
        " assign parity_err = 1'b0; endmodule\n")
    spec = fi.detect_safety_mechanism(d)
    assert spec is not None
    assert spec.detect_port == "parity_err"


def test_detect_flag_only_no_declaration_does_not_fire(tmp_path):
    # a decoder-shaped module with a genuine detect flag (`err`) BUT no
    # corrected-data output and NO safety declaration must NOT fire. Under the
    # OLD gate the bare detect flag alone made it applicable (the #145 leak);
    # the tightened gate now requires positive structure OR a declaration.
    d = _rtl(tmp_path)
    (d / "p.v").write_text(
        "module plain_enc(input [7:0] data_in, output [8:0] code_out);"
        " assign code_out = 9'b0; endmodule\n"
        "module plain_dec(input [8:0] code_in, output err);"
        " assign err = 1'b0; endmodule\n")
    assert fi.detect_safety_mechanism(d) is None
