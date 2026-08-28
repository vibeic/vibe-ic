"""#559 — `fpga_qsf_lint` called a missing file a violation, and passed silently.

Two defects, opposite directions, in the same gate.

**A missing QSF exited 1.** rc 1 is a defect verdict, so the P0 umbrella — which
reads the exit code — would have recorded a real QSF lint failure against a
design whose QSF simply was not at the path it was given. It is now rc 2,
"could not check", which the CI dispatcher already separates from a finding via
`run_tolerating_uncheckable`.

**A clean lint said nothing about its scope.** `PASS: QSF lint clean` was
printed identically for a fully populated project and for one with no
assignments at all, so nothing in the output distinguished a real lint from a
vacuous one.

The distinction that matters here, and the reason both had to be fixed together:
an EMPTY QSF is not the same as a MISSING one. An empty file genuinely has no
`TOP_LEVEL_ENTITY`, so `missing-top-entity` is a true finding and rc 1 is
correct — that case is asserted below so the fix for the missing-file path
cannot swallow it.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "fpga_qsf_lint.py"

QSF = """\
set_global_assignment -name TOP_LEVEL_ENTITY top
set_global_assignment -name VERILOG_FILE top.v
set_location_assignment PIN_A1 -to clk
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to clk
"""

RTL = "module top(input wire clk, output wire q);\nendmodule\n"


def _run(qsf, rtl_dir, out_dir):
    return _pr.run(
        [sys.executable, str(PROG), "--qsf-file", str(qsf),
         "--rtl-dir", str(rtl_dir), "--out-dir", str(out_dir)],
        capture_output=True, text=True)


@pytest.fixture
def project(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text(RTL, encoding="utf-8")
    (rtl / "top.qsf").write_text(QSF, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    return rtl / "top.qsf", rtl, out


def test_missing_qsf_is_uncheckable_not_a_violation(project, tmp_path):
    qsf, rtl, out = project
    proc = _run(tmp_path / "absent.qsf", rtl, out)
    assert proc.returncode == 2, (
        f"a missing QSF exited {proc.returncode}; rc 1 is a defect verdict and "
        f"would be recorded as a real lint failure against the design")
    assert "VACUOUS_PASS" in proc.stderr


def test_empty_qsf_is_still_a_real_finding(project, tmp_path):
    """The boundary the fix must not cross.

    An empty file exists and genuinely lacks TOP_LEVEL_ENTITY, so this is a
    finding about the project, not an unusable input.
    """
    empty = tmp_path / "empty.qsf"
    empty.write_text("", encoding="utf-8")
    _, rtl, out = project
    proc = _run(empty, rtl, out)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "missing-top-entity" in proc.stdout


def test_clean_pass_states_what_it_examined(project):
    qsf, rtl, out = project
    proc = _run(qsf, rtl, out)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "examined" in proc.stdout, (
        f"a clean lint does not say how much it linted: {proc.stdout!r}")
    for token in ("verilog file", "pin assignment", "RTL module"):
        assert token in proc.stdout, proc.stdout


def test_json_report_carries_the_counts(project):
    qsf, rtl, out = project
    _run(qsf, rtl, out)
    doc = json.loads((out / "fpga_qsf_lint.json").read_text(encoding="utf-8"))
    assert doc["total_findings"] == 0
    ex = doc["examined"]
    assert ex["verilog_files"] == 1, doc
    assert ex["pin_assignments"] == 1, doc
    assert ex["rtl_modules"] == 1, doc


def test_counts_track_the_input(tmp_path):
    """The counts must be measured, not constants.

    A denominator that reports the same number regardless of input discloses
    nothing while looking like it does.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "a.v").write_text("module a(input wire c);\nendmodule\n", encoding="utf-8")
    (rtl / "b.v").write_text("module b(input wire c);\nendmodule\n", encoding="utf-8")
    qsf = rtl / "p.qsf"
    qsf.write_text(
        "set_global_assignment -name TOP_LEVEL_ENTITY a\n"
        "set_global_assignment -name VERILOG_FILE a.v\n"
        "set_global_assignment -name VERILOG_FILE b.v\n"
        "set_location_assignment PIN_A1 -to c\n"
        "set_location_assignment PIN_A2 -to d\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    _run(qsf, rtl, out)
    doc = json.loads((out / "fpga_qsf_lint.json").read_text(encoding="utf-8"))
    ex = doc["examined"]
    assert ex["verilog_files"] == 2, doc
    assert ex["pin_assignments"] == 2, doc
    assert ex["rtl_modules"] == 2, doc
