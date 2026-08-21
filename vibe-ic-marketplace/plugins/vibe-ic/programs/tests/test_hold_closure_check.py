#!/usr/bin/env python3
"""Tests for hold_closure_check.py (Step 20 post-CTS hold-fixing substance gate).

Covers:
  * PASS via parsed hold report (worst hold slack >= 0)
  * FAIL via parsed hold report (negative hold slack — the real backend failure)
  * PASS via DEF diff (hold buffers inserted vs pre-hold post_cts.def)
  * FAIL via byte-identical post_hold.def == post_cts.def (no fixing happened)
  * FAIL via instance-count regression
  * FAIL via differs-but-no-new-cell-and-no-report (insufficient evidence)
  * FAIL on missing required post_hold.def
  * FAIL on empty post_hold.def
  * FAIL on garbage (non-DEF) post_hold.def
  * FAIL when no report AND pre-hold input post_cts.def missing
  * SKIP on missing project dir
  * WAIVED via waivers.json
  * JSON report shape (gate/verdict/findings)
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hold_closure_check as hc  # noqa: E402


# --------------------------------------------------------------------------
# DEF fixture builders
# --------------------------------------------------------------------------
def _def_text(components):
    """Build a minimal-but-valid DEF with `components` instance lines."""
    lines = [
        "VERSION 5.8 ;",
        "DIVIDERCHAR \"/\" ;",
        "BUSBITCHARS \"[]\" ;",
        "DESIGN top ;",
        "UNITS DISTANCE MICRONS 1000 ;",
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;",
        f"COMPONENTS {components} ;",
    ]
    for i in range(components):
        lines.append(
            f"- _inst_{i}_ sky130_fd_sc_hd__inv_2 + PLACED ( {i*10} 0 ) N ;")
    lines += [
        "END COMPONENTS",
        "NETS 0 ;",
        "END NETS",
        "END DESIGN",
    ]
    return "\n".join(lines) + "\n"


def _write_pnr(project, post_hold=None, post_cts=None):
    pnr = project / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    if post_hold is not None:
        (pnr / "post_hold.def").write_text(post_hold)
    if post_cts is not None:
        (pnr / "post_cts.def").write_text(post_cts)
    return pnr


def _write_hold_report(project, text, name="post_hold_timing.rpt", sub="sta"):
    d = project / "phase3" / "stage3" / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return d / name


# --------------------------------------------------------------------------
# PASS via hold report
# --------------------------------------------------------------------------
def test_pass_hold_report_nonnegative(tmp_path):
    # post_hold.def differs from post_cts.def AND a hold report shows slack>=0.
    _write_pnr(tmp_path,
               post_hold=_def_text(120),
               post_cts=_def_text(100))
    _write_hold_report(
        tmp_path,
        "Startpoint: ff1/CLK\nEndpoint: ff2/D\n"
        "hold slack (MET)               0.0453\n")
    rc = hc.main([str(tmp_path)])
    assert rc == 0


def test_fail_hold_report_negative(tmp_path):
    # The real backend failure: hold report shows a NEGATIVE hold slack.
    _write_pnr(tmp_path,
               post_hold=_def_text(105),
               post_cts=_def_text(100))
    _write_hold_report(
        tmp_path,
        "Startpoint: ff1/CLK\nEndpoint: ff2/D\n"
        "hold slack (VIOLATED)         -0.1230\n")
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert any(f["rule"] == "HOLD_SLACK_NEGATIVE" for f in data["findings"])


def test_negative_report_wins_even_if_def_grew(tmp_path):
    # A negative hold report must FAIL even when the DEF diff alone would PASS.
    _write_pnr(tmp_path,
               post_hold=_def_text(200),   # grew a lot
               post_cts=_def_text(100))
    _write_hold_report(tmp_path, "worst hold slack -0.05\n")
    rc = hc.main([str(tmp_path)])
    assert rc == 1


# --------------------------------------------------------------------------
# PASS / FAIL via DEF diff (no report)
# --------------------------------------------------------------------------
def test_pass_def_diff_buffers_inserted(tmp_path):
    _write_pnr(tmp_path,
               post_hold=_def_text(143),   # CTS 100 -> +43 hold buffers
               post_cts=_def_text(100))
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "PASS"
    assert data["summary"]["inserted_instance_delta"] == 43
    assert any(f["rule"] == "HOLD_CELLS_INSERTED" for f in data["findings"])


def test_fail_byte_identical_to_input(tmp_path):
    # The classic hole: post_hold.def == post_cts.def (no fixing happened).
    same = _def_text(100)
    _write_pnr(tmp_path, post_hold=same, post_cts=same)
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert any(f["rule"] == "POST_HOLD_IDENTICAL_TO_INPUT"
               for f in data["findings"])


def test_fail_instance_count_regression(tmp_path):
    _write_pnr(tmp_path,
               post_hold=_def_text(80),    # fewer than CTS — impossible
               post_cts=_def_text(100))
    rc = hc.main([str(tmp_path)])
    assert rc == 1


def test_fail_differs_but_no_new_cell_no_report(tmp_path):
    # Same component count, files differ (e.g. only a comment), no hold report.
    pnr = _write_pnr(tmp_path, post_cts=_def_text(100))
    ph = _def_text(100) + "# touched but no new cell\n"
    (pnr / "post_hold.def").write_text(ph)
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert any(f["rule"] == "NO_INSERTED_CELLS_NO_REPORT"
               for f in data["findings"])


def test_fail_no_report_and_no_postcts(tmp_path):
    # Only post_hold.def, no report, no pre-hold baseline => cannot verify.
    _write_pnr(tmp_path, post_hold=_def_text(100))
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert any(f["rule"] == "NO_HOLD_EVIDENCE" for f in data["findings"])


# --------------------------------------------------------------------------
# Missing / empty / garbage required artefact (honesty)
# --------------------------------------------------------------------------
def test_fail_missing_post_hold_def(tmp_path):
    # pnr dir exists with post_cts.def but no post_hold.def.
    _write_pnr(tmp_path, post_cts=_def_text(100))
    rc = hc.main([str(tmp_path)])
    assert rc == 1


def test_fail_empty_post_hold_def(tmp_path):
    pnr = _write_pnr(tmp_path, post_cts=_def_text(100))
    (pnr / "post_hold.def").write_text("")
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert any(f["rule"] == "POST_HOLD_DEF_EMPTY" for f in data["findings"])


def test_fail_garbage_post_hold_def(tmp_path):
    pnr = _write_pnr(tmp_path, post_cts=_def_text(100))
    (pnr / "post_hold.def").write_text("this is not a DEF file at all\n" * 5)
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert any(f["rule"] == "POST_HOLD_DEF_UNPARSEABLE"
               for f in data["findings"])


# --------------------------------------------------------------------------
# SKIP / WAIVED
# --------------------------------------------------------------------------
def test_skip_missing_project_dir(tmp_path):
    missing = tmp_path / "nope"
    rc = hc.main([str(missing)])
    assert rc == 2


def test_waived_when_artefact_absent(tmp_path):
    # No post_hold.def at all, but a waiver declares the step waived.
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "hold_closure",
            "ticket": "WAIVE-20",
            "reason": "non-production pilot run; hold closed at Step 23",
        }]
    }))
    out = tmp_path / "rep.json"
    rc = hc.main([str(tmp_path), "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "WAIVED"


def test_waiver_does_not_mask_negative_slack(tmp_path):
    # A waiver only applies on absence; if the artefact IS present and the
    # report shows negative slack, it must still FAIL (no vacuous waiver pass).
    _write_pnr(tmp_path, post_hold=_def_text(105), post_cts=_def_text(100))
    _write_hold_report(tmp_path, "hold slack -0.2\n")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{"id": "hold_closure", "ticket": "W", "reason": "x" * 25}]
    }))
    rc = hc.main([str(tmp_path)])
    assert rc == 1


# --------------------------------------------------------------------------
# JSON report shape
# --------------------------------------------------------------------------
def test_json_report_shape(tmp_path):
    _write_pnr(tmp_path, post_hold=_def_text(143), post_cts=_def_text(100))
    out = tmp_path / "out.json"
    hc.main([str(tmp_path), "--json", str(out)])
    data = json.loads(out.read_text())
    assert data["gate"] == "hold_closure_check"
    assert data["verdict"] in ("PASS", "FAIL", "WAIVED")
    assert isinstance(data["findings"], list)
    assert all("severity" in f and "rule" in f and "message" in f
               for f in data["findings"])


def test_json_directory_autocreated(tmp_path):
    _write_pnr(tmp_path, post_hold=_def_text(110), post_cts=_def_text(100))
    out = tmp_path / "nested" / "deep" / "out.json"
    hc.main([str(tmp_path), "--json", str(out)])
    assert out.is_file()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
