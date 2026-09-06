"""rc 2 from `vacuous_testbench_check` is a disclosed skip, not a failure.

TWO CONSUMERS OF ONE EXIT CODE DISAGREED.

  * `vacuous_testbench_check` prints `VACUOUS_PASS:` and exits 2 when it found
    no testbench to examine, and says in its own words that this is "the
    flow's disclosed-skip convention"; `program_exit_zero` consumes it as
    VACUOUS_PASS.
  * `design_one_shot_runner.step_step4_functional_evidence` did
    `if vacuous_rc != 0: ... "FAIL"`, so the identical code meant "the
    testbench is vacuous" there.

A gate that examined nothing has accused nobody, and reddening a run on its
silence hands the reader a reason that names the wrong thing.

AND THE EXIT CODE ALONE CANNOT SETTLE IT. rc 2 has a SECOND producer inside
the checker: an `OSError` is written as verdict `IO_ERROR` and also exits 2.
"Could not read it" is not "read it and there was nothing", so the two must
not collapse into one branch — the REPORT'S VERDICT decides, and IO_ERROR
keeps the blocking behaviour it has today.

The checker's own module header used to state the contract the OTHER way
("exit 2 = NOT_APPLICABLE / IO error (blocking vacuity tier in Step 4)"),
contradicting the branch forty lines below it. The runner was implementing the
header. Both are pinned here so they cannot drift apart again.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
CHECKER = PROGRAMS / "vacuous_testbench_check.py"
sys.path.insert(0, str(PROGRAMS))


# ── the checker's contract, as the checker states it ───────────────────────

def test_header_and_branch_agree_that_rc2_is_the_disclosed_skip():
    # ASKED OF THE PARSER, not sliced off the front of the file. The file
    # opens with a shebang, so `src.index('"""', 3)` lands on the docstring's
    # OPENING quote and every assertion below then measures the shebang line.
    import ast
    header = ast.get_docstring(ast.parse(CHECKER.read_text())) or ""
    assert "DISCLOSED-SKIP" in header.upper(), (
        "the module header no longer states the disclosed-skip convention")
    assert "NOT ON THE BARE EXIT CODE" in header.upper(), (
        "the header must tell a consumer to branch on the report's verdict; "
        "the previous header told it the opposite and a consumer obeyed")
    assert "blocking vacuity tier in Step 4" not in header, (
        "the retired contract line is back in the header — that is the "
        "sentence the runner was implementing when it read rc 2 as a FAIL")


def test_checker_still_distinguishes_its_two_rc2_verdicts():
    """The distinction the fix depends on must exist in the checker."""
    src = CHECKER.read_text()
    assert 'verdict == "NOT_APPLICABLE"' in src
    assert 'verdict == "IO_ERROR"' in src


# ── the checker, run for real, on each of its three reachable verdicts ─────

def _tb(project: Path, body: str) -> Path:
    d = project / "phase2" / "stage1" / "sim" / "tb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tb_x.v").write_text(body)
    return project


_LIVE = """module tb_y;
  reg clk = 0; reg [7:0] d = 0; wire [7:0] q;
  dut u_dut (.clk(clk), .d(d), .q(q));
  always #5 clk = ~clk;
  initial begin
    d = 8'h5a; #20;
    if (q !== 8'h5a) $fatal(1, "mismatch");
    $display("TEST PASSED");
    $finish;
  end
endmodule
"""

_VACUOUS = """module tb_x;
  initial begin
    $display("TEST PASSED");
    $finish;
  end
endmodule
"""


def _run_checker(project: Path):
    import subprocess
    rep = project / "r.json"
    cp = subprocess.run(
        [sys.executable, str(CHECKER), str(project), "--json", str(rep)],
        capture_output=True, text=True, timeout=300)
    return cp.returncode, json.loads(rep.read_text()), cp.stdout


def test_checker_rc0_is_pass(tmp_path):
    rc, rep, _ = _run_checker(_tb(tmp_path, _LIVE))
    assert (rc, rep["verdict"]) == (0, "PASS")


def test_checker_rc1_is_a_real_finding(tmp_path):
    rc, rep, _ = _run_checker(_tb(tmp_path, _VACUOUS))
    assert (rc, rep["verdict"]) == (1, "FAIL")


def test_checker_rc2_on_an_empty_tree_is_not_applicable(tmp_path):
    rc, rep, out = _run_checker(tmp_path)
    assert (rc, rep["verdict"]) == (2, "NOT_APPLICABLE")
    assert any(l.startswith("VACUOUS_PASS:") for l in out.splitlines()), (
        "the stdout sentinel must be at LINE start — `_stdout_signals_vacuous` "
        "matches it there, and the report JSON is printed ahead of it, so a "
        "string-start test measures the JSON blob instead")


