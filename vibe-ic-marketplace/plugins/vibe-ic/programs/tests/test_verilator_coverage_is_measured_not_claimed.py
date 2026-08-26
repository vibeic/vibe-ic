"""Step 4's coverage must be MEASURED, not claimed.

THE DEFECT these pin. `reports/phase2/coverage/coverage_actual.json` had TWO
producers — `design_one_shot_runner`, which writes a functional-verification
verdict payload, and `verilator_coverage_measure measure`, which writes the
line/toggle/branch measurement. On every real run the functional payload won
the path, and `verilator_coverage_measure check` reported, correctly, that
line/toggle/branch was never measured for the design. It never was: the three
instrumentation flags `--coverage / --coverage-line / --coverage-toggle`
appeared in exactly ONE file in the plugin (the measure program itself) and no
runner, gate or program ever invoked it. The `measure` half was left to "the
agent before this gate", i.e. to nobody.

The three directions pinned here:

  1. THE NUMBER IS MEASURED — `measure-tb` instruments the project's own
     testbench, runs it, and reads the totals out of the coverage.dat that run
     produced.
  2. THE NUMBER MOVES — make a branch genuinely unreachable and the measured
     branch percentage falls. A number that does not move whatever the RTL
     does is not a measurement.
  3. THE CHECKER STILL REFUSES — with no measurement at the declared path
     (absent, empty, or another producer's payload) the gate does NOT pass.

Plus the structural direction that made 1-3 necessary: one producer per path,
and the measurement actually wired into a runner.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PLUGIN = PROGRAMS.parent
SCRIPT = PROGRAMS / "verilator_coverage_measure.py"
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
RUNNER = PROGRAMS / "design_one_shot_runner.py"

sys.path.insert(0, str(PROGRAMS))
import verilator_coverage_measure as gate  # noqa: E402

needs_verilator = pytest.mark.skipif(
    shutil.which("verilator") is None,
    reason="verilator not on PATH — the measurement cannot be taken here")

#: A DUT whose `always` block has exactly two branch arms, both reachable.
_DUT_BOTH_ARMS_REACHABLE = """
module dut (input wire clk, input wire rst, input wire a, output reg q);
    always @(posedge clk) begin
        if (rst) q <= 1'b0;
        else     q <= a;
    end
endmodule
"""

#: The SAME DUT with one extra arm that is structurally unreachable: it is
#: guarded by `rst` while already inside the `else` of `if (rst)`.
_DUT_WITH_UNREACHABLE_ARM = """
module dut (input wire clk, input wire rst, input wire a, output reg q);
    always @(posedge clk) begin
        if (rst) q <= 1'b0;
        else begin
            if (rst) q <= 1'b1;
            else     q <= a;
        end
    end
