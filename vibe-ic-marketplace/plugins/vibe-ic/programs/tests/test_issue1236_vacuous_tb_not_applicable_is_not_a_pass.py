"""The FOURTH gate of the shape #1173 repaired. vibe-ic#1115, re-implementing #1236.

`test_issue1115b_three_channel_repairs.py` fixed three gates that had already
decided a run was inapplicable and said so on no channel that changes a verdict.
`vacuous_testbench_check` is the same shape and was left out of that batch, and
it is the one this repo can least afford to leave silent: it is the ONLY
UNCONDITIONAL program in step 4's gate (the flow says so in its own comment —
"the only unconditional program in this gate is vacuous_testbench_check"), so
when it says nothing, nothing else in that step is obliged to speak.

WHAT IT DID
-----------
On a project with no sim tree it writes

    {"gate": "vacuous_testbench", "verdict": "NOT_APPLICABLE",
     "reason": "no sim tree (step did not run)"}

to stdout and to its `--json` report, and exits 2. `_check_program_exit_zero`
reads that as the disclosed-skip tier and also reads the stdout channel:
`_stdout_signals_vacuous`, which matches `VACUOUS_PASS` at LINE START. A JSON
blob carrying the word inside a quoted field does not match it. MEASURED against
the consumer itself, on the pre-fix program:

    _stdout_signals_vacuous('{\\n  "verdict": "NOT_APPLICABLE"\\n}')  -> False

So the producer emitted nothing, the gate said so where no tier is decided, and
the step recorded an ordinary PASS.

WHY THE JSON CHANNEL DOES NOT ALREADY COVER IT
----------------------------------------------
It is read — `_json_report_signals_vacuous` returns True here. But that bucket is
COUNTED, and `check_step` promotes the step on it only when the count is
unanimous (`len(all_vacuous_cmds) >= len(ran_hints)`): every gate clause that
dispatched a program must have disclosed the same. This clause sits in an
`all_of` beside `cpu_functional_oracle_waiver_check`, `l10_tb_conformance_check`,
`l12_tb_coverage_check`, `verilator_coverage_measure` and others, so on any run
where a sibling substantively examines something the count is not unanimous and
the step still records PASS — carrying a `PARTIALLY-VACUOUS` reason, which names
the hole rather than closing it.

rc 2 is the disclosed-skip convention. The flow maps it to VACUOUS_PASS, so a
legitimately sim-free run remains non-red while a repo-level consumer can no
longer mistake zero examined testbenches for an ordinary PASS.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
from flow_compliance_check import (  # noqa: E402
    _json_report_signals_vacuous,
    _stdout_signals_vacuous,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_GATE = "vacuous_testbench_check.py"
#: the clause verbatim as `flow/phase1_phase2_phase3.yaml` writes it, so the
#: JSON channel is probed at the path the FLOW names rather than one this test
#: invented.
_CLAUSE = "vacuous_testbench_check . --json reports/phase2/gates/vacuous_testbench.json"

#: A testbench that prints a pass and never drives the design — the defect the
#: gate exists for, and the negative control every disclosure below is paired
#: with. Trips D1 (`PASS_PLACEHOLDER`) and D3 (no live instantiation anywhere).
_VACUOUS_TB = """\
module case_3;
  reg clk = 0;
  // PASS_PLACEHOLDER - replace with real stimulus
  initial begin
    $display("PASS");
    $finish;
  end
endmodule
"""

#: The same scenario written honestly: the DUT is instantiated LIVE and the
#: check is falsifiable. The gate must call this PASS and must NOT disclose it
#: as vacuous, or the repair below is a blanket amnesty.
_REAL_TB = """\
module case_3;
  reg clk = 0; reg rst_n = 0; wire [7:0] q;
  dut u_dut (.clk(clk), .rst_n(rst_n), .q(q));
  always #5 clk = ~clk;
  initial begin
    #20 rst_n = 1;
    #20 if (q !== 8'h00) begin $display("FAIL"); $finish; end
    $display("PASS"); $finish;
  end
