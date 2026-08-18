"""Step-2.7 §4.05 guard for the PR #9 Rule-15 per-module scoping.

PR #9 scoped rtl_hygiene Rule-15 (assign-width-truncate) per module to kill a
cross-module same-named-reg false-positive. But it also partitioned PARAMETER
resolution per module, so a reg whose width param lives in a `package` (or file
scope) OUTSIDE the module region could no longer resolve `[NAME-1:0]` — a genuine
within-module truncation was then silently DROPPED (Step-2.7 HIGH false-skip,
ground-truthed against verilator WIDTHTRUNC).

FIX: resolve package-/file-scope params GLOBALLY (`_global_param_consts`) and seed
each per-region width map with them (`extra_consts`), while in-region params still
override (so the cross-module same-name FP fix is preserved). This file PINS the
no-leak (package param) case AND the two FP cases that must stay clean.

chip-AGNOSTIC: pure module-scope + parameter-scope parse.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402


def _truncate_findings(src):
    return [f for f in H.rule_assign_width_truncate(src, "d.sv")
            if "assign-width-truncate" in (getattr(f, "rule", "") or getattr(f, "msg", "") or str(f))]


_PKG_PARAM = """\
package widths_pkg;
  parameter int NARROW = 8;
endpackage

module dut
  import widths_pkg::*;
  (input clk);
  reg [NARROW-1:0] narrow_r;
  reg [31:0]       wide_r;
  always @(posedge clk) begin
    narrow_r <= wide_r;
  end
endmodule
"""

_FILE_SCOPE_PARAM = """\
parameter int NARROW = 8;
module dut(input clk);
  reg [NARROW-1:0] narrow_r;
  reg [31:0]       wide_r;
  always @(posedge clk) narrow_r <= wide_r;
endmodule
"""

# cross-module same-named reg of different widths, correct in-module assigns —
# the FP the PR fixes; must stay CLEAN.
_XMOD_FP = """\
module a(input clk, input [9:0] din, output reg [9:0] q);
  reg [9:0] mem_addr_r;
  always @(posedge clk) begin mem_addr_r <= din; q <= mem_addr_r; end
endmodule
module b(input clk, input [31:0] din, output reg [31:0] q);
  reg [31:0] mem_addr_r;
  always @(posedge clk) begin mem_addr_r <= din; q <= mem_addr_r; end
endmodule
"""

# same-named localparam at DIFFERENT values per module — must stay CLEAN
# (in-region param overrides the global seed; no cross-module collision).
_SAME_LOCALPARAM = """\
module a(input clk); localparam W=4; reg [W-1:0] r; reg [W-1:0] s; always @(posedge clk) r<=s; endmodule
module b(input clk); localparam W=8; reg [W-1:0] r; reg [W-1:0] s; always @(posedge clk) r<=s; endmodule
"""


def test_package_scope_width_param_truncate_still_fires():
    f = _truncate_findings(_PKG_PARAM)
    assert len(f) >= 1, "package-param width-truncate (wide_r 32 -> narrow_r 8) must fire"


def test_file_scope_width_param_truncate_still_fires():
    assert len(_truncate_findings(_FILE_SCOPE_PARAM)) >= 1


def test_global_param_consts_collects_outside_module_params_only():
    g = H._global_param_consts(_PKG_PARAM)
    assert g.get("NARROW") == 8
    # a localparam declared INSIDE a module must NOT leak into the global map
    g2 = H._global_param_consts(_SAME_LOCALPARAM)
    assert "W" not in g2


def test_cross_module_same_name_reg_fp_stays_clean():
    assert _truncate_findings(_XMOD_FP) == []


def test_same_named_localparam_diff_values_stays_clean():
    assert _truncate_findings(_SAME_LOCALPARAM) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
