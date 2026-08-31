"""A run that already meets setup never enters the convergence loop, correctly.

`_SHIP_SIGNOFF_REPAIR_TCL` takes a design signature before and after the
sign-off repair, and when the repair changed NO instance it keeps the base
route rather than throwing a DRC-clean route away to ship an identical one
(v1.8.43). The whole reroute + convergence block lives in the `else` of that
test. So a design that closes setup runs zero convergence passes — by design,
on a run that is behaving correctly.

`ship_postroute_convergence_exhaustion_check` had a state for "the loop ran and
the log is truncated" and none for "the emitter deliberately did not enter the
block", and the runner invokes it on BOTH branches. MEASURED on spm x gf180mcuD
(run spm_manual_1.14.30, plugin v1.14.30), from the run's own 211-line
`phase3/stage3/pnr/signoff_spef_repair.log`::

    SHIP_WNS_BEFORE:       10.742564475371312
    SHIP_WNS_AFTER_REPAIR: 10.742564475371312
    SHIP_REPAIR_NOOP: 1 (repair changed no instance; base route kept ...)
    <no SHIP_ROUTING_CLEARED, no SHIP_WNS_CVG_PASS*, no SHIP_CVG_*>
    SHIP_SIGNOFF_REPAIR_DONE

and it published `reports/phase3/ship_convergence_exhaustion.json` with verdict
ERROR and `passes_observed: 0`. Every design that closes setup posted that.

THE LOAD-BEARING NEGATIVE CONTROL is
`test_silence_with_no_disclosure_is_still_an_ERROR`. The fix reads a POSITIVE
marker the emitter writes, never the ABSENCE of pass markers; keyed on absence
it would also excuse a truncated log and an abnormal exit, which is the
opposite lie and the state this checker exists to name.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ship_postroute_convergence_exhaustion_check as C   # noqa: E402

_NOOP_LOG = """\
SHIP_WNS_BEFORE: 10.742564475371312
[INFO] Placement Analysis
SHIP_WNS_AFTER_REPAIR: 10.742564475371312
DESIGN_SIGNATURE _ship_sig1=1135:588166120
SHIP_REPAIR_NOOP: 1 (repair changed no instance; base route kept rather than re-routed for nothing)
SHIP_MIN_AREA_DONE: deficient=20 patched=11 unpatchable=9 pin_merged_skipped=145
SHIP_SIGNOFF_REPAIR_DONE
"""

_TRUNCATED_LOG = """\
SHIP_WNS_BEFORE: -4.4438
SHIP_ROUTING_CLEARED: 2575 (spare_preserved=0)
[INFO] Global routing
"""

_EXHAUSTED_LOG = "".join(
    f"SHIP_WNS_CVG_PASS{i}: {-4.5 + i:.4f}\nSHIP_DRV_CVG_PASS{i}: {200 - 10 * i}\n"
    for i in range(8)) + "SHIP_WNS_POSTROUTE: -1.6742\n"


def test_the_disclosed_non_entry_is_NOT_APPLICABLE_not_an_error():
    verdict, findings, summary = C.audit(_NOOP_LOG)
    assert verdict == "NOT_APPLICABLE", (
        f"got {verdict}: a run that closed setup and said so is neither a "
        f"convergence result nor an error")
    assert summary["passes_observed"] == 0
    assert summary.get("loop_entered") is False
    assert any(f.label == "loop_not_entered" for f in findings)


def test_NOT_APPLICABLE_is_never_folded_into_PASS():
    """It must be RENDERED AS ITSELF. Folded into PASS, a run that skipped the
    loop would be counted as a run that converged."""
    verdict, _f, _s = C.audit(_NOOP_LOG)
    assert verdict != "PASS"


def test_NOT_APPLICABLE_exits_zero(tmp_path):
    log = tmp_path / "signoff_spef_repair.log"
    log.write_text(_NOOP_LOG)
    assert C.main([str(log)]) == 0


def test_silence_with_no_disclosure_is_still_an_ERROR():
    """NEGATIVE CONTROL. Keyed on the absence of pass markers rather than on
    the emitter's own statement, the fix would excuse a truncated log too."""
    verdict, _f, summary = C.audit(_TRUNCATED_LOG)
    assert verdict == "ERROR", (
        "a log with no convergence passes AND no non-entry disclosure is a "
        "truncated or abnormal run, and must stay an error")
    assert summary.get("loop_entered") is None


def test_a_log_with_passes_takes_the_ordinary_path_regardless():
    """The two emitter branches are mutually exclusive; if a log somehow
    carried both, the MEASUREMENTS win — a real convergence is never
    reclassified as not-applicable."""
    verdict, _f, summary = C.audit(_NOOP_LOG + _EXHAUSTED_LOG)
    assert verdict in ("FAIL", "PASS")
    assert summary["passes_observed"] == 8
    assert summary.get("loop_entered") is True


def test_the_bound_exhausted_while_converging_FAIL_is_untouched():
    """The defect this checker was BUILT for must still be caught."""
    verdict, findings, _s = C.audit(_EXHAUSTED_LOG)
    assert verdict == "FAIL"
    assert any(f.label == "bound_exhausted_while_converging" for f in findings)


def test_a_directory_scan_reaches_the_same_verdict(tmp_path):
    """The standalone CLI and the in-runner call must not disagree on one log.
    Before the marker was added to the scan vocabulary, a directory holding
    exactly this log refused with rc 2 for 'no log carries the markers'."""
    (tmp_path / "phase3/stage3/pnr").mkdir(parents=True)
    (tmp_path / "phase3/stage3/pnr/signoff_spef_repair.log").write_text(_NOOP_LOG)
    assert C.main([str(tmp_path)]) == 0