# ── the runner's decision, on each (rc, verdict) pair ──────────────────────

@pytest.fixture
def step4(monkeypatch, tmp_path):
    """Drive `step_step4_functional_evidence` with a chosen (rc, verdict).

    The decision under test is "which of the two rc-2 verdicts is this", so
    the (rc, report) pair is the input and is supplied directly. Inducing a
    real `IO_ERROR` needs a tree the checker cannot read, which is not
    reproducible across the hosts this suite runs on; the branch would then be
    exercised nowhere, and an unexercised branch is where this whole class of
    bug lives.
    """
    import design_one_shot_runner as d

    project = tmp_path / "proj"
    (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (project / "phase2" / "stage1" / "rtl" / "chip_top.v").write_text(
        "module chip_top(input clk, input rst, input d, output q);\n"
        "endmodule\n")

    state = {}

    def _fake_run(cmd, cwd=None, timeout=600, env=None):
        prog = Path(cmd[1]).name if len(cmd) > 1 else ""
        if prog == "vacuous_testbench_check.py":
            rep = Path(cmd[cmd.index("--json") + 1])
            rep.parent.mkdir(parents=True, exist_ok=True)
            rep.write_text(json.dumps(
                {"gate": "vacuous_testbench",
                 "verdict": state["verdict"],
                 "reason": state.get("reason", "")}))
            return state["rc"], state.get("out", ""), ""
        if prog == "cpu_functional_oracle_waiver_check.py":
            rep = Path(cmd[cmd.index("--json") + 1])
            rep.parent.mkdir(parents=True, exist_ok=True)
            rep.write_text("{}")
            return 0, "oracle ok", ""
        raise AssertionError(f"unexpected subprocess: {cmd}")

    monkeypatch.setattr(d, "_run", _fake_run)

    def drive(rc, verdict, reason="", with_results=True):
        state.update(rc=rc, verdict=verdict, reason=reason)
        sim = d._pl.sim_dir(project)
        sim.mkdir(parents=True, exist_ok=True)
        rx = sim / "results.xml"
        if with_results:
            rx.write_text("<testsuites/>")
        elif rx.exists():
            rx.unlink()
        return d.step_step4_functional_evidence(project, "digital_cmd_driven")

    return drive


def test_rc0_still_passes(step4):
    """CONTROL. rc 0 is unchanged."""
    assert step4(0, "PASS").status == "PASS"


def test_rc1_is_still_a_fail(step4):
    """CONTROL, and the one that matters most: a REAL vacuous testbench must
    still redden the run. A fix that made rc 2 non-blocking by making every
    non-zero non-blocking would pass every other test in this file."""
    sr = step4(1, "FAIL", reason="vacuous testbench")
    assert sr.status == "FAIL"
    assert "rc=1" in sr.detail


def test_rc2_not_applicable_is_not_a_failure(step4):
    """THE FIX. RED BEFORE IT: `status == "FAIL"`, detail
    `vacuous_testbench_check rc=2: ...`."""
    sr = step4(2, "NOT_APPLICABLE", reason="no sim tree (step did not run)")
    assert sr.status != "FAIL", sr.detail
    assert "vacuous_testbench_check rc=2" not in sr.detail


def test_rc2_not_applicable_is_disclosed_not_swallowed(step4):
    """And it is not silently green either — the skip is stated in the record,
    with the gate's own reason, so a reader can see that this run's Step 4
    carries a gate that examined nothing."""
    sr = step4(2, "NOT_APPLICABLE", reason="no sim tree (step did not run)")
    assert sr.extras.get("vacuous_disclosed_skip"), sr.extras
    assert "NOT_APPLICABLE" in sr.extras["vacuous_disclosed_skip"]


def test_rc2_io_error_still_blocks(step4):
    """THE SECOND PRODUCER OF rc 2. A gate that could not READ the tree has
    not disclosed a skip — it has failed to measure, and the run must not
    continue as though it had consented."""
    sr = step4(2, "IO_ERROR", reason="Permission denied: sim/tb")
    assert sr.status == "FAIL", sr.detail
    assert "IO_ERROR" in sr.detail, (
        "the failure must name WHICH rc-2 this was; 'rc=2' alone is the "
        "ambiguity that produced the defect")


def test_missing_evidence_still_fails_after_a_disclosed_skip(step4):
    """THE DIRECTION WRITTEN DOWN FIRST, and the one that decides whether this
    change weakened anything: a project with no functional evidence must still
    FAIL after the rc-2 skip stops being read as a failure. It does — on
    `no results.xml`, which is the branch that actually owns that question and
    states the true reason."""
    sr = step4(2, "NOT_APPLICABLE", reason="no sim tree", with_results=False)
    assert sr.status == "FAIL"
    assert "results.xml" in sr.detail
