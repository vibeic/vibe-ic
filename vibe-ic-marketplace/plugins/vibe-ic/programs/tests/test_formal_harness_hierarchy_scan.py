#!/usr/bin/env python3
"""The Step-5 formal harness search covered ONE PATH and answered for the DESIGN.

`_pick_provable` preferred the declared top and then descended through thin
single-child rename wrappers. The descent gave up the moment a module
instantiated anything other than exactly one child — and `generate` then
reported

    "no module with a construction-safe reset-safety property"

which is a statement about every module there is, derived from having examined
a single chain of them.

MEASURED (subservient x sky130A, round 1). `subservient` instantiates TWO
children, so the walk broke at the top and step 5 reported NOT_APPLICABLE.
Pointing the SAME program at `subservient_gpio` — same project, same RTL —
emitted a complete harness with two construction-safe properties. Step 5 failed
and steps 7, 8, 10 and 11 went MISSING as blocked-by-upstream: one unreachable
branch costing five canonical steps, on every hierarchical design whose
top-level outputs are driven by more than one sub-module.

These tests pin BOTH directions, because a search that finds something is only
correct if it also declines to find the wrong thing:

  * the two-child top now emits, and DISCLOSES that the property was proven on a
    sub-module rather than on the declared top;
  * a module that is provable but instantiated NOWHERE under the top is NOT
    picked — the scan covers the design, not the directory. Picking it would
    replace one adjacent measurement with another.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1] / "formal_harness_gen.py"

#: Bound for the launch in `_run`. NOT a round number picked by feel:
#: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest harness
#: bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed.
#: The landed value was 120. MEASURED here: this generator runs against a
#: three-module Verilog string held in this file and takes 0.05 s worst of 5
#: calls, so 60 s is ~1200x headroom and the bound is a hang detector, which is
#: all it was ever meant to be.
_GEN_TIMEOUT_S = 60


def _run(tmp_path: Path, rtl: str, top: str) -> dict:
    src = tmp_path / "design.v"
    src.write_text(rtl)
    out_json = tmp_path / "res.json"
    subprocess.run(
        [sys.executable, str(PROG), "--rtl", str(src), "--top", top,
         "--out", str(tmp_path / "harness.sv"), "--json", str(out_json)],
        capture_output=True, text=True, timeout=_GEN_TIMEOUT_S)
    return json.loads(out_json.read_text())


# A top with TWO children — the exact shape the walk could not get past. Neither
# child is a rename wrapper; both carry a registered output with a literal reset
# value, so the property machinery has always been able to prove them.
TWO_CHILD = """
module top_two (input clk, input rst_n, output [7:0] o_a, output o_b);
  child_a u_a (.clk(clk), .rst_n(rst_n), .o(o_a));
  child_b u_b (.clk(clk), .rst_n(rst_n), .o(o_b));
endmodule
module child_a (input clk, input rst_n, output reg [7:0] o);
  always @(posedge clk) if (!rst_n) o <= 8'h00; else o <= o + 1;
endmodule
module child_b (input clk, input rst_n, output reg o);
  always @(posedge clk) if (!rst_n) o <= 1'b0; else o <= ~o;
endmodule
"""


def test_two_child_top_is_reachable_and_emits(tmp_path):
    """The defect itself: this used to report NOT_APPLICABLE."""
    res = _run(tmp_path, TWO_CHILD, "top_two")
    assert res["verdict"] == "EMITTED", res.get("reason")
    assert res["top"] in ("child_a", "child_b")
    assert res["selection"] == "hierarchy_scan"


def test_a_submodule_property_is_not_reported_as_the_top_s(tmp_path):
    """Emitting is only half of it — the record must not overstate WHAT was
    proven. A property proven on `child_a` is not a property of `top_two`."""
    res = _run(tmp_path, TWO_CHILD, "top_two")
    assert res["proves_declared_top"] is False
    assert res["declared_top"] == "top_two"
    assert res["top"] != "top_two"


def test_declared_top_still_wins_when_it_is_itself_provable(tmp_path):
    """The scan is a FALLBACK. A provable top must still be preferred, or the
    fix would have traded a missed proof for a weaker one."""
    rtl = """
module top_prov (input clk, input rst_n, output reg [3:0] o);
  always @(posedge clk) if (!rst_n) o <= 4'h0; else o <= o + 1;
  helper_a u_a (.clk(clk), .rst_n(rst_n));
  helper_b u_b (.clk(clk), .rst_n(rst_n));
endmodule
module helper_a (input clk, input rst_n); endmodule
module helper_b (input clk, input rst_n); endmodule
"""
    res = _run(tmp_path, rtl, "top_prov")
    assert res["verdict"] == "EMITTED"
    assert res["top"] == "top_prov"
    assert res["selection"] == "declared_top"
    assert res["proves_declared_top"] is True


def test_provable_module_outside_the_hierarchy_is_not_picked(tmp_path):
    """THE REVERSE CASE, and the one that decides whether this is a fix or a
    second adjacent measurement.

    `orphan_prov` is provable and sits in the same file — but nothing under
    `top_two_np` instantiates it, so it is not part of this design. Proving a
    reset property there would answer about a module the flow was never asked
    about. The correct answer here is still NOT_APPLICABLE.
    """
    rtl = """
module top_two_np (input clk, input rst_n, output o_a, output o_b);
  comb_a u_a (.clk(clk), .rst_n(rst_n), .o(o_a));
  comb_b u_b (.clk(clk), .rst_n(rst_n), .o(o_b));
endmodule
module comb_a (input clk, input rst_n, output o);
  assign o = rst_n & clk;
endmodule
module comb_b (input clk, input rst_n, output o);
  assign o = rst_n | clk;
endmodule
module orphan_prov (input clk, input rst_n, output reg [7:0] o);
  always @(posedge clk) if (!rst_n) o <= 8'hAB; else o <= o + 1;
endmodule
"""
    res = _run(tmp_path, rtl, "top_two_np")
    assert res["verdict"] == "NOT_APPLICABLE", (
        f"picked {res.get('top')!r}, which nothing under the top instantiates")
    # and the reason must name the scope it actually searched
    assert "hierarchy" in res["reason"]


def test_not_applicable_reason_no_longer_claims_every_module(tmp_path):
    """The old wording — "no module with a construction-safe reset-safety
    property" — was the false part: it was true of one chain, stated of all."""
    rtl = """
module top_comb (input clk, input rst_n, output o);
  assign o = clk & rst_n;
endmodule
"""
    res = _run(tmp_path, rtl, "top_comb")
    assert res["verdict"] == "NOT_APPLICABLE"
    assert res["reason"].startswith("no module in the declared top's hierarchy")
