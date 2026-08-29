"""A tool that CRASHED must never be rendered as a coverage number.

REGRESSION for a measured DT1 (at-speed transition-fault ATPG) defect on
spm x gf180mcuD, plugin v1.12.51. This file pins THE REPORTING DEFECT: a tool
that could not RUN was rendered as a graded measurement of the DESIGN.

The sibling PDK-selection defect that triggered it on this particular run (a
sky130 Liberty resolved for a gf180mcu design) is pinned separately in
`test_dt1_atpg_liberty_follows_the_design.py`. They are separate because they
fail independently, and because THIS one is the load-bearing guard: it holds
for ANY tool crash from ANY cause, whatever the resolver chose. Without it the
next crash lies the same way.

Yosys reads a Liberty that models NONE of the netlist's cells WITHOUT error: `read_liberty` succeeds,
`flatten` succeeds, exit code 0, the output file exists, and the
"gate-levelised" core is still 197 untouched blackboxes. `_gate_levelise`
checked exactly exit-code-0 and file-exists, so it returned ok. The ATPG
then died on the FIRST fault inside `sat`:

    ERROR: No SAT model available for cell fb._392_ (gf180mcu_..._and3_1).

Because the per-fault marker is emitted BEFORE the `sat` command, the log
held a marker with no verdict after it, which `parse_sat_verdict` scored
ABORT — "attempted but left undecided". ABORT sits in the coverage
DENOMINATOR, so ONE phantom abort made det+red+abort = 1, cleared the
"no gradeable verdicts -> ERROR" guard, and rendered a hard tool crash as
"TDF test-coverage 0.0% < floor 90.0%" — a graded DESIGN failure. The
design's real at-speed test coverage, measured on the flow's own cut
netlist with only the Liberty changed, is 100.0%.

"The ATPG aborted" and "this design has 0% coverage" are different facts,
and only one of them is about the design.

Each test below is paired with a CONTROL that must stay green in both
directions, so the guards cannot be satisfied by code that changes every
input's answer — in particular a GENUINE undecided fault must STILL be a
conservative ABORT that counts as undetected (anti-gaming intact).

chip/PDK/vendor-AGNOSTIC throughout: the guards key on yosys's own generic-cell
vocabulary and on yosys's own `ERROR:` diagnostic, never on a library, chip or
vendor name. The gf180/sky130 strings that appear below are REPRODUCTIONS of
the measured artefacts, never inputs to the logic under test.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
SCRIPT = PROG / "transition_fault_atpg_run.py"
assert SCRIPT.exists()

sys.path.insert(0, str(PROG))
import transition_fault_atpg_run as tdf  # noqa: E402
import lec_run  # noqa: E402

# ── Measured reference numbers (spm x gf180mcuD, v1.12.51) ────────────────
_MEASURED_UNRESOLVED_INSTANCES = 197
_MEASURED_UNRESOLVED_TYPES = 11
_WRONG_LIB = ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
              "sky130_fd_sc_hd__tt_025C_1v80.lib")
_RIGHT_LIB = ("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
              "gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib")

# An excerpt of the SUBJECT's real flat_core.v (yosys `write_verilog -noattr`
# of a core whose Liberty modelled none of its cells): the cells survive
# verbatim as blackbox instantiations.
_UNLEVELISED_CORE = """
module spm(clk, rst, x, y);
  input clk;
  input rst;
  wire _395_;
  gf180mcu_fd_sc_mcu7t5v0__and3_1 _361_ (
    .A1(_395_),
    .A2(x[31]),
    .A3(_458_),
    .Z(_176_)
  );
  gf180mcu_fd_sc_mcu7t5v0__aoi21_1 _362_ (
    .A1(_395_),
    .A2(x[30]),
    .ZN(_177_)
  );
  gf180mcu_fd_sc_mcu7t5v0__nor2_1 _363_ (
    .A1(_176_),
    .A2(_177_),
    .ZN(y[0])
  );
  assign _395_ = ~rst;
endmodule
"""

# The SAME cut netlist levelised with the library its cells actually come from:
# yosys inlines every cell to pure `assign` logic. This is the real shape of
# the ARM-A core (measured: 1431 assigns, 0 instantiations of any kind).
_LEVELISED_CORE = """
module spm(clk, rst, x, y);
  input clk;
  input rst;
  wire _395_;
  assign _364__A1 = ~rst;
  assign _201__A3 = _0459_ | _0460_;
  assign _0459_ = ~_395_;
  assign y[0] = ~(_176_ | _177_);
