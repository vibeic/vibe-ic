"""ORGANIC #750 [P2] — rtl_hygiene Rule 14 (divmod-by-zero-const) now harvests a
module-HEADER parameter as the truncated-divisor WIDTH source.

Form3 `module m #(parameter W=8) ... localparam [W-1:0] DW = W'(2**W); % DW`
(==0) was MISSED because the shipped Rule-14 built its constant env only from
`;`-terminated localparam/parameter decls (`_LOCALPARAM_DECL_RE`), and a header
param is comma/paren-terminated. `_harvest_header_params` now seeds the env from
the module header FIRST, so a body localparam whose width comes from a header
param is provable.

§4.05 no-leak (all must stay CLEAN): a non-truncated header divisor
`#(parameter DEPTH=256) % DEPTH`; a non-truncated `9'(2**W)`==256; a RUNTIME
(signal) divisor; a header param with a NON-CONSTANT default (resolves None →
skipped). Forms 1 & 2 still fire.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402


def _divmod(tmp_path, text):
    p = tmp_path / "dut.sv"
    p.write_text(text)
    return [f for f in H.lint_file(p) if f.rule == "divmod-by-zero-const"]


# ── 驗收 (issue body, verbatim shape) ───────────────────────────────────────
_ACCEPT = (
    "module m #(parameter W=8)(input [W-1:0] p, output [W-1:0] o);\n"
    "  localparam [W-1:0] DW = W'(2**W);   // W'(256) truncates to 0\n"
    "  assign o = p % DW;                  // modulo-by-zero\n"
    "endmodule\n"
)


def test_acceptance_form3_header_param_divisor(tmp_path):
    """END-STATE: Form3 header-param-width truncated divisor (`DW`==0) WARNs."""
    f = _divmod(tmp_path, _ACCEPT)
    assert len(f) == 1
    assert f[0].severity == "WARN"
    assert f[0].symbol == "DW"


def test_form3_via_program_main(tmp_path):
    """Invoke the program's main() end-to-end (rc=1, divmod text present)."""
    import subprocess
    p = tmp_path / "f3.sv"
    p.write_text(_ACCEPT)
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "rtl_hygiene_lint.py"), str(p)],
        capture_output=True, text=True)
    assert "divmod-by-zero-const" in r.stdout
    assert r.returncode == 1


# ── positive retention: Forms 1 & 2 still fire ──────────────────────────────
def test_form1_literal_cast_still_fires(tmp_path):
    f = _divmod(tmp_path,
                "module m(input [7:0] p, output [7:0] o);\n"
                "  localparam [7:0] DW = 8'(256);\n"
                "  assign o = p % DW;\nendmodule\n")
    assert len(f) == 1


def test_form2_internal_localparam_still_fires(tmp_path):
    f = _divmod(tmp_path,
                "module m(input [7:0] p, output [7:0] o);\n"
                "  localparam W = 8;\n"
                "  localparam [W-1:0] DW = W'(2**W);\n"
                "  assign o = p % DW;\nendmodule\n")
    assert len(f) == 1


# ── §4.05 no-leak negatives ─────────────────────────────────────────────────
def test_noleak_nontruncated_header_param_depth(tmp_path):
    """`#(parameter DEPTH=256) % DEPTH` — DEPTH is 256, NOT zero → clean."""
    f = _divmod(tmp_path,
                "module m #(parameter DEPTH=256)(input [31:0] a, output [31:0] o);\n"
                "  assign o = a % DEPTH;\nendmodule\n")
    assert f == []


def test_noleak_nontruncated_wide_cast(tmp_path):
    """`9'(2**W)` with W=8 → 256 (fits 9 bits, not 0) → clean."""
    f = _divmod(tmp_path,
                "module m #(parameter W=8)(input [8:0] a, output [8:0] o);\n"
                "  localparam [8:0] DW = 9'(2**W);\n"
                "  assign o = a % DW;\nendmodule\n")
    assert f == []


def test_noleak_runtime_signal_divisor(tmp_path):
    """A runtime signal divisor `% d` is NOT a compile-time const → clean."""
    f = _divmod(tmp_path,
                "module m(input [7:0] a, input [7:0] d, output [7:0] o);\n"
                "  assign o = a % d;\nendmodule\n")
    assert f == []


def test_noleak_header_param_nonconstant_default(tmp_path):
    """§4.05 (issue body): a header param with a NON-CONSTANT default resolves
    to None and is skipped — never guessed into a fabricated truncation."""
    f = _divmod(tmp_path,
                "module m #(parameter W = SOME_PKG::WID)"
                "(input [7:0] a, output [7:0] o);\n"
                "  localparam [W-1:0] DW = W'(2**W);\n"
                "  assign o = a % DW;\nendmodule\n")
    assert f == []


def test_harvest_header_params_skips_nonconstant(tmp_path):
    """Unit-level: `_harvest_header_params` seeds a non-zero constant default as
    a usable width-source, skips a non-constant default, and (§4.05) NEVER marks
    a BARE-LITERAL-0 default into zero_consts — it is an overridable placeholder,
    not a provable divide-by-zero (SERV `#(parameter width=0)`)."""
    consts, zeros, lineof = {}, {}, {}
    src = "module m #(parameter A=4, parameter B=runtime_sig, parameter C=0)();"
    H._harvest_header_params(src, consts, zeros, lineof)
    assert consts.get("A") == 4       # non-zero literal seeds a width source
    assert "B" not in consts          # non-constant default skipped
    assert "C" not in zeros           # bare-literal-0 default NOT proven-zero
    assert "C" not in consts          # bare-literal-0 placeholder dropped entirely


def test_harvest_header_params_marks_derived_zero(tmp_path):
    """A header param whose value comes from a DERIVED/TRUNCATING expression
    (`W'(2**W)` == 0) IS provably zero regardless of override → enters
    zero_consts (this is the #750 idiom)."""
    consts, zeros, lineof = {}, {}, {}
    src = "module m #(parameter W=8, parameter [W-1:0] DW = W'(2**W))();"
    H._harvest_header_params(src, consts, zeros, lineof)
    assert consts.get("W") == 8
    assert "DW" in zeros              # derived truncation is a real zero
