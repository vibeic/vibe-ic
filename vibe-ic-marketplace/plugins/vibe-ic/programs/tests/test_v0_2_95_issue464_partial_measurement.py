#!/usr/bin/env python3
"""tests/test_v0_2_95_issue464_partial_measurement.py

Pins ORGANIC-20260606 #464 — the A4 corner sweep silently swallowed failed AC
sub-analyses. In the field, ngspice's `ac` open-loop gain/UGBW measure ERRORed
at every sizing point ("vdb(vout) argument out of range", "no such vector as
gain", "meas ac dcgain ... failed!" -> ugbw=0.0, dcgain empty) while only the
transient `meas` converged — yet corner_results.json still stamped
_provenance="real_ngspice" + PASS_INFORMATIONAL with NO field recording the AC
failure (the evidence lived only in the raw log).

建議修法 (now implemented and pinned here):
  - the per-log parser scans each ngspice log for per-analysis error markers
    ("Error:", "failed!", missing-vector messages);
  - affected metrics become null (NOT bogus zeros);
  - a per-block sim_warnings / partial_measurement field is added;
  - provenance becomes "real_ngspice_partial" + an analysis_status map per
    analysis type.

CORPUS-SWEEP regression guard: a fully-clean sweep keeps full provenance
("real_ngspice") and partial_measurement=False with no warnings.

chip-AGNOSTIC: synthetic block names (u_block_*), no chip/vendor/SKU literal;
ngspice is never invoked — the lowest-level docker shim is monkeypatched to
return canned ngspice transcripts.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent / "analog_real_corner_sweep.py")
sys.path.insert(0, str(PROG.parent))


def _load_module():
    spec = importlib.util.spec_from_file_location("analog_real_corner_sweep", PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = _load_module()


# ── Canned ngspice transcripts (delta_sigma-shaped converter deck) ─────────
#
# CLEAN: both tran and ac converged — every metric is a real value.
_CLEAN_LOG = """\
Circuit: * u_block delta-sigma
Doing analysis at TEMP = 27.000000 and TNOM = 27.000000

vstep = 6.000000e-01
vsettle = 1.190796e+00
dv = 5.907960e-01
dcgain = 6.512000e+01
ugbw = 4.231000e+07
MEAS vout= 1.190796e+00  vstep= 6.000000e-01  dv= 5.907960e-01  ugbw= 4.231000e+07  dcgain= 6.512000e+01
"""

# PARTIAL: the transient `meas` converged (vsettle/vstep/dv real) but the AC
# sub-analysis ERRORed at this sizing point exactly as the field reported.
# `vdb(vout)` is out of range -> `gain` never created -> the two ac measures
# fail; ngspice still echoes a BOGUS ugbw=0.0 through the `$&` summary line.
_PARTIAL_LOG = """\
Circuit: * u_block delta-sigma
Doing analysis at TEMP = 27.000000 and TNOM = 27.000000

