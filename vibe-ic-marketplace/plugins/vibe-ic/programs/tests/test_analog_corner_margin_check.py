#!/usr/bin/env python3
"""Unit tests for analog_corner_margin_check.py

Covers the SKILL.md A4 thresholds (skills/analog-output-verify/SKILL.md):
  * ≥27 corners (3 process × 3 temp × 3 voltage)
  * every corner margin ≥10%

Plus the no-false-alert / graceful-degrade contract.
"""
import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import analog_corner_margin_check as mod  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ───────────────────────── fixtures ─────────────────────────

#: What a corner artefact says its circuit contains. `structure_and_geometry`
#: means at least one bound input reached the content — a design-bound sweep.
DESIGN_BOUND = "structure_and_geometry"


def _write_corners(tmp_path, corners, *, block="ldo",
                   fname="A4_corners.json", extra=None,
                   design_content=DESIGN_BOUND):
    """Build a project tree with one analog block carrying an A4
    corner artefact, and return the project root.

    `design_content` is written by DEFAULT, and that default is the point of
    this parameter rather than a convenience. This gate stopped certifying an
    artefact that declines to say what circuit produced its corners, so a
    fixture that omitted the field would be asserting that omission still
    certifies the strictest PVT claim in the repo — which is the inverted
    incentive the rule exists to remove. Every PASS fixture below now STATES
    the content it certifies; the tests about corner counts and margin floors
    are about counts and floors, and they need an artefact that clears every
    other rule to be about only that.

    Pass `design_content=None` to build the pre-disclosure shape deliberately.
    """
    proj = tmp_path / "project"
    bdir = proj / "phase3" / "analog" / block
    bdir.mkdir(parents=True, exist_ok=True)
    payload = {"block": block, "total_corners": len(corners),
               "corners": corners}
    if design_content is not None:
        payload["design_content"] = design_content
    if extra:
        payload.update(extra)
    (bdir / fname).write_text(json.dumps(payload))
    return proj


def _full_pvt(margin_pct=12.0):
    """A real 27-corner PVT cube (3 process × 3 temp × 3 voltage)."""
    out = []
    for proc in ("ss", "tt", "ff"):
        for temp in ("m40c", "27c", "125c"):
            for volt in ("lo", "nom", "hi"):
                out.append({
                    "name": f"{proc}_{temp}_{volt}",
                    "process": proc, "temp": temp, "voltage": volt,
                    "margin_pct": margin_pct,
                })
    return out


def run_cli(proj):
    res = _pr.run(
        [sys.executable, str(PROG_DIR / "analog_corner_margin_check.py"),
         str(proj)],
        capture_output=True, text=True)
    return res


# ───────────────────── good (PASS) fixtures ─────────────────────

class TestFullPvtPass:
    def test_27_corner_pass(self, tmp_path):
        proj = _write_corners(tmp_path, _full_pvt(12.0))
        res = run_cli(proj)
        assert res.returncode == 0, res.stdout + res.stderr
        assert "PASS" in res.stdout

    def test_exactly_27_corners_counted(self, tmp_path):
        proj = _write_corners(tmp_path, _full_pvt(11.0))
        result = mod.run_audit(proj)
        assert result.passed is True
        assert result.summary["blocks_checked"] == 1
        assert result.summary["details"][0]["total_corners"] == 27

    def test_margin_exactly_at_floor_passes(self, tmp_path):
        # 10% is the floor — exactly 10 must PASS (>= not >).
        proj = _write_corners(tmp_path, _full_pvt(10.0))
        result = mod.run_audit(proj)
        assert result.passed is True

    def test_accepts_runner_filename(self, tmp_path):
        # SKILL says A4_corners.json; runner emits corner_results.json.
        proj = _write_corners(tmp_path, _full_pvt(15.0),
                              fname="corner_results.json")
        res = run_cli(proj)
        assert res.returncode == 0

    def test_margin_fraction_form(self, tmp_path):
        # `margin` given as a fraction (0.12) → 12%.
        corners = []
        for c in _full_pvt():
            del c["margin_pct"]
            c["margin"] = 0.12
            corners.append(c)
        proj = _write_corners(tmp_path, corners)
        result = mod.run_audit(proj)
        assert result.passed is True

    def test_margin_derived_from_value_target_tol(self, tmp_path):
        # value on-target, tolerance band 5% → full margin → PASS.
        corners = [{"name": f"c{i}", "value": 1.8, "target": 1.8,
                    "tolerance": 0.05} for i in range(27)]
        proj = _write_corners(tmp_path, corners)
        result = mod.run_audit(proj)
        assert result.passed is True


# ───────────────────── bad (FAIL) fixtures ─────────────────────

class TestInsufficientCorners:
    def test_9_corners_fail(self, tmp_path):
        # The 9-corner (3 proc × 3 temp) matrix that the *old*
        # analog_corner_sweep_check accepts must FAIL this stricter gate.
        corners = [{"name": f"c{i}", "margin_pct": 12.0} for i in range(9)]
        proj = _write_corners(tmp_path, corners)
        res = run_cli(proj)
        assert res.returncode == 1
        assert "INSUFFICIENT_PVT_CORNERS" in res.stdout

    def test_26_corners_fail(self, tmp_path):
        # one short of the cube.
        corners = _full_pvt()[:26]
        proj = _write_corners(tmp_path, corners)
        result = mod.run_audit(proj)
        assert result.passed is False
        rules = {f.rule for f in result.findings}
        assert "INSUFFICIENT_PVT_CORNERS" in rules


