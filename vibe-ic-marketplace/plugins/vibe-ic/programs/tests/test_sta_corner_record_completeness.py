"""sta_corner_record_completeness_check — the timing RECORD-completeness gate.

The measured defect: a campaign ledger carried NO STA column while two ICs
violated setup at the slow sign-off corner (-4.33 ns / TNS -259.13 and
-2.35 ns / TNS -10.36), both persisting through the post-fix verify runs.
Timing was absent from the record, so "the phase-3 failures were LVS tooling
artifacts" was allowed to stand as the whole explanation.

These tests exercise the program's PUBLIC contract only — `main(argv)`'s exit
code and the verdict JSON it writes (verdict / rules_violated / the per-corner
evidence table). No private helper, regex or internal data structure is
touched, so the gate stays free to be refactored.

A second measured defect, same disease: a "multi-corner" STA read the typ
liberty THREE TIMES, varying only the SPEF. Three corners were reported, one
library was analysed, and the report did not say so — so a run that DEGRADED to
single-corner was byte-indistinguishable from one that did not. The cost: 139
`max_slew` DRV violations at the slow corner, invisible because the flow never
asked OpenSTA for DRV in that report at all.

Fixtures:
  * a slow sign-off corner VIOLATING while the typ corner passes  -> FAIL
  * a corner that RAN but is absent from the report               -> FAIL
  * every corner reported and every sign-off corner met           -> PASS
  * corner libraries resolving to DISTINCT files (the regression
    control: a healthy multi-corner run must be unchanged)        -> PASS
  * corner libraries COLLAPSED onto one, disclosed      -> SINGLE_CORNER_ONLY
  * the same collapse, undisclosed / unrecorded                   -> FAIL
  * max_slew DRV violations present                               -> FAIL
  * DRV never queried (unqueried != clean)                        -> FAIL
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sta_corner_record_completeness_check as G  # noqa: E402


# ── fixture builders ───────────────────────────────────────────────────────
def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _declare(run: Path, *, primary: str = "TT") -> None:
    """Emit the corner DECLARATIONS a real run carries: the RC-axis and
    process-axis sign-off stances plus the PVT matrix naming the nominal
    corner. These are the artifacts the gate reads to learn which corners are
    sign-off — the same ones `phase3_one_shot_runner` writes."""
    _write(run / "reports/phase3/multi_corner_spef_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_spef",
        "corners_extracted": ["max", "min", "nom"],
        "corner_count": 3, "multi_corner": True,
        "setup_corner": "max", "hold_corner": "min",
        # The RC axis reads ONE process liberty across its corners by design
        # (parasitics vary, process does not) — recorded and disclosed, so it
        # can never be mistaken for a multi-LIBRARY claim.
        "corner_library_resolution": {
            "axis": "rc_parasitic",
            "liberty_by_corner": {"max": _LIB_TT, "min": _LIB_TT},
            "distinct_library_count": 1, "reported_corner_count": 2,
            "collapsed": True, "unresolved_corners": [],
            "unresolved_reason": "the RC axis varies parasitics only",
            "degradation_disclosure": "RC characterisation, not multi-process.",
        },
    }))
    _write(run / "reports/phase3/mcorner_ocv_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_ocv_process",
        "setup_process_corner": "SS", "hold_process_corner": "FF",
        "multi_process_corner": True,
        "corner_library_resolution": {
            "axis": "process",
            "liberty_by_corner": {"SS": _LIB_SS, "FF": _LIB_FF},
            "distinct_library_count": 2, "reported_corner_count": 2,
            "collapsed": False, "unresolved_corners": [],
            "unresolved_reason": None, "degradation_disclosure": None,
        },
    }))
    _write(run / "phase2/stage2/constraints/pvt_matrix.json", json.dumps({
        "version": "1.0", "primary_corner": primary, "corner_count": 3,
        "multi_corner": True,
        "corners": [
            {"name": "lib__ss_100C_1v40", "label": "SS"},
            {"name": "lib__tt_025C_1v80", "label": "TT"},
            {"name": "lib__ff_n40C_1v95", "label": "FF"},
        ],
    }))


# The check-types attestation the emitter appends when `report_check_types`
# actually ran. Its ABSENCE is how the gate tells "queried and clean" apart from
# "never asked" — so every fixture that means to be clean must carry it.
_DRV_OK = ("SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew "
           "min_pulse_width max_capacitance\n")

_LIB_TT = "/pdk/lib/cells__tt_025C_1v80.lib"
_LIB_SS = "/pdk/lib/cells__ss_100C_1v60.lib"
_LIB_FF = "/pdk/lib/cells__ff_n40C_1v95.lib"


def _multicorner(setup_slack: float, hold_slack: float,
                 setup_tns: float = 0.0, hold_tns: float = 0.0,
                 *, omit_hold_section: bool = False,
                 liberty: str = _LIB_TT, drv: str = _DRV_OK) -> str:
    body = (
        "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)\n"
        "# SETUP corner: max-RC   HOLD corner: min-RC\n"
        "# corners_available: max,min,nom\n"
        f"# corner_liberty: max={liberty}\n"
        f"# corner_liberty: min={liberty}\n"
        "# distinct_corner_libraries: 1 across 2 reported corner(s)\n"
        f"=== SETUP (max-RC corner, SPEF=max, liberty={liberty}) ===\n"
        f"worst slack max {setup_slack}\n"
        f"tns max {setup_tns}\n"
        + drv
    )
    if not omit_hold_section:
        body += (
            f"=== HOLD (min-RC corner, SPEF=min, liberty={liberty}) ===\n"
            f"worst slack min {hold_slack}\n"
            f"tns max {hold_tns}\n"
            + drv
        )
    return body


def _mcorner_ocv(setup_slack: float, hold_slack: float,
                 *, setup_lib: str = _LIB_SS, hold_lib: str = _LIB_FF,
                 drv: str = _DRV_OK) -> str:
    return (
        f"=== SETUP corner: process=SS liberty={setup_lib}, "
        "SPEF=design.max.spef ===\n"
        "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
        f"worst slack max {setup_slack}\n"
        "tns max 0.00\n"
        + drv +
        f"=== HOLD corner: process=FF liberty={hold_lib}, "
        "SPEF=design.min.spef ===\n"
        "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
        f"worst slack min {hold_slack}\n"
        "tns max 0.00\n"
        + drv
    )


def _nominal(setup_slack: float) -> str:
    return f"worst slack max {setup_slack}\ntns max 0.00\n"


def _run(tmp: Path, name: str) -> Path:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _judge(run: Path, tmp: Path) -> tuple:
    """Invoke the program the way the flow does and read back its verdict."""
    out = tmp / f"{run.name}.json"
    rc = G.main([str(run), "--json", str(out)])
    return rc, json.loads(out.read_text())


# ── FIXTURE 1: slow sign-off corner violates while typ passes ──────────────
def test_slow_signoff_corner_violating_while_typ_passes_fails(tmp_path):
    """The subservient shape: the typ corner reports MET, the slow sign-off
    corner is deeply negative. A typ-only 'MET' must not carry the run."""
    run = _run(tmp_path, "slow_violating")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(-4.33, 0.36, setup_tns=-259.13, hold_tns=-223.23))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(-25.12, 0.21))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.05))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert res["verdict"] == "FAIL"
    assert "R3_SIGNOFF_CORNER_VIOLATION" in res["rules_violated"]


def test_typ_met_while_signoff_violated_is_named_a_misleading_pass(tmp_path):
    """The verdict must SAY that the typ corner met while a sign-off corner
    violated — the whole point is that this combination reads as a pass."""
    run = _run(tmp_path, "misleading")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(-2.35, 0.52, setup_tns=-10.36))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(-60.27, 0.32))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.00))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    blob = " ".join(res["reasons"]).lower()
    assert "misleading pass" in blob


def test_violating_signoff_corner_appears_in_the_evidence_table(tmp_path):
    """The absence of a per-corner table IS the defect being fixed, so the
    gate must emit the corner, both slacks, the TNS and the source log."""
    run = _run(tmp_path, "evidence")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(-4.33, 0.36, setup_tns=-259.13, hold_tns=-223.23))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(-25.12, 0.21))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.05))

    _rc, res = _judge(run, tmp_path)

    by_name = {(c["axis"], c["corner"]): c for c in res["corners"]}
    setup_row = by_name[("rc", "max")]
    assert setup_row["setup_wns_ns"] == -4.33
    assert setup_row["tns_ns"] == -259.13
    assert setup_row["role_class"] == "signoff"
    assert "sta_spef_multicorner.rpt" in setup_row["source"]

    hold_row = by_name[("rc", "min")]
    assert hold_row["hold_wns_ns"] == 0.36
    assert "sta_spef_multicorner.rpt" in hold_row["source"]

    # The process axis is judged too, with its own source log.
    assert by_name[("process", "SS")]["setup_wns_ns"] == -25.12
    assert "sta_mcorner_ocv.rpt" in by_name[("process", "SS")]["source"]


# ── FIXTURE 2: a corner that ran but is absent from the report ─────────────
def test_corner_that_ran_but_is_absent_from_the_report_fails(tmp_path):
    """The flow declared and ran a HOLD sign-off corner, but the report carries
    no HOLD section. An unreported corner must not be indistinguishable from a
    met one — every sign-off slack that IS present here is comfortably met, so
    only the missing corner can carry the FAIL."""
    run = _run(tmp_path, "corner_absent")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(5.00, 0.0, omit_hold_section=True))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(1.00))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert res["verdict"] == "FAIL"
    assert "R2_DECLARED_BUT_UNREPORTED" in res["rules_violated"]
    # No slack anywhere is negative — the FAIL is purely the missing corner.
    assert "R3_SIGNOFF_CORNER_VIOLATION" not in res["rules_violated"]
    min_row = next(c for c in res["corners"]
                   if (c["axis"], c["corner"]) == ("rc", "min"))
    assert min_row["reported"] is False


def test_declared_corner_with_no_report_at_all_fails(tmp_path):
    """A verdict may outlive the report it cites: the stance declares max/min
    sign-off corners while the multicorner report is gone entirely. That must
    FAIL, not self-skip — self-skipping on an absent report is precisely the
    hole this gate closes."""
    run = _run(tmp_path, "report_missing")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert "R2_DECLARED_BUT_UNREPORTED" in res["rules_violated"]
    blob = " ".join(res["reasons"]).lower()
    assert "no timing datapoint" in blob


def test_verdict_citing_a_missing_report_fails(tmp_path):
    """A prior STA verdict can outlive the report it cites. The citation proves
    corners were analysed and the missing target proves nothing survived to
    substantiate it, so the run must FAIL rather than read as 'nothing to
    judge' — a stale FAIL verdict with no evidence behind it is not a record."""
    run = _run(tmp_path, "dangling")
    _write(run / "reports/phase3/sta/post_route_signoff_corner.json",
           json.dumps({"verdict": "FAIL", "setup_worst_slack_ns": -52.48,
                       "report": "phase3/stage3/sta/sta_spef_multicorner.rpt"}))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert res["verdict"] == "FAIL"
    assert "R2_DECLARED_BUT_UNREPORTED" in res["rules_violated"]
    blob = " ".join(res["reasons"])
    assert "does NOT exist" in blob


