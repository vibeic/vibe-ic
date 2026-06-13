"""ORGANIC #590 — step_lvs proceeded when step_pnr FAILed mid-tcl and
labelled the inevitable checkpoint mismatch a "design/extraction defect"
(hundreds of `(no pin, node is ...)` against an otherwise clean
checkpoint — the final DEF/pin-label stages were simply never written).

Fix: step_lvs takes `upstream_pnr`; a non-PASS pnr outcome SKIPs with
finding LVS_UPSTREAM_PNR_INCOMPLETE naming the pnr failure. The
orchestrator hands it the last pnr StepResult from the plan.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
    )


def test_lvs_skips_on_upstream_pnr_fail(tmp_path):
    """The issue's exact 現象: pnr FAIL (mid-tcl death) → lvs must SKIP
    naming the upstream failure, never the design-defect wording."""
    pnr_fail = R.StepResult(
        "pnr", "FAIL", 12.3,
        "ROUTE_NOT_CONVERGED: detailed route completed with 297 "
        "violations remaining (final DRT-0199).")
    r = R.step_lvs(tmp_path, "chip_top", _pdk(), "",
                   upstream_pnr=pnr_fail)
    assert r.status == "SKIP"
    assert r.extras["finding"] == "LVS_UPSTREAM_PNR_INCOMPLETE"
    assert "ROUTE_NOT_CONVERGED" in r.detail
    assert "design/extraction defect" not in r.detail.split("not a")[0]


def test_lvs_skips_on_upstream_pnr_timeout(tmp_path):
    pnr_to = R.StepResult("pnr", "TIMEOUT", 3600.0, "rc=124 killed")
    r = R.step_lvs(tmp_path, "chip_top", _pdk(), "",
                   upstream_pnr=pnr_to)
    assert r.status == "SKIP"
    assert r.extras["upstream_pnr_status"] == "TIMEOUT"


def test_lvs_proceeds_on_upstream_pnr_pass(tmp_path):
    """NEGATIVE: pnr PASS → the gate must NOT trip; lvs proceeds into
    its normal flow (here: fails later on missing inputs, which is the
    pre-existing behaviour — anything but the upstream-SKIP)."""
    pnr_ok = R.StepResult("pnr", "PASS", 100.0, "def=chip_top.def")
    r = R.step_lvs(tmp_path, "chip_top", _pdk(), "",
                   upstream_pnr=pnr_ok)
    assert r.extras.get("finding") != "LVS_UPSTREAM_PNR_INCOMPLETE"


def test_lvs_proceeds_without_upstream_info(tmp_path):
    """Standalone invocation (no plan context) keeps the old behaviour."""
    r = R.step_lvs(tmp_path, "chip_top", _pdk(), "")
    assert r.extras.get("finding") != "LVS_UPSTREAM_PNR_INCOMPLETE"


def test_orchestrator_hands_pnr_result_to_lvs():
    src = inspect.getsource(R.main)
    assert "upstream_pnr=_pnr_result" in src
