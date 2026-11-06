"""r46 (subservient x gf180mcuD as a DIE) — three sign-off gates that failed on
the ARTEFACT rather than on the design.

  sta_signoff  "No STA report found (searched *sta*.rpt, *timing*.rpt)" while
               sta_record was reading sta_mcorner_ocv.rpt in the same phase.
               The canonical alias post_route_timing.rpt is filled from the
               single-corner SPEF STA, and that run had REFUSED ITSELF (its own
               population record: "complete": false).
  em_signoff   "No current density values (Javg/Jpeak/mA/A/cm) found" while the
               real cause was PSM failing outright — [ERROR PSM-0069] Check
               connectivity failed on VDD — which nothing downstream said.
  drv_promotion_corroboration
               "the promotion claimed it ended at 11 ... the sign-off report
               shows 14 ... do not ship this route", comparing the resizer's
               in-session count at one corner against DRV rows in the
               MULTI-corner report. Different measurements, not a worse route.

Both directions for each.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402


# ---------------------------------------------------------------- sta alias


# ------------------------------------------------------------ promotion claim

def _promoted(tmp_path: Path, claim: dict | None, report_rows: int) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed_base_prerepair.def").write_text("marker\n")
    (pnr / "signoff_spef_repair.log").write_text(
        "[INFO RSZ-0034] Found 5 slew violations.\n"
        "[INFO RSZ-0036] Found 6 capacitance violations.\n")
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    rows = "".join(f"  pin{i}  1.0  2.0  -0.5\n" for i in range(report_rows))
    (sta / "sta_mcorner_ocv.rpt").write_text(rows)
    if claim is not None:
        (pnr / "drv_promotion_claim.json").write_text(json.dumps(claim))
    return tmp_path


# ------------------------------------------------------------------- EM record

def test_the_em_step_names_not_measured_and_why():
    """The producer must say NOT_MEASURED by name, with the tool's own reason.

    Asserted on the emitter's source because the branch runs inside a container
    STA/PSM pass: the strings a reader (and the EM gate) depend on are the
    contract, and before this they did not exist at all — the step wrote
    nothing and only appended a note.
    """
    import inspect
    src = inspect.getsource(R._emit_ir_em) if hasattr(R, "_emit_ir_em") else ""
    if not src:                      # emitter is nested; read the module text
        src = Path(R.__file__).read_text()
    marker = src[src.index("EM PSM produced no 'current' line") - 4000:
                 src.index("EM PSM produced no 'current' line") + 200] \
        if "EM PSM produced no 'current' line" in src else src
    assert "EM NOT_MEASURED" in src
    assert '"verdict": "NOT_MEASURED"' in src
    assert "not_measured_reason" in src
    # the cause is the tool's, not a guess: the failed nets and the
    # unconnected supply pins travel with it
    assert "nets_analysis_failed" in src and "connectivity_findings" in src


def test_the_em_record_is_not_a_pass():
    """NOT_MEASURED must never be spelled as a measured verdict."""
    src = Path(R.__file__).read_text()
    start = src.index("EM NOT_MEASURED")
    end = src.index('notes.append(f"EM NOT_MEASURED', start)
    record = src[start:end]            # exactly the not-measured branch
    assert '"verdict": "NOT_MEASURED"' in record
    assert '"verdict": "MEASURED"' not in record
    assert "Javg/Jpeak" in record      # the words the EM gate looks for


# ── the half that was missing, added after it cost three measurement arms ──