def test_verdict_citing_a_present_report_is_not_flagged(tmp_path):
    """The citation rule must not fire when the cited evidence is there."""
    run = _run(tmp_path, "citation_ok")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(6.18, 0.54))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.00))
    _write(run / "reports/phase3/sta/post_route_signoff_corner.json",
           json.dumps({"verdict": "PASS",
                       "report": "phase3/stage3/sta/sta_spef_multicorner.rpt"}))

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    assert res["verdict"] == "PASS"


# ── FIXTURE 3: the control — a genuinely clean run must PASS ───────────────
def test_every_corner_reported_and_every_signoff_met_passes(tmp_path):
    """A gate that cannot return clean is an alarm, not a gate. Every declared
    corner is reported for the role it serves and every sign-off corner is
    met, so the verdict must be PASS with exit 0."""
    run = _run(tmp_path, "clean")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(6.18, 0.54))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.00))

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    assert res["verdict"] == "PASS"
    assert res["rules_violated"] == []


def test_clean_run_still_emits_the_full_per_corner_table(tmp_path):
    """Evidence is emitted on PASS too — a gate that only shows its working
    when it fails reproduces the missing-record defect on every clean run."""
    run = _run(tmp_path, "clean_evidence")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(6.18, 0.54))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.00))

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    reported = {(c["axis"], c["corner"]): c for c in res["corners"]
                if c["reported"]}
    # both axes, both roles, each with its slack and its source log
    assert reported[("rc", "max")]["setup_wns_ns"] == 6.18
    assert reported[("rc", "min")]["hold_wns_ns"] == 0.54
    assert reported[("process", "SS")]["setup_wns_ns"] == 2.68
    assert reported[("process", "FF")]["hold_wns_ns"] == 0.33
    for row in reported.values():
        assert row["source"]


