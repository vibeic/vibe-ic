"""Tests for ship_postroute_convergence_exhaustion_check.

The defect this gate exists for: the post-reroute convergence loop announces a
policy break (`SHIP_CVG_CLOSED` / `SHIP_CVG_PLATEAU` / ...) but announces
NOTHING when it simply runs out of passes. Both exits publish the same
`SHIP_WNS_POSTROUTE` line and the same VIOLATED setup verdict, so a run that
stopped COUNTING is indistinguishable from one that stopped CONVERGING — and
they call for opposite actions (raise a constant vs change the design).

BIDIRECTIONAL NEGATIVE CONTROL is the point of this file: it is not enough to
show the gate FAILs the bound-exhausted-while-converging shape. It must also
PASS the plateaued shape that reaches the same bound and publishes the same
kind of number, otherwise the gate is just "did the loop hit its bound", which
would fire on every healthy long run and be worthless. `test_plateaued_*` and
`test_still_converging_*` are the same log shape differing ONLY in the trend of
the last transition.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import ship_postroute_convergence_exhaustion_check as C  # noqa: E402

SCRIPT = PROG / "ship_postroute_convergence_exhaustion_check.py"


def _log(passes, terminal=None, postroute=None, unrouted=None, estimate=None):
    """Build a synthetic loop transcript. `passes` is [(wns, drv), ...]."""
    lines = []
    for i, (wns, drv) in enumerate(passes):
        if wns is not None:
            lines.append(f"SHIP_WNS_CVG_PASS{i}: {wns}")
        if drv is not None:
            lines.append(f"SHIP_DRV_CVG_PASS{i}: {drv}")
    if terminal:
        lines.append(terminal)
    if estimate is not None:
        lines.append(f"SPEF_REPAIR_WNS_AFTER: {estimate}")
    if postroute is not None:
        lines.append(f"SHIP_WNS_POSTROUTE: {postroute}")
    if unrouted is not None:
        lines.append(f"SHIP_WNS_UNROUTED: {unrouted}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# The measured shape, quoted from the emitter's own source comment above
# `_SHIP_POSTROUTE_CVG_MAX_PASSES` (bound was 3 at the time of that capture).
# --------------------------------------------------------------------------
MEASURED_BOUND3 = [(-4.4438, 190), (-3.0167, 179), (-1.3748, 78)]


def test_measured_bound3_capture_is_flagged_as_still_converging():
    """The exact transcript the emitter's comment records: ~1.5 ns of gain per
    pass, DRV collapsing, no plateau in sight, bound reached."""
    verdict, findings, summary = C.audit(
        _log(MEASURED_BOUND3, postroute=-1.6742), bound=3)
    assert verdict == "FAIL"
    assert summary["bound_exhausted"] is True
    assert summary["still_converging_at_exit"] is True
    assert any(f.label == "bound_exhausted_while_converging" for f in findings)


def test_still_converging_by_wns_alone():
    """WNS improving faster than the plateau threshold is sufficient, even with
    DRV flat."""
    verdict, _, summary = C.audit(
        _log([(-4.0, 50), (-3.0, 50)], postroute=-3.0), bound=2)
    assert verdict == "FAIL"
    assert summary["still_converging_at_exit"] is True


def test_still_converging_by_drv_alone():
    """The loop's plateau break requires BOTH axes to stop improving, so a
    falling DRV keeps it converging even when WNS is flat."""
    verdict, _, summary = C.audit(
        _log([(-4.0, 90), (-4.0, 40)], postroute=-4.0), bound=2)
    assert verdict == "FAIL"
    assert summary["still_converging_at_exit"] is True


# --------------------------------------------------------------------------
# NEGATIVE CONTROL: same shape, same bound reached, same published number —
# only the trend differs. The gate must NOT fire.
# --------------------------------------------------------------------------
def test_plateaued_at_bound_passes():
    """Bound reached, but the last pass gained less than the plateau threshold
    and DRV did not fall: the next pass would have tripped the loop's own
    plateau break, so this IS a convergence result."""
    verdict, findings, summary = C.audit(
        _log([(-2.10, 12), (-2.05, 12)], postroute=-2.05), bound=2)
    assert verdict == "PASS"
    assert summary["bound_exhausted"] is True
    assert summary["still_converging_at_exit"] is False
    assert any(f.label == "bound_exhausted_but_plateaued" for f in findings)


def test_gain_exactly_at_threshold_is_plateau_not_converging():
    """The loop breaks on `wns_now <= wns_prev + 0.10`, so a gain of exactly
    0.10 is a PLATEAU. Off-by-one here would invert the verdict on a boundary
    run."""
    verdict, _, summary = C.audit(
        _log([(-2.00, 5), (-1.90, 5)], postroute=-1.90), bound=2)
    assert verdict == "PASS"
    assert summary["still_converging_at_exit"] is False


def test_threshold_uses_the_loops_expression_form_not_the_difference():
    """REGRESSION. `wns_now <= wns_prev + 0.10` and `wns_now - wns_prev > 0.10`
    are algebraically equal and NOT equal in IEEE doubles. At prev=-2.00,
    now=-1.90 the loop plateaus (prev+0.10 is exactly -1.9) while the
    difference is 0.10000000000000009 and the difference form calls it
    still-improving — so a gate written the natural way contradicts the loop it
    audits, and reports a converged run as bound-exhausted.

    This test fails against the difference form and passes against the
    expression form, which is the only reason it is here."""
    prev, now = -2.00, -1.90
    assert (now - prev) > 0.10, "difference form would call this improving"
    assert not (now > prev + 0.10), "expression form calls this a plateau"
    _, _, summary = C.audit(_log([(prev, 5), (now, 5)], postroute=now), bound=2)
    assert summary["still_converging_at_exit"] is False


def test_drv_rising_with_flat_wns_is_plateau():
    verdict, _, summary = C.audit(
        _log([(-2.00, 5), (-1.99, 9)], postroute=-1.99), bound=2)
    assert verdict == "PASS"
    assert summary["still_converging_at_exit"] is False


# --------------------------------------------------------------------------
# Policy-terminated exits: the loop said why it stopped, so the bound is not
# the story regardless of the trend.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("marker", [
    "SHIP_CVG_CLOSED",
    "SHIP_CVG_CLOSED_DRV_UNMEASURED",
    "SHIP_CVG_PLATEAU",
    "SHIP_CVG_NONNUMERIC",
])
def test_terminal_marker_is_a_pass(marker):
    verdict, findings, summary = C.audit(
        _log(MEASURED_BOUND3, terminal=marker, postroute=-1.6742), bound=3)
    assert verdict == "PASS"
    assert summary["terminal_marker"] == marker
    assert any(f.label == "loop_ended_on_own_policy" for f in findings)


def test_closed_drv_unmeasured_is_not_misreported_as_closed():
    """CLOSED is a prefix of CLOSED_DRV_UNMEASURED; matching the shorter marker
    first would silently upgrade a DRV-unmeasured close to a full close."""
    _, _, summary = C.audit(
        _log([(-0.0005, -1)], terminal="SHIP_CVG_CLOSED_DRV_UNMEASURED"),
        bound=8)
    assert summary["terminal_marker"] == "SHIP_CVG_CLOSED_DRV_UNMEASURED"


# --------------------------------------------------------------------------
# Honest-FAIL contract: nothing here may become a vacuous PASS.
# --------------------------------------------------------------------------
def test_no_markers_is_error_not_pass():
    verdict, _, _ = C.audit("global_route done\ndetailed_route done\n", bound=8)
    assert verdict == "ERROR"


def test_short_run_without_terminal_marker_is_indeterminate():
    """Fewer passes than the bound AND no terminal marker: the loop neither
    ended on policy nor reached its backstop. Truncated log or abnormal exit —
    not a convergence result, and not a pass."""
    verdict, findings, _ = C.audit(
        _log([(-4.0, 90), (-3.0, 40)], postroute=-3.0), bound=8)
    assert verdict == "ERROR"
    assert any(f.label == "indeterminate_exit" for f in findings)


def test_single_pass_at_bound_is_indeterminate():
    verdict, _, _ = C.audit(_log([(-4.0, 90)], postroute=-4.0), bound=1)
    assert verdict == "ERROR"


def test_missing_wns_on_last_transition_is_indeterminate():
    """A missing measurement is UNMEASURED, not plateaued — it must not be
    allowed to resolve to a PASS."""
    raw = "SHIP_WNS_CVG_PASS0: -4.0\nSHIP_DRV_CVG_PASS0: 90\n" \
          "SHIP_DRV_CVG_PASS1: 40\nSHIP_WNS_POSTROUTE: -3.0\n"
    verdict, _, _ = C.audit(raw, bound=2)
    assert verdict == "ERROR"


def test_unmeasured_drv_cannot_prove_convergence():
    """The emitter writes -1 when the DRV probe could not run. UNMEASURED is
    not ZERO and must not satisfy 'DRV still falling'."""
    verdict, _, summary = C.audit(
        _log([(-2.00, -1), (-1.99, -1)], postroute=-1.99), bound=2)
    assert verdict == "PASS"
    assert summary["still_converging_at_exit"] is False


# --------------------------------------------------------------------------
# The estimate is not a closure.
# --------------------------------------------------------------------------
def test_estimate_is_named_as_an_estimate():
    _, findings, summary = C.audit(
        _log([(-2.10, 12), (-2.05, 12)], postroute=-2.05, estimate=0.0003),
        bound=2)
    assert summary["estimate_wns_after"] == pytest.approx(0.0003)
    note = [f for f in findings if f.label == "estimate_is_not_closure"]
    assert note, "a positive-looking estimate must be named as an estimate"
    assert "not what this design ships" in note[0].detail


def test_estimate_never_becomes_the_fail_reason():
    """A healthy-looking estimate must not rescue a bound-exhausted run, and
    must not itself be the reason a run fails."""
    verdict, findings, _ = C.audit(
        _log(MEASURED_BOUND3, postroute=-1.6742, estimate=0.0003), bound=3)
    assert verdict == "FAIL"
    fails = [f for f in findings if f.severity == "FAIL"]
    assert all(f.label != "estimate_is_not_closure" for f in fails)


def test_unrouted_number_is_reported_when_reroute_failed():
    verdict, findings, summary = C.audit(
        _log(MEASURED_BOUND3, unrouted=-1.6742), bound=3)
    assert verdict == "FAIL"
    assert summary["unrouted_wns"] == pytest.approx(-1.6742)
    assert any("SHIP_WNS_UNROUTED" in f.detail for f in findings)


# --------------------------------------------------------------------------
# CLI / exit-code contract.
# --------------------------------------------------------------------------
def _run(args):
    return subprocess.run([sys.executable, str(SCRIPT)] + args,
                          capture_output=True, text=True)


def test_cli_exit_1_on_converging_bound_exhaustion(tmp_path):
    log = tmp_path / "pnr.log"
    log.write_text(_log(MEASURED_BOUND3, postroute=-1.6742))
    res = _run([str(log), "--bound", "3"])
    assert res.returncode == 1
    assert "FAIL" in res.stdout
    assert "bound_exhausted_while_converging" in res.stdout


def test_cli_exit_0_on_plateau(tmp_path):
    log = tmp_path / "pnr.log"
    log.write_text(_log([(-2.10, 12), (-2.05, 12)], postroute=-2.05))
    res = _run([str(log), "--bound", "2"])
    assert res.returncode == 0
    assert "PASS" in res.stdout


def test_cli_exit_2_on_missing_file(tmp_path):
    res = _run([str(tmp_path / "nope.log")])
    assert res.returncode == 2


def test_cli_exit_2_on_empty_file(tmp_path):
    log = tmp_path / "empty.log"
    log.write_text("")
    res = _run([str(log)])
    assert res.returncode == 2


def test_cli_exit_2_on_bad_bound(tmp_path):
    log = tmp_path / "pnr.log"
    log.write_text(_log(MEASURED_BOUND3, postroute=-1.6742))
    res = _run([str(log), "--bound", "0"])
    assert res.returncode == 2


def test_cli_scans_a_run_directory(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "unrelated.log").write_text("nothing to see\n")
    (tmp_path / "logs" / "pnr.log").write_text(
        _log(MEASURED_BOUND3, postroute=-1.6742))
    res = _run([str(tmp_path), "--bound", "3"])
    assert res.returncode == 1
    assert "bound_exhausted_while_converging" in res.stdout


def test_cli_exit_2_on_directory_without_markers(tmp_path):
    (tmp_path / "a.log").write_text("global_route done\n")
    res = _run([str(tmp_path)])
    assert res.returncode == 2


def test_cli_json_report(tmp_path):
    log = tmp_path / "pnr.log"
    log.write_text(_log(MEASURED_BOUND3, postroute=-1.6742))
    out = tmp_path / "r.json"
    res = _run([str(log), "--bound", "3", "--json", str(out)])
    assert res.returncode == 1
    report = json.loads(out.read_text())
    assert report["gate"] == "ship_postroute_convergence_exhaustion_check"
    assert report["verdict"] == "FAIL"
    assert report["summary"]["still_converging_at_exit"] is True


# --------------------------------------------------------------------------
# The gate must stay honest about the emitter it mirrors.
# --------------------------------------------------------------------------
def test_plateau_threshold_matches_the_emitter():
    """If someone changes the loop's plateau constant without changing this
    gate, the two disagree about what 'improving' means and the gate starts
    lying. Pin them together."""
    runner = (PROG / "phase3_one_shot_runner.py").read_text()
    assert "_ship_prev_wns + 0.10" in runner, (
        "the loop's plateau threshold moved; update PLATEAU_WNS_GAIN_NS")
    assert C.PLATEAU_WNS_GAIN_NS == 0.10


def test_default_bound_matches_the_emitter():
    runner = (PROG / "phase3_one_shot_runner.py").read_text()
    assert f"_SHIP_POSTROUTE_CVG_MAX_PASSES = {C.DEFAULT_BOUND}" in runner, (
        "the emitter's backstop moved; update DEFAULT_BOUND")


def test_terminal_markers_all_exist_in_the_emitter():
    """Every marker this gate treats as a policy break must actually be emitted
    by the loop, or the gate would silently never see it and report a healthy
    exit as bound exhaustion."""
    runner = (PROG / "phase3_one_shot_runner.py").read_text()
    for marker in C.TERMINAL_MARKERS:
        assert marker in runner, f"{marker} is not emitted by the runner"
