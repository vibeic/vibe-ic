"""ORGANIC #592 — canonicalize's per-stage DEF audit expected the
end-of-tcl routed.def only: after any mid-tcl death past routing it
reported "per-stage DEFs missing: ['routed.def']. Re-run ... from
scratch" while the routed_preantenna.def checkpoint (#548) sat right
there — emitter↔checker drift against the runner's own checkpoint
convention, with factually wrong from-scratch advice.

Fix: stage names source from the shared _PNR_CHECKPOINT_STAGES table;
route-stage evidence = routed.def OR routed_preantenna.def; when only
the checkpoint exists the note says resume-from-checkpoint.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

_AUDIT_SRC = inspect.getsource(R.step_canonicalize_artefacts)


def test_stage_list_sourced_from_shared_checkpoint_table():
    """The hand-typed stage list is gone — names come from
    _PNR_CHECKPOINT_STAGES so the two sites cannot drift again."""
    assert "_PNR_CHECKPOINT_STAGES" in _AUDIT_SRC
    assert '["floorplan.def", "placed.def", "post_cts.def",' \
        not in _AUDIT_SRC


def test_checkpoint_alias_and_resume_advice_present():
    assert "routed_preantenna.def" in _AUDIT_SRC
    assert "Resume from the checkpoint" in _AUDIT_SRC
    # the from-scratch advice survives ONLY for genuinely-missing stages
    assert "from scratch" in _AUDIT_SRC


def test_shared_table_route_stage_is_preantenna():
    """The shared table's route-stage filename is the checkpoint —
    pinning the emitter side of the contract this fix consumes."""
    names = [f for f, _ in R._PNR_CHECKPOINT_STAGES]
    assert "routed_preantenna.def" in names
    assert "floorplan.def" in names and "placed.def" in names


def _audit_missing_logic(pnr_out: Path):
    """Re-execute the fixed audit logic shape on a fixture dir (the full
    step needs container tooling; the gate under test is pure path
    logic — mirrored here byte-for-byte from the runner)."""
    expected = [f for f, _l in R._PNR_CHECKPOINT_STAGES
                if f != "routed_preantenna.def"] + ["routed.def"]
    missing = [n for n in expected if not (pnr_out / n).is_file()]
    checkpoint = pnr_out / "routed_preantenna.def"
    from_checkpoint = "routed.def" in missing and checkpoint.is_file()
    if from_checkpoint:
        missing.remove("routed.def")
    return missing, from_checkpoint


def test_mid_tcl_death_shape_resolves_to_resume(tmp_path):
    """The issue's exact 現象: every stage through the checkpoint exists,
    routed.def does not (mid-tcl death after route) → no missing-stage
    complaint for the route stage; resume advice instead."""
    pnr = tmp_path / "pnr"
    pnr.mkdir()
    for fname in ("floorplan.def", "placed.def", "post_cts.def",
                  "post_hold.def", "routed_preantenna.def"):
        (pnr / fname).write_text("VERSION 5.8 ;\n")
    missing, from_checkpoint = _audit_missing_logic(pnr)
    assert from_checkpoint is True
    assert "routed.def" not in missing
    assert missing == []


def test_genuinely_missing_route_still_reported(tmp_path):
    """NEGATIVE: neither routed.def nor the checkpoint → route stage IS
    missing (the from-scratch advice is then correct)."""
    pnr = tmp_path / "pnr"
    pnr.mkdir()
    for fname in ("floorplan.def", "placed.def"):
        (pnr / fname).write_text("VERSION 5.8 ;\n")
    missing, from_checkpoint = _audit_missing_logic(pnr)
    assert from_checkpoint is False
    assert "routed.def" in missing