endmodule
"""


def _run(project: Path):
    """Run the gate through the clause the FLOW declares, cwd=project."""
    argv = [sys.executable, str(PROGRAMS / _GATE)] + _CLAUSE.split()[1:]
    p = _pr.run(argv, cwd=str(project), capture_output=True,
                       text=True)
    return p.returncode, p.stdout + p.stderr


def _seed(tmp_path: Path, tb: str | None) -> Path:
    """A project root. `tb=None` is the NOT_APPLICABLE case: no sim tree at all,
    which is what a step that did not run leaves behind."""
    (tmp_path / "phase2" / "stage1").mkdir(parents=True, exist_ok=True)
    if tb is not None:
        d = tmp_path / "phase2" / "stage1" / "sim" / "tb"
        d.mkdir(parents=True, exist_ok=True)
        (d / "case_3.v").write_text(tb)
    return tmp_path


# --------------------------------------------------------------------------
# the property
# --------------------------------------------------------------------------
def test_not_applicable_reaches_the_channel_that_tiers_the_step(tmp_path):
    rc, out = _run(_seed(tmp_path, None))
    assert rc == 2, out
    assert '"verdict": "NOT_APPLICABLE"' in out, out
    assert _stdout_signals_vacuous(out), (
        "the producing step left no sim tree, the gate said so in its own JSON "
        "and did not reach the one stdout channel `check_step` "
        f"promotes on — so the flow records a plain PASS:\n{out}")


def test_the_consumer_is_shape_sensitive_which_is_why_this_was_invisible():
    """The measurement the repair rests on. The word was always in the output;
    the SHAPE is what no consumer could match. If this stopped being true the
    repair would be cargo-culting a prefix nobody needs."""
    assert _stdout_signals_vacuous("VACUOUS_PASS: vacuous_testbench examined 0")
    assert not _stdout_signals_vacuous(
        '{\n  "gate": "vacuous_testbench",\n  "verdict": "NOT_APPLICABLE"\n}')


def test_the_json_channel_alone_does_not_tier_this_step(tmp_path):
    """WHY THE STDOUT SENTINEL IS NEEDED AT ALL, stated as a measurement rather
    than as an argument.

    The gate's `--json` report IS read by the consumer — that is asserted here,
    not assumed — but `check_step` promotes on that bucket only when the count
    is unanimous across every clause in the step that dispatched a program. The
    flow gives this step several such clauses, so a lone JSON disclosure leaves
    the step reporting PASS. Both facts have to hold for the repair to be the
    right one, so both are pinned.
    """
    p = _seed(tmp_path, None)
    rc, _out = _run(p)
    assert rc == 2
    assert _json_report_signals_vacuous(p, _CLAUSE), (
        "the JSON channel stopped reading this gate's report; if that is "
        "intended, the stdout sentinel is now the ONLY disclosure and this "
        "test's premise needs rewriting rather than deleting")

    import yaml  # noqa: PLC0415
    flow = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
    doc = yaml.safe_load(flow.read_text(errors="replace"))
    # Count the clauses in THIS step that append `__RAN_HINT__` — the
    # denominator `check_step` divides by. Structural: found by locating the
    # step whose gate quotes this program, never by a step number typed here.
    dispatchers = 0
    found = False

    def walk(node):
        nonlocal dispatchers, found
        if isinstance(node, dict):
            gate = node.get("gate")
            if gate is not None and _GATE[:-3] in yaml.safe_dump(gate):
                found = True
                dispatchers = _count_dispatchers(gate)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    def _count_dispatchers(node) -> int:
        n = 0
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("program_exit_zero", "optional_program_exit_zero"):
                    n += 1
                else:
                    n += _count_dispatchers(v)
        elif isinstance(node, list):
            for v in node:
                n += _count_dispatchers(v)
        return n

    walk(doc)
    assert found, f"{_GATE} is no longer wired into any gate in {flow}"
    assert dispatchers > 1, (
        f"this step now has {dispatchers} program-dispatching clause(s). With "
        f"exactly one, the counted JSON channel would be unanimous by "
        f"construction and would tier the step on its own — the stdout "
        f"sentinel would then be redundant rather than load-bearing, and this "
        f"repair's justification would need restating")


# --------------------------------------------------------------------------
# PAIRED GUARDS — the disclosure must not become a blanket amnesty
# --------------------------------------------------------------------------
def test_a_genuinely_vacuous_testbench_still_FAILS(tmp_path):
    """The direction that matters more than the green one. A sim tree that IS
    present and DOES hold a testbench printing a pass without driving the design
    must still exit 1, and must not be disclosed as vacuous — the gate examined
    something and found it deficient, which is the opposite of examining
    nothing."""
    rc, out = _run(_seed(tmp_path, _VACUOUS_TB))
    assert rc == 1, (
        f"the defect this gate exists for was waved through:\n{out}")
    assert "PASS_PLACEHOLDER" in out, out
    assert not _stdout_signals_vacuous(out), (
        f"a real finding was disclosed as 'I examined nothing':\n{out}")


def test_a_testbench_that_drives_the_DUT_stays_a_plain_PASS(tmp_path):
    """The false-positive control. A populated, honest sim tree must keep its
    PASS and must NOT be demoted to VACUOUS_PASS, or every real run loses the
    tier it earned."""
    rc, out = _run(_seed(tmp_path, _REAL_TB))
    assert rc == 0, out
    assert '"verdict": "PASS"' in out, out
    assert not _stdout_signals_vacuous(out), (
        f"a populated run was demoted to VACUOUS_PASS:\n{out}")


def test_an_empty_sim_tree_is_also_not_applicable(tmp_path):
    """The other arm of the same verdict: the sim directory exists but holds no
    testbench. That is still a producer that emitted nothing, and it must
    disclose on the same channel as the no-tree case — otherwise the repair
    covers one spelling of the hole and not the hole."""
    p = _seed(tmp_path, None)
    (p / "phase2" / "stage1" / "sim").mkdir(parents=True, exist_ok=True)
    rc, out = _run(p)
    assert rc == 2, out
    assert "NOT_APPLICABLE" in out, out
    assert _stdout_signals_vacuous(out), out
