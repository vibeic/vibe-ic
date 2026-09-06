"""`final_audit`'s step record must carry the verdict, not the 25 lines after it.

THE DEFECT, MEASURED.  `design_one_shot_runner.step_final_audit` put
`out.splitlines()[-25:]` in its step record and nothing else.  On subservient's
own transcript (`reports/audit/flow_compliance_check.log`, 394 lines,
2026-09-06) the verdict

    Overall: FAIL  (strict=True)
    Phase 2 strict-structural mode: 2 structural gates FAILed
      l9_rtl_pin_consistency_check — ...
      spec_required_artifact_check — ...

sits at lines 228-231.  The 25-line window starts at line 370 and holds
twenty-four `GATE_RAN` rows plus one `STRUCTURAL MEASUREMENT` row — the LEDGER
of which gates ran, which says nothing about which of them gated.  That is why
a reader of the step record saw `final_audit FAIL` and learned nothing: the
reason had been printed, and the record carried the 141 lines that came after
it.  A longer tail is not the fix — the distance from the verdict to the end of
the report is a property of the report.

MUTATIONS THESE TESTS MUST KILL:
  * Reverting `head` to `out.splitlines()[-25:]` fails
    `test_the_verdict_and_its_gating_gates_survive`.
  * Selecting by a bigger tail instead of by the report's own delimiters
    (e.g. `[-200:]`) still fails `test_the_elision_is_declared`, because a
    window that happens to reach the verdict does not SAY what it skipped.
  * Dropping the containment short-circuit — always prepending the block —
    fails `test_a_short_report_is_byte_identical`, the control that no report
    which already carried its verdict has its record changed.
  * Removing the cap's notice (keeping the truncation) fails
    `test_a_capped_block_says_how_many_it_dropped`.
"""

import importlib
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

D = importlib.import_module("design_one_shot_runner")


def _base_detail(out):
    """EXACTLY what this step used to put in its record."""
    return "\n".join(out.splitlines()[-25:])


def _report(n_pad, verdict_block, n_tail):
    return "\n".join(
        ["pad %d" % i for i in range(n_pad)]
        + verdict_block
        + [""]
        + ["  GATE_RAN gate_%d rc=0 PASS" % i for i in range(n_tail)])


VERDICT = [
    "Overall: FAIL  (strict=True)",
    "Phase 2 strict-structural mode: 2 structural gates FAILed",
    "  l9_rtl_pin_consistency_check — L9 <-> RTL top pin/direction mismatch",
    "  spec_required_artifact_check — 1 declared artifact(s) absent or empty.",
]


def test_the_verdict_and_its_gating_gates_survive():
    out = _report(220, VERDICT, 140)
    base = _base_detail(out)
    fixed = D._final_audit_detail(out, "/x/flow_compliance_check.log")
    # the defect, pinned: the old detail carried NONE of it
    assert "Overall:" not in base
    assert "l9_rtl_pin_consistency_check" not in base
    # and the fix carries all four lines, verbatim and in order
    assert fixed.startswith("\n".join(VERDICT))
    for line in VERDICT:
        assert line in fixed


def test_the_historical_tail_is_kept_underneath():
    """An ADDITION, never a replacement: whatever the record used to end with
    it still ends with."""
    out = _report(220, VERDICT, 140)
    assert D._final_audit_detail(out, "/x").endswith(_base_detail(out))


def test_the_elision_is_declared():
    """What was skipped must be COUNTED and the transcript NAMED — otherwise
    the two halves read as one continuous passage."""
    out = _report(220, VERDICT, 140)
    fixed = D._final_audit_detail(out, "/x/flow_compliance_check.log")
    marks = [l for l in fixed.splitlines() if "elided here" in l]
    assert len(marks) == 1, fixed
    assert "/x/flow_compliance_check.log" in marks[0]
    # the count is the real gap, not a guess
    lines = out.splitlines()
    expected = (len(lines) - 25) - (220 + len(VERDICT))
    assert str(expected) in marks[0], (marks[0], expected)


def test_a_short_report_is_byte_identical():
    """THE CONTROL.  A report short enough that the old window already held
    the verdict must produce EXACTLY the old string."""
    for n_pad in (0, 5, 15):
        out = _report(n_pad, VERDICT, 2)
        assert len(out.splitlines()) <= 25
        assert D._final_audit_detail(out, "/x") == _base_detail(out)


def test_a_verdict_already_inside_the_window_is_byte_identical():
    out = _report(0, VERDICT, 18)          # Overall: lands inside the last 25
    assert "Overall:" in _base_detail(out)
    assert D._final_audit_detail(out, "/x") == _base_detail(out)


def test_a_report_with_no_verdict_line_gets_no_default():
    """"Could not read it" is not "read it and it was empty": with no
    `Overall:` anywhere the record is the old tail and nothing is invented."""
    out = "\n".join("line %d" % i for i in range(300))
    assert D._final_audit_detail(out, "/x") == _base_detail(out)