vstep = 6.000000e-01
vsettle = 1.190796e+00
dv = 5.907960e-01
Error: vdb(vout): argument out of range for log
Error: no such vector as gain
meas ac dcgain  find gain at=1 failed!
meas ac ugbw   when gain=0 failed!
MEAS vout= 1.190796e+00  vstep= 6.000000e-01  dv= 5.907960e-01  ugbw= 0.000000e+00  dcgain=
"""


def _install_docker_shim(monkeypatch, ngspice_log):
    """Monkeypatch the lowest-level docker shim so ngspice is never invoked.

    Path-probe / file-test commands return rc=0; the `ngspice -b ...` command
    returns the canned transcript. Exercises the FULL real pipeline (parser,
    nulling, run_block aggregation) — only the container call is faked.
    """
    class _CP:
        def __init__(self, rc, out):
            self.returncode = rc
            self.stdout = out
            self.stderr = ""

    def fake_docker(container, cmd, timeout=120):
        if "ngspice -b" in cmd or "/ngspice -b" in cmd or " -b " in cmd:
            return _CP(0, ngspice_log)
        if cmd.startswith("command -v ngspice"):
            return _CP(0, "/usr/bin/ngspice")
        # test -e / test -f probes succeed (pdk lib reachable, path verbatim)
        return _CP(0, "")

    monkeypatch.setattr(M, "_docker", fake_docker)
    monkeypatch.setattr(M, "_resolve_ngspice", lambda c: "/usr/bin/ngspice")
    # Reset caches that may have been seeded by an earlier test.
    M._NGSPICE_CACHE.clear()
    M._CONTAINER_PATH_CACHE.clear()


def _make_project(tmp_path, block, btype):
    """A project with NO delivered netlist, on purpose.

    What these end-to-end tests measure — `analysis_status["ac"]`,
    `analysis_status["tran"]`, the `ugbw` metric — are properties of the
    BUILT-IN template deck for this block type. A delivered netlist would (
    correctly) become the subject of measurement and the assertions would be
    about a different circuit, so the fixture leaves the upstream output absent
    and the tests take the explicit opt-in below. The sweep will not reach the
    simulator without it; that refusal is covered elsewhere."""
    bdir = tmp_path / "phase3" / "analog" / block
    bdir.mkdir(parents=True, exist_ok=True)
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.write_text(json.dumps({"blocks": [{"name": block, "type": btype}]}))
    return bdir


def _exercise_builtin_template(monkeypatch):
    """Opt in to the built-in table deliberately, the one way it is reachable.

    Returns nothing; the caller asserts the resulting artefact is LABELLED as
    built-in, so this suite is also a live guard on that labelling."""
    monkeypatch.setenv("ANALOG_ALLOW_BUILTIN_NETLIST", "1")


def _assert_labelled_builtin(cr):
    assert cr["design_traceable"] is False, (
        "a deck this program authored must never read as design-traceable")
    assert cr["netlist_provenance"] == "builtin_template"
    assert "BUILT-IN" in cr["deck_authored_by"]
    assert cr["builtin_override"] == "ANALOG_ALLOW_BUILTIN_NETLIST"


# ─────────────────── (1) unit: the per-log failure scanner ───────────────────

def test_scanner_detects_ac_failure_and_warnings():
    failed, failed_keys, warnings = M._scan_analysis_failures(_PARTIAL_LOG)
    assert "ac" in failed, "AC sub-analysis failure not detected"
    # the explicit failed measures are named
    assert "dcgain" in failed_keys and "ugbw" in failed_keys
    # the raw diagnostic lines are surfaced as warnings (evidence, not swallowed)
    joined = "\n".join(warnings)
    assert "argument out of range" in joined
    assert "no such vector as gain" in joined
    assert "failed!" in joined


def test_scanner_clean_log_has_no_failures():
    failed, failed_keys, warnings = M._scan_analysis_failures(_CLEAN_LOG)
    assert failed == set()
    assert failed_keys == set()
    assert warnings == []


# ─────────────── (2) parser: failed-analysis metrics become null ──────────────

def test_run_ngspice_nulls_ac_metrics_not_bogus_zero(monkeypatch):
    _install_docker_shim(monkeypatch, _PARTIAL_LOG)
    ok, meas, raw, status = M._run_ngspice("c", "/x/run.sp")
    assert ok is True  # ngspice returned rc=0 (transient converged)
    # The transient metrics are REAL.
    assert meas["vsettle"] == pytest.approx(1.190796)
    # The AC metrics are NULL — NOT the bogus 0.0 the $& echo produced.
    assert meas["ugbw"] is None, "ugbw kept its bogus zero instead of being nulled"
    assert "ac" in status["failed_analyses"]
    assert "ugbw" in status["nulled_metrics"]
    assert status["partial"] is True
    assert status["warnings"], "no warnings recorded for a failed AC analysis"


def test_run_ngspice_clean_keeps_real_metrics(monkeypatch):
    _install_docker_shim(monkeypatch, _CLEAN_LOG)
    ok, meas, raw, status = M._run_ngspice("c", "/x/run.sp")
    assert ok is True
    assert meas["ugbw"] == pytest.approx(4.231e7)
    assert meas["dcgain"] == pytest.approx(65.12)
    assert status["failed_analyses"] == []
    assert status["nulled_metrics"] == []
    assert status["partial"] is False
    assert status["warnings"] == []


# ─────────── (3) end-to-end run_block: provenance downgrade + fields ──────────

def test_run_block_partial_downgrades_provenance(tmp_path, monkeypatch):
    block = "u_block_partial"
    _make_project(tmp_path, block, "delta_sigma")
    _install_docker_shim(monkeypatch, _PARTIAL_LOG)
    _exercise_builtin_template(monkeypatch)
    rc = M.run_block(tmp_path, block, "c", "sky130", "auto")
    assert rc == 0  # transient gives a usable vout, so the block still completes
    cr = json.loads((tmp_path / "phase3" / "analog" / block
                     / "corner_results.json").read_text())
    _assert_labelled_builtin(cr)
    # provenance is DOWNGRADED (the headline #464 fix)
    assert cr["_provenance"] == "real_ngspice_partial"
    # first-class partial-measurement evidence is present
    assert cr["partial_measurement"] is True
    assert "ac" in cr["failed_analyses"]
    assert cr["analysis_status"]["ac"] == "FAILED"
    assert cr["analysis_status"]["tran"] == "OK"
    assert any("argument out of range" in w for w in cr["sim_warnings"])
    # the nulled AC metric did NOT leak a bogus zero into the run record
    runs = cr["all_runs"]
    assert all(r.get("ugbw") is None for r in runs), \
        "a bogus ugbw=0.0 leaked into all_runs despite the AC failure"


def test_run_block_clean_keeps_full_provenance(tmp_path, monkeypatch):
    """CORPUS-SWEEP regression guard: a fully-clean sweep keeps full
    provenance ('real_ngspice') and no warnings (the issue's explicit
    no-regression condition)."""
    block = "u_block_clean"
    _make_project(tmp_path, block, "delta_sigma")
    _install_docker_shim(monkeypatch, _CLEAN_LOG)
    _exercise_builtin_template(monkeypatch)
    rc = M.run_block(tmp_path, block, "c", "sky130", "auto")
    assert rc == 0
    cr = json.loads((tmp_path / "phase3" / "analog" / block
                     / "corner_results.json").read_text())
    _assert_labelled_builtin(cr)
    assert cr["_provenance"] == "real_ngspice"
    assert cr["partial_measurement"] is False
    assert cr["sim_warnings"] == []
    assert cr["failed_analyses"] == []
    assert cr["analysis_status"]["ac"] == "OK"
    assert cr["analysis_status"]["tran"] == "OK"
    # real AC metrics survive
    runs = cr["all_runs"]
    assert any(r.get("ugbw") == pytest.approx(4.231e7) for r in runs)


def test_results_json_mirrors_partial_provenance(tmp_path, monkeypatch):
    block = "u_block_partial2"
    _make_project(tmp_path, block, "delta_sigma")
    _install_docker_shim(monkeypatch, _PARTIAL_LOG)
    _exercise_builtin_template(monkeypatch)
    M.run_block(tmp_path, block, "c", "sky130", "auto")
    rj = json.loads((tmp_path / "phase3" / "analog" / block
                     / "sizing_loop" / "results.json").read_text())
    assert rj["netlist_provenance"] == "builtin_template"
    assert rj["_provenance"] == "real_ngspice_partial"
    assert rj["partial_measurement"] is True
    assert rj["sim_warnings"]
