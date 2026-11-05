"""Issue #1975 — Step 4 must not turn connectivity into functional evidence.

The bidirectional control is intentionally split across the same public gates
the flow runs:

* positive: a self-checking TB under ``sim_full_stack/`` is discovered, and a
  non-zero professional JUnit denominator closes the functional requirement;
* negatives: placeholder/no-DUT, connectivity-only, and absent TB trees do not
  release Step 4.

The tests are structural and chip-agnostic. No simulator is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import vacuous_testbench_check as VACUOUS  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


SELF_CHECKING_TB = """\
module tb_dut_core;
  reg clk = 0;
  reg [7:0] a = 1, b = 2;
  wire [7:0] q;
  dut_core u_dut (.clk(clk), .a(a), .b(b), .q(q));
  always #5 clk = ~clk;
  initial begin
    #11;
    assert (q === (a + b)) else $fatal(1, "declared add behavior failed");
    $finish;
  end
endmodule
"""

CONNECTIVITY_ONLY_TB = """\
module tb_dut_core;
  reg clk = 0;
  wire alive;
  dut_core u_dut (.clk(clk), .alive(alive));
  always #5 clk = ~clk;
  initial begin #20; $display("FULL_STACK_TB_DONE"); $finish; end
endmodule
"""

PLACEHOLDER_TB = """\
module tb_dut_core;
  initial begin
    $display("PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  // dut_core u_dut (.clk(clk));
endmodule
"""

JUNIT_PASS = (
    "<testsuites><testsuite name='functional' tests='1' failures='0' "
    "errors='0' skipped='0'><testcase name='declared_behavior'/>"
    "</testsuite></testsuites>"
)


def _full_stack_tb(project: Path, body: str) -> Path:
    root = project / "phase2/stage1/sim_full_stack"
    root.mkdir(parents=True, exist_ok=True)
    (root / "tb_dut_core_full.v").write_text(body)
    return root












def test_real_reference_tb_in_sim_full_stack_is_not_hidden(tmp_path):
    real_tb = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "tools",
        "protocol_tb", "aid_class_reference_tb.v")
    root = tmp_path / "phase2/stage1/sim_full_stack"
    root.mkdir(parents=True)
    (root / "aid_class_reference_tb.v").symlink_to(real_tb)

    rec = VACUOUS.check(tmp_path)
    assert rec["verdict"] == "PASS", rec
    assert Path(rec["sim_root"]) == root
    assert rec["testbenches_scanned"] == 1


def test_placeholder_no_dut_tb_in_sim_full_stack_fails(tmp_path):
    root = _full_stack_tb(tmp_path, PLACEHOLDER_TB)
    res = VACUOUS.check(tmp_path)
    assert Path(res["sim_root"]) == root
    assert res["verdict"] == "FAIL", res
    assert "no_live_instantiation" in res["detectors_tripped"]
