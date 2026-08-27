"""reference_tb must REFUSE when its RTL input was never produced, instead of
reporting FAIL as though the reference TB had run and the design had lost.

Measured on a 20-problem Phase-2 run: `reference_tb` reported FAIL "rtl/ missing"
on 15 of 20 designs.  In all 15 the upstream producer `rtl_gen` had returned
BLOCKED, so rtl/ genuinely did not exist -- the message was TRUE but it was a
statement about an ABSENT INPUT, not about the design.  In the same runs
`rtl_validate` and `sim` reported BLOCKED for that identical state, and after
the ECO loop re-ran `rtl_gen` the very same gate reported SKIP for the very
same class.  One gate, two verdicts, decided by an unrelated upstream step.

The properties pinned here:
  * absent RTL yields the runner's documented refusal status, naming the
    producer that should have filled the directory;
  * the refusal is NOT silencing -- the run verdict stays red;
  * the refusal record is RECONCILABLE with the verdict the same gate emits
    once the producer succeeds;
  * the gate can still FAIL for its own real reason;
  * the refusal keeps the ECO recovery loop engaged;
  * a plain Phase-1 design doc with no harness gets the same verdict.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import design_one_shot_runner as DOR               # noqa: E402

# A registered class the AID reference TB can never bind (generic_full_stack,
# half_duplex_bus=False) and one it does bind -- both from the class registry.
_NON_AID_CLASS = "digital_arithmetic_primitive"
_AID_CLASS = "aid_class_half_duplex_single_wire"

_DIGITAL_TOP = [
    {"name": "clk", "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "a", "direction": "input"},
    {"name": "b", "direction": "input"},
    {"name": "y", "direction": "output"},
]


def _plain_phase1_project(tmp_path: Path, ports=None) -> Path:
    """A plain Phase-1 design doc on disk. No benchmark record, no dataset id,
    no harness directory -- only what Phase 1 itself emits."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "dut", "top_ports": ports or _DIGITAL_TOP}))
    return tmp_path


# ── 1. the refusal itself ───────────────────────────────────────────────────

def test_absent_rtl_is_a_refusal_not_a_design_verdict(tmp_path):
    p = _plain_phase1_project(tmp_path)
    assert not DOR._pl.rtl_dir(p).is_dir(), "precondition: rtl/ absent"
    r = DOR.step_reference_tb(p, "chip_top", _NON_AID_CLASS)

    assert r.status == DOR._spf.REFUSAL_STATUS == "BLOCKED", (
        f"absent RTL must be a refusal, not a design verdict; got {r.status}")
    # It must name the PRODUCER, not just restate its own input check.
    assert r.extras.get("producer_step") == "rtl_gen"
    assert r.extras.get("refused_for") == "absent_declared_input"
    assert "rtl_gen" in r.detail
    assert "NOTHING is known" in r.detail


# ── 2. refusing is not silencing ────────────────────────────────────────────

def test_refusal_still_makes_the_run_red(tmp_path):
    """A refusal must not become a green run. BLOCKED is enumerated in
    `_aggregate_verdict._FAIL_STATUSES`; this pins that it stays there."""
    p = _plain_phase1_project(tmp_path)
    r = DOR.step_reference_tb(p, "chip_top", _NON_AID_CLASS)
    verdict = DOR._aggregate_verdict([DOR.StepResult("rtl_gen", "PASS"), r])
    assert verdict not in ("PASS", "PASS_WITH_WAIVERS"), (
        f"the refusal was absorbed into a green verdict: {verdict}")


# ── 3. the two verdicts must be reconcilable ────────────────────────────────

