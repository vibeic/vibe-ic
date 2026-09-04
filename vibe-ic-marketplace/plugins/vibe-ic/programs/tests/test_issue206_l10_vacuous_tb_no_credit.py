#!/usr/bin/env python3
"""Regression for #206 — l10_tb_conformance_check must NOT award coverage
credit to a testbench that never instantiates the DUT.

The defect: the gate greps a blob of ALL testbench text for the case id / opcode
and counts a case "covered" on a match. A placeholder testbench prints
`$display("[TB corner_operand] PASS_PLACEHOLDER (replace with real stimulus)")`
and leaves the DUT commented out — so the case id lands in the blob and the case
was credited. Five such files earned PASS 5/5: a check counting cases PRESENT,
not cases EXERCISED.

The fix shares the SUBSTANCE detector with vacuous_testbench_check
(#209): when nothing under the sim tree drives the DUT the "evidence" is theatre,
so the blob is suppressed and genuine digital cases FAIL — while a tree with a
real driver keeps its full evidence corpus (a trace-companion TB beside a driver
still credits its cases), and the anchored A/M verification_intent waiver path is
untouched.

chip-AGNOSTIC: synthetic generic module/case names only.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l10_tb_conformance_check as gate   # noqa: E402
import _l10_execution as execution        # noqa: E402
import vacuous_testbench_check as vtb      # noqa: E402


# The exact shape the scaffolder emits: portless module, PASS_PLACEHOLDER
# printed with the case id, DUT instantiation commented out. Never drives.
VACUOUS_TB = """\
module tb_corner_operand;
  reg clk, reset_n;
  initial begin
    clk = 0; reset_n = 0;
    #1000 $display("[TB corner_operand] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  // widget u_dut (.clk(clk), .reset_n(reset_n));
endmodule
"""

# A genuinely-exercising testbench: a LIVE (uncommented) DUT instantiation.
DRIVING_TB = """\
module tb_corner_operand;
  reg clk, reset_n;
  wire done;
  widget u_dut (.clk(clk), .reset_n(reset_n), .done(done));
  initial begin
    clk = 0; reset_n = 0; #20 reset_n = 1;
    #1000 if (done !== 1'b1) begin $display("[TB corner_operand] FAIL"); $fatal; end
    $display("[TB corner_operand] PASS");
    $finish;
  end
endmodule
"""

# A portless documentation/trace companion — emits an L10 trace marker and
# instantiates nothing BY DESIGN. Legitimate ONLY beside a real driver.
TRACE_COMPANION = """\
module l10_coverage_trace;
  initial $display("[L10] case corner_operand covered");
endmodule
"""

CASES = [{"id": "corner_operand", "category": "state_transition"}]


def _run(tmp_path: Path, tb_files: dict, executed=None) -> tuple[int, dict]:
    tb = tmp_path / "sim" / "tb"
    tb.mkdir(parents=True)
    for name, body in tb_files.items():
        (tb / name).write_text(body)
    l10 = tmp_path / "L10_TEST_CASES.json"
    l10.write_text(json.dumps(CASES))
    if executed:
        execution.write_record(
            tmp_path, l10,
            [{"id": case_id, "verdict": verdict, "sim_executed": True}
             for case_id, verdict in executed.items()], producer="test")
    out = tmp_path / "reports" / "l10_tb_conformance.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--project", str(tmp_path), "--out", str(out)])
    return rc, json.loads(out.read_text())


# ---------------------------------------------------------------------------
# THE DEFECT — a vacuous tree must FAIL, not score PASS n/n.
# ---------------------------------------------------------------------------
def test_vacuous_tb_tree_fails(tmp_path):
    rc, rep = _run(tmp_path, {"corner_operand.v": VACUOUS_TB})
    assert rc == 1, "a testbench that never instantiates the DUT must FAIL L10"
    assert rep["vacuous_sim_tree"] is True
    assert rep["sim_tree_drives_dut"] is False
    assert rep["not_executed"] == 1 and rep["ok"] == 0
    # evidence emission (#206 point 3): the offending file is named.
    assert any("corner_operand.v" in f for f in rep["vacuous_testbench_files"])


def test_five_vacuous_tbs_do_not_earn_full_credit(tmp_path):
    """The literal reported symptom: five placeholder files, PASS 5/5 before."""
    cases = [{"id": f"case_{i}", "category": "state_transition"}
             for i in range(5)]
    tb = tmp_path / "sim" / "tb"
    tb.mkdir(parents=True)
    for i in range(5):
        (tb / f"case_{i}.v").write_text(
            VACUOUS_TB.replace("corner_operand", f"case_{i}"))
    l10 = tmp_path / "L10.json"
    l10.write_text(json.dumps(cases))
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb), "--out", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 1, "five vacuous TBs must not earn 5/5 coverage"
    assert rep["ok"] == 0 and rep["not_executed"] == 5


# ---------------------------------------------------------------------------
# NO REGRESSION — a genuinely-driving tree must still PASS; a trace companion
# beside a real driver must still credit its case.
# ---------------------------------------------------------------------------
def test_driving_tb_still_passes(tmp_path):
    rc, rep = _run(tmp_path, {"corner_operand.v": DRIVING_TB},
                   executed={"corner_operand": "PASS"})
    assert rc == 0, "a testbench that really drives the DUT must PASS"
    assert rep["vacuous_sim_tree"] is False
    assert rep["sim_tree_drives_dut"] is True
    assert rep["ok"] == 1 and rep["fail"] == 0


def test_trace_companion_beside_driver_still_credits(tmp_path):
    """A driving TB + a portless trace companion: the tree drives, so its full
    evidence corpus stands and the trace marker still credits the case."""
    rc, rep = _run(tmp_path, {"corner_operand.v": DRIVING_TB,
                              "l10_coverage_trace.v": TRACE_COMPANION},
                   executed={"corner_operand": "PASS"})
    assert rc == 0
    assert rep["vacuous_sim_tree"] is False
    assert rep["ok"] == 1


# ---------------------------------------------------------------------------
# ALIGNMENT — l10 and the vacuous gate share ONE substance verdict; they must
# never disagree about whether a given tree drives the DUT.
# ---------------------------------------------------------------------------
def test_shared_substance_helper_agrees(tmp_path):
    assert vtb.any_source_drives_dut([VACUOUS_TB]) is False
    assert vtb.any_source_drives_dut([DRIVING_TB]) is True
    assert vtb.source_drives_dut(TRACE_COMPANION) is False
    # l10's verdict is driven by that same helper.
    rc_vac, _ = _run(tmp_path / "a", {"t.v": VACUOUS_TB})
    rc_drv, _ = _run(tmp_path / "b", {"t.v": DRIVING_TB},
                     executed={"corner_operand": "PASS"})
    assert (rc_vac, rc_drv) == (1, 0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
