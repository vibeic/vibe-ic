"""#2098 — one classification for a finding a gate says cannot be waived.

`l6_fsm_scaffold_actionable_check` printed "this blocking applicability
finding is not waiverable" while `flow_compliance_check` recorded the very
same step as ``WAIVED-DEFERRED: l6_fsm_scaffold_actionable_check — …
(ticket=ENFORCEMENT:advisory, review_required=true)``. Two programs, two
answers about ONE finding, and the flow's answer is the one that decides the
verdict — so the gate's sentence was decoration.

Read the enforcement contract before choosing a side, as the issue asks. The
flow row wires this gate ``advisory_program_exit_zero``, and its own
``advisory_reason`` says exactly what that advisory class is FOR: the L6
prose-walker "emits `transitions: []` every time it runs", so blocking would
fail 41 of 107 published roots for one producer defect. That is a statement
about the gate's ordinary actionability debt. It is not a statement about the
#1977 applicability contradiction — a finding that L6's own no-FSM claim is
contradicted by input-side RTL structure, which no producer repair makes go
away. So the flow's waiver policy is the side that has to recognise the gate's
non-waiverable class; the gate keeps the claim, and now says it on a channel
the flow reads.

Both directions are proved here: a non-waiverable finding cannot be deferred,
and an advisory one still can.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


GATE = "l6_fsm_scaffold_actionable_check"
PROG = PROGRAMS / f"{GATE}.py"

AUTHORED_FSM = """
module core_ctrl(input clk, input rst, output reg done);
  reg [2:0] state;
  always @(posedge clk) begin
    if (rst) state <= 3'd0;
    else case (state)
      3'd0: state <= 3'd1;
      3'd1: state <= 3'd2;
      3'd2: state <= 3'd0;
      default: state <= 3'd0;
    endcase
  end
  always @(posedge clk) done <= (state == 3'd2);
endmodule
"""

NO_FSM_RTL = """
module datapath(input clk, input [7:0] a, output reg [7:0] y);
  always @(posedge clk) y <= a + 8'd1;
endmodule
"""

L1_CPU = {
    "ic_name": "synth_core",
    "description": ("A 32-bit RV32I soft-core processor. The instruction set "
                    "is fixed by the input; the program counter and the "
                    "register file are architectural state."),
    "interface": "wishbone",
}
L2_CPU = {"architecture": ("bit-serial datapath; instruction fetch over the "
                           "memory bus. The micro-architecture, including any "
                           "control structure, is left to the implementer.")}

#: L6 as the producer honestly writes it when the input documents no FSM.
L6_SILENT_INPUT = {
    "fsm_states": [], "fsm_machines": [], "fsm_states_source": [],
    "no_fsm_in_input": True, "no_fsm_states_in_input": True,
}
#: L6 that DOES declare a control FSM, unscaffoldably (zero transitions) —
#: the ordinary actionability debt the flow row's advisory_reason is about.
L6_UNSCAFFOLDABLE = {
    "no_fsm_in_input": False, "no_fsm_states_in_input": False,
    "fsm_states": [{"name": "IDLE", "transitions": [], "actions": [],
                    "evidence": "datasheet p1"},
                   {"name": "RUN", "transitions": [], "actions": [],
                    "evidence": "datasheet p1"}],
}


def _project(tmp_path: Path, name: str, l6: dict) -> Path:
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(L1_CPU), encoding="utf-8")
    (gd / "L2_ARCHITECTURE.json").write_text(json.dumps(L2_CPU),
                                             encoding="utf-8")
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps(l6),
                                              encoding="utf-8")
    return proj


def _stage_rtl_from_input(project: Path, body: str = AUTHORED_FSM) -> Path:
    """RTL the way a reused-IP design has it: it arrives in the INPUT."""
    vdir = project / "input" / "vendor_rtl"
    vdir.mkdir(parents=True, exist_ok=True)
    path = vdir / "core_ctrl.v"
    path.write_text(body, encoding="utf-8")
    return path


def _give_umbrella_an_rtl_dir(project: Path, body: str = NO_FSM_RTL) -> Path:
    """`_run_structural_rtl_gates` returns "not executed" with no RTL dir."""
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    path = rtl / "datapath.v"
    path.write_text(body, encoding="utf-8")
    return path


def _run_gate(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _contradiction_project(tmp_path: Path, name: str) -> Path:
    proj = _project(tmp_path, name, L6_SILENT_INPUT)
    _stage_rtl_from_input(proj)
    _give_umbrella_an_rtl_dir(proj)
    return proj


def _ordinary_debt_project(tmp_path: Path, name: str) -> Path:
    proj = _project(tmp_path, name, L6_UNSCAFFOLDABLE)
    _give_umbrella_an_rtl_dir(proj)
    return proj




# ---------------------------------------------------------------------------
# The premise: without the two-source advisory class there is nothing to
# override, so state it rather than assume it.
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Direction 1 — a NON-waiverable finding cannot be deferred.
# ---------------------------------------------------------------------------

def test_the_gate_declares_the_contradiction_on_a_machine_channel(tmp_path):
    """The claim moves from an English sentence to a token the flow reads."""
    r = _run_gate(_contradiction_project(tmp_path, "declares"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "not\n              waiverable" in r.stdout or \
           "not waiverable" in " ".join(r.stdout.split()), r.stdout
    tokens = [ln for ln in r.stderr.splitlines()
              if ln.lstrip().startswith("NON_WAIVERABLE:")]
    assert tokens, (
        "the gate says the finding is not waiverable in prose only; the "
        "consumer reads tokens, so the claim cannot bind: " + r.stderr)
    assert "EXTRACTION_APPLICABILITY_CONTRADICTION" in tokens[0]






# ---------------------------------------------------------------------------
# Direction 2 — an ADVISORY finding still can be deferred. The advisory class
# exists for a measured reason (the L6 transition producer) and this must not
# quietly promote it.
# ---------------------------------------------------------------------------

def test_ordinary_actionability_debt_carries_no_token(tmp_path):
    r = _run_gate(_ordinary_debt_project(tmp_path, "debt_token"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert not [ln for ln in (r.stdout + "\n" + r.stderr).splitlines()
                if ln.lstrip().startswith("NON_WAIVERABLE:")], (
        "the ordinary transitions-debt FAIL claimed non-waiverability it "
        "does not have: " + r.stdout + r.stderr)








# ---------------------------------------------------------------------------
# The detector itself: a token, not prose.
# ---------------------------------------------------------------------------


