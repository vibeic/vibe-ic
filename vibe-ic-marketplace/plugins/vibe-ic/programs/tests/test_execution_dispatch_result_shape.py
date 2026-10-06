"""Ordinary dispatch preserves the Phase-2 DFT chain's list return contract."""
import pytest

import design_one_shot_runner as design
import execution_policy as policy
import step_preflight


@pytest.mark.parametrize("shape", ["scalar", "list", "tuple"])
@pytest.mark.parametrize("outcome,expected_status,completed", [
    ("adopted", "PASS", 3),
    ("not_applicable", "PASS", 3),
    ("incomplete", "NOT_MEASURED", 1),
    ("failed", "FAIL", 1),
    ("candidate_failed", "FAIL", 1),
])
def test_dft_dispatch_preserves_factory_shape_and_evidence(
        tmp_path, monkeypatch, shape, outcome, expected_status, completed):
    monkeypatch.setattr(policy, "_ordinary_runtime", {})
    span = dict(step_preflight.RUNNER_PLANS[
        "design_one_shot_runner"].sites)["dft_lec_chain"]
    assert span == ("11", "12", "13")
    calls = []
    statuses = {"adopted": "ADOPTED", "not_applicable": "NOT_APPLICABLE",
                "incomplete": "NOT_MEASURED", "failed": "FAIL",
                "candidate_failed": "NOT_MEASURED"}

    def dispatch(project, step_id):
        assert project == tmp_path
        calls.append(step_id)
        return {"step_id": step_id, "status": statuses[outcome],
                "candidate_statuses": {
                    "native": "FAIL" if outcome == "candidate_failed" else statuses[outcome]}}

    monkeypatch.setattr(policy, "dispatch_fixed_step", dispatch)
    created = []

    def factory(detail, extras):
        # This is the same refusal row and one-element list used by the
        # production dft_lec_chain site before plan.extend consumes it.
        row = design._preflight_refusal("dft_lec_chain")(detail, extras)
        result = [row] if shape == "list" else (row,) if shape == "tuple" else row
        created.append(result)
        return result

    result = policy.dispatch_ordinary_site(
        tmp_path, "design_one_shot_runner", "dft_lec_chain", factory)
    assert result is created[0]
    if shape == "scalar":
        plan = [result]
    else:
        plan = []
        plan.extend(result)
    assert len(plan) == 1
    row = plan[0]
    assert row.name == "dft_lec_chain"
    assert row.status == expected_status
    assert calls == list(span[:completed])
    assert [r["step_id"] for r in row.extras["execution_results"]] == calls
    assert row.extras["execution_results"][0]["status"] == statuses[outcome]
    if outcome == "candidate_failed":
        assert row.extras["execution_results"][0]["candidate_statuses"]["native"] == "FAIL"
