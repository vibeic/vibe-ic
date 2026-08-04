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
    `main()` (`'"SKIPPED-CONDITION" if s_passed is None'`), keyed on the
    ENCLOSING FUNCTION rather than a byte window because #559's comment block
    had already pushed #447 1538 bytes away and the byte window read that as a
    regression. The verdict expression has since moved into
    `_p0_umbrella_status`, its one owner, so the substring is now checked in the
    function that owns the decision — and, more to the point, the tri-state is
    checked by CALLING it, which no relocation can satisfy accidentally.

    The `main()` half is kept as a wiring assertion: the owner is only the owner
    if the site that publishes the step actually calls it."""
    import inspect
    assert F._p0_umbrella_status(None, []) == "SKIPPED-CONDITION"
    owner = inspect.getsource(F._p0_umbrella_status)
    assert '"SKIPPED-CONDITION"' in owner
    assert "#447" in owner
    fn = inspect.getsource(F.main)
    assert 'id="P0"' in fn
    assert "_p0_umbrella_status(s_passed, structural_gate_records)" in fn


def test_rtl_present_still_executes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\nendmodule\n")
    passed, fails, skips, waivers = F._run_structural_rtl_gates(tmp_path)
    # checkers actually ran: the umbrella is a real boolean verdict now
    assert passed in (True, False)
