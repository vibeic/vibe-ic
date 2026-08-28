"""#693 family — a declared analog axis with no data is not a SKIP.

Found by RUNNING two never-wired gates on the published corpus, which is the
whole hypothesis behind #693: never wired means never exercised outside a
fixture its own author wrote.

Both printed `[SKIP]` and exited 0 on every project, and TWO different
situations shared that status:

    no ENOB/OSR target in the spec        the formula genuinely does not apply
    target DECLARED, no corner data      the block IS graded on this axis and
                                         nobody measured it

The second is an absence, and it was reported as a pass. On the published ADC it
is a real finding, not a hypothetical.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
ENOB = PROGRAMS / "analog_adc_enob_corner_check.py"
SIGMA = PROGRAMS / "analog_sigma_delta_gain_floor_check.py"


def _project(tmp: Path, spec: dict) -> Path:
    d = tmp / "phase3" / "analog" / "blk"
    d.mkdir(parents=True)
    (d.parent / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "blk"}]}))
    (d / "spec.json").write_text(json.dumps(spec))
    return tmp


def _rc(gate: Path, project: Path) -> int:
    return _pr.run([sys.executable, str(gate), str(project)],
                          capture_output=True, text=True).returncode


def test_a_declared_enob_target_with_no_corner_data_is_rc2(tmp_path):
    p = _project(tmp_path, {"specs": [{"name": "enob", "min": 11.5,
                                       "unit": "bits"}]})
    assert _rc(ENOB, p) == 2, (
        "a block that declares an ENOB target and has no corner data was "
        "measured by nothing, and must not exit 0")


def test_a_block_with_no_enob_target_is_still_rc0(tmp_path):
    """NOT-APPLICABLE must stay a pass. The formula genuinely does not apply to
    a block that is not resolution-graded, and turning that into a failure
    would make the gate un-wireable — which is how a gate ends up switched
    off."""
    p = _project(tmp_path, {"specs": [{"name": "dropout", "max": 200,
                                       "unit": "mV"}]})
    assert _rc(ENOB, p) == 0


def test_a_declared_osr_with_no_corner_data_is_rc2(tmp_path):
    # `type` is the key the detector reads (`kind` is not one of them) — the
    # fixture has to satisfy the gate's real precondition, not a plausible one.
    p = _project(tmp_path, {"type": "sigma-delta ADC",
                            "specs": [{"name": "osr", "value": 64}]})
    assert _rc(SIGMA, p) == 2


def test_a_block_that_is_not_oversampled_is_still_rc0(tmp_path):
    p = _project(tmp_path, {"specs": [{"name": "gain", "min": 20}]})
    assert _rc(SIGMA, p) == 0