def test_nominal_corner_alone_is_not_a_timing_verdict(tmp_path):
    """A run whose ONLY timing artifact is the nominal single-corner report,
    while sign-off corners were declared, is a typ-only record and must FAIL."""
    run = _run(tmp_path, "typ_only")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(1.50))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert "R2_DECLARED_BUT_UNREPORTED" in res["rules_violated"]


# ── scope guards ───────────────────────────────────────────────────────────
def test_run_with_no_corner_declaration_is_not_applicable(tmp_path):
    """With nothing declared and nothing recorded the gate must say so rather
    than invent a sign-off corner set — and must not block the run."""
    run = _run(tmp_path, "bare")

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    assert res["verdict"] == "NOT_APPLICABLE"
    blob = " ".join(res["reasons"]).lower()
    assert "no_corner_declaration" in blob


def test_corner_names_are_read_from_the_run_not_hardcoded(tmp_path):
    """The gate must learn corner identity from the run's own declaration. A
    PDK using an entirely different corner vocabulary is judged the same way."""
    run = _run(tmp_path, "other_pdk")
    _write(run / "reports/phase3/multi_corner_spef_stance.json", json.dumps({
        "corners_extracted": ["rcworst", "rcbest", "cworst"],
        "setup_corner": "rcworst", "hold_corner": "rcbest",
    }))
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           "# SETUP corner: rcworst-RC   HOLD corner: rcbest-RC\n"
           "# corners_available: rcworst,rcbest,cworst\n"
           "=== SETUP (rcworst-RC corner, SPEF=rcworst) ===\n"
           "worst slack max -0.90\n"
           "tns max -12.00\n"
           "=== HOLD (rcbest-RC corner, SPEF=rcbest) ===\n"
           "worst slack min 0.11\n"
           "tns max 0.00\n")

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    names = {c["corner"] for c in res["corners"]}
    assert {"rcworst", "rcbest"} <= names
    row = next(c for c in res["corners"] if c["corner"] == "rcworst")
    assert row["role_class"] == "signoff"
    assert row["setup_wns_ns"] == -0.90


