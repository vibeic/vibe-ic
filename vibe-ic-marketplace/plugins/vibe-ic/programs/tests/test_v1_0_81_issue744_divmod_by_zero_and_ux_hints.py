"""ORGANIC #744 [P2] — rtl_hygiene_lint divide/modulo-by-zero rule (width-
truncated divisor) + 2 author-UX hint strings.

R3-1: a `localparam [7:0] DW = 8'(256)` truncates to 0, so `ptr % DW` is
      modulo-by-ZERO → x at runtime (functionally dead). Passed iverilog -g2012,
      verilator -Wall, AND every rtl_hygiene rule — only the hidden behavioral
      scorer caught it. New Rule 14 flags a `%`/`/` whose divisor is a
      compile-time constant evaluating to 0.
R3-2: latency MISMATCH message gains a counting-origin hint.
R3-3: PPA verdict gains an in-container-measurement-only hint.

§4.05 no-leak: a real NONZERO divisor and a RUNTIME-SIGNAL divisor are NOT
flagged; a `$display("...%0d...")` format spec is NOT mistaken for a `% 0`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_LINT = _PROGRAMS / "rtl_hygiene_lint.py"


def _lint(tmp_path, text):
    p = tmp_path / "dut.sv"
    p.write_text(text)
    return [f for f in H.lint_file(p) if f.rule == "divmod-by-zero-const"]


# ── R3-1 acceptance: the issue's 驗收 verbatim shape ─────────────────────────
_ACCEPT_RTL = ("module m(input [7:0] p, output [7:0] o); "
               "localparam [7:0] DW = 8'(256); assign o = p % DW; endmodule\n")


def test_acceptance_width_truncated_modulo_by_zero(tmp_path):
    """END-STATE via the real program: the width-truncated `8'(256)`==0 divisor
    is WARN-flagged as modulo-by-zero."""
    p = tmp_path / "dz.sv"
    p.write_text(_ACCEPT_RTL)
    cp = subprocess.run(
        [sys.executable, str(_LINT), "--severity", "WARN", str(p)],
        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout
    assert "divmod-by-zero-const" in cp.stdout
    assert "modulo-by-zero" in cp.stdout and "DW" in cp.stdout


def test_const_eval_width_truncation():
    # 8'(256) truncates to the low 8 bits → 0; 8'(255) → 255.
    assert H._eval_const_int("8'(256)", {}) == 0
    assert H._eval_const_int("8'(255)", {}) == 255
    assert H._eval_const_int("8'(2**8)", {}) == 0
    assert H._eval_const_int("4'(16)", {}) == 0


# ── §4.05 no-leak ────────────────────────────────────────────────────────────
def test_noleak_nonzero_const_divisor_not_flagged(tmp_path):
    assert _lint(tmp_path, ("module m(input [7:0] p, output [7:0] o); "
                            "localparam [7:0] DW = 8'(255); assign o = p % DW; "
                            "endmodule\n")) == []


def test_noleak_runtime_signal_divisor_not_flagged(tmp_path):
    assert _lint(tmp_path, ("module m(input [7:0] p, d, output [7:0] o); "
                            "assign o = p % d; endmodule\n")) == []


def test_noleak_display_format_spec_not_flagged(tmp_path):
    # the printf-format blast-radius: %0d inside a string literal must NOT fire.
    txt = ('module tb; initial $display("dur=%0d idx=%0d t=%0t", a, b, $time);\n'
           'endmodule\n')
    assert _lint(tmp_path, txt) == []


def test_bare_literal_zero_divisor_flagged(tmp_path):
    assert len(_lint(tmp_path, ("module m(input [7:0] p, output [7:0] o); "
                                "assign o = p / 0; endmodule\n"))) >= 1


def test_noleak_coverage_annotation_prefix_not_flagged(tmp_path):
    """§4.05 (adversarial-review MEDIUM) — a Verilator/covered coverage-annotation
    line prefix `%000000` at line start has NO left operand and must NOT be read
    as `% 0`. A real `% DW` on a later line still fires."""
    txt = (
        "%000000    module m(input [7:0] p, output [7:0] o);\n"
        "%000000    localparam [7:0] DW = 8'(256);\n"
        "%001498    assign o = p % DW;\n"   # leading % is a coverage marker
        "%000000    endmodule\n")
    fires = _lint(tmp_path, txt)
    # the coverage prefixes must NOT fire; only the genuine `p % DW` (DW==0) fires
    # — exactly once, despite four line-leading `%` markers.
    assert len(fires) == 1, [f.message for f in fires]
    assert fires[0].symbol == "DW"


# ── R3-2 / R3-3 author-UX hints ──────────────────────────────────────────────
def test_latency_mismatch_carries_counting_origin_hint():
    src = (_PROGRAMS / "latency_conformance_check.py").read_text()
    # the MISMATCH branch must print the #744 counting-origin hint.
    i = src.index('LATENCY-MISMATCH: measured=')
    assert "hint (#744)" in src[i:i + 1200]
    assert "measured+1" in src[i:i + 1200]


def test_ppa_verdict_carries_in_container_only_hint():
    src = (_PROGRAMS / "ppa_area_threshold_check.py").read_text()
    assert "hint (#744)" in src
    assert "in-container measurement" in src and "opposite-sign" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
