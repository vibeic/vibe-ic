"""FMEDA mechanism detection must (1) never read a COMMENT sentence as a module
declaration, and (2) pick the GENUINE ECC encoder/decoder pair by port
structure — not the first module in file order.

Measured on opentitan_aes x sky130A (v1.9.65): the header comments
`// This module controls the AES cipher core ...` (aes_cipher_control.sv) and
`// This module implements the shadowed AES GCM control register ...`
(aes_ctrl_gcm_reg_shadowed.sv) were matched by `_MODULE_RE` on RAW text, minting
phantom modules `controls`/`implements`; `_module_ports` then spanned from the
comment into a real module header and gave them real ports, so the declared-safety
arm paired them into a phantom ECC whose TB (`controls u_enc`, `implements u_dec`)
references modules that do not exist -> iverilog FAILs -> DC UNMEASURED -> FS1 FAIL
on a design that ships a genuine SEC-DED ECC (prim_secded_inv_64_57_{enc,dec}).

After the fix FS1 measures the real ECC: DC=100.00% (4096/4096) >= 99% ASIL-D.
These are the bidirectional negative controls (flow-change-acceptance): each
asserts the FIXED behaviour and each FAILs against the pre-fix code.
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


# A genuine SEC-DED-shaped decoder (corrected data output NARROWER than the
# codeword input, PAIRED with a detect port) + its width-matching encoder.
_DEC = (
    "module ecc_dec(\n"
    "  input        [6:0] data_i,\n"
    "  output logic [3:0] data_o,\n"
    "  output logic       err_o\n"
    ");\n"
    "  assign data_o = data_i[3:0];\n"
    "  assign err_o  = ^data_i;\n"
    "endmodule\n")
_ENC = (
    "module ecc_enc(\n"
    "  input        [3:0] data_i,\n"
    "  output logic [6:0] data_o\n"
    ");\n"
    "  assign data_o = {3'b0, data_i};\n"
    "endmodule\n")


def test_comment_prose_is_not_read_as_a_module_declaration(tmp_path):
    """A comment `// This module implements ...` directly above a real module
    must NOT fabricate a phantom module named `implements`. Pre-fix, the phantom
    stole the real decoder's ports and was selected; post-fix the REAL module is."""
    d = _rtl(tmp_path)
    # A safety declaration so detection is applicable at all.
    (d / "ecc_dec.sv").write_text(
        "// SEC-DED ECC: this module implements the decoder for parity checks\n"
        + _DEC)
    (d / "ecc_enc.sv").write_text(
        "// this module controls the encode path\n" + _ENC)
    spec = fi.detect_safety_mechanism(d)
    assert spec is not None
    # The phantom prose words must never be chosen as enc/dec modules.
    assert spec.dec_module == "ecc_dec", spec.dec_module
    assert spec.enc_module == "ecc_enc", spec.enc_module
    assert "implements" not in (spec.dec_module, spec.enc_module)
    assert "controls" not in (spec.dec_module, spec.enc_module)


def test_prefers_genuine_ecc_over_detect_only_decoy(tmp_path):
    """A detect-only module that sorts FIRST by name (a shadow register with an
    `err_*` flag but NO corrected-data output) must not out-rank a structurally
    genuine ECC decoder. Pre-fix the first-by-order module won; post-fix the
    positive-structure (corrected-output AND detect) decoder wins."""
    d = _rtl(tmp_path)
    # 'aaa_shadow' sorts before 'ecc_dec' — the file-order trap.
    (d / "aaa_shadow.sv").write_text(
        "// parity-protected shadow register\n"
        "module aaa_shadow(\n"
        "  input        [31:0] q_i,\n"
        "  output logic        err_update_o\n"
        ");\n"
        "  assign err_update_o = ^q_i;\n"
        "endmodule\n")
    (d / "ecc_dec.sv").write_text(_DEC)
    (d / "ecc_enc.sv").write_text(_ENC)
    spec = fi.detect_safety_mechanism(d)
    assert spec is not None
    assert spec.dec_module == "ecc_dec", spec.dec_module
    # the genuine pair, with the real widths — not the 1-bit decoy
    assert spec.code_width == 7 and spec.data_width == 4


def test_encoder_pair_prefers_width_match(tmp_path):
    """The encoder is chosen to MIRROR the decoder's widths (in==data_width,
    out==code_width), not the first wider-than-input module in file order."""
    d = _rtl(tmp_path)
    (d / "ecc_dec.sv").write_text(_DEC)
    (d / "ecc_enc.sv").write_text(_ENC)
    # a decoy 'aaa_widen' that sorts first and is wider-out-than-in but does NOT
    # mirror the decoder widths (2 -> 9, vs the decoder's 4 -> 7).
    (d / "aaa_widen.sv").write_text(
        "module aaa_widen(input [1:0] x_i, output [8:0] y_o);\n"
        "  assign y_o = {7'b0, x_i};\nendmodule\n")
    spec = fi.detect_safety_mechanism(d)
    assert spec is not None
    assert spec.enc_module == "ecc_enc", spec.enc_module
    assert spec.code_width == 7 and spec.data_width == 4
