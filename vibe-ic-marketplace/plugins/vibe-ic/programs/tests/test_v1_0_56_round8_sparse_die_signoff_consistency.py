#!/usr/bin/env python3
"""Regression tests for the round-8 sparse-die sign-off CONSISTENCY gap.

The #684 sparse-die guard deliberately emits SPARSE_DIE_TAPCELL_SKIPPED +
SPARSE_DIE_FILL_SKIPPED at core_util < threshold on an empty fixed wrapper
(correct — don't flood empty silicon). But two downstream sign-off gates did
NOT read that signal and FAILed the very op the runner correctly bounded:
  * the latch-up well-tap presence check (perc_equivalent + the standalone
    latchup_esd_spacing_check) FAILed ZERO_TAPS, and
  * metal_fill_density_check FAILed FILL_NO_SUBSTANCE.
Recurs on ANY sub-threshold-util harness/wrapper top (a common SoC pattern).

Fix: the runner writes a DURABLE attestation reports/phase3/sparse_die_skip.json
(parsed from the OpenROAD log markers); both gates + the perc_equivalent
welltap category read it and VACUOUS-PASS / downgrade-to-review the attested
skip instead of fabricate-FAILing.

§4.05 negative (no-leak): a NON-sparse design with 0 taps / 0 fillers and no
attestation must STILL FAIL ZERO_TAPS / FILL_NO_SUBSTANCE — covered by the
*_no_attestation_still_fails tests.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))
import phase3_one_shot_runner as r  # noqa: E402
import metal_fill_density_check as mfd  # noqa: E402
import latchup_esd_spacing_check as lat  # noqa: E402

_OR_LOG = (
    "[INFO] placement done\n"
    "SPARSE_DIE_TAPCELL_SKIPPED: core_util=0.022% < 5.0% — full-die tapcell "
    "tiling bounded on an empty fixed wrapper.\n"
    "SPARSE_DIE_FILL_SKIPPED: core_util=0.034% < 5.0% — full-die decap/fill "
    "tiling bounded to avoid filling an empty fixed wrapper.\n"
    "[INFO] route done\n")


# ── runner: parse + write the durable attestation ─────────────────────
def test_parse_sparse_die_skip_extracts_both():
    att = r._parse_sparse_die_skip(_OR_LOG)
    assert att["tapcell_skipped"] is True
    assert att["fill_skipped"] is True
    assert att["tapcell_core_util_pct"] == 0.022
    assert att["fill_core_util_pct"] == 0.034


def test_parse_sparse_die_skip_ignores_puts_template():
    # The Tcl `puts "SPARSE_DIE_..."` template line must NOT be counted as a
    # fired skip (only the runtime-emitted marker counts).
    tcl = 'puts "SPARSE_DIE_TAPCELL_SKIPPED: core_util=$_tap_util% < 5.0%"\n'
    att = r._parse_sparse_die_skip(tcl)
    assert att["tapcell_skipped"] is False
    assert att["fill_skipped"] is False


def test_write_and_load_attestation(tmp_path):
    r._write_sparse_die_skip_attestation(tmp_path, [_OR_LOG])
    p = tmp_path / "reports" / "phase3" / "sparse_die_skip.json"
    assert p.is_file()
    loaded = r._load_sparse_die_skip(tmp_path)
    assert loaded["tapcell_skipped"] is True
    assert loaded["fill_skipped"] is True


def test_no_skip_writes_no_attestation(tmp_path):
    r._write_sparse_die_skip_attestation(tmp_path, ["[INFO] normal run\n"])
    assert not (tmp_path / "reports" / "phase3" / "sparse_die_skip.json").exists()
    assert r._load_sparse_die_skip(tmp_path) is None


# ── perc_equivalent welltap category: attested 0-tap → MANUAL_REVIEW ───
def _welltap_category_result(project: Path, comps):
    """Mirror the runner's category decision (the load-bearing branch)."""
    wt = r._welltap_presence_check(comps)
    att = r._load_sparse_die_skip(project)
    tap_skip_attested = bool(att and att.get("tapcell_skipped"))
    if wt["status"] == "WELLTAP_PRESENT":
        return "PASS"
    if tap_skip_attested:
        return "MANUAL_REVIEW"
    return "FAIL"


_STD_ONLY = [("u0", "sky130_fd_sc_hd__inv_1"),
             ("u1", "sky130_fd_sc_hd__nand2_1"),
             ("u2", "sky130_fd_sc_hd__dfrtp_1")]


def test_welltap_attested_zero_tap_is_review(tmp_path):
    r._write_sparse_die_skip_attestation(tmp_path, [_OR_LOG])
    assert _welltap_category_result(tmp_path, _STD_ONLY) == "MANUAL_REVIEW"


def test_welltap_no_attestation_zero_tap_still_fails(tmp_path):
    # §4.05 NO-LEAK — no attestation → a genuine 0-tap break still FAILs.
    assert _welltap_category_result(tmp_path, _STD_ONLY) == "FAIL"