class TestSubMarginFail:
    def test_one_corner_below_floor_fails(self, tmp_path):
        corners = _full_pvt(12.0)
        corners[13]["margin_pct"] = 5.0  # one bad corner
        corners[13]["name"] = "weak_corner"
        proj = _write_corners(tmp_path, corners)
        res = run_cli(proj)
        assert res.returncode == 1
        assert "MARGIN_BELOW_FLOOR" in res.stdout
        assert "weak_corner" in res.stdout

    def test_derived_margin_outside_band_fails(self, tmp_path):
        # value 10% off-target but tolerance only 5% → margin negative.
        corners = [{"name": f"c{i}", "value": 1.98, "target": 1.8,
                    "tolerance": 0.05} for i in range(27)]
        proj = _write_corners(tmp_path, corners)
        result = mod.run_audit(proj)
        assert result.passed is False
        assert any(f.rule == "MARGIN_BELOW_FLOOR" for f in result.findings)


# ───────────────── no-false-alert / graceful skip ─────────────────

class TestGracefulDegrade:
    def test_no_analog_dir_skips(self, tmp_path):
        proj = tmp_path / "empty_project"
        proj.mkdir()
        res = run_cli(proj)
        # #521 — a margin gate that read no margin is VACUOUS (rc 2).
        assert res.returncode == 2
        result = mod.run_audit(proj)
        assert result.summary.get("skipped") is True
        assert result.summary.get("reason") == "no_analog_dir"

    def test_no_corner_file_skips(self, tmp_path):
        proj = tmp_path / "project"
        (proj / "phase3" / "analog" / "ldo").mkdir(parents=True)
        result = mod.run_audit(proj)
        assert result.passed is True
        assert result.summary.get("reason") == "no_corner_data"

    def test_deterministic_stub_is_skipped_not_failed(self, tmp_path):
        # honest stub (1 corner, simulator_run False) must NOT FAIL.
        proj = _write_corners(
            tmp_path,
            [{"name": "tt_27c", "simulator_run": False, "margin": None}],
            extra={"extraction_strategy": "deterministic_stub"})
        res = run_cli(proj)
        assert res.returncode == 0
        result = mod.run_audit(proj)
        assert result.passed is True
        assert result.summary["details"][0].get("stub") is True

    def test_informational_corners_no_margin_no_violation(self, tmp_path):
        # 27 corners that carry no numeric margin (e.g. POR trip-point)
        # → MISSING reported, but NOT flagged as a violation.
        corners = [{"name": f"c{i}", "simulator_run": True}
                   for i in range(27)]
        proj = _write_corners(tmp_path, corners)
        result = mod.run_audit(proj)
        assert result.passed is True
        rules = {f.rule for f in result.findings}
        assert "MARGIN_BELOW_FLOOR" not in rules
        assert "MARGIN_DATA_MISSING" in rules

    def test_a_clean_cube_that_names_no_circuit_does_not_certify(
            self, tmp_path):
        """The rule this file's default now states, asserted here rather than
        left implicit in a default. 27 corners and every margin above the
        floor is true of a library nominal exactly as of a design; an artefact
        that will not say which must not certify the step it is the evidence
        for. Naming a library default certifies in its own tier — only
        silence costs."""
        proj = _write_corners(tmp_path, _full_pvt(12.0), design_content=None)
        res = run_cli(proj)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "MARGIN_SUBJECT_UNDECLARED" in res.stdout

    def test_unparsable_json_reports_error_not_crash(self, tmp_path):
        proj = tmp_path / "project"
        bdir = proj / "phase3" / "analog" / "ldo"
        bdir.mkdir(parents=True)
        (bdir / "A4_corners.json").write_text("{not valid json")
        result = mod.run_audit(proj)
        assert result.passed is False
        assert any(f.rule == "CORNER_PARSE_ERROR" for f in result.findings)

    def test_not_a_directory_exits_2(self, tmp_path):
        bogus = tmp_path / "nope"
        res = _pr.run(
            [sys.executable,
             str(PROG_DIR / "analog_corner_margin_check.py"), str(bogus)],
            capture_output=True, text=True)
        assert res.returncode == 2


# ───────────────────── JSON verdict shape ─────────────────────

class TestJsonOutput:
    def test_json_report_written(self, tmp_path):
        proj = _write_corners(tmp_path, _full_pvt(12.0))
        out = tmp_path / "report.json"
        res = _pr.run(
            [sys.executable,
             str(PROG_DIR / "analog_corner_margin_check.py"),
             str(proj), "--json", str(out)],
            capture_output=True, text=True)
        assert res.returncode == 0
        report = json.loads(out.read_text())
        assert report["program"] == "analog_corner_margin_check"
        assert report["passed"] is True
        assert report["summary"]["min_corners_required"] == 27
        assert report["summary"]["min_margin_pct"] == 10.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