def test_the_last_overall_wins():
    """A nested sub-audit may print its own verdict; the RUN's verdict is the
    final one."""
    out = "\n".join(
        ["Overall: PASS  (sub-audit)"] + ["pad"] * 200
        + ["Overall: FAIL  (strict=True)", "  the real one"] + [""]
        + ["tail %d" % i for i in range(40)])
    fixed = D._final_audit_detail(out, "/x")
    assert fixed.startswith("Overall: FAIL  (strict=True)\n  the real one")


def test_a_capped_block_says_how_many_it_dropped():
    """The cap is a bound on the RECORD, never a silent narrowing: it names
    the number it did not show and where they all are."""
    n = D._FINAL_AUDIT_VERDICT_MAX_LINES + 41
    block = ["Overall: FAIL  (strict=True)"] + [
        "  gate_%d — why" % i for i in range(n - 1)]
    out = _report(200, block, 40)
    fixed = D._final_audit_detail(out, "/x/t.log")
    note = [l for l in fixed.splitlines() if "further gating line(s) NOT shown" in l]
    assert len(note) == 1, fixed[:2000]
    assert "41" in note[0], note[0]
    assert "/x/t.log" in note[0]
    # and it really is capped
    assert fixed.count("— why") == D._FINAL_AUDIT_VERDICT_MAX_LINES - 1


def test_the_block_is_delimited_by_the_report_not_by_a_constant():
    """Two reports with the SAME verdict but different distances to the end
    must both carry it — which a tail of any fixed size cannot do for both."""
    near = _report(30, VERDICT, 30)
    far = _report(30, VERDICT, 4000)
    for out in (near, far):
        assert "Overall: FAIL  (strict=True)" in D._final_audit_detail(out, "/x")


def test_step_final_audit_uses_it():
    """The helper must be WIRED. A correct function nothing calls is the
    defect this repo keeps meeting (see spec_declaration_emit --verify)."""
    import ast
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    assert "head = _final_audit_detail(out, transcript)" in src
    # The old expression must be gone from the CODE. It survives in prose
    # above (that is the measurement this fix is built on), so the check is
    # over the parsed tree, not over the file's characters.
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "step_final_audit"]
    assert len(fn) == 1
    body_src = ast.unparse(fn[0])
    assert "splitlines()[-25:]" not in body_src, body_src[:400]
    assert "_final_audit_detail(out, transcript)" in body_src


# --- END TO END: the STEP RECORD, not just the helper ---------------------- #
#
# The behaviour tests above drive `_final_audit_detail` directly, so reverting
# the CALL SITE to `out.splitlines()[-25:]` leaves them green (measured: M6/M7
# killed only `test_step_final_audit_uses_it`). These drive `step_final_audit`
# itself, so the record a reader actually gets is what is pinned.

def _long_transcript(verdict_line):
    return "\n".join(
        ["  - [SKIPPED-CONDITION] Step M%d" % i for i in range(220)]
        + [verdict_line,
           "Phase 2 strict-structural mode: 2 structural gates FAILed",
           "  l9_rtl_pin_consistency_check — L9 <-> RTL top pin mismatch",
           "  spec_required_artifact_check — 1 declared artifact(s) absent."]
        + [""]
        + ["  GATE_RAN gate_%d rc=0 PASS reason_class=-" % i
           for i in range(140)]) + "\n"


def _drive(tmp_path, monkeypatch, out, rc):
    monkeypatch.setattr(
        D, "_run",
        lambda cmd, cwd=None, timeout=600, env=None: (rc, out, ""))
    return D.step_final_audit(tmp_path, phase=2)


def test_the_step_record_names_the_gates_that_gated(tmp_path, monkeypatch):
    out = _long_transcript("Overall: FAIL  (strict=True)")
    r = _drive(tmp_path, monkeypatch, out, 1)
    assert r.status == "FAIL"
    assert "Overall: FAIL  (strict=True)" in r.detail
    assert "l9_rtl_pin_consistency_check" in r.detail
    assert "spec_required_artifact_check" in r.detail
    # and the old window's content is still there
    assert "GATE_RAN gate_139" in r.detail


def test_the_step_record_carries_a_waived_verdict_too(tmp_path, monkeypatch):
    out = _long_transcript("Overall: PASS_WITH_WAIVERS  (strict=True)")
    r = _drive(tmp_path, monkeypatch, out, 0)
    assert r.status == "WAIVED", r.status
    assert "Overall: PASS_WITH_WAIVERS" in r.detail


def test_a_short_transcript_record_is_byte_identical(tmp_path, monkeypatch):
    """THE CONTROL at the step level: a report that already fitted keeps the
    exact record it had."""
    out = "Overall: FAIL  (strict=True)\n  because\n\ntail\n"
    r = _drive(tmp_path, monkeypatch, out, 1)
    assert r.detail == "\n".join(out.splitlines()[-25:])