def test_float_noise_does_not_manufacture_a_violation(tmp_path):
    """A slack a hair below zero inside the tolerance is met, so STA rounding
    never produces a phantom FAIL."""
    run = _run(tmp_path, "noise")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(-0.0005, 0.54))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.00))

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    assert res["verdict"] == "PASS"


# ══ R4: a multi-corner verdict must be backed by multiple corner LIBRARIES ══
#
# Measured: a "multi-corner" STA read the typ liberty three times, varying only
# the SPEF. Three corners were reported; ONE library was analysed. The report
# did not say so, so a degraded run was indistinguishable from a real one.

def _collapse_stance(run: Path, *, disclose: bool, lib: str = _LIB_TT) -> None:
    """Both sign-off axes resolve every corner onto the SAME library — the
    process libs were not found, so `SS` and `FF` are the typ lib wearing corner
    labels. `disclose` toggles whether the run admits it."""
    block = {
        "axis": "process",
        "liberty_by_corner": {"SS": lib, "FF": lib},
        "distinct_library_count": 1, "reported_corner_count": 2,
        "collapsed": disclose, "unresolved_corners": ["SS", "FF"],
        "unresolved_reason": (
            "the active PDK exposed no distinct SS/FF process liberty"),
        "degradation_disclosure": (
            "2 process corners reported, 1 distinct liberty analysed."
            if disclose else None),
    }
    _write(run / "reports/phase3/mcorner_ocv_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_ocv_process",
        "setup_process_corner": "SS", "hold_process_corner": "FF",
        "multi_process_corner": True,
        "corner_library_resolution": block,
    }))
    rc_block = dict(block, axis="rc_parasitic",
                    liberty_by_corner={"max": lib, "min": lib})
    _write(run / "reports/phase3/multi_corner_spef_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_spef",
        "corners_extracted": ["max", "min", "nom"], "corner_count": 3,
        "multi_corner": True, "setup_corner": "max", "hold_corner": "min",
        "corner_library_resolution": rc_block,
    }))
    _write(run / "phase2/stage2/constraints/pvt_matrix.json", json.dumps({
        "version": "1.0", "primary_corner": "TT", "corner_count": 1,
        "corners": [{"name": "cells__tt_025C_1v80", "label": "TT"}],
    }))


