"""ORGANIC #585 — step_pnr reported PASS when detailed route COMPLETED
with nonzero DRT violations (`Completing 100% with N violations`,
`[INFO DRT-0199] Number of violations = N`, rc=0): the unconverged GDS
flowed downstream and one congestion root-cause surfaced as hundreds of
fake DRC/LVS/STA findings (live: 297 route violations → 640 DRC).

Fix: _drt_final_violations() parses the LAST DRT-0199 count (fallback:
last `Completing 100% with N violations`); step_pnr FAILs with finding
ROUTE_NOT_CONVERGED naming N + the congestion knobs when N > 0; outputs
stay on disk but are marked non-signoff in extras.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# ── parser semantics ─────────────────────────────────────────────────────────

def test_parses_last_drt_0199_count():
    log = (
        "[INFO DRT-0195] Start 55th optimization iteration.\n"
        "Completing 100% with 312 violations.\n"
        "[INFO DRT-0199] Number of violations = 312.\n"
        "[INFO DRT-0195] Start 56th optimization iteration.\n"
        "Completing 100% with 297 violations.\n"
        "[INFO DRT-0199] Number of violations = 297.\n"
    )
    assert R._drt_final_violations(log) == 297


def test_parses_completing_line_fallback():
    log = "Completing 100% with 5 violations.\n"
    assert R._drt_final_violations(log) == 5


def test_converged_route_reads_zero():
    log = (
        "Completing 100% with 0 violations.\n"
        "[INFO DRT-0199] Number of violations = 0.\n"
        "[INFO DRT-0267] cpu time = ...\n"
    )
    assert R._drt_final_violations(log) == 0


def test_no_route_in_log_reads_none():
    assert R._drt_final_violations("") is None
    assert R._drt_final_violations("GPL-0301 utilization 120%") is None


def test_spef_repair_incremental_reroute_final_count_wins():
    """The post-route SPEF-repair incremental reroute prints its own
    DRT-0199 — the LAST one is the shipped geometry's state."""
    log = (
        "[INFO DRT-0199] Number of violations = 0.\n"   # main route clean
        "SPEF_REPAIR_CAPTABLE: ...\n"
        "[INFO DRT-0199] Number of violations = 3.\n"   # reroute left 3
    )
    assert R._drt_final_violations(log) == 3


# ── verdict wiring (the issue's 現象 end-state) ─────────────────────────────

def test_step_pnr_wires_route_convergence_gate():
    """step_pnr must consult _drt_final_violations after the rc gate and
    FAIL with ROUTE_NOT_CONVERGED naming the knobs when N > 0."""
    src = inspect.getsource(R.step_pnr)
    assert "_drt_final_violations" in src
    assert "ROUTE_NOT_CONVERGED" in src
    assert "--die-um" in src and "--util" in src
    assert "non_signoff_outputs" in src
    # the gate runs AFTER the rc/def-file FAIL gate
    assert src.index("rc != 0 or not def_file.is_file()") \
        < src.index("ROUTE_NOT_CONVERGED")


def test_drt_gate_verdict_directions(tmp_path):
    """Both directions per the issue: N>0 → FAIL shape; N==0 → no gate
    trip. Exercised through the parser + the wiring contract (full
    step_pnr needs docker; the parser is the deterministic core)."""
    bad = "Completing 100% with 297 violations.\n" \
          "[INFO DRT-0199] Number of violations = 297.\n"
    good = "[INFO DRT-0199] Number of violations = 0.\n"
    assert R._drt_final_violations(bad) == 297      # would FAIL
    assert R._drt_final_violations(good) == 0       # stays PASS
