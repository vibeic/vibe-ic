"""v0.3.26 — ORGANIC #527: SPEF-based post-route STA becomes the Step-23
canonical basis when a SPEF exists; estimate-based report_checks is fallback
only; a sign-flip / >1ns disagreement is surfaced as a named discrepancy
artifact; the repair decision (no_repair_needed.flag vs repair_log.json) gates on the
SPEF-based report.

Field round-4 evidence (reproduced for REAL in-container during this fix on
the same routed design): estimate-based slack 0.47 MET vs SPEF-based -12.27
VIOLATED — the old flow canonicalized the optimistic estimate.

NEGATIVE (#527's own no-leak clause): with NO SPEF the behavior is byte-for-
byte the pre-#527 one (estimate-based copy + MET flag).

chip-AGNOSTIC: synthetic project + fake docker; no chip literal as logic.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

EST_MET = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
           0.47   slack (MET)
"""

EST_MET_TNS0 = EST_MET + "\ntns 0.00\n"

SPEF_VIOLATED = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
         -12.27   slack (VIOLATED)

tns max -60088.21
wns max -12.27
worst slack max -12.27
"""






















def test_postroute_timing_repair_status_gen_prefers_spef_report(tmp_path):
    import postroute_timing_repair_status_gen as G
    p = tmp_path
    pnr = p / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "sta.rpt").write_text(EST_MET_TNS0)            # estimate: MET
    sta = p / "phase3/stage3/sta"
    sta.mkdir(parents=True)
    (sta / "sta_spef_based.rpt").write_text(SPEF_VIOLATED)  # spef: VIOLATED
    rc = G.main([str(p)])
    assert rc == 0
    repair = p / "phase3/stage3/postroute_timing_repair"
    assert (repair / "repair_log.json").is_file(), \
        "SPEF-VIOLATED must drive repair_log.json even when the estimate is MET"
    assert not (repair / "no_repair_needed.flag").is_file()
    d = json.loads((repair / "repair_log.json").read_text())
    assert "sta_spef_based" in d.get("sta_source", "")