def test_same_class_two_verdicts_are_reconcilable(tmp_path):
    """The gate reports one thing when rtl/ is absent and another when it is
    present. Those records must AGREE about whether the gate applies to the
    class at all -- otherwise the divergence is unexplained."""
    absent = _plain_phase1_project(tmp_path / "absent")
    r_absent = DOR.step_reference_tb(absent, "chip_top", _NON_AID_CLASS)

    present = _plain_phase1_project(tmp_path / "present")
    rtl = DOR._pl.rtl_dir(present)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dut.v").write_text(
        "module dut(input clk, input rst_n, input a, input b, output y);\n"
        "  assign y = a & b;\nendmodule\n")
    r_present = DOR.step_reference_tb(present, "chip_top", _NON_AID_CLASS)

    assert r_present.status == "SKIP", (
        f"precondition: this class SKIPs once rtl/ exists; got {r_present.status}")
    # The refusal must have SAID so, rather than leaving the reader to guess
    # that a FAIL and a SKIP were the same underlying situation.
    assert r_absent.extras.get("would_apply_when_present") is False
    assert "will SKIP" in r_absent.detail


def test_refusal_says_the_design_is_untested_when_the_gate_does_apply(tmp_path):
    """Opposite pole: for a class the AID TB DOES bind, the refusal must not
    claim the gate would have skipped."""
    p = _plain_phase1_project(tmp_path)
    r = DOR.step_reference_tb(p, "chip_top", _AID_CLASS)
    assert r.status == "BLOCKED"
    assert r.extras.get("would_apply_when_present") is True
    assert "genuinely untested" in r.detail
    assert "will SKIP" not in r.detail


# ── 4. constructed genuine violation: the gate can still FAIL ───────────────

def test_gate_can_still_fail_for_its_real_reason(tmp_path, monkeypatch):
    """Non-regression on the FAIL path. With the RTL input PRESENT and the
    class on the AID track, a genuinely broken gate asset must still produce
    FAIL -- the refusal above must not have made FAIL unreachable."""
    p = _plain_phase1_project(tmp_path)
    rtl = DOR._pl.rtl_dir(p)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dut.v").write_text("module dut(); endmodule\n")
    monkeypatch.setattr(DOR, "PROTOCOL_TB", tmp_path / "no_such_reference_tb.v")

    r = DOR.step_reference_tb(p, "chip_top", _AID_CLASS)
    assert r.status == "FAIL", f"the FAIL path became unreachable; got {r.status}"
    assert "reference TB missing" in r.detail


# ── 5. the ECO recovery loop must still engage on the refusal ───────────────

def test_refusal_keeps_the_eco_recovery_loop_engaged():
    """The ECO loop in `main()` exits on PASS / SKIP / WAIVED and iterates on
    anything else. The 15 recoveries measured on that run depended on the
    absent-RTL verdict NOT being one of the exit statuses."""
    eco_loop_exit_statuses = ("PASS", "SKIP", "WAIVED")
    assert DOR._spf.REFUSAL_STATUS not in eco_loop_exit_statuses, (
        "the refusal status exits the ECO loop -- rtl_gen would never be "
        "re-run and the recovery would be lost")


# ── 6. FLOW-BACK: no harness anywhere ───────────────────────────────────────

def test_flow_back_plain_phase1_doc_no_harness(tmp_path):
    """A plain Phase-1 design doc, with no benchmark harness on disk and no
    dataset record in the call, must reach the identical verdict."""
    p = _plain_phase1_project(tmp_path)
    harness_shaped = [q for q in p.rglob("*")
                      if any(t in q.name.lower()
                             for t in ("bench", "dataset", "prob", "harness"))]
    assert harness_shaped == [], f"harness leaked into the fixture: {harness_shaped}"

    r = DOR.step_reference_tb(p, "chip_top", _NON_AID_CLASS)
    assert r.status == "BLOCKED"
    assert r.extras.get("producer_step") == "rtl_gen"
    # and the message it produced carries no benchmark vocabulary
    low = r.detail.lower()
    for tok in ("verilogeval", "cvdp", "rtllm", "benchmark", "pass@1", "prob0"):
        assert tok not in low, f"benchmark literal {tok!r} leaked into the record"
