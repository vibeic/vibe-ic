"""#682 — a gate that never ran read exactly like one that passed.

`flow_compliance_check` reported a STEP's verdict and never named the GATE that
produced it. Only the failing branches wrote the command; a gate that ran and
passed left no trace. So `grep -c <gate> flow_compliance_check.log` returned 0
for a gate that had just written `{"verdict": "FAIL", "rc": 1}`, 0 for one that
certainly ran, and 0 for one that was never wired — three different facts, one
answer.

It cost a false alarm: a round-report concluded from that grep that
`drv_promotion_corroboration` writes a blocking FAIL the compliance gate never
reads. Verified false — the gate is wired at step 23, it ran, it wrote its
verdict, and step 23 was FAIL. The inference only looked sound because the record
could not separate "never read" from "not recorded".

MEASURED after the fix, on the caravel_user_project x sky130A cell:

    GATE EXECUTION LEDGER: 74 invocation(s)
      GATE_RAN formal_proof_evidence_check         rc=0   PASS
      GATE_RAN cpu_functional_oracle_waiver_check  rc=1   FAIL
      ...
    gates recorded as RUN: 71
      drv_promotion_corroboration_check      did NOT run in this cell
      sta_corner_record_completeness_check   did NOT run in this cell

Same shape as #544 ("the run looked clean because the only gate that would have
disagreed had not spoken"), which fixed the AGGREGATION and left the
OBSERVABILITY open.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
F = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = F
try:
    _spec.loader.exec_module(F)
except SystemExit:
    pass


def setup_function(_fn):
    F._GATE_LEDGER.clear()


# ── the name a reader greps for ───────────────────────────────────────────
def test_the_recorded_name_is_the_one_a_reader_would_grep():
    assert F._gate_name("drv_promotion_corroboration_check . --json x.json") \
        == "drv_promotion_corroboration_check"
    assert F._gate_name("python3 /a/b/sta_corner_record_completeness_check.py .") \
        == "sta_corner_record_completeness_check"


def test_an_empty_command_does_not_crash_the_ledger():
    assert F._gate_name("") == "<empty>"


# ── a passing gate is recorded, which is the whole point ──────────────────
def test_a_gate_that_passed_is_recorded():
    """The defect in one assertion. Recording only failures is how an absence
    became indistinguishable from a pass."""
    F._record_gate_execution("some_check .", 0, "PASS")
    lines = "\n".join(F.gate_ledger_lines())
    assert "GATE_RAN some_check" in lines and "PASS" in lines


def test_every_outcome_is_recorded_not_just_the_bad_ones():
    for rc, verdict in ((0, "PASS"), (1, "FAIL"), (2, "VACUOUS_PASS"),
                        (3, "PASS_WITH_WAIVERS"), (None, "CRASHED"),
                        (None, "TIMEOUT"), (None, "NOT_FOUND")):
        F._record_gate_execution(f"g_{verdict.lower()}_check .", rc, verdict)
    lines = "\n".join(F.gate_ledger_lines())
    assert lines.count("GATE_RAN") == 7
    assert "launch-failed" in lines, "a gate that could not launch must say so"


def test_the_block_is_emitted_even_when_nothing_ran():
    """A record that appears only when there is something to report cannot be
    used to prove there was nothing."""
    lines = F.gate_ledger_lines()
    assert lines and "no program gate was invoked" in lines[0]


# ── the wiring, which is what makes it a record at all ────────────────────
def test_a_PASSING_gate_is_recorded_END_TO_END(tmp_path, monkeypatch):
    """MUTATION-DRIVEN, and the assertion this file was missing. Restricting the
    record to `if not ok` left all eight tests green while restoring the exact
    defect: a gate that ran and passed leaves no trace, so grep cannot tell it
    from one that never ran. Every other test here either builds the ledger by
    hand or reads the source; only this one drives the real evaluator and then
    asks whether the PASS is in the record."""
    called = {}

    def fake_inner(project, cmd_str):
        called["cmd"] = cmd_str
        return True, "all good"            # a PASS, the case that was invisible

    monkeypatch.setattr(F, "_%s__check_program_exit_zero" % "", fake_inner,
                        raising=False)
    monkeypatch.setattr(F, "__check_program_exit_zero", fake_inner,
                        raising=False)
    ok, _out = F._check_program_exit_zero(tmp_path, "quiet_passing_check .")
    assert ok is True
    lines = "\n".join(F.gate_ledger_lines())
    assert "GATE_RAN quiet_passing_check" in lines, (
        "a gate that RAN and PASSED left no trace — the whole defect")
    assert "PASS" in lines


def test_the_record_is_not_conditional_on_the_outcome():
    """The same property, read off the source: `_record_gate_execution` must sit
    at the wrapper's body indent, not under any branch."""
    src = (_PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    i = src.index("def _check_program_exit_zero(project: Path, cmd_str: str)")
    j = src.index("def __check_program_exit_zero(", i)
    wrapper = src[i:j]
    line = next(l for l in wrapper.splitlines()
                if "_record_gate_execution(cmd_str" in l)
    assert line.startswith("    _record_gate_execution("), (
        f"the record is nested under a branch: {line!r}")


def test_the_evaluator_records_every_return_by_WRAPPING():
    """LOAD-BEARING. Inserting a call at each of the eleven return points leaves
    a return added later unrecorded — and an unrecorded gate is exactly the
    defect. The wrapper cannot be bypassed by a new return."""
    src = (_PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    i = src.index("def _check_program_exit_zero(project: Path, cmd_str: str)")
    j = src.index("def __check_program_exit_zero(", i)
    wrapper = src[i:j]
    assert "__check_program_exit_zero(project, cmd_str)" in wrapper
    assert "_record_gate_execution(cmd_str, rc, verdict)" in wrapper


def test_the_verdict_is_read_from_the_snippet_not_re_derived():
    """One classification, not a second that can disagree with the first. A
    parallel derivation here would be a new way for the record to be wrong about
    the run it describes."""
    src = (_PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    i = src.index("def _check_program_exit_zero(project: Path, cmd_str: str)")
    j = src.index("def __check_program_exit_zero(", i)
    wrapper = src[i:j]
    for sentinel in ("_VACUOUS_HINT_PREFIX", "_WAIVER_HINT_PREFIX",
                     "_CRASH_HINT_PREFIX"):
        assert sentinel in wrapper, sentinel
    assert "subprocess" not in wrapper, "the wrapper must not run anything itself"


def test_main_prints_the_ledger_unconditionally():
    """A block printed only on failure leaves the passing case exactly as
    unreadable as it was."""
    src = (_PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    i = body.index("for _line in gate_ledger_lines():")
    # it must sit at function-body indent inside main, not under an `if`
    line = body[body.rfind("\n", 0, i) + 1:i + 40]
    assert line.startswith("    for _line"), line
