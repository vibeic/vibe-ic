#!/usr/bin/env python3
"""Tests for l8_frame_end_gap_derivation_check.py (LL-3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "l8_frame_end_gap_derivation_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _setup(tmp_path: Path, frame_end_us: float | None = None,
           ibt_max: float = 22.0):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, ibt_max],
        "tSRS_min_us": 20.0,
    }))
    l8: dict = {"internal_clock_MHz": 50}
    if frame_end_us is not None:
        l8["frame_end_gap_us"] = frame_end_us
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))


def test_no_frame_end_gap_skipped(tmp_path):
    _setup(tmp_path, frame_end_us=None)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0  # skipped


def test_too_wide_errors(tmp_path):
    _setup(tmp_path, frame_end_us=80.0)  # > 2*22 = 44
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_WIDE"
               for f in rep["findings"])


def test_too_tight_errors(tmp_path):
    _setup(tmp_path, frame_end_us=21.0)  # < 22 + 3 = 25
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_TIGHT"
               for f in rep["findings"])


def test_derived_correctly_passes(tmp_path):
    _setup(tmp_path, frame_end_us=27.0)  # in [25, 44]
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_l2_max_factor_override_passes_wider(tmp_path):
    """L2 may override max_factor to allow wider gap when spec demands."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "frame_end_gap_max_factor": 5.0,  # 5*22 = 110us upper bound
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "frame_end_gap_us": 80.0,  # was failing at default 2.0; passes at 5.0
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_waiver_skips(tmp_path):
    _setup(tmp_path, frame_end_us=80.0)  # would normally fail
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "frame_end_gap_derivation_override",
            "rationale": "EXAMPLE_TESTER-V2 tester tolerates 80us per vendor email",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_ticks_field_at_50MHz(tmp_path):
    """Verify we can parse tick-form fields with rate suffix."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "frame_end_gap_ticks_50MHz": 4000,  # = 80us → too wide
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_WIDE"
               for f in rep["findings"])


# ─────────────────────────────────────────────────────────────────────
# layergate-3 STRENGTHENING — the rate resolver used to be a hard-coded
# 4-entry table (50/5/100/25 MHz). Any other clock made the whole gate
# return None and SILENTLY SKIP: a gate that cannot fire proves nothing.
# Both directions are asserted: the gutted/odd-rate layer must now FAIL,
# and a correctly-derived value at the same odd rate must still PASS.
# Fixtures are synthesized neutral data.
# ─────────────────────────────────────────────────────────────────────

def _setup_ticks(tmp_path, l8: dict, ibt_max: float = 22.0):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, ibt_max], "tSRS_min_us": 20.0,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))


def test_ticks_at_an_unlisted_rate_in_key_now_fires(tmp_path):
    """12 MHz is not in the old hard-coded table. 960 ticks @12MHz = 80us
    → must FAIL, where before the gate skipped itself."""
    _setup_ticks(tmp_path, {"frame_end_gap_ticks_12MHz": 960})
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_WIDE"
               for f in rep["findings"])


def test_ticks_at_an_unlisted_rate_in_key_still_passes_when_correct(tmp_path):
    """324 ticks @12MHz = 27us, inside [25, 44] → PASS. Proves the new
    resolver is not simply always-fail."""
    _setup_ticks(tmp_path, {"frame_end_gap_ticks_12MHz": 324})
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout


def test_ticks_rate_resolved_from_declared_clock_domain(tmp_path):
    """No rate in the key at all — resolved from the design's OWN
    clock_domains[] record. 960 ticks @12MHz = 80us → FAIL."""
    _setup_ticks(tmp_path, {
        "frame_end_gap_ticks": 960,
        "clock_domains": [{"name": "clk_a", "source_pin": "clk_a",
                           "domain_kind": "primary", "freq_mhz": 12.0,
                           "period_ns": 1000.0 / 12.0}],
    })
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_WIDE"
               for f in rep["findings"])
    # The report must disclose WHERE the conversion factor came from.
    assert "clock_domains" in rep["summary"]["frame_end_key"]


def test_ticks_rate_resolved_from_scalar_clock_mhz(tmp_path):
    _setup_ticks(tmp_path, {"frame_end_gap_ticks": 324, "clock_mhz": 12.0})
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout


def test_ticks_with_no_resolvable_clock_still_skips(tmp_path):
    """No rate anywhere => still a documented skip, NOT a fabricated
    conversion. l8_clock_period_actionability_check is the gate that
    reports the missing clock."""
    _setup_ticks(tmp_path, {"frame_end_gap_ticks": 960})
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["skipped_reason"]
