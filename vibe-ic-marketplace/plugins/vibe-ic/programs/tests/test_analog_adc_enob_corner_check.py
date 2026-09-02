"""test_analog_adc_enob_corner_check.py — R12 system-ENOB per-corner (v1.3.54).

Proves the gate (a) PASSes when every corner clears the ENOB target, (b) FAILs
when a NON-typ corner droops below it (the "measured at typ only" escape the
gate closes — ENOB computed per-corner, not just typ), (c) honest-SKIPs when a
converter has an ENOB target but no per-corner SNDR/ENOB was measured (the
real field-class corner file shape: OTA gains, no per-corner SNDR).

Block names are synthetic — no chip/SKU literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_adc_enob_corner_check.py"


def _mk(project: Path, block: str, spec: dict, corners: dict | None):
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps(spec))
    if corners is not None:
        (d / "corner_results.json").write_text(json.dumps(corners))


def _run(project: Path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "r.json")],
        capture_output=True, text=True)
    rpt = json.loads((project / "r.json").read_text())
    return r, rpt


def _adc_spec(enob=14):
    return {"block": "adc0", "type": "adc",
            "specs": [{"name": "enob", "target": enob, "min": 10,
                       "units": "bit"}]}


def test_pass_all_corners_meet_enob(tmp_path: Path):
    # SNDR 87.9 dB -> ENOB ~ 14.31 at every corner
    corners = {"corners": [
        {"name": "TT_27c", "sndr_db": 87.9},
        {"name": "SS_125c", "sndr_db": 87.5},
        {"name": "FF_-40c", "sndr_db": 88.4},
    ]}
    _mk(tmp_path, "adc0", _adc_spec(14), corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert rpt["verdict"] == "PASS"


def test_fail_non_typ_corner_droops(tmp_path: Path):
    """Typ meets ENOB=14 but the hot corner droops to ~13.6 -> FAIL, and the
    failing corner (NOT typ) is named."""
    corners = {"corners": [
        {"name": "TT_27c", "sndr_db": 87.9},       # ENOB ~14.31 OK
        {"name": "SS_125c", "enob": 13.6},         # BELOW target
    ]}
    _mk(tmp_path, "adc0", _adc_spec(14), corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert rpt["verdict"] == "FAIL"
    blk = next(b for b in rpt["blocks"] if b.get("status") == "FAIL")
    failing = {fc["corner"] for fc in blk["failing_corners"]}
    assert "SS_125c" in failing
    assert "TT_27c" not in failing


def test_skip_when_no_per_corner_sndr(tmp_path: Path):
    """field-class shape: ADC block with ENOB target but the corner file
    carries only OTA gains (no per-corner SNDR/ENOB) -> honest SKIP."""
    corners = {"corners": [
        {"name": "TT_27c", "ota_dc_gain_db": 55.1},
        {"name": "SS_125c", "ota_dc_gain_db": 51.5},
    ]}
    _mk(tmp_path, "adc0", _adc_spec(14), corners)
    r, rpt = _run(tmp_path)
    # RE-ANCHORED (#693 family). These four asserted `returncode == 0` and
    # `verdict == "SKIP"` for a block that DECLARES this axis and carries no
    # usable data — and this test's own name and docstring already call that
    # "not a silent pass" / "must be UNMEASURED". The assertion contradicted
    # the property the test is named for: at the exit-code level rc 0 IS a
    # pass, so a wired flow counted it among the gates that passed.
    #
    # A block with NO target at all is still SKIP / rc 0 — genuinely not
    # applicable, and that case is unchanged.
    assert r.returncode == 2
    assert rpt["verdict"] == "UNMEASURED"


def test_nan_enob_is_not_a_silent_pass(tmp_path: Path):
    """Step-2.7 finding — a NaN ENOB/SNDR corner (non-converged sim, bareword
    NaN from json allow_nan=True) must be UNMEASURED, never a clean pass. A
    lone NaN corner => SKIP, not [PASS]."""
    d = tmp_path / "phase3" / "analog" / "adc0"
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(_adc_spec(14)))
    (d / "corner_results.json").write_text(
        '{"corners": [{"name": "SS_125c", "enob": NaN}]}')
    r, rpt = _run(tmp_path)
    # RE-ANCHORED (#693 family). These four asserted `returncode == 0` and
    # `verdict == "SKIP"` for a block that DECLARES this axis and carries no
    # usable data — and this test's own name and docstring already call that
    # "not a silent pass" / "must be UNMEASURED". The assertion contradicted
    # the property the test is named for: at the exit-code level rc 0 IS a
    # pass, so a wired flow counted it among the gates that passed.
    #
    # A block with NO target at all is still SKIP / rc 0 — genuinely not
    # applicable, and that case is unchanged.
    assert r.returncode == 2
    assert rpt["verdict"] == "UNMEASURED", rpt


def test_nan_does_not_mask_real_fail(tmp_path: Path):
    d = tmp_path / "phase3" / "analog" / "adc0"
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(_adc_spec(14)))
    (d / "corner_results.json").write_text(
        '{"corners": [{"name": "TT_27c", "sndr_db": NaN},'
        ' {"name": "SS_125c", "enob": 13.6}]}')
    r, rpt = _run(tmp_path)
    assert r.returncode == 1
    assert rpt["verdict"] == "FAIL"


def test_skip_when_not_a_graded_converter(tmp_path: Path):
    """A block with no ENOB/SNDR target is not graded -> SKIP."""
    spec = {"block": "ldo0", "type": "ldo",
            "specs": [{"name": "Vout", "target": 1.2}]}
    corners = {"corners": [{"name": "TT_27c", "sndr_db": 60.0}]}
    _mk(tmp_path, "ldo0", spec, corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0
    assert rpt["verdict"] == "SKIP"


def test_unmeasured_publishes_a_typed_reason_class(tmp_path: Path):
    """UNMEASURED must say WHY, in the taxonomy's own vocabulary.

    An UNMEASURED verdict exits 2. A consumer that reads only the exit code
    and the prose has no typed reason to read, and
    `_flow_reason_taxonomy.infer_nonverdict_reason` is deliberately
    fail-closed: an unclassified non-verdict is classified EXECUTION_ERROR,
    which tells a reader the gate CRASHED. This gate does not crash here — it
    runs, examines the block, and finds no corner carrying the field the
    declared axis is graded on. That is a zero measured denominator.

    Measured on a real run (u_hawaii_adc, v1.15.93): Step A4 carried
    `analog_adc_enob_corner_check rc=2 verdict=INCOMPLETE
    reason_class=EXECUTION_ERROR` for exactly this input.
    """
    spec = {"block": "adc0", "type": "adc",
            "specs": [{"name": "enob", "target": 14}]}
    # A corner that ran, and carries no sndr/enob field at all.
    corners = {"corners": [{"name": "TT_27c", "vout_v": 0.62}]}
    _mk(tmp_path, "adc0", spec, corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 2
    assert rpt["verdict"] == "UNMEASURED", rpt
    assert rpt.get("reason_class") == "ZERO_DENOMINATOR", rpt


def test_reason_class_is_not_skip_eligible(tmp_path: Path):
    """The published class must not be able to launder UNMEASURED into a skip.

    ZERO_DENOMINATOR is in `_flow_reason_taxonomy.INCOMPLETE`. If a later edit
    moved this gate to a SKIP_ELIGIBLE class, the step would silently leave the
    follow-up population, so the class is pinned against the taxonomy itself
    rather than against a literal.
    """
    import _flow_reason_taxonomy as tax
    spec = {"block": "adc0", "type": "adc",
            "specs": [{"name": "enob", "target": 14}]}
    corners = {"corners": [{"name": "TT_27c", "vout_v": 0.62}]}
    _mk(tmp_path, "adc0", spec, corners)
    _r, rpt = _run(tmp_path)
    cls = rpt.get("reason_class")
    assert cls not in tax.SKIP_ELIGIBLE, cls
    assert cls in tax.INCOMPLETE, cls