endmodule
"""

_TB = """
`timescale 1ns/1ps
module tb_dut_oracle;
    reg clk = 1'b0; reg rst; reg a; wire q;
    dut u (.clk(clk), .rst(rst), .a(a), .q(q));
    always #5 clk = ~clk;
    initial begin
        rst = 1'b1; a = 1'b0;
        @(posedge clk); @(posedge clk);
        rst = 1'b0;
        a = 1'b1; @(posedge clk);
        a = 1'b0; @(posedge clk);
        $finish;
    end
endmodule
"""


def _project(tmp_path: Path, dut_src: str) -> Path:
    """A minimal project in the canonical layout the runner discovers."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    rtl.mkdir(parents=True)
    sim.mkdir(parents=True)
    (rtl / "dut.v").write_text(dut_src)
    (sim / "tb_dut_oracle.v").write_text(_TB)
    return tmp_path


def _measure(project: Path) -> tuple[int, dict, str]:
    out = project / "reports" / "phase2" / "coverage" / "coverage_verilator.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "measure-tb",
         "--project", str(project), "--out", str(out)],
        capture_output=True, text=True, timeout=900)
    payload = json.loads(out.read_text()) if out.is_file() else {}
    return r.returncode, payload, r.stdout + r.stderr


# --- 1. the number is MEASURED --------------------------------------------
@needs_verilator
def test_measure_tb_reads_totals_out_of_a_real_coverage_dat(tmp_path):
    rc, payload, log = _measure(_project(tmp_path, _DUT_BOTH_ARMS_REACHABLE))
    assert rc == 0, log
    dat = Path(payload["coverage_dat"])
    assert dat.is_file(), f"no coverage.dat behind the number: {log}"
    # The totals must be reproducible FROM the data file, not merely stored
    # next to it: re-parse the .dat and demand the same numbers.
    reparsed = gate.scope_totals(gate.parse_coverage_dat(str(dat)),
                                 payload["rtl_sources"])
    assert reparsed is not None
    assert reparsed["totals"] == payload["totals"]
    for cat in ("line", "toggle", "branch"):
        assert payload["totals"][cat]["total"] > 0, \
            f"{cat} has no coverage points — nothing was instrumented"


@needs_verilator
def test_measurement_scope_excludes_the_testbench(tmp_path):
    """A testbench runs top to bottom by construction; folding it into the
    totals reports the stimulus's coverage as the design's."""
    _, payload, log = _measure(_project(tmp_path, _DUT_BOTH_ARMS_REACHABLE))
    scoped = [Path(f).name for f in payload["scope_files"]]
    assert scoped == ["dut.v"], log
    # ... while the testbench is still REPORTED, so the exclusion is visible.
    assert any("tb_dut_oracle" in Path(f).name for f in payload["per_file"])


# --- 2. the number MOVES ---------------------------------------------------
@needs_verilator
def test_branch_coverage_falls_when_a_branch_becomes_unreachable(tmp_path):
    """THE ANTI-FABRICATION CONTROL. Identical stimulus, one extra arm the
    design can never execute: the measured branch percentage must fall. If it
    does not move, the number is not a measurement."""
    _, base, log_b = _measure(
        _project(tmp_path / "reachable", _DUT_BOTH_ARMS_REACHABLE))
    _, mutant, log_m = _measure(
        _project(tmp_path / "unreachable", _DUT_WITH_UNREACHABLE_ARM))
    assert base["totals"]["branch"]["pct"] == 100.0, log_b
    assert mutant["totals"]["branch"]["total"] > \
        base["totals"]["branch"]["total"], log_m
    assert mutant["totals"]["branch"]["pct"] < \
        base["totals"]["branch"]["pct"], (
            "branch coverage did not move when a branch became unreachable — "
            f"base={base['totals']['branch']} mutant={mutant['totals']['branch']}")
    # And the unreached point is visible in the raw data as a zero-hit point.
    assert mutant["totals"]["branch"]["covered"] < \
        mutant["totals"]["branch"]["total"]


# --- 3. the checker still REFUSES an unmeasured artefact -------------------
def _check(path: Path) -> int:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "check", "--coverage-json", str(path),
         # Pin the capability decision so the verdict is a property of the
         # artefact, not of whatever the host happens to have installed.
         "--verilator-bin", "verilator"],
        capture_output=True, text=True).returncode


@pytest.mark.parametrize("content,label", [
    (None, "absent"),
    ("", "empty file"),
    ("{}", "empty object"),
    (json.dumps({"verdict": "PASS", "verification_track": "oracle_tb",
                 "vectors_passed": 28, "vectors_total": 28}),
     "another producer's functional payload"),
    (json.dumps({"line_pct": 95, "toggle_pct": 92, "branch_pct": 91}),
     "a bare percentage claim"),
])
def test_check_never_passes_without_a_measurement(tmp_path, content, label):
    p = tmp_path / "coverage_verilator.json"
    if content is not None:
        p.write_text(content)
    assert _check(p) != 0, f"check PASSED on {label} — no measurement behind it"


@needs_verilator
def test_check_passes_the_measurement_then_refuses_it_once_emptied(tmp_path):
    project = _project(tmp_path, _DUT_BOTH_ARMS_REACHABLE)
    rc, payload, log = _measure(project)
    assert rc == 0, log
    out = Path(project / "reports" / "phase2" / "coverage"
               / "coverage_verilator.json")
    assert _check(out) == 0, "a real measurement was refused"
    Path(payload["coverage_dat"]).unlink()
    out.write_text("")
    assert _check(out) != 0, \
        "check passed after the measurement was deleted"


# --- the structural direction: ONE PRODUCER PER PATH, and it is WIRED ------
def test_the_measurement_has_its_own_path(tmp_path):
    assert gate.COVERAGE_MEASUREMENT_REL != "coverage/coverage_actual.json"
    assert "coverage_actual" not in gate.COVERAGE_MEASUREMENT_REL, (
        "the measurement must not share a path with the functional-verdict "
        "payload design_one_shot_runner writes to coverage_actual.json")


def test_step4_gate_and_coverage_closure_read_the_measurement_path():
    yaml_text = FLOW_YAML.read_text()
    measurement = Path(gate.COVERAGE_MEASUREMENT_REL).name
    assert (f"verilator_coverage_measure check --coverage-json "
            f"reports/phase2/coverage/{measurement}") in yaml_text, (
        "the Step-4 coverage gate still audits a path it does not own")
    import coverage_closure
    assert coverage_closure.COVERAGE_MEASUREMENT_REL == \
        gate.COVERAGE_MEASUREMENT_REL


def test_the_flow_actually_runs_the_instrumentation():
    """`check` without a `measure` is a gate over an artefact nobody produces.
    A runner must take the measurement, with instrumentation ON."""
    runner = RUNNER.read_text()
    assert "def step_verilator_coverage(" in runner
    assert "plan.append(step_verilator_coverage(" in runner, \
        "the coverage measurement step is defined but never dispatched"
    for flag in gate.COVERAGE_INSTRUMENTATION_FLAGS:
        assert flag in SCRIPT.read_text(), f"{flag} not in the measure argv"