def test_welltap_with_taps_passes(tmp_path):
    # Real taps present → PASS regardless of attestation.
    r._write_sparse_die_skip_attestation(tmp_path, [_OR_LOG])
    comps = _STD_ONLY + [("tap0", "sky130_fd_sc_hd__tapvpwrvgnd_1")]
    assert _welltap_category_result(tmp_path, comps) == "PASS"


# ── metal_fill_density_check: attested 0-fill → no FILL_NO_SUBSTANCE ────
def _make_fill_project(tmp_path: Path, *, attest: bool) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    # routed.def + filled.def identical size (0 fillers, no growth) + done
    # marker → the FILL_NO_SUBSTANCE trigger shape.
    (pnr / "routed.def").write_text("DESIGN x ;\nCOMPONENTS 3 ;\nEND COMPONENTS\n")
    (pnr / "filled.def").write_text("DESIGN x ;\nCOMPONENTS 3 ;\nEND COMPONENTS\n")
    (pnr / "metal_fill.done").write_text("metal_fill_done\n")
    rep = tmp_path / "reports"
    rep.mkdir(exist_ok=True)
    (rep / "density.json").write_text(json.dumps({"filler_instances": 0}))
    if attest:
        r._write_sparse_die_skip_attestation(tmp_path, [_OR_LOG])
    return tmp_path


def _has_finding(findings, cat):
    return any(getattr(f, "category", None) == cat
               or (isinstance(f, dict) and f.get("category") == cat)
               for f in findings)


def test_metal_fill_attested_zero_fill_no_substance_error(tmp_path):
    proj = _make_fill_project(tmp_path, attest=True)
    findings, stats = mfd.audit(proj)
    assert stats.get("sparse_die_fill_skip_attested") is True
    assert not _has_finding(findings, "FILL_NO_SUBSTANCE")


def test_metal_fill_no_attestation_still_fails(tmp_path):
    # §4.05 NO-LEAK — without the attestation a 0-filler/no-growth fill is
    # still FILL_NO_SUBSTANCE.
    proj = _make_fill_project(tmp_path, attest=False)
    findings, stats = mfd.audit(proj)
    assert stats.get("sparse_die_fill_skip_attested") is False
    assert _has_finding(findings, "FILL_NO_SUBSTANCE")


# ── latchup gate: attested 0-tap → non-conclusive deferred ─────────────
_DEF_STD_NO_TAP = """VERSION 5.8 ;
DESIGN x ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
COMPONENTS 3 ;
- u0 sky130_fd_sc_hd__inv_1 + PLACED ( 1000 1000 ) N ;
- u1 sky130_fd_sc_hd__nand2_1 + PLACED ( 2000 1000 ) N ;
- u2 sky130_fd_sc_hd__dfrtp_1 + PLACED ( 3000 1000 ) N ;
END COMPONENTS
END DESIGN
"""


def _make_def_project(tmp_path: Path, *, attest: bool) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(_DEF_STD_NO_TAP)
    if attest:
        r._write_sparse_die_skip_attestation(tmp_path, [_OR_LOG])
    return tmp_path


def test_latchup_attested_zero_tap_deferred_not_gap(tmp_path):
    proj = _make_def_project(tmp_path, attest=True)
    rep = lat.run_geometry_layer(str(proj / "phase3/stage3/pnr/routed.def"))
    assert rep["spacing"]["status"] == "WELLTAP_SPARSE_DIE_DEFERRED"
    assert rep["any_conclusive_gap"] is False


def test_latchup_no_attestation_zero_tap_is_gap(tmp_path):
    # §4.05 NO-LEAK — without the attestation a real 0-tap design is still a
    # conclusive WELLTAP_SPACING_GAP.
    proj = _make_def_project(tmp_path, attest=False)
    rep = lat.run_geometry_layer(str(proj / "phase3/stage3/pnr/routed.def"))
    assert rep["spacing"]["status"] == "WELLTAP_SPACING_GAP"
    assert rep["spacing"]["reason"] == "ZERO_TAPS"
    assert rep["any_conclusive_gap"] is True


def test_latchup_cli_exit_codes(tmp_path):
    """End-to-end CLI: attested skip → exit 0; no attestation → exit 1."""
    proj = _make_def_project(tmp_path, attest=True)
    dfp = str(proj / "phase3/stage3/pnr/routed.def")
    p = subprocess.run([sys.executable, str(PROGS / "latchup_esd_spacing_check.py"),
                        dfp], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout
    # remove attestation → conclusive gap → exit 1
    (proj / "reports" / "phase3" / "sparse_die_skip.json").unlink()
    p2 = subprocess.run([sys.executable, str(PROGS / "latchup_esd_spacing_check.py"),
                         dfp], capture_output=True, text=True)
    assert p2.returncode == 1, p2.stdout
