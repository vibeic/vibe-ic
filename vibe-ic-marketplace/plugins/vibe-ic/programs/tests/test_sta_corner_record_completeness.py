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

Fixtures:
  * a slow sign-off corner VIOLATING while the typ corner passes  -> FAIL
  * a corner that RAN but is absent from the report               -> FAIL
  * every corner reported and every sign-off corner met           -> PASS
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
    }))
    _write(run / "reports/phase3/mcorner_ocv_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_ocv_process",
        "setup_process_corner": "SS", "hold_process_corner": "FF",
        "multi_process_corner": True,
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


def _multicorner(setup_slack: float, hold_slack: float,
                 setup_tns: float = 0.0, hold_tns: float = 0.0,
                 *, omit_hold_section: bool = False) -> str:
    body = (
        "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)\n"
        "# SETUP corner: max-RC   HOLD corner: min-RC\n"
        "# corners_available: max,min,nom\n"
        "=== SETUP (max-RC corner, SPEF=max) ===\n"
        f"worst slack max {setup_slack}\n"
        f"tns max {setup_tns}\n"
    )
    if not omit_hold_section:
        body += (
            "=== HOLD (min-RC corner, SPEF=min) ===\n"
            f"worst slack min {hold_slack}\n"
            f"tns max {hold_tns}\n"
        )
    return body


def _mcorner_ocv(setup_slack: float, hold_slack: float) -> str:
    return (
        "=== SETUP corner: process=SS liberty, SPEF=design.max.spef ===\n"
        "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
        f"worst slack max {setup_slack}\n"
        "tns max 0.00\n"
        "=== HOLD corner: process=FF liberty, SPEF=design.min.spef ===\n"
        "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
        f"worst slack min {hold_slack}\n"
        "tns max 0.00\n"
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
