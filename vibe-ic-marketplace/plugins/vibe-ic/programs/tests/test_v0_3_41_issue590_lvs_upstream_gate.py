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












def test_orchestrator_hands_pnr_result_to_lvs():
    src = inspect.getsource(R.main)
    assert "upstream_pnr=_pnr_result" in src