# ── FIXTURE A (the regression control): corner libs resolve to DISTINCT files
def test_distinct_corner_libraries_still_report_multi_corner(tmp_path):
    """A run whose corner libraries genuinely differ must be unchanged: PASS,
    no R4, and NOT labelled single-corner. This is the regression the R4 rule
    could most easily cause — a gate that flags every run as degraded is as
    useless as one that flags none."""
    run = _run(tmp_path, "distinct_libs")
    _declare(run)     # process axis: SS -> ss lib, FF -> ff lib (2 distinct)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.05))

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    assert res["verdict"] == "PASS"
    assert res["single_corner_only"] is False
    assert not [r for r in res["rules_violated"] if r.startswith("R4")]
    # the evidence names the two distinct libraries it signed off with
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")
    assert proc["distinct_library_count"] == 2
    # corner keys are case-normalised for matching
    assert sorted(proc["liberty_by_corner"]) == ["ff", "ss"]


# ── FIXTURE B: every corner collapses onto ONE library ─────────────────────
def test_collapsed_corner_libraries_are_not_signed_off_as_multi_corner(tmp_path):
    """Three corners reported, one library analysed. DISCLOSED by the run, so
    it is not a FAIL — a PDK that ships one library cannot do better — but the
    verdict must not read as multi-corner sign-off."""
    run = _run(tmp_path, "collapsed_disclosed")
    _collapse_stance(run, disclose=True)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33, setup_lib=_LIB_TT, hold_lib=_LIB_TT))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.05))

    rc, res = _judge(run, tmp_path)

    # exit 0 — the degradation may be unavoidable and does not fail the run
    assert rc == 0
    # ...but the verdict STRING carries the limitation, so no downstream
    # summary can quote a bare "PASS" and have it read as multi-corner closure
    assert res["verdict"] == "SINGLE_CORNER_ONLY"
    assert res["single_corner_only"] is True
    blob = " ".join(res["reasons"])
    assert "SINGLE-CORNER DEGRADATION" in blob
    # it names WHICH corners shared a library and WHY the others were missing
    assert "cells__tt_025C_1v80.lib" in blob
    assert "no distinct SS/FF process liberty" in blob


def test_collapsed_libraries_while_claiming_multi_corner_fails(tmp_path):
    """The same collapse with NO disclosure anywhere: reporting N corners
    backed by one library while claiming multi-corner sign-off is a false
    claim regardless of intent."""
    run = _run(tmp_path, "collapsed_silent")
    _collapse_stance(run, disclose=False)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33, setup_lib=_LIB_TT, hold_lib=_LIB_TT))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert res["verdict"] == "FAIL"
    assert "R4_MULTI_CORNER_CLAIM_UNSUPPORTED" in res["rules_violated"]
    assert "FALSE CLAIM" in " ".join(res["reasons"])


