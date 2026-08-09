#!/usr/bin/env python3
"""memory_read_pipeline_check: the FAIL verdict must be REACHABLE — and the
WARN/PASS verdicts must survive.

THE DEFECT
----------
The program advertises three exit codes and a three-valued verdict
(PASS / WARN / FAIL), and both of its real callers grade it purely on the
exit status:

  * ``flow/phase1_phase2_phase3.yaml`` step 2 wires it as
    ``optional_program_exit_zero`` — "conditional-on-inputs, not advisory,
    and fails its step on a non-zero exit" (flow_compliance_check's own
    words at the ADVISORY-slot comment);
  * ``flow_compliance_check._STRUCTURAL_RTL_GATES`` dispatches it in the P0
    umbrella, where rc 1 becomes a ``FAIL`` gate record and rc 0 a ``PASS``.

Every ``Finding`` the program could construct was hard-coded to severity
``WARN``, so ``fails`` was empty on every possible input, ``verdict ==
"FAIL"`` was unreachable and ``return 1`` was dead. Both callers therefore
recorded an unconditional PASS for this gate on every project that had RTL
at all — a green that no design could ever have earned or lost.

WHAT THIS FILE ASSERTS
----------------------
Only measured things: the exit code of a real run, the JSON the run emits,
and the (passed, snippet) pair the real consumer returns. Nothing here
reads the program's source, so a future edit cannot satisfy it by moving a
string around.

BOTH DIRECTIONS
---------------
A gate proven to reach FAIL and nothing else is the same disease pointing
the other way, so the FAIL cases and the PASS/WARN cases are asserted
side by side:

  reachable FAIL   a module that DOCUMENTS a no-lag read and REGISTERS it
                   (``contradictory_read_doc``), and a port carrying both a
                   procedural and a continuous driver
                   (``mixed_read_semantics``);
  reachable PASS   a registered read whose header states the 1-cycle
                   latency, and a genuinely combinational read;
  reachable WARN   a registered read that documents nothing — an omission,
                   which stays advisory and must NOT gate the flow. This
                   case is what keeps the fix from being "make every
                   memory red".

All fixtures are synthetic and name no design, PDK or part.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
PROGRAM = PROGRAMS / "memory_read_pipeline_check.py"
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as FCC  # noqa: E402  (real consumer)


# ── synthetic RTL fixtures ───────────────────────────────────────────────
#
# One memory shape, four contracts. Only the header comment and the driver
# form change between them, so any verdict difference is attributable to
# the property under test and nothing else.

_LYING_DOC = """\
// lookup_store — small byte-wide lookup array.
// Reads are single-cycle combinational (synchronous): rdata is valid on
// the same cycle the address is presented.
module lookup_store(input clk, input [6:0] addr, output reg [7:0] rdata);
    reg [7:0] store [0:127];
    always @(posedge clk) rdata <= store[addr];
endmodule
"""

_MIXED_DRIVERS = """\
// lookup_store — registered read.
module lookup_store(input clk, input [6:0] addr, output reg [7:0] rdata);
    reg [7:0] store [0:127];
    always @(posedge clk) rdata <= store[addr];
    assign rdata = store[addr];
endmodule
"""

_HONEST_DOC = """\
// lookup_store — 1-cycle read latency: rdata lags addr by one clock.
module lookup_store(input clk, input [6:0] addr, output reg [7:0] rdata);
    reg [7:0] store [0:127];
    always @(posedge clk) rdata <= store[addr];
endmodule
"""

_TRULY_COMBINATIONAL = """\
// lookup_store — combinational read, and the RTL agrees.
module lookup_store(input [6:0] addr, output wire [7:0] rdata);
    reg [7:0] store [0:127];
    assign rdata = store[addr];
endmodule
"""

_UNDOCUMENTED = """\
module lookup_store(input clk, input [6:0] addr, output reg [7:0] rdata);
    reg [7:0] store [0:127];
    always @(posedge clk) rdata <= store[addr];
