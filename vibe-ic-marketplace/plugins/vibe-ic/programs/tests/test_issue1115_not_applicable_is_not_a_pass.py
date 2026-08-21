"""NOT_APPLICABLE must not reach the flow as PASS. vibe-ic#1115.

`vacuous_testbench_check` writes `"reason": "no sim tree (step did not run)"`
into its own JSON and then exits 0. `flow_compliance_check` reads the EXIT CODE,
so the step was recorded as a plain PASS: the producing step emitted nothing and
the checker read the absence as consent.

That is LibreLane 3.0.8's `klayout.py:486-490` shape — `return {}` when the PDK
has no DRC deck, so `Checker.KLayoutDRC` finds nothing, warns, and passes — in
our own tree, found by `tools/liar_census.py --probes empty_output`.

The repair is the channel this repo already owns: `flow_compliance_check`
promotes the step to the VACUOUS_PASS tier ON THE PASSING PATH when stdout
carries the prefix. rc stays 0, because flipping it would fail every
legitimately sim-free project — a permanently red gate is a gate people route
around. What changes is that the flow stops recording "checked, fine" for a
thing nobody checked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "vacuous_testbench_check.py"

sys.path.insert(0, str(PROGRAMS))
from flow_compliance_check import _stdout_signals_vacuous  # noqa: E402


def _run(project: Path):
    p = subprocess.run([sys.executable, str(GATE), str(project)],
                       capture_output=True, text=True, timeout=55)
    return p.returncode, p.stdout + p.stderr


def test_no_sim_tree_is_disclosed_as_vacuous_not_recorded_as_a_pass(tmp_path):
    """The producer never ran. rc 0 alone would reach the flow as PASS."""
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert '"verdict": "NOT_APPLICABLE"' in out, out
    assert _stdout_signals_vacuous(out), (
        "the gate exited 0 over a project whose sim step never ran, and said "
        "nothing the consumer reads — so `flow_compliance_check` records PASS "
        f"for a testbench nobody examined:\n{out}")


def test_the_disclosure_says_the_population_was_zero(tmp_path):
    """A reader has to be able to tell '0 vacuous testbenches out of 40' from
    '0 out of 0'. The count is the whole difference."""
    _, out = _run(tmp_path)
    assert "0 testbench(es)" in out, out
    assert "no sim tree" in out, out


def test_a_populated_tree_still_passes_WITHOUT_the_vacuous_marker(tmp_path):
    """The false-positive control, and the one that stops this being a ban: a
    real testbench with a real assertion is an ordinary PASS, and marking it
    vacuous would demote every honest run."""
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True)
    # A live testbench by this gate's own definition: it INSTANTIATES the DUT
    # and asserts a falsifiable property. Both halves are required -- the first
    # fixture here had the assertion and no instantiation, and the gate
    # correctly called it vacuous, which is the assertion working.
    (sim / "tb_top.sv").write_text(
        "module tb_top;\n"
        "  reg clk = 0; reg rst = 1; wire q;\n"
        "  dut u_dut (.clk(clk), .rst(rst), .q(q));\n"
        "  always #5 clk = ~clk;\n"
        "  initial begin\n"
        "    #20 rst = 0;\n"
        "    #20 if (q !== 1'b1) $fatal(1, \"q wrong after reset\");\n"
        "    $display(\"PASS\");\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n")
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert '"verdict": "NOT_APPLICABLE"' not in out, out
    assert not _stdout_signals_vacuous(out), (
        "a populated sim tree was disclosed as vacuous — this would demote "
        f"every honest run to VACUOUS_PASS:\n{out}")


def test_a_real_vacuous_testbench_still_FAILS(tmp_path):
    """The paired guard. If this went green the gate would have become a
    disclosure with no teeth."""
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True)
    (sim / "tb_top.sv").write_text(
        "module tb_top;\n"
        "  initial begin\n"
        "    $display(\"hello\");\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n")
    rc, out = _run(tmp_path)
    assert rc == 1, (
        "a testbench that asserts nothing was not caught — the gate's own "
        f"subject:\n{out}")