endmodule
"""

# A core levelised to yosys GENERIC primitives rather than to `assign`s. These
# ARE resolved logic — the SAT engine models `$_*_` natively — so they must
# never be reported as unresolved.
_GENERIC_PRIMITIVE_CORE = """
module spm(clk, rst, x, y);
  input clk;
  $_AND_ _361_ (
    .A(_395_),
    .B(x[31]),
    .Y(_176_)
  );
  $_NOR_ _363_ (
    .A(_176_),
    .B(_177_),
    .Y(y[0])
  );
  $_DFF_P_ _400_ (
    .C(clk),
    .D(_176_),
    .Q(_395_)
  );
endmodule
"""

# The SUBJECT's real sat_run.log tail: the setup marker and the first fault
# marker are both emitted, then yosys dies INSIDE the sat pass.
_CRASH_LOG = """
4. Executing FLATTEN pass (flatten design).
VIBEICTDF_SETUP_DONE
VIBEICTDF _000_ STR

5. Executing SAT pass (solving SAT problems in the circuit).
Using SAT solver `kissat'.

Setting up SAT problem:
Import set-constraint: \\f1._000_ = 1'0
Final constraint equation: \\f1._000_ = 1'0

ERROR: No SAT model available for cell fb._392_ (gf180mcu_fd_sc_mcu7t5v0__and3_1).
"""

# A GENUINE undecided fault: the marker is present, the solver ran, and it
# reached no verdict (per-fault timeout). No fatal diagnostic anywhere. This is
# a statement about the DESIGN's hardness and must stay a conservative ABORT.
_UNDECIDED_LOG = """
VIBEICTDF_SETUP_DONE
VIBEICTDF _000_ STR

5. Executing SAT pass (solving SAT problems in the circuit).
Setting up SAT problem:
Import set-constraint: \\f1._000_ = 1'0
Solving problem with 12567 variables and 32003 clauses..
Timeout reached while solving.
"""

_DETECTED_LOG = """
VIBEICTDF _000_ STR
Solving problem with 12567 variables and 32003 clauses..
SAT model found: FAIL!
"""

_REDUNDANT_LOG = """
VIBEICTDF _000_ STR
Solving problem with 12567 variables and 32003 clauses..
SAT proof finished - no model found: SUCCESS!
"""


# ══════════════════════════════════════════════════════════════════════════
# (2a) Gate-levelisation must verify its OWN output
# ══════════════════════════════════════════════════════════════════════════

def test_unresolved_cells_are_a_levelisation_failure():
    """A core whose cells the Liberty did not model is NOT gate-levelised."""
    unresolved = tdf.unresolved_cell_types(_UNLEVELISED_CORE)
    assert unresolved, "the surviving blackboxes must be reported"
    assert sum(unresolved.values()) == 3
    why = tdf.levelisation_failure_reason(_UNLEVELISED_CORE, _WRONG_LIB)
    assert why, "an unlevelised core must be refused, not returned as ok"
    # The refusal must name the Liberty that was read — that is the ONE fact
    # the operator needs and the one the 0.0% coverage number never carried.
    assert _WRONG_LIB in why
    # ...and it must say what it is NOT, so nobody reads it as a design result.
    assert "not" in why.lower() and "coverage" in why.lower()


def test_levelised_core_is_accepted():
    """CONTROL — a core that DID levelise must stay green."""
    assert tdf.unresolved_cell_types(_LEVELISED_CORE) == {}
    assert tdf.levelisation_failure_reason(_LEVELISED_CORE, _RIGHT_LIB) == ""


def test_generic_yosys_primitives_are_resolved_logic():
    """CONTROL — `$_*_` cells are logic the SAT engine models natively; a core
    made of them is levelised, not unresolved. Without this control the guard
    is satisfied by code that calls every instantiation unresolved."""
    assert tdf.unresolved_cell_types(_GENERIC_PRIMITIVE_CORE) == {}
    assert tdf.levelisation_failure_reason(_GENERIC_PRIMITIVE_CORE,
                                           _RIGHT_LIB) == ""


def test_gate_levelise_postcondition_is_wired_into_the_step():
    """The guard must run inside `_gate_levelise`, not merely exist."""
    src = SCRIPT.read_text()
    body = src.split("def _gate_levelise(", 1)[1].split("\ndef ", 1)[0]
    assert "levelisation_failure_reason" in body, (
        "_gate_levelise must verify its own output before returning ok")


# ══════════════════════════════════════════════════════════════════════════
# (2b) A crash is not an abort
# ══════════════════════════════════════════════════════════════════════════

def test_fatal_tool_error_is_not_an_abort():
    """The measured crash block must classify as a TOOL failure."""
    assert tdf.parse_sat_verdict(_CRASH_LOG) == "TOOL_ERROR"


def test_genuine_undecided_fault_is_still_an_abort():
    """CONTROL — anti-gaming. A fault the solver attempted and left undecided
    is STILL an ABORT and still counts as undetected. If this ever became
    TOOL_ERROR, a design could dodge the coverage floor by timing out."""
    assert tdf.parse_sat_verdict(_UNDECIDED_LOG) == "ABORT"


def test_decided_verdicts_are_unchanged():
    """CONTROL — detection and redundancy proofs keep their meaning."""
    assert tdf.parse_sat_verdict(_DETECTED_LOG) == "DET"
    assert tdf.parse_sat_verdict(_REDUNDANT_LOG) == "RED"


def test_crash_produces_no_gradeable_verdict_at_all():
    """The whole point: the crash must leave det+red+abort == 0, so the
    producer's ERROR guard fires and NO coverage number is ever computed.

    Pre-fix this was det=0 red=0 abort=1 -> coverage_math(0,0,1) -> 0.0%."""
    faults = [("_000_", "STR", "1", "0")]
    results, _example, setup_done = tdf._parse_batch_log(_CRASH_LOG, faults, [])
    assert [v for _, _, v in results] == ["TOOL_ERROR"]
    # The setup marker IS emitted before the first sat — which is exactly why
    # the pre-existing `not setup_done and graded == 0` guard could not fire.
    assert setup_done is True
    gradeable = [v for _, _, v in results if v in ("DET", "RED", "ABORT")]
    assert gradeable == [], "a crash must contribute nothing to the grade"


def test_the_fabricated_number_is_what_we_are_preventing():
    """Documents the arithmetic the phantom ABORT produced, so the regression
    is legible: ONE mislabelled crash IS a 0.0% coverage claim."""
    cov = tdf.coverage_math(0, 0, 1)
    assert cov["tdf_test_coverage_pct"] == 0.0
    assert cov["sampled_faults"] == 1


def test_fatal_message_is_quoted_verbatim_for_the_operator():
    msg = tdf._fatal_tool_message(_CRASH_LOG)
    assert "No SAT model available" in msg
    assert tdf._fatal_tool_message(_UNDECIDED_LOG) == ""   # CONTROL


def test_tool_error_guard_is_wired_ahead_of_the_grading():
    """The TOOL_ERROR check must precede the coverage arithmetic, so a crash
    can never reach `coverage_math`."""
    src = SCRIPT.read_text()
    body = src.split("def run_tdf_atpg(", 1)[1]
    guard = body.find('v == "TOOL_ERROR"')
    math = body.find("cov = coverage_math(")
    assert guard != -1 and math != -1
    assert guard < math, "the tool-failure guard must run before grading"


# ══════════════════════════════════════════════════════════════════════════
# (2c) A dead batch is not a slow batch
# ══════════════════════════════════════════════════════════════════════════

def test_truncation_advice_is_conditional_on_spending_the_wall():
    """"Raise --timeout" is only true advice if the batch actually spent its
    wall. The measured run told the operator that 397 faults "were not reached
    within the 1995 s wall budget" — from a process that used ~2 s of it."""
    src = SCRIPT.read_text()
    body = src.split("def run_tdf_atpg(", 1)[1]
    assert "_WALL_SPENT_FRACTION" in body, (
        "the budget-truncation advice must be gated on the wall actually spent")
    assert "did NOT run out of time" in body
    assert 0.0 < tdf._WALL_SPENT_FRACTION <= 1.0


def test_no_library_or_chip_literal_in_the_guards():
    """chip/PDK/vendor-AGNOSTIC: the logic must key on yosys's own vocabulary,
    never on a library name. Library strings may appear only in comments and
    docstrings (as the measured evidence) — never in executable code."""
    src = SCRIPT.read_text()
    body = src.split("def unresolved_cell_types(", 1)[1].split("\ndef ", 1)[0]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("#"))
    code = code.split('"""')[0] + "".join(code.split('"""')[2::2])
    for literal in ("sky130", "gf180", "sg13", "nangate", "asap7", "spm"):
        assert literal not in code.lower(), f"chip/PDK literal {literal!r} in code"