def test_multi_corner_claim_without_any_library_record_fails(tmp_path):
    """The measured shape: a multi-corner claim whose report never says which
    liberty each corner used. Unverifiable multi-corner sign-off must not pass
    for want of a record — that would rebuild the defect inside its own gate."""
    run = _run(tmp_path, "unrecorded")
    _write(run / "reports/phase3/multi_corner_spef_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_spef",
        "corners_extracted": ["max", "min", "nom"], "corner_count": 3,
        "multi_corner": True, "setup_corner": "max", "hold_corner": "min",
    }))
    _write(run / "phase2/stage2/constraints/pvt_matrix.json",
           json.dumps({"primary_corner": "TT", "corners": []}))
    # the pre-fix report: corner sections, no liberty named anywhere
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)\n"
           "# SETUP corner: max-RC   HOLD corner: min-RC\n"
           "# corners_available: max,min,nom\n"
           "=== SETUP (max-RC corner, SPEF=max) ===\n"
           "worst slack max 0.412\ntns max 0.00\n"
           "=== HOLD (min-RC corner, SPEF=min) ===\n"
           "worst slack min 0.083\ntns max 0.00\n")

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert "R4_LIBRARY_RESOLUTION_UNRECORDED" in res["rules_violated"]
    assert "UNVERIFIABLE" in " ".join(res["reasons"])


# ══ R5: max_slew / DRV violations must be surfaced ═════════════════════════
#
# Measured: 139 max_slew violations at the slow corner, entirely invisible to
# the flow's check.

def _drv_table(kind: str, n: int) -> str:
    """An OpenSTA `report_check_types` DRV table carrying `n` violators."""
    rows = "".join(
        f"_{i:04d}_/A                     1.50     9.97    -8.47 (VIOLATED)\n"
        for i in range(n))
    return (f"{kind}\n\n"
            "Pin                          Limit     Slew    Slack\n"
            "----------------------------------------------------\n"
            + rows + "\n")


def test_max_slew_violations_are_surfaced(tmp_path):
    """DRV violations sitting in the report body must reach the verdict. They
    were present and unreported: timing MET at every corner while the design
    carried 139 max_slew violations."""
    run = _run(tmp_path, "drv_violating")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33) + _DRV_OK + _drv_table("max slew", 139))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.05))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert res["verdict"] == "FAIL"
    assert "R5_DRV_VIOLATION" in res["rules_violated"]
    blob = " ".join(res["reasons"])
    assert "max_slew x139" in blob
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")
    assert proc["drv"]["violations"]["max_slew"] == 139
    # ...and every slack in the run MET, so slack alone would have passed it
    assert "R3_SIGNOFF_CORNER_VIOLATION" not in res["rules_violated"]


def test_drv_never_queried_is_not_a_clean_result(tmp_path):
    """The deeper defect: if the flow never asks OpenSTA for DRV, the report
    cannot show a slew violation however many there are. An unqueried limit is
    indistinguishable from a met one."""
    run = _run(tmp_path, "drv_unqueried")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08, drv=""))     # no report_check_types at all
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.05))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert "R5_DRV_UNQUERIED" in res["rules_violated"]
    assert "never asked for DRV" in " ".join(res["reasons"])


def test_drv_queried_and_clean_passes(tmp_path):
    """The control for R5: the query ran and found nothing. Only the marker
    distinguishes this from the unqueried case."""
    run = _run(tmp_path, "drv_clean")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.05))

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    assert res["verdict"] == "PASS"
    assert not [r for r in res["rules_violated"] if r.startswith("R5")]
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")
    assert proc["drv"]["queried"] is True
    assert proc["drv"]["violations"] == {}


def test_evidence_table_shows_library_resolution_and_drv_on_pass(tmp_path):
    """The per-axis library + DRV evidence is printed on PASS as well as FAIL.
    A gate that hid the resolution while policing it would be absurd."""
    run = _run(tmp_path, "evidence")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))

    rc, res = _judge(run, tmp_path)
    table = G.render_table(res)

    assert rc == 0
    assert "corner-library resolution + DRV" in table
    assert "libraries=2" in table          # the process axis signed off with 2
    assert "DRV            queried, clean" in table
    assert _LIB_SS in table and _LIB_FF in table


