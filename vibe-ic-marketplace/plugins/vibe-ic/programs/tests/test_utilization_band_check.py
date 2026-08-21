"""Tests for utilization_band_check.py — advisory utilization band classifier.

Covers:
  * PASS — utilization inside the advisory 50-75 band.
  * WARN (not FAIL) — outside the band (the corpus reality: most legit
    fixed-die designs are < 50%); rc still 0.
  * real FAIL — derivable utilization <= 0 or > 100 (impossible/illegal).
  * missing-data honesty — NO_DATA never vacuous-passes; --strict FAILs it.
  * real-corpus CLEAN sweep — NO design FAILs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import utilization_band_check as u  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


_DENSITY_TMPL = (
    "# Metal-fill / density report — OpenROAD filler_placement\n"
    "# filler instances placed: 0\n"
    "# std-cell row utilization (post-fill): {pct}%\n")


def _make_density(tmp_path: Path, pct, rel="reports/density.rpt") -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_DENSITY_TMPL.format(pct=pct))
    return tmp_path


# --------------------------------------------------------------------------
# PASS — in-band.
# --------------------------------------------------------------------------
def test_pass_in_band(tmp_path):
    proj = _make_density(tmp_path, 62.0)
    rc = u.main([str(proj), "--json", str(tmp_path / "r.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["utilization_pct"] == 62.0
    assert rep["summary"]["pass"] is True


# --------------------------------------------------------------------------
# WARN — below band is advisory only (rc=0), the dominant corpus reality.
# --------------------------------------------------------------------------
def test_warn_under_band_is_not_fail(tmp_path):
    proj = _make_density(tmp_path, 13.0)
    rc = u.main([str(proj), "--json", str(tmp_path / "r.json")])
    assert rc == 0  # advisory, NOT a failure
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "WARN"
    assert rep["summary"]["pass"] is True
    assert any(f["category"] == "UTIL_UNDER_BAND" for f in rep["findings"])


def test_warn_over_band_is_not_fail(tmp_path):
    proj = _make_density(tmp_path, 85.0)
    rc = u.main([str(proj)])
    assert rc == 0
    verdict, findings = u.classify(85.0, "x")
    assert verdict == "WARN"
    assert any(f.category == "UTIL_OVER_BAND" for f in findings)


# --------------------------------------------------------------------------
# real FAIL — impossible / illegal utilization.
# --------------------------------------------------------------------------
def test_fail_over_100(tmp_path):
    proj = _make_density(tmp_path, 142.0)
    rc = u.main([str(proj), "--json", str(tmp_path / "r.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["summary"]["pass"] is False
    assert any(f["category"] == "UTIL_OVER_100" for f in rep["findings"])


def test_fail_negative_via_direct_arg():
    rc = u.main(["--util", "-5"])
    assert rc == 1
    verdict, findings = u.classify(-5.0, "--util")
    assert verdict == "FAIL"
    assert any(f.category == "UTIL_NONPOSITIVE" for f in findings)


def test_zero_is_precision_floor_not_corruption(tmp_path):
    # v0.2.69 — report_design_area prints integer-rounded utilization:
    # a parsed 0 means "< 0.5%, below report precision", NOT a corrupt
    # report. WARN UTIL_ZERO_UNRESOLVED, rc=0. Negative still FAILs.
    proj = _make_density(tmp_path, 0.0)
    rc = u.main([str(proj), "--json", str(tmp_path / "r.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "WARN"
    assert any(f["category"] == "UTIL_ZERO_UNRESOLVED"
               for f in rep["findings"])
    # it must NOT claim a band was verified
    assert all(f["category"] != "UTIL_IN_BAND" for f in rep["findings"])


# --------------------------------------------------------------------------
# missing-data honesty.
# --------------------------------------------------------------------------
def test_no_data_is_not_vacuous_pass(tmp_path):
    # Empty project dir — no density artefact.
    rc = u.main([str(tmp_path), "--json", str(tmp_path / "r.json")])
    assert rc == 0  # without --strict, advisory NO_DATA
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "NO_DATA"
    assert rep["summary"]["utilization_pct"] is None
    # It must NOT claim a band was verified.
    assert all(f["category"] != "UTIL_IN_BAND" for f in rep["findings"])
    assert any(f["category"] == "NO_DATA" for f in rep["findings"])


def test_no_data_strict_fails(tmp_path):
    rc = u.main([str(tmp_path), "--strict"])
    assert rc == 1


def test_missing_project_dir_rc2(tmp_path):
    rc = u.main([str(tmp_path / "does_not_exist")])
    assert rc == 2


# --------------------------------------------------------------------------
# Fraction coercion + JSON source.
# --------------------------------------------------------------------------
def test_fraction_coerced_to_pct(tmp_path):
    p = tmp_path / "reports" / "phase3" / "density.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"core_utilization": 0.6}))
    rc = u.main([str(tmp_path), "--json", str(tmp_path / "r.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["utilization_pct"] == 60.0
    assert rep["verdict"] == "PASS"


# --------------------------------------------------------------------------
# Real-corpus CLEAN sweep — the HARD rule: no legitimate design may FAIL.
# --------------------------------------------------------------------------
_CORPUS = corpus_path()


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="real corpus not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_corpus_no_false_fail():
    projects = sorted({
        rpt.parent.parent
        for rpt in _CORPUS.glob("*/reports/density.rpt")
    })
    if not projects:
        pytest.skip("no corpus density.rpt found")
    fails = []
    for proj in projects:
        verdict, _ = u.classify(*u.read_utilization(proj))
        assert verdict != "NO_DATA", f"{proj} had a density.rpt but no value parsed"
        if verdict == "FAIL":
            fails.append(str(proj))
    assert fails == [], f"utilization band FALSE-FIRED on legit designs: {fails}"


def test_unresolved_disclosure_named_verdict(tmp_path):
    # honest unresolved disclosure (quantized-floor class, the shape a
    # real post-fill report emits) → named UNRESOLVED_DISCLOSED, not
    # NO_DATA; default rc stays 0, --strict flags it.
    rpt = tmp_path / "reports"; rpt.mkdir()
    (rpt / "density.rpt").write_text(
        "# Metal-fill / density report\n"
        "# core-area utilization (report_design_area, post-fill): unresolved\n"
        "# (report_design_area printed 0% — integer-rounded floor)\n")
    pct, src = u.read_utilization(tmp_path)
    assert pct is None and src is not None
    verdict, findings = u.classify(pct, src)
    assert verdict == "UNRESOLVED_DISCLOSED"
    assert any(f.category == "UNRESOLVED_DISCLOSED" for f in findings)


def test_truly_absent_artefact_still_no_data(tmp_path):
    pct, src = u.read_utilization(tmp_path)
    assert pct is None and src is None
    verdict, _ = u.classify(pct, src)
    assert verdict == "NO_DATA"


def test_keyvalue_pct_form_from_own_odb_fill_report(tmp_path):
    # v0.3.24 emitter↔checker drift guard: the runner's own #445 rows-
    # already-full odb fill report writes the KEY-VALUE form
    # `row_utilization_pct 99.75` (unit declared by the `_pct` suffix, no
    # `%` sign). The checker must parse its own emitter's format — a real
    # corpus artefact in this shape classified NO_DATA before the fix.
    rpt = tmp_path / "reports"; rpt.mkdir()
    (rpt / "density.rpt").write_text(
        "# Cell/metal fill density report (openroad odb)\n"
        "filler_instances 2594\n"
        "row_utilization_pct 99.75\n"
        "core_inst_count 2932\n"
        "# rows already full (>=95%): fill complete, 0 new fillers needed\n")
    pct, src = u.read_utilization(tmp_path)
    assert pct == 99.75 and src == "reports/density.rpt"
    verdict, _ = u.classify(pct, src)
    assert verdict != "NO_DATA"
