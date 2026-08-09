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


# ─────────────────────────────────────────────────────────────────────
# THE FAIL VERDICT WAS UNREACHABLE FROM THE ONLY CALLER.
#
# Every test above passes `--strict`. The P0 structural umbrella does
# not: `flow_compliance_check._structural_gate_argv` builds
# `[python, <program>, <project>]` for a plain-argv gate. Under that argv
# the old `main()` returned `1 if args.strict and not passed else 0` — so
# rc was 0 for EVERY run the flow performs, while the JSON claimed
# `"passed": true` next to an ERROR finding. rc 0 is PASS to the
# umbrella, so the exact bug this gate documents scored green.
#
# These tests build the argv by CALLING THE UMBRELLA'S OWN BUILDER
# rather than re-typing it, so they exercise the real construction path;
# a re-typed argv agrees with the umbrella only by coincidence. Both
# directions are asserted on returned values (exit code + emitted JSON),
# never on program text. Fixtures are synthetic neutral data.
# ─────────────────────────────────────────────────────────────────────

def _umbrella_argv(project: Path) -> list[str]:
    """The argv the P0 structural umbrella really runs this gate with."""
    sys.path.insert(0, str(PROG.parent))
    import flow_compliance_check as fcc

    assert "l8_frame_end_gap_derivation_check" in fcc._STRUCTURAL_RTL_GATES
    return fcc._structural_gate_argv(
        "l8_frame_end_gap_derivation_check", project,
        rtl_dir=project / "phase2" / "stage1" / "rtl")


def _umbrella_argv_without_strict(project: Path) -> list[str]:
    """The same argv with any `--strict` removed.

    The property this fix owns is that the DEFAULT is correct, so the
    no-strict shape is asserted explicitly rather than inferred from what
    the caller happens to build today. Filtering instead of asserting
    `--strict not in argv` keeps the test honest if a caller-side fix
    later adds the flag: the default must still produce the verdict, and
    the test must not start passing merely because the flag arrived.
    """
    return [a for a in _umbrella_argv(project) if a != "--strict"]


def _run_as_umbrella(project: Path, report: Path):
    """Drive the gate the way the flow does, minus any `--strict`."""
    return subprocess.run(
        _umbrella_argv_without_strict(project) + ["--json", str(report)],
        capture_output=True, text=True)


def test_error_is_reachable_from_the_umbrella_argv(tmp_path):
    """DIRECTION 1 — fails against the unfixed program.

    A gap above the derived upper bound, driven with the umbrella's own
    argv (no `--strict`): the gate must return its FAIL verdict, and the
    JSON must not publish `passed: true` beside an ERROR finding.
    Unfixed: rc 0 and passed True.
    """
    _setup(tmp_path, frame_end_us=80.0)      # bound is 2 * 22 = 44us
    rep_path = tmp_path / "umbrella.json"
    r = _run_as_umbrella(tmp_path, rep_path)

    assert r.returncode == 1, (
        f"FAIL verdict unreachable from the real caller: rc={r.returncode}\n"
        f"{r.stdout}")
    rep = json.loads(rep_path.read_text())
    assert rep["passed"] is False, rep
    assert [f["rule"] for f in rep["findings"]] == [
        "L8_FRAME_END_GAP_TOO_WIDE"]
    assert rep["summary"]["upper_bound_us"] == 44.0

    # And through the caller's argv EXACTLY as built, whatever it becomes.
    raw = subprocess.run(_umbrella_argv(tmp_path),
                         capture_output=True, text=True)
    assert raw.returncode == 1, raw.stdout


def test_too_tight_is_reachable_from_the_umbrella_argv(tmp_path):
    """DIRECTION 1, other ERROR rule — also unreachable when unfixed."""
    _setup(tmp_path, frame_end_us=21.0)      # bound is 22 + 3 = 25us
    rep_path = tmp_path / "umbrella.json"
    r = _run_as_umbrella(tmp_path, rep_path)

    assert r.returncode == 1, r.stdout
    rep = json.loads(rep_path.read_text())
    assert rep["passed"] is False, rep
    assert [f["rule"] for f in rep["findings"]] == [
        "L8_FRAME_END_GAP_TOO_TIGHT"]


def test_umbrella_argv_still_passes_an_in_range_value(tmp_path):
    """DIRECTION 2 — proves the gate is not now always-fail.

    Same argv, same fixture shape, only the derived value differs: a gap
    inside [25, 44] must still return the PASS verdict with an empty
    findings list and `passed: true`.
    """
    _setup(tmp_path, frame_end_us=27.0)
    rep_path = tmp_path / "umbrella.json"
    r = _run_as_umbrella(tmp_path, rep_path)

    assert r.returncode == 0, r.stdout
    rep = json.loads(rep_path.read_text())
    assert rep["passed"] is True, rep
    assert rep["findings"] == []
    assert rep["summary"]["lower_bound_us"] == 25.0


def test_umbrella_argv_still_exits_zero_on_the_skip_paths(tmp_path):
    """DIRECTION 2, blast radius — every corpus project reaches the gate
    through a skip path (no `frame_end_gap_*` field in L8). Those must
    keep exiting 0, or the default change re-scores them all at once."""
    _setup(tmp_path, frame_end_us=None)
    rep_path = tmp_path / "umbrella.json"
    r = _run_as_umbrella(tmp_path, rep_path)

    assert r.returncode == 0, r.stdout
    rep = json.loads(rep_path.read_text())
    assert rep["passed"] is True
    assert rep["findings"] == []
    assert rep["summary"]["skipped_reason"]


def test_waiver_still_suppresses_under_the_umbrella_argv(tmp_path):
    """DIRECTION 2, escape hatch — a waived project must not be turned
    red by the default change."""
    _setup(tmp_path, frame_end_us=80.0)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "frame_end_gap_derivation_override",
            "rationale": "synthetic fixture: master tolerates the wide gap",
        }],
    }))
    rep_path = tmp_path / "umbrella.json"
    r = _run_as_umbrella(tmp_path, rep_path)

    assert r.returncode == 0, r.stdout
    rep = json.loads(rep_path.read_text())
    assert rep["passed"] is True
    assert rep["findings"] == []


def test_strict_flag_is_still_accepted_and_no_longer_gates_the_verdict(
        tmp_path):
    """`--strict` stays parseable (existing command lines keep working)
    and now produces the SAME verdict as its absence."""
    _setup(tmp_path, frame_end_us=80.0)
    strict = subprocess.run(
        _umbrella_argv(tmp_path) + ["--strict",
                                    "--json", str(tmp_path / "s.json")],
        capture_output=True, text=True)
    plain = _run_as_umbrella(tmp_path, tmp_path / "p.json")

    assert strict.returncode == 1, strict.stderr
    assert strict.returncode == plain.returncode
    assert (json.loads((tmp_path / "s.json").read_text())["passed"]
            is json.loads((tmp_path / "p.json").read_text())["passed"]
            is False)
