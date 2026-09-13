"""A completed rung does not finish a ladder whose next rung was not admitted."""
import lec_run
from test_issue2194_ladder_runs_one_rung_per_process import _FakeYosys, _drive


def _run_with_admission_exhaustion(monkeypatch, after):
    now = [0.0]
    budget_cls = lec_run.StepBudget
    monkeypatch.setattr(lec_run, "StepBudget", lambda total_s: budget_cls(
        total_s, clock=lambda: now[0]))
    fake = _FakeYosys()

    def run(*args, **kwargs):
        launched, raw = fake(*args, **kwargs)
        if "Executing EQUIV_INDUCT pass." in raw:
            extra = "Proved 20 previously unproven $equiv cells.\n"
            raw += extra
            with kwargs["live_log_path"].open("a") as log:
                log.write(extra)
        result = launched, raw
        if len(fake.scripts) == after:
            now[0] = 8000.0
        return result

    return _drive(monkeypatch, run)


# `after` counts yosys PROCESSES, one per rung. Since 6dc565435 the ladder is
# five rungs (`equiv_simple_short`, `equiv_simple_full`, then the three
# induction rungs), so admission runs out after the THIRD process to leave
# `equiv_induct_seq4` as the completed checkpoint, and after the FIFTH to let
# the last rung finish.
def test_unadmitted_next_rung_keeps_completed_checkpoint_resumable(monkeypatch):
    rc, report = _run_with_admission_exhaustion(monkeypatch, 3)
    assert rc == 0  # Producer writes evidence; the independent gate owns PASS.
    assert report["lec_ladder"]["complete"] is False
    assert report["lec_attempts_detail"][-1]["launched"] is False
    assert report["compared_points"] == 40
    assert report["unproven_points"] == 60
    assert report["lec_resume"]["state"] == "RESUMABLE"
    assert report["lec_resume"]["resumable_from_rung"] == "equiv_induct_seq4"


def test_unadmitted_next_rung_does_not_claim_engine_exhaustion(monkeypatch):
    _, report = _run_with_admission_exhaustion(monkeypatch, 3)
    assert report["step_budget_exhausted"] is True
    assert report["step_budget_stopped_this_proof"] is False
    # Admission was spent, but no running attempt exhausted a resource.
    # Keep this distinct from an observed process stop (the #2182 contract).
    assert report["exhausted_resource"] is None
    why = report["verdict_explanation"]
    assert "later proof rung was not admitted" in why
    assert "ladder was exhausted" not in why
    assert "raising --timeout / VIBEIC_LEC_YOSYS_TIMEOUT_S cannot" not in why


def test_completed_last_rung_remains_complete_when_it_outlasts_admission(monkeypatch):
    _, report = _run_with_admission_exhaustion(monkeypatch, 5)
    assert report["step_budget_exhausted"] is True
    assert report["lec_ladder"]["complete"] is True
    assert report["lec_resume"]["state"] == "COMPLETE"
    assert report["lec_resume"]["resumable_from_rung"] is None
