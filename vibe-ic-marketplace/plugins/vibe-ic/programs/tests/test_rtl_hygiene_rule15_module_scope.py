"""ORGANIC #757r2 (gapP) — rule_assign_width_truncate (Rule 15, #757) must scope
its decl-width map + assign scan PER MODULE.

ROOT CAUSE (chip-AGNOSTIC): Rule 15 built ONE flat, file-wide, first-decl-wins
width map (`_collect_decl_widths(src)`, `widths.setdefault(n, w)`) and scanned
assignments globally. When two SIBLING modules in one file declare a same-named
reg at DIFFERENT widths, a width-CORRECT within-module assignment was looked up
against the OTHER module's narrower width → a FALSE WIDTHTRUNC WARN. The same
cross-module same-name-collision class was already fixed for the MULTIDRIVEN rule
via `_module_regions` (#782/#788/#799) — a SEPARATE code path Rule 15 did not use.

FIX: iterate `_module_regions(src)`; per region build the width map from THAT
region's declarations only and scan assignments only within that region,
resolving widths against the region-local map. Line numbers are computed against
the FULL src via the region base offset.

§4.05 no-leak: a genuine within-module truncation STILL fires (single + two
modules), and an in-module `[W-1:0]` param-width correct assignment stays clean
(param resolution intact). verilator -Wall agrees: 0 real truncation on the FP
file; both real truncations flagged.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_LINT = _PROGRAMS / "rtl_hygiene_lint.py"


def _trunc(tmp_path, text, name="dut.sv"):
    p = tmp_path / name
    p.write_text(text)
    return [f for f in H.lint_file(p) if f.rule == "assign-width-truncate"]


# ── POS: the gapP cross-module same-name collision file → 0 findings ─────────
# Two sibling modules declare a same-named reg `r` at DIFFERENT widths. Within
# module `b`, `r=i` (both 32 bits) is width-CORRECT; it must NOT be flagged using
# module `a`'s narrower [7:0] `r`.
_GAPP_FP = (
    "module a(input clk); reg [7:0] r; endmodule\n"
    "module b(input clk, input [31:0] i); reg [31:0] r; always @(*) r=i; endmodule\n"
)


def test_pos_cross_module_same_name_collision_no_false_positive(tmp_path):
    """FP eliminated: a width-correct in-module assign is no longer flagged by a
    sibling module's narrower same-named decl."""
    assert _trunc(tmp_path, _GAPP_FP) == []


def test_pos_no_false_positive_via_program_main(tmp_path):
    """End-to-end through __main__ at --severity WARN: rc=0, no warning."""
    p = tmp_path / "gapP_repro.v"
    p.write_text(_GAPP_FP)
    r = subprocess.run(
        [sys.executable, str(_LINT), str(p), "--severity", "WARN"],
        capture_output=True, text=True)
    assert "assign-width-truncate" not in r.stdout
    assert r.returncode == 0


# ── NEG-1: a GENUINE within-same-module truncation still fires ───────────────
def test_neg1_genuine_within_module_truncation_still_flagged(tmp_path):
    f = _trunc(
        tmp_path,
        "module m(input clk, input [31:0] a, output reg [7:0] r);\n"
        "  always @(*) r = a;\nendmodule\n")
    assert len(f) == 1
    assert f[0].severity == "WARN"
    assert f[0].symbol == "r"
    assert "32 bits" in f[0].message and "8 bits" in f[0].message


# ── NEG-2: two real truncations in two different modules → BOTH flagged ──────
def test_neg2_two_real_truncations_two_modules_both_flagged(tmp_path):
    f = _trunc(
        tmp_path,
        "module m1(input clk, input [31:0] a, output reg [7:0] r);\n"
        "  always @(*) r = a;\nendmodule\n"
        "module m2(input clk, input [15:0] b, output reg [3:0] s);\n"
        "  always @(*) s = b;\nendmodule\n")
    assert len(f) == 2
    symbols = sorted(x.symbol for x in f)
    assert symbols == ["r", "s"]
    # line numbers computed against the FULL src (region-base offset): the second
    # module's truncation is NOT reported at the first module's line.
    lines = sorted(x.line for x in f)
    assert lines == [2, 5]


# ── NEG-3: in-module [W-1:0] param-width correct assignment → not flagged ────
def test_neg3_param_width_correct_assignment_clean(tmp_path):
    """Param resolution intact WITHIN the region: an equal-width `[W-1:0]`
    assignment is not flagged."""
    assert _trunc(
        tmp_path,
        "module m #(parameter W=32)(input clk, input [W-1:0] a, "
        "output reg [W-1:0] y);\n"
        "  always @(*) y = a;\nendmodule\n") == []


# ── helper: the region-scoped worker is exposed and correct ──────────────────
def test_region_worker_scopes_width_lookup(tmp_path):
    """`_assign_width_truncate_in_region` over module `b`'s region resolves `r`
    to 32 bits (its OWN decl), not module `a`'s 8 bits → no finding."""
    src = H.strip_comments(_GAPP_FP)
    regions = H._module_regions(src)
    names = [n for n, _, _ in regions]
    assert names == ["a", "b"]
    all_findings = []
    for _n, lo, hi in regions:
        all_findings += H._assign_width_truncate_in_region(src, "dut.sv", lo, hi)
    assert all_findings == []
