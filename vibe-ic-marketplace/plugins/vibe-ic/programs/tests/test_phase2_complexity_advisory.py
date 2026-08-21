"""Tests for the ADVISORY-ONLY design-complexity hook wired into
design_one_shot_runner.

Contract (additive, non-gating):
  - step_complexity_advisory emits reports/phase2/complexity_advisory.json
    and returns a StepResult with status "ADVISORY" (never PASS/FAIL/SKIP).
  - An estimator exception is swallowed: the step still returns ADVISORY,
    does NOT propagate, and an "ADVISORY" status cannot change the runner's
    aggregate verdict (proved against _aggregate_verdict).
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as p2  # noqa: E402
import design_complexity_estimator as dce  # noqa: E402


def _toy_project(tmp_path):
    proj = tmp_path / "demo"
    rtl = proj / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.sv").write_text(
        "module chip_top(input clk, input reset_n,\n"
        "                input [31:0] din, output reg [31:0] dout);\n"
        "  always @(posedge clk) dout <= din;\n"
        "endmodule\n"
    )
    return proj


def test_advisory_emitted_for_toy_project(tmp_path):
    proj = _toy_project(tmp_path)
    sr = p2.step_complexity_advisory(proj)

    # (a) advisory is emitted and non-gating
    assert sr.status == "ADVISORY"
    adv = proj / "reports" / "phase2" / "complexity_advisory.json"
    assert adv.is_file()
    data = json.loads(adv.read_text())
    assert data["advisory_only"] is True
    assert "score" in data and "tier" in data
    assert isinstance(data["recommendations"], dict)
    # tier must be one of the estimator's known tiers
    assert data["tier"] in {"TRIVIAL", "SMALL", "MEDIUM", "LARGE", "COMPLEX"}
    # StepResult carries the same score/tier
    assert sr.extras.get("tier") == data["tier"]
    assert sr.output_files == ["reports/phase2/complexity_advisory.json"]


def test_estimator_exception_does_not_propagate(tmp_path, monkeypatch):
    proj = _toy_project(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("estimator blew up")

    # runner does `from design_complexity_estimator import estimate` inside
    # the step, so patch the module attribute it resolves.
    monkeypatch.setattr(dce, "estimate", _boom)

    # must NOT raise
    sr = p2.step_complexity_advisory(proj)
    assert sr.status == "ADVISORY"           # still advisory, never FAIL
    assert "estimator blew up" in (sr.extras.get("error") or "")


def test_advisory_status_cannot_change_aggregate_verdict():
    """An ADVISORY step among all-PASS steps keeps the verdict PASS, and
    among a FAIL keeps FAIL — i.e. it never alters pass/fail logic."""
    SR = p2.StepResult
    advisory = SR("complexity_advisory", "ADVISORY")

    all_pass = [SR("a", "PASS"), advisory, SR("b", "PASS")]
    assert p2._aggregate_verdict(all_pass) == "PASS"

    # advisory does not rescue a real FAIL, and does not itself fail
    with_fail = [SR("a", "PASS"), advisory, SR("b", "FAIL")]
    assert p2._aggregate_verdict(with_fail) == "FAIL"

    # advisory alone never yields FAIL
    assert p2._aggregate_verdict([advisory]) == "PASS"


def test_advisory_exception_path_keeps_verdict_pass(tmp_path, monkeypatch):
    """End-to-end of the non-fatal guarantee: even when the estimator
    raises, the resulting StepResult slotted into a PASS plan keeps PASS."""
    proj = _toy_project(tmp_path)
    monkeypatch.setattr(
        dce, "estimate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    sr = p2.step_complexity_advisory(proj)
    plan = [p2.StepResult("rtl_gen", "PASS"), sr,
            p2.StepResult("synth", "PASS")]
    assert p2._aggregate_verdict(plan) == "PASS"
