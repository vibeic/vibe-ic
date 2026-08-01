"""Pillar 5 must never silently PASS an analog IC as "pure-digital".

Regression for the FALSE-PASS found by a clean-room mixed-signal run: the
analog runner writes its block list to `phase3/analog/analog_block_list.json`,
but `_is_analog_ic` only accepted the project-ROOT `analog/analog_block_list.json`
or a per-block **GDS** (an A5-layout artefact). An analog IC whose A-track ran
the real corner sweep (A4) but stopped before layout — the normal state whenever
A5 is waived — was therefore classified pure-digital, and Pillar 5 (analog
closed-loop verification, the load-bearing pillar for a mixed-signal IC)
reported PASS while verifying nothing.

chip-AGNOSTIC: fixtures carry no chip name, vendor, SKU or block topology.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark_verify_report import _is_analog_ic  # noqa: E402


def _mk(tmp_path: Path, rel: str, body: str = "{}") -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ── the leak: an A-track that stopped before layout ──────────────────────────

@pytest.mark.parametrize("rel", [
    # the path the analog runner actually writes (the original miss)
    "phase3/analog/analog_block_list.json",
    # per-block artefacts from A1..A4 — all pre-layout, so none imply a GDS
    "phase3/analog/blk/corner_results.json",
    "phase3/analog/blk/spec.json",
    "phase3/analog/blk/topology.md",
    "phase3/analog/blk/blk.sp",
])
def test_pre_layout_analog_artefact_is_detected(tmp_path, rel):
    """Any A1..A4 artefact must mark the IC analog — Pillar 5 must engage even
    though A5 never produced a GDS."""
    _mk(tmp_path, rel)
    assert _is_analog_ic(tmp_path) is True, (
        f"{rel} present but IC classified pure-digital — Pillar 5 would "
        "silently PASS without verifying any analog block"
    )


def test_legacy_root_block_list_still_detected(tmp_path):
    """The pre-existing project-root location must keep working."""
    _mk(tmp_path, "analog/analog_block_list.json")
    assert _is_analog_ic(tmp_path) is True


def test_block_gds_still_detected(tmp_path):
    """The pre-existing A5-GDS signal must keep working."""
    _mk(tmp_path, "phase3/analog/blk/blk.gds", "")
    assert _is_analog_ic(tmp_path) is True


# ── the positive case: a genuinely pure-digital IC must stay N/A ─────────────

def test_pure_digital_ic_stays_not_analog(tmp_path):
    """No analog artefact anywhere -> still pure-digital. Widening detection
    must not start claiming every digital IC has analog blocks."""
    _mk(tmp_path, "phase2/stage1/rtl/top.v", "module top(); endmodule\n")
    _mk(tmp_path, "phase3/stage3/pnr/top.def", "VERSION 5.8 ;\n")
    _mk(tmp_path, "phase3/stage3/pnr/top.gds", "")
    _mk(tmp_path, "reports/code_coverage.json", json.dumps({"line_pct": 95}))
    assert _is_analog_ic(tmp_path) is False


def test_empty_project_is_not_analog(tmp_path):
    assert _is_analog_ic(tmp_path) is False


def test_digital_gds_outside_analog_dir_is_not_analog(tmp_path):
    """A GDS that is not under phase3/analog/ is a digital die, not a block."""
    _mk(tmp_path, "phase3/analog_notes.txt", "x")
    _mk(tmp_path, "phase3/stage3/pnr/die.gds", "")
    assert _is_analog_ic(tmp_path) is False


# ── Pillar 5 must not pass on mere PRESENCE of analog blocks ─────────────────
#
# Second leak from the same clean-room run: `g_analog` passed whenever the
# block list existed ("presence; deep check via analog skills"), so the
# load-bearing analog pillar was structurally unable to fail — it reported PASS
# on a run whose A-track verdict was FAIL and whose corner sweep never resolved
# its .meas statements. Pillar 5 now requires a CONVERGED A-track.

import subprocess  # noqa: E402


def _run_report(project: Path) -> str:
    prog = Path(__file__).resolve().parents[1] / "benchmark_verify_report.py"
    r = subprocess.run([sys.executable, str(prog), str(project)],
                       capture_output=True, text=True)
    return r.stdout + r.stderr


def _analog_project(tmp_path: Path, verdict: str, partial: bool) -> Path:
    _mk(tmp_path, "phase3/analog/analog_block_list.json",
        json.dumps({"blocks": [{"name": "blk_a"}, {"name": "blk_b"}]}))
    _mk(tmp_path, "reports/phase3/analog_one_shot.json",
        json.dumps({"verdict": verdict}))
    for blk in ("blk_a", "blk_b"):
        _mk(tmp_path, f"phase3/analog/{blk}/corner_results.json",
            json.dumps({"partial_measurement": partial and blk == "blk_b",
                        # `partial_measurement` says whether every corner
                        # resolved; it says nothing about WHICH CIRCUIT
                        # resolved them. A fixture silent on the second was
                        # asserting that a sweep which will not name its
                        # subject can still show the analog loop closed.
                        "design_content": "structure_and_geometry"}))
    return tmp_path


def test_pillar5_does_not_pass_on_failing_a_track(tmp_path):
    """A-track verdict FAIL must not yield analog=PASS."""
    _analog_project(tmp_path, "FAIL", partial=False)
    out = _run_report(tmp_path)
    assert "analog=FAIL" in out, f"Pillar 5 passed a FAILing A-track: {out}"


def test_pillar5_does_not_pass_on_partial_corner_sweep(tmp_path):
    """A partial corner sweep (.meas unresolved) is not a verified block."""
    _analog_project(tmp_path, "PASS", partial=True)
    out = _run_report(tmp_path)
    assert "analog=PENDING" in out, f"Pillar 5 passed a PARTIAL sweep: {out}"


def test_pillar5_missing_a_track_verdict_is_pending(tmp_path):
    """No A-track report at all -> PENDING, never a silent pass."""
    _mk(tmp_path, "phase3/analog/analog_block_list.json",
        json.dumps({"blocks": [{"name": "blk_a"}]}))
    out = _run_report(tmp_path)
    assert "analog=PENDING" in out, f"Pillar 5 passed with no A-track: {out}"


def test_pillar5_passes_on_converged_a_track(tmp_path):
    """The positive case must still pass — a converged A-track with fully
    measured sweeps, over netlists the artefacts say are design-bound."""
    _analog_project(tmp_path, "PASS", partial=False)
    out = _run_report(tmp_path)
    assert "analog=CONVERGED" in out, f"converged A-track did not pass: {out}"


def test_pillar5_does_not_pass_a_loop_that_closed_on_a_library_default(
        tmp_path):
    """The same converged A-track, over artefacts that RECORD that the circuit
    they measured came from a topology library with no bound input reaching any
    device parameter. Real corners on a library nominal are a measurement of
    that topology; the analog loop has not closed on this design.

    Deliberately its own state and not FAIL: a run whose A-track failed is the
    row above, and an honest ceiling must never be shown scoring the same as a
    run that invented content to fill the gap."""
    _analog_project(tmp_path, "PASS", partial=False)
    for blk in ("blk_a", "blk_b"):
        p = tmp_path / "phase3" / "analog" / blk / "corner_results.json"
        d = json.loads(p.read_text())
        d["design_content"] = "structure_only"
        p.write_text(json.dumps(d))
    out = _run_report(tmp_path)
    assert "analog=STRUCTURE_ONLY" in out, out
    assert "analog=CONVERGED" not in out, out


def test_pillar5_does_not_pass_a_sweep_that_will_not_name_its_subject(
        tmp_path):
    """Silence must not be the cheap answer. Same converged A-track, the one
    field removed — which is the shape of every artefact written before the
    field existed, and of every stale one. Pre-fix this tree read
    'CONVERGED — all corner sweeps fully measured' and PASSED the pillar."""
    _analog_project(tmp_path, "PASS", partial=False)
    for blk in ("blk_a", "blk_b"):
        p = tmp_path / "phase3" / "analog" / blk / "corner_results.json"
        d = json.loads(p.read_text())
        d.pop("design_content")
        p.write_text(json.dumps(d))
    out = _run_report(tmp_path)
    assert "analog=UNDISCLOSED" in out, out
    assert "analog=CONVERGED" not in out, out
