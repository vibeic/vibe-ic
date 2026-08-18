"""test_analog_sigma_delta_gain_floor_check.py — R14 integrator-gain floor (v1.3.54).

Step-2.7 adversarial focus: PROVE the 20*log10(OSR) floor + margin can NOT
false-pass a gain-starved design.
  * a 42.8 dB OTA against the OSR=256 floor (48.16 dB) -> hard FAIL, per corner
    measured-vs-floor printed (the exact hot-corner residual).
  * omitting the gain field must SKIP, never PASS (no silent green on missing
    data).
  * a bigger OSR raises the floor, so the SAME gain that passed at low OSR
    FAILs at high OSR (floor tracks OSR, not a fixed number).
  * the margin band produces a non-failing WARN (marginal) — corpus-clean.

Block names synthetic — no chip/SKU literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "analog_sigma_delta_gain_floor_check.py")


def _mk(project: Path, block: str, spec: dict, corners: dict | None):
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps(spec))
    if corners is not None:
        (d / "corner_results.json").write_text(json.dumps(corners))


def _run(project: Path, *args: str):
    r = subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "r.json"), *args],
        capture_output=True, text=True)
    rpt = json.loads((project / "r.json").read_text())
    return r, rpt


def _ds_spec(osr=256):
    return {"block": "mod0", "type": "delta_sigma",
            "specs": [
                {"name": "converter_type", "value": "incremental_delta_sigma"},
                {"name": "osr", "target": osr},
                {"name": "enob", "target": 14},
            ]}


def test_gain_starved_design_hard_fails(tmp_path: Path):
    """42.8 dB < 48.16 dB floor (OSR=256) -> FAIL — cannot false-pass."""
    corners = {"corners": [
        {"name": "TT_27c", "ota_dc_gain_db": 55.0},
        {"name": "SS_125c", "ota_dc_gain_db": 42.8},   # gain-starved hot corner
    ]}
    _mk(tmp_path, "mod0", _ds_spec(256), corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert rpt["verdict"] == "FAIL"
    blk = next(b for b in rpt["blocks"] if b.get("status") == "FAIL")
    fc = blk["failing_corners"][0]
    assert fc["corner"] == "SS_125c"
    assert abs(fc["gain_floor_db"] - 48.165) < 0.01
    assert fc["deficit_db"] > 5.0


def test_pass_with_healthy_margin(tmp_path: Path):
    corners = {"corners": [
        {"name": "TT_27c", "ota_dc_gain_db": 60.0},
        {"name": "SS_125c", "ota_dc_gain_db": 55.0},
    ]}
    _mk(tmp_path, "mod0", _ds_spec(256), corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert rpt["verdict"] == "PASS"


def test_marginal_is_warn_not_fail(tmp_path: Path):
    """Above the floor but inside the 3 dB guard band -> WARN, exit 0."""
    corners = {"corners": [
        {"name": "FF_125c", "ota_dc_gain_db": 48.34},  # 0.18 dB over floor
    ]}
    _mk(tmp_path, "mod0", _ds_spec(256), corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0
    assert rpt["verdict"] == "WARN"


def test_floor_tracks_osr(tmp_path: Path):
    """The SAME 60 dB gain that passes at OSR=64 (floor 36 dB) FAILs at a huge
    OSR whose floor exceeds it — the floor is 20*log10(OSR), not a constant."""
    corners = {"corners": [{"name": "SS_125c", "ota_dc_gain_db": 60.0}]}
    _mk(tmp_path, "modA", _ds_spec(64), corners)
    r, rpt = _run(tmp_path)
    assert rpt["verdict"] == "PASS"
    # OSR = 1_000_000 -> floor = 120 dB >> 60 dB -> FAIL
    _mk(tmp_path, "modB", _ds_spec(1_000_000), corners)
    r, rpt = _run(tmp_path)
    assert rpt["verdict"] == "FAIL"


def test_skip_on_missing_gain_field(tmp_path: Path):
    """No gain field on any corner -> SKIP, never a silent PASS."""
    corners = {"corners": [
        {"name": "TT_27c", "ota_gbw_hz": 3e7},
        {"name": "SS_125c", "ota_gbw_hz": 2e7},
    ]}
    _mk(tmp_path, "mod0", _ds_spec(256), corners)
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


def test_nan_gain_is_not_a_silent_pass(tmp_path: Path):
    """Step-2.7 finding — a non-converged corner reporting NaN gain (reachable
    via json allow_nan=True from analog_real_corner_sweep) must NOT count as a
    clean measured pass. A lone NaN corner => no valid measurement => SKIP,
    never [PASS]."""
    d = tmp_path / "phase3" / "analog" / "mod0"
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(_ds_spec(256)))
    # bareword NaN, exactly what json.dumps(allow_nan=True) emits
    (d / "corner_results.json").write_text(
        '{"corners": [{"name": "SS_125c", "ota_dc_gain_db": NaN}]}')
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


def test_nan_worst_corner_does_not_mask_real_fail(tmp_path: Path):
    """A NaN corner mixed with a real below-floor corner still FAILs on the
    real corner — the NaN is excluded, not treated as a clean pass."""
    d = tmp_path / "phase3" / "analog" / "mod0"
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(_ds_spec(256)))
    (d / "corner_results.json").write_text(
        '{"corners": [{"name": "TT_27c", "ota_dc_gain_db": NaN},'
        ' {"name": "SS_125c", "ota_dc_gain_db": 42.8}]}')
    r, rpt = _run(tmp_path)
    assert r.returncode == 1
    assert rpt["verdict"] == "FAIL"


def test_skip_when_not_sigma_delta(tmp_path: Path):
    """A SAR ADC (no OSR / not oversampled) -> the floor does not apply -> SKIP."""
    spec = {"block": "sar0", "type": "sar_adc",
            "specs": [{"name": "enob", "target": 12}]}
    corners = {"corners": [{"name": "TT_27c", "ota_dc_gain_db": 20.0}]}
    _mk(tmp_path, "sar0", spec, corners)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0
    assert rpt["verdict"] == "SKIP"
