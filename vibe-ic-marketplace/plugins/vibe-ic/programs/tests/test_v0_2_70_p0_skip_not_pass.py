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


def test_p0_source_renders_skipped_condition():
    """The P0 StepResult must render SKIPPED-CONDITION when nothing executed,
    and the #447 rationale must be documented at that site.

    Keyed on the ENCLOSING FUNCTION rather than a fixed byte window around
    `id="P0"`. The window was 900 chars and #447 now sits 1538 away, because
    vibe-ic#559 added a comment block explaining the headline count between them
    — a documentation change the old assertion read as a regression. Function
    scope is also strictly stronger: a byte window can be satisfied by a `#447`
    that happens to be nearby, function scope cannot."""
    import inspect
    fn = inspect.getsource(F.main)
    assert 'id="P0"' in fn
    assert '"SKIPPED-CONDITION" if s_passed is None' in fn
    assert "#447" in fn


def test_rtl_present_still_executes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\nendmodule\n")
    passed, fails, skips, waivers = F._run_structural_rtl_gates(tmp_path)
    # checkers actually ran: the umbrella is a real boolean verdict now
    assert passed in (True, False)