endmodule
"""


# ── harnesses ────────────────────────────────────────────────────────────

def _run_cli(tmp_path: Path, rtl: str) -> tuple[int, dict]:
    """Run the program the way its Usage line spells it. Returns (rc, json)."""
    src = tmp_path / "lookup_store.v"
    src.write_text(textwrap.dedent(rtl))
    out = tmp_path / "gate.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(src), "--json", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode, json.loads(out.read_text()) if out.exists() else {}


def _flow_clause_command() -> str:
    """The step-2 gate command, taken from the flow definition itself.

    Re-typing the argv here would make the test agree with the flow by
    coincidence; if the clause is ever re-worded or unwired, this raises
    instead of quietly testing a command nothing runs.
    """
    flow = yaml.safe_load(FLOW_YAML.read_text())
    for step in flow.get("steps", []):
        gate = step.get("gate") or {}
        for group in gate.values():
            if not isinstance(group, list):
                continue
            for clause in group:
                if not isinstance(clause, dict):
                    continue
                for spec in clause.values():
                    cmd = spec.get("command") if isinstance(spec, dict) else None
                    if cmd and cmd.split()[0] == "memory_read_pipeline_check":
                        return cmd
    raise AssertionError(
        "no flow clause invokes memory_read_pipeline_check — the gate is "
        "unwired, so nothing below measures the real caller")


def _run_through_flow_consumer(tmp_path: Path, rtl: str) -> tuple[bool, str, dict]:
    """Drive `flow_compliance_check`, the module the flow actually uses.

    Returns (passed, snippet, emitted_json).
    """
    cmd = _flow_clause_command()
    project = tmp_path / "proj"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "lookup_store.v").write_text(textwrap.dedent(rtl))
    (project / "reports" / "phase2" / "gates").mkdir(parents=True)
    passed, snippet = FCC._check_program_exit_zero(project, cmd)
    art = project / "reports" / "phase2" / "gates" / "memory_read_pipeline.json"
    return passed, snippet, (json.loads(art.read_text()) if art.exists() else {})


# ── DIRECTION 1: the FAIL verdict is reachable ───────────────────────────

def test_documented_no_lag_read_that_is_actually_registered_is_a_FAIL(tmp_path):
    """A module that states the OPPOSITE of its own read path fails.

    This is the shape the program's own "Real occurrence" section describes:
    the header promised same-cycle availability, the flops delivered a
    1-cycle lag, and the consumer read stale data every fetch. Against the
    unfixed program this returns rc 0 / verdict WARN, because no finding
    site could produce a FAIL severity.
    """
    rc, out = _run_cli(tmp_path, _LYING_DOC)
    assert rc == 1, f"expected the documented exit-1, got {rc}: {out}"
    assert out["verdict"] == "FAIL"
    assert out["fails"] >= 1
    assert [f["rule"] for f in out["findings"]] == ["contradictory_read_doc"]
    assert out["findings"][0]["severity"] == "FAIL"


def test_port_with_both_a_procedural_and_a_continuous_driver_is_a_FAIL(tmp_path):
    """`rdata <= store[a]` together with `assign rdata = store[a]`.

    Not merely ambiguous latency: a variable may not carry a procedural and
    a continuous driver at once, so this cannot elaborate and can never be
    the intended design. Unfixed: rc 0 / verdict WARN.
    """
    rc, out = _run_cli(tmp_path, _MIXED_DRIVERS)
    assert rc == 1, f"expected the documented exit-1, got {rc}: {out}"
    assert out["verdict"] == "FAIL"
    assert out["fails"] >= 1
    assert "mixed_read_semantics" in [f["rule"] for f in out["findings"]]


def test_the_flow_consumer_sees_the_failure(tmp_path):
    """End-to-end through `flow_compliance_check`, not through a re-typed argv.

    The step-2 clause is `optional_program_exit_zero`, which fails its step
    on a non-zero exit. Unfixed, `passed` is True for every possible RTL —
    which is what made this gate's green unearned.
    """
    passed, snippet, art = _run_through_flow_consumer(tmp_path, _LYING_DOC)
    assert passed is False, f"consumer accepted a contradicted read: {snippet}"
    assert art.get("verdict") == "FAIL"
    assert art.get("fails", 0) >= 1


# ── DIRECTION 2: PASS and WARN are still reachable ───────────────────────

def test_registered_read_with_an_honest_latency_note_still_PASSes(tmp_path):
    """The fix must not turn every memory red."""
    rc, out = _run_cli(tmp_path, _HONEST_DOC)
    assert rc == 0
    assert out["verdict"] == "PASS"
    assert out["total_findings"] == 0


def test_a_genuinely_combinational_read_still_PASSes(tmp_path):
    rc, out = _run_cli(tmp_path, _TRULY_COMBINATIONAL)
    assert rc == 0
    assert out["verdict"] == "PASS"
    assert out["total_findings"] == 0


def test_an_undocumented_registered_read_stays_an_advisory_WARN(tmp_path):
    """Silence about latency is an omission, not a contradiction.

    Making THIS loud is what would have reddened every existing project, so
    it is pinned: a finding is reported, the verdict says WARN, and the exit
    code stays 0 so the flow is not gated.
    """
    rc, out = _run_cli(tmp_path, _UNDOCUMENTED)
    assert rc == 0
    assert out["verdict"] == "WARN"
    # `.get` on purpose: the preservation tests must hold against the UNFIXED
    # program too (which emits no `fails` key), so that the mutation control
    # separates "the FAIL became reachable" from "the schema grew a field".
    assert out.get("fails", 0) == 0
    assert out["warnings"] >= 1
    assert [f["rule"] for f in out["findings"]] == ["registered_read_undocumented"]


def test_the_flow_consumer_still_accepts_an_honest_module(tmp_path):
    passed, snippet, art = _run_through_flow_consumer(tmp_path, _HONEST_DOC)
    assert passed is True, snippet
    assert art.get("verdict") == "PASS"


def test_the_flow_consumer_still_accepts_an_undocumented_module(tmp_path):
    """The advisory tier must reach the consumer as a pass, not as a red."""
    passed, snippet, art = _run_through_flow_consumer(tmp_path, _UNDOCUMENTED)
    assert passed is True, snippet
    assert art.get("verdict") == "WARN"
    assert art.get("fails", 0) == 0


# ── the near-miss guard: prose is not a claim ────────────────────────────

@pytest.mark.parametrize("header", [
    # "combinational" describing something that is not the read contract
    "// Combinational glue logic reads addr_q and drives the index.\n",
    "// The read is registered; the output decode downstream is combinational.\n",
    # an async RESET is not an async READ
    "// Async reset, registered read of the array.\n",
])
def test_prose_that_merely_mentions_combinational_is_not_a_contradiction(
        tmp_path, header):
    """The FAIL arm fails a step of the real flow, so it must not fire on
    prose that never claims a no-lag read. These stay in the advisory tier
    (or pass outright when they state the registered contract)."""
    rc, out = _run_cli(tmp_path, header + _UNDOCUMENTED)
    assert rc == 0, f"prose header was read as a contradiction: {out}"
    assert out["verdict"] in ("PASS", "WARN")
    assert out.get("fails", 0) == 0


# ── the third exit code still means what it says ─────────────────────────

def test_missing_input_is_still_exit_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path / "absent.v")],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
