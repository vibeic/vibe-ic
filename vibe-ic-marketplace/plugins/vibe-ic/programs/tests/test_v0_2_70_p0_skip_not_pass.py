"""v0.2.70 — #447: P0 structural-gate umbrella must not count
0-executed-checkers as PASS.

The audited rot: a pure-analog project (no RTL anywhere) showed
"[PASS] Step P0: Structural-RTL gates (226 checkers)" with the note
"SKIP: no RTL directory found" — 0/226 checkers executed yet counted
as an executed PASS in the strict verdict.

Pinned behaviour: `_run_structural_rtl_gates` returns None (not True)
as its first element when no RTL exists, and the P0 StepResult renders
SKIPPED-CONDITION (excluded from executed-PASS counts).

chip-AGNOSTIC: synthetic empty/RTL fixtures only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as F  # noqa: E402


def test_no_rtl_returns_none_not_true(tmp_path):
    passed, fails, skips, waivers = F._run_structural_rtl_gates(tmp_path)
    assert passed is None          # "not executed", NOT a PASS
    assert fails == [] and waivers == []
    assert any("no RTL" in s for s in skips)


def test_p0_renders_skipped_condition():
    """The P0 StepResult must render SKIPPED-CONDITION when nothing executed,
    and the #447 rationale must be documented at that site.

    ASSERTED ON BEHAVIOUR FIRST. This used to be a source-substring test over
    `main()` (`'"NOT_APPLICABLE" if s_passed is None'`), keyed on the
    ENCLOSING FUNCTION rather than a byte window because #559's comment block
    had already pushed #447 1538 bytes away and the byte window read that as a
    regression. The verdict expression has since moved into
    `_p0_umbrella_status`, its one owner, so the substring is now checked in the
    function that owns the decision — and, more to the point, the tri-state is
    checked by CALLING it, which no relocation can satisfy accidentally.

    The `main()` half is kept as a wiring assertion: the owner is only the owner
    if the site that publishes the step actually calls it."""
    import inspect
    # RE-DERIVED (T118). v1.24.80 (3c501d609 / a4caf1550, #2642) split #447's
    # "nothing executed" into the two states it always conflated: nothing
    # executed because Step 1 has not produced RTL yet (NOT_APPLICABLE /
    # ASKED_BEFORE_PRODUCER), and nothing executed although Step 1 completed
    # and promised RTL (FAIL). The owner cannot tell the two apart from
    # `(executed, records)` alone; the caller supplies `rtl_promised`, and the
    # context-free call is pinned as FAIL by the owner's own truth table
    # (test_p0_umbrella_verdict_coverage, test_t73_flow_declarations). What
    # #447 pinned -- the not-yet-due empty dispatch renders NOT_APPLICABLE and
    # never PASS -- is asserted in the context that makes it so.
    status, reason = F._p0_umbrella_status(None, [], rtl_promised=False)
    assert status == "NOT_APPLICABLE", (status, reason)
    assert reason == F._reason_taxonomy.ASKED_BEFORE_PRODUCER, reason
    # #447's core, in EITHER context: nothing executed is never a PASS.
    for promised in (False, True):
        assert F._p0_umbrella_status(None, [], rtl_promised=promised)[0] \
            != "PASS", promised
    owner = inspect.getsource(F._p0_umbrella_status)
    # R-0915-85 — the word the owner writes is `NOT_APPLICABLE`, and it must
    # DECLARE what makes it so; #447's sentence is unchanged and the reference
    # to it stays, which is what keeps this a wiring assertion about the one
    # owner rather than about a spelling.
    assert '_T.Verdict.NOT_APPLICABLE.value' in owner or \
        '"NOT_APPLICABLE"' in owner, owner[:400]
    assert "#447" in owner
    fn = inspect.getsource(getattr(F, '_audit_project', F.main))
    assert 'id="P0"' in fn
    # The call spans two lines since R-0915-85 gave the owner a PAIR to return
    # (the word and the reason beside it), so the wiring is asserted on the
    # call, not on one line's worth of it.
    _flat = " ".join(fn.split())
    assert "_p0_umbrella_status( s_passed, structural_gate_records" in _flat \
        or "_p0_umbrella_status(s_passed, structural_gate_records" in _flat, \
        _flat[:400]
    # ...and it supplies the context: an empty dispatch in `main()` is judged
    # not-yet-due, and only the post-Step-1 resolution may turn it into FAIL.
    # Without this the #447 state above would be unreachable from the one
    # publishing site.
    assert "rtl_promised=s_passed is not None" in _flat, _flat[:400]


def test_rtl_present_still_executes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\nendmodule\n")
    passed, fails, skips, waivers = F._run_structural_rtl_gates(tmp_path)
    # checkers actually ran: the umbrella is a real boolean verdict now
    assert passed in (True, False)