def test_drv_count_does_not_bleed_into_adjacent_check_tables(tmp_path):
    """`report_check_types` prints several tables back to back. The negative
    numbers in a NEIGHBOURING table (OpenSTA's `Group Slack` / `Required Width`
    output, and the recovery/removal checks) must not be counted as DRV
    violators — an inflated count is as dishonest as a hidden one."""
    run = _run(tmp_path, "drv_bleed")
    _declare(run)
    report = (
        _mcorner_ocv(2.68, 0.33)
        + _drv_table("max slew", 2)
        + "recovery\n\n"
          "Pin                          Limit    Slack\n"
          "-------------------------------------------\n"
          "_9001_/CLK                    1.50    -3.20 (VIOLATED)\n"
          "_9002_/CLK                    1.50    -1.10 (VIOLATED)\n"
          "\n"
          "Required Width\n\n"
          "Pin                          Limit    Slack\n"
          "-------------------------------------------\n"
          "_9003_/CLK                    0.50    -0.90\n"
    )
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt", report)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.41, 0.08))

    rc, res = _judge(run, tmp_path)
    proc = next(a for a in res["axis_evidence"] if a["axis"] == "process")

    # exactly the 2 max_slew violators, none of the 3 rows from the
    # recovery / Required-Width tables that follow it
    assert proc["drv"]["violations"] == {"max_slew": 2}
    assert proc["drv"]["total"] == 2
    assert rc == 1 and "R5_DRV_VIOLATION" in res["rules_violated"]


def test_measured_shape_rc_corners_over_one_library_no_process_axis(tmp_path):
    """The exact measured shape, end to end: the PDK shipped no distinct
    process libraries, so the process-corner STA never ran and the ONLY
    multi-corner artifact is the RC report — several corners over one library.
    Post-fix the run records the resolution, so the verdict names the
    degradation instead of reading as multi-corner sign-off."""
    run = _run(tmp_path, "measured_shape")
    _write(run / "reports/phase3/multi_corner_spef_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_spef",
        "corners_extracted": ["max", "min", "nom"], "corner_count": 3,
        "multi_corner": True, "setup_corner": "max", "hold_corner": "min",
        "multicorner_sta_report": "phase3/stage3/sta/sta_spef_multicorner.rpt",
        "corner_library_resolution": {
            "axis": "rc_parasitic",
            "liberty_by_corner": {"max": _LIB_TT, "min": _LIB_TT},
            "distinct_library_count": 1, "reported_corner_count": 2,
            "collapsed": True,
            "unresolved_corners": ["SS", "FF"],
            "unresolved_reason": (
                "the active PDK exposed no distinct SS/FF process liberty"),
            "degradation_disclosure": (
                "RC characterisation over 1 liberty, not multi-process."),
        },
    }))
    _write(run / "phase2/stage2/constraints/pvt_matrix.json", json.dumps({
        "primary_corner": "TT",
        "corners": [{"name": "cells__tt_025C_1v80", "label": "TT"}]}))
    # every corner MET with TNS 0 — slack alone gives a clean bill of health
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.412, 0.083))

    rc, res = _judge(run, tmp_path)

    assert rc == 0
    assert res["verdict"] == "SINGLE_CORNER_ONLY"
    blob = " ".join(res["reasons"])
    assert "SINGLE-CORNER DEGRADATION" in blob
    assert "no distinct SS/FF process liberty" in blob
    # and it is explicit about what such a record CANNOT show
    assert "CANNOT be seen in this record" in blob


def test_measured_shape_with_max_slew_violations_fails(tmp_path):
    """The same shape once DRV is actually queried: setup and hold MET at every
    corner with TNS 0, but 139 max_slew violators. Slack alone passes it; the
    run must not."""
    run = _run(tmp_path, "measured_drv")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.412, 0.083) + _drv_table("max slew", 139))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(2.68, 0.33))

    rc, res = _judge(run, tmp_path)

    assert rc == 1
    assert "R5_DRV_VIOLATION" in res["rules_violated"]
    assert "R3_SIGNOFF_CORNER_VIOLATION" not in res["rules_violated"]
    rc_ax = next(a for a in res["axis_evidence"] if a["axis"] == "rc")
    assert rc_ax["drv"]["violations"] == {"max_slew": 139}
