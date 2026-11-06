"""vibe-ic#2146 — the professional-TB producer runs what it generates, or
refuses by name.

WHAT WAS BROKEN, MEASURED
=========================
`design_one_shot_runner.step_professional_tb_gen` (flow step 4, Phase-2
"Simulation") calls `professional_tb_gen.generate()`, which writes a complete
cocotb bundle into `phase2/stage1/sim_professional/<top>/` — `tb_<top>.py`,
`Makefile`, the L28 coverage model, the L29 SVA, the verification plan. It then
ran the simulator only for `dut_kind in (serial_stream, parallel_arith,
expert_reference)`. Every other class had its bundle generated and left, and
NOTHING IN THE BUNDLE SAID SO: the only trace was the absence of a
`results.xml`, which a downstream reader cannot tell apart from "the suite ran
and produced nothing".

Measured 2026-09-07 over every project root on one host carrying a
`sim_professional` tree: 346 roots, 198 with an unmeasured sibling suite of any
kind, and 145 carrying a GENERATED professional bundle (a Makefile beside a
`tb_<top>.py`) that produced no transcript at all. Three of those 145 were PASS
at Step 4 on their sibling unit-TB suite alone — the three the issue names, and
no others. (Lane czsimbridge measured 331 / 194 four hours earlier on the same
host; the corpus is live lane trees and it grew between the two readings.)

Two further facts, both measured in the pinned image (cocotb 2.2.0.dev, Icarus
14.0) and both invisible until the bundle was actually run:

  * the generic-class scaffold declared its unfilled state by raising
    `cocotb.result.TestSkip`. cocotb 2.x keeps `cocotb.result` as an empty
    shim, so that raise is `AttributeError: module 'cocotb' has no attribute
    'result'` and the transcript reads failures=1 — a FUNCTIONAL FAILURE OF
    THE DESIGN for a testbench that never reached the design.
  * `_professional_tb_exec_site` asked `_tool_in_container`, which in LOCAL
    exec mode (no docker client on PATH — a run INSIDE the image) executes on
    the local filesystem and therefore answered True for a container nothing
    had entered. The site was recorded as "container" and the run dispatched
    through a real `docker exec` argv: rc=127, no log, no transcript.

WHAT THESE TESTS PIN
====================
  * every generated bundle is either MEASURED (a parsable JUnit) or REFUSED BY
    NAME (a `professional_tb_refusal.json` naming the suite and the reason) —
    never silent;
  * the refusal names the bundle and carries a reason;
  * a stale refusal does not outlive the transcript that answers it;
  * the emitted unfilled hook binds to a skip API the running cocotb HAS, and
    the scaffold still refuses to be a vacuous pass;
  * the exec site does not claim a container in local exec mode;
  * a run whose transcript is a SKIP is still not credited as a pass.

The bundle-running arms are pure-python: the simulator is replaced at the
runner's own dispatch seams, so these tests state the CONTROL FLOW invariant
and no test here needs a simulator. The end-to-end evidence that the bundles
really run in the pinned image is the lane's acceptance measurement.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_gen as PTB             # noqa: E402


REFUSAL = "professional_tb_refusal.json"


# --------------------------------------------------------------------------
# fixtures — a project whose generator emits a bundle, with the simulator
# replaced at the runner's own seams.
# --------------------------------------------------------------------------






_SKIPPED_XML = ('<testsuites><testsuite name="tb_dut" tests="1" failures="0" '
                'errors="0" skipped="1"><testcase name="t">'
                '<skipped message="Test was skipped"/></testcase>'
                '</testsuite></testsuites>')
_PASS_XML = ('<testsuites><testsuite name="tb_dut" tests="1" failures="0" '
             'errors="0" skipped="0"><testcase name="t"/>'
             '</testsuite></testsuites>')
_FAIL_XML = ('<testsuites><testsuite name="tb_dut" tests="2" failures="1" '
             'errors="0" skipped="0"><testcase name="t"><failure/></testcase>'
             '<testcase name="u"/></testsuite></testsuites>')




# --------------------------------------------------------------------------
# THE INVARIANT
# --------------------------------------------------------------------------












# --------------------------------------------------------------------------
# THE VERDICT DOES NOT MOVE BECAUSE THE BUNDLE NOW RUNS
# --------------------------------------------------------------------------










# --------------------------------------------------------------------------
# THE EMITTED HOOK MUST BE EXPRESSIBLE IN THE TOOLCHAIN THAT RUNS IT
# --------------------------------------------------------------------------
def _generic_scaffold() -> str:
    shape = {
        "top": "widget", "kind": "generic",
        "ports": [{"name": "a", "dir": "input", "width": 4},
                  {"name": "y", "dir": "output", "width": 4}],
        "cr": {"clk": "clk", "rst": "rst_n", "period_ns": 10,
               "active_high": False},
    }
    return PTB.emit_generic_tb(shape)


def test_DEFECT_the_unfilled_hook_does_not_raise_a_removed_attribute():
    """RED on origin/main: the scaffold raised `cocotb.result.TestSkip`, and
    the pinned image's cocotb 2.2 has no `cocotb.result.TestSkip` — so running
    the bundle recorded failures=1 with an AttributeError, charging the DESIGN
    for a testbench that never reached it."""
    tb = _generic_scaffold()
    assert "raise cocotb.result.TestSkip(" not in tb, tb
    ast.parse(tb)


def test_the_unfilled_hook_binds_to_whichever_skip_api_exists():
    tb = _generic_scaffold()
    tree = ast.parse(tb)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_UNFILLED_HOOK" in names, tb
    # both arms present: the 1.x class and the 2.x pytest skip exception
    assert "from cocotb.result import TestSkip" in tb
    assert "pytest" in tb and "skip" in tb


def test_the_scaffold_is_still_never_a_vacuous_pass():
    """Unchanged property, re-asserted: it raises, and it never prints the
    token that would let the bridge credit it."""
    tb = _generic_scaffold()
    assert "PROFESSIONAL_TB PASS" in tb           # named as a REQUIREMENT
    assert "dut._log.info('PROFESSIONAL_TB PASS')" not in tb
    tree = ast.parse(tb)
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.AsyncFunctionDef)
           and any("cocotb.test" in ast.unparse(d) for d in n.decorator_list)]
    assert fns, tb
    assert any(isinstance(c, ast.Raise) for f in fns for c in ast.walk(f))


# --------------------------------------------------------------------------
# THE EXEC SITE
# --------------------------------------------------------------------------






# --------------------------------------------------------------------------
# THE REASON HAS TO BE ACTIONABLE
# --------------------------------------------------------------------------




def test_the_producer_reports_how_many_sources_it_will_compile(tmp_path):
    """`generate()` computes the source list to write the Makefile; the count
    is what lets the runner refuse an unelaboratable bundle by name."""
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "widget",
        "top_ports": [{"name": "a", "dir": "input", "width": 4},
                      {"name": "y", "dir": "output", "width": 4},
                      {"name": "clk", "dir": "input", "width": 1}],
        "clock_domains": [{"name": "clk", "source_pin": "clk"}]}))
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "widget.v").write_text(
        "module widget(input [3:0] a, input clk, output reg [3:0] y);"
        " always @(posedge clk) y <= a; endmodule\n")
    res = PTB.generate(tmp_path)
    assert res["status"] == "PASS", res
    assert res["rtl_files"] == 1, res
