"""ORGANIC #757 [P2] — rtl_hygiene_lint gains rule_assign_width_truncate
(+ helper _collect_decl_widths): WARN on a non-blocking/blocking/continuous
assignment whose RHS is a SINGLE declared signal (a bare VARREF — no slice, no
operator) strictly WIDER than a WHOLE-signal LHS (verilator WIDTHTRUNC).

Conservative zero-FP: both widths must be known from a literal `[H:L]` range or
the canonical `[NAME-1:0]` param form. Expression RHS, sliced LHS, and
arithmetic/$clog2 ranges are SKIPPED (under-report, never over-report).

§4.05 no-leak: equal-width / widening assigns clean; expression RHS skipped;
sliced LHS skipped; `==` comparison not misread as an assignment; a GENUINE
truncation still WARNs (continuous + blocking + param-width forms).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_LINT = _PROGRAMS / "rtl_hygiene_lint.py"


def _trunc(tmp_path, text):
    p = tmp_path / "dut.sv"
    p.write_text(text)
    return [f for f in H.lint_file(p) if f.rule == "assign-width-truncate"]


# ── 驗收: the named "Width mismatch" defect is now flagged ───────────────────
_ACCEPT = (
    "module iir(input clk, input [31:0] temp_y, output reg [15:0] y);\n"
    "  always @(posedge clk) y <= temp_y;\n"
    "endmodule\n"
)


def test_acceptance_nonblocking_truncation_flagged(tmp_path):
    """END-STATE: 32-bit `temp_y` → 16-bit `y` is WARN (verilator WIDTHTRUNC)."""
    f = _trunc(tmp_path, _ACCEPT)
    assert len(f) == 1
    assert f[0].severity == "WARN"
    assert f[0].symbol == "y"
    assert "32 bits" in f[0].message and "16 bits" in f[0].message


def test_acceptance_via_program_main(tmp_path):
    p = tmp_path / "iir.sv"
    p.write_text(_ACCEPT)
    r = subprocess.run([sys.executable, str(_LINT), str(p)],
                       capture_output=True, text=True)
    assert "assign-width-truncate" in r.stdout
    assert r.returncode == 1


# ── positive retention across assignment kinds ──────────────────────────────
def test_continuous_assign_truncation_flagged(tmp_path):
    f = _trunc(tmp_path,
               "module m(input [31:0] wide, output [15:0] narrow);\n"
               "  assign narrow = wide;\nendmodule\n")
    assert len(f) == 1


def test_blocking_assign_truncation_flagged(tmp_path):
    f = _trunc(tmp_path,
               "module m(input [31:0] wide, output reg [15:0] narrow);\n"
               "  always @(*) narrow = wide;\nendmodule\n")
    assert len(f) == 1


def test_param_width_form_resolved_and_flagged(tmp_path):
    """`[NAME-1:0]` param-form LHS width resolves and a wider RHS is flagged."""
    f = _trunc(tmp_path,
               "module m #(parameter NB=16)(input [31:0] wide, "
               "output reg [NB-1:0] narrow);\n"
               "  always @(*) narrow = wide;\nendmodule\n")
    assert len(f) == 1


# ── §4.05 no-leak negatives ─────────────────────────────────────────────────
def test_noleak_equal_width(tmp_path):
    assert _trunc(tmp_path,
                  "module m(input clk, input [15:0] a, output reg [15:0] y);\n"
                  "  always @(posedge clk) y <= a;\nendmodule\n") == []


def test_noleak_widening_assign(tmp_path):
    """Wider LHS (zero/sign-extension), no truncation → clean."""
    assert _trunc(tmp_path,
                  "module m(input clk, input [7:0] a, output reg [15:0] y);\n"
                  "  always @(posedge clk) y <= a;\nendmodule\n") == []


def test_noleak_expression_rhs_skipped(tmp_path):
    """Expression RHS width depends on signedness/extension a regex can't infer
    → conservatively skipped (under-report)."""
    assert _trunc(tmp_path,
                  "module m(input clk, input [31:0] a, input [31:0] b, "
                  "output reg [15:0] y);\n"
                  "  always @(posedge clk) y <= a ^ b;\nendmodule\n") == []


def test_noleak_sliced_lhs_skipped(tmp_path):
    """A bit-select LHS sets its own width and is intentional → skipped."""
    assert _trunc(tmp_path,
                  "module m(input clk, input [31:0] a, output reg [31:0] y);\n"
                  "  always @(posedge clk) y[15:0] <= a;\nendmodule\n") == []


def test_noleak_equality_not_misread_as_assignment(tmp_path):
    """`big == y` must NOT be parsed as `big = y`."""
    assert _trunc(tmp_path,
                  "module m(input clk, input [31:0] big, output reg [15:0] y);\n"
                  "  always @(posedge clk) if (big == y) y <= 16'd0;\n"
                  "endmodule\n") == []


def test_noleak_unknown_width_skipped(tmp_path):
    """If either operand width is unknown ($clog2 range), never guess → clean."""
    assert _trunc(tmp_path,
                  "module m(input clk, input [$clog2(64)-1:0] a, "
                  "output reg [15:0] y);\n"
                  "  always @(posedge clk) y <= a;\nendmodule\n") == []


# ── helper-level unit ───────────────────────────────────────────────────────
def test_collect_decl_widths_literal_and_param_and_scalar():
    w = H._collect_decl_widths(
        "module m #(parameter NB=8)("
        "input [31:0] big, output reg [NB-1:0] mid, input flag);")
    assert w.get("big") == 32
    assert w.get("mid") == 8       # [NB-1:0] resolved via param
    assert w.get("flag") == 1      # un-ranged scalar → width 1


def test_collect_decl_widths_omits_unresolvable():
    w = H._collect_decl_widths("module m(input [$clog2(64)-1:0] x, output [W*2-1:0] y);")
    assert "x" not in w
    assert "y" not in w
