"""Tests for scope_periodic_pulse_check.py.

All tests use ``--mock-samples-csv`` so no real scope hardware is required.
The synthetic CSVs are tiny piecewise-constant waveforms that exercise the
same pulse-detection + verdict logic the real scope path uses.

Importantly, this file does NOT import ``usbtmc`` — the program is
designed so that the USB dependency is loaded lazily, only when the user
actually asks the program to talk to a scope.
"""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "scope_periodic_pulse_check.py")


# ---------------------------------------------------------------------------
# CSV synthesisers
# ---------------------------------------------------------------------------
def _write_csv(path: Path, samples):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_us", "voltage"])
        for t, v in samples:
            w.writerow([f"{t:.3f}", f"{v:.4f}"])


def _gen_pulses(span_us: float,
                pulse_centres_us,
                pulse_width_us: float,
                step_us: float = 1.0,
                v_high: float = 3.3,
                v_low: float = 0.0):
    """Build a (time_us, voltage) sample stream.

    Idle-high at v_high, drops to v_low for pulse_width_us starting at each
    centre - width/2. Sample step is step_us.
    """
    centres = list(pulse_centres_us)
    samples = []
    t = 0.0
    n = int(span_us / step_us) + 1
    for _ in range(n):
        v = v_high
        for c in centres:
            start = c - pulse_width_us / 2
            end = c + pulse_width_us / 2
            if start <= t <= end:
                v = v_low
                break
        samples.append((t, v))
        t += step_us
    return samples


def _run(args, csv_path=None, extra=None):
    cmd = [sys.executable, str(PROG)]
    if csv_path is not None:
        cmd += ["--mock-samples-csv", str(csv_path)]
    cmd += list(args)
    if extra:
        cmd += list(extra)
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_help_does_not_crash():
    """argparse exits 0 on --help; capture SystemExit cleanly."""
    r = _run(["--help"])
    assert r.returncode == 0, r.stderr
    assert "scope" in r.stdout.lower()
    # Confirm the new generic name is exposed
    assert "--period-ms" in r.stdout
    assert "--mock-samples-csv" in r.stdout


def test_ten_periodic_pulses_fail(tmp_path):
    """10 pulses, 26 µs wide, 5 ms apart over 50 ms — must FAIL."""
    span_us = 50_000.0
    centres = [(i + 1) * 5_000.0 - 2_500.0 for i in range(10)]  # 2.5, 7.5, ..., 47.5 ms
    samples = _gen_pulses(span_us, centres, pulse_width_us=26.0, step_us=1.0)
    csv_path = tmp_path / "buggy.csv"
    _write_csv(csv_path, samples)

    r = _run(["--period-ms", "5", "--period-tol-ms", "1",
              "--pulse-min-us", "10", "--pulse-max-us", "100"],
             csv_path=csv_path)
    assert r.returncode == 1, f"expected FAIL, got rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "FAIL" in r.stdout
    assert "periodic" in r.stdout.lower() or "period" in r.stdout.lower()


def test_zero_pulses_pass(tmp_path):
    """Flat HIGH waveform — 0 pulses — PASS."""
    span_us = 50_000.0
    samples = _gen_pulses(span_us, [], pulse_width_us=26.0, step_us=10.0)
    csv_path = tmp_path / "flat.csv"
    _write_csv(csv_path, samples)

    r = _run(["--period-ms", "5"], csv_path=csv_path)
    assert r.returncode == 0, f"expected PASS, got rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "PASS" in r.stdout
    assert "0 in-band pulse" in r.stdout


def test_single_isolated_pulse_pass(tmp_path):
    """Exactly 1 in-band pulse — PASS."""
    span_us = 50_000.0
    samples = _gen_pulses(span_us, [25_000.0], pulse_width_us=30.0, step_us=1.0)
    csv_path = tmp_path / "single.csv"
    _write_csv(csv_path, samples)

    r = _run(["--period-ms", "5"], csv_path=csv_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "1 in-band pulse" in r.stdout


def test_irregular_spacing_pass(tmp_path):
    """5 pulses with no two consecutive gaps within tol — PASS with note.

    Gaps (between consecutive falling edges) are 4, 11, 16, 7 ms. Target
    period is 25 ms ± 1 ms, so NO consecutive gap matches.
    """
    span_us = 50_000.0
    centres = [2_000.0, 6_000.0, 17_000.0, 33_000.0, 40_000.0]
    samples = _gen_pulses(span_us, centres, pulse_width_us=30.0, step_us=1.0)
    csv_path = tmp_path / "irregular.csv"
    _write_csv(csv_path, samples)

    r = _run(["--period-ms", "25", "--period-tol-ms", "1"], csv_path=csv_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "not the timer-bug pattern" in r.stdout


def test_pulses_too_wide_pass(tmp_path):
    """200 µs pulses — outside accepted band — 0 in-band — PASS."""
    span_us = 50_000.0
    centres = [(i + 1) * 5_000.0 for i in range(8)]
    samples = _gen_pulses(span_us, centres, pulse_width_us=200.0, step_us=2.0)
    csv_path = tmp_path / "wide.csv"
    _write_csv(csv_path, samples)

    r = _run(["--period-ms", "5",
              "--pulse-min-us", "10", "--pulse-max-us", "100"],
             csv_path=csv_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "0 in-band pulse" in r.stdout or "0 LOW pulses" in r.stdout


def test_pulses_too_narrow_pass(tmp_path):
    """5 µs pulses — below 10 µs floor — none accepted — PASS.

    Use a 0.5 µs step so the narrow LOW excursion is captured.
    """
    span_us = 50_000.0
    centres = [(i + 1) * 5_000.0 for i in range(8)]
    samples = _gen_pulses(span_us, centres, pulse_width_us=5.0, step_us=0.5)
    csv_path = tmp_path / "narrow.csv"
    _write_csv(csv_path, samples)

    r = _run(["--period-ms", "5",
              "--pulse-min-us", "10", "--pulse-max-us", "100"],
             csv_path=csv_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_period_arg_shifts_sensitivity(tmp_path):
    """10 pulses at 5 ms spacing must NOT FAIL when target is 10 ms."""
    span_us = 50_000.0
    centres = [(i + 1) * 5_000.0 - 2_500.0 for i in range(10)]
    samples = _gen_pulses(span_us, centres, pulse_width_us=26.0, step_us=1.0)
    csv_path = tmp_path / "shifted.csv"
    _write_csv(csv_path, samples)

    # Target 10 ms ± 1 — none of the 5-ms gaps match.
    r = _run(["--period-ms", "10", "--period-tol-ms", "1"],
             csv_path=csv_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "not the timer-bug pattern" in r.stdout


def test_missing_csv_returns_2(tmp_path):
    """Nonexistent --mock-samples-csv path must yield exit 2."""
    r = _run([], csv_path=tmp_path / "does-not-exist.csv")
    assert r.returncode == 2, f"got rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_exit_code_pass_is_zero(tmp_path):
    samples = _gen_pulses(50_000.0, [], pulse_width_us=26.0, step_us=10.0)
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, samples)
    r = _run([], csv_path=csv_path)
    assert r.returncode == 0


def test_exit_code_fail_is_one(tmp_path):
    centres = [(i + 1) * 5_000.0 - 2_500.0 for i in range(10)]
    samples = _gen_pulses(50_000.0, centres, pulse_width_us=26.0, step_us=1.0)
    csv_path = tmp_path / "f.csv"
    _write_csv(csv_path, samples)
    r = _run(["--period-ms", "5"], csv_path=csv_path)
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# v0.65.1 — --expect present flag (positive verification)
# ---------------------------------------------------------------------------
def test_expect_present_passes_on_periodic_pulses(tmp_path):
    """--expect present: 10 periodic 5-ms-apart pulses → PASS (pattern
    IS there, as spec'd). Same CSV shape the default absent-mode would
    FAIL on — just flipped interpretation."""
    centres = [(i + 1) * 5_000.0 - 2_500.0 for i in range(10)]
    samples = _gen_pulses(50_000.0, centres, pulse_width_us=26.0, step_us=1.0)
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, samples)
    r = _run(["--expect", "present", "--period-ms", "5"], csv_path=csv_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "periodic pattern confirmed" in r.stdout


def test_expect_present_fails_on_empty_window(tmp_path):
    """--expect present + 0 pulses → FAIL (expected pattern missing)."""
    samples = _gen_pulses(50_000.0, [], pulse_width_us=26.0, step_us=10.0)
    csv_path = tmp_path / "empty.csv"
    _write_csv(csv_path, samples)
    r = _run(["--expect", "present", "--period-ms", "5"], csv_path=csv_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout
    assert "expected periodic pattern MISSING" in r.stdout


def test_expect_present_min_periodic_threshold(tmp_path):
    """--expect present --min-periodic 5: if only 3 consecutive
    periodic gaps exist (4 pulses), FAIL because need ≥ 5."""
    centres = [5_000.0, 10_000.0, 15_000.0, 20_000.0]  # 4 pulses, 3 gaps
    samples = _gen_pulses(50_000.0, centres, pulse_width_us=26.0, step_us=1.0)
    csv_path = tmp_path / "few.csv"
    _write_csv(csv_path, samples)
    r = _run(
        ["--expect", "present", "--period-ms", "5", "--min-periodic", "5"],
        csv_path=csv_path,
    )
    assert r.returncode == 1
    assert "only 3 consecutive" in r.stdout


def test_expect_default_is_absent(tmp_path):
    """No --expect flag → default behaviour (absent) preserved."""
    centres = [(i + 1) * 5_000.0 - 2_500.0 for i in range(10)]
    samples = _gen_pulses(50_000.0, centres, pulse_width_us=26.0, step_us=1.0)
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, samples)
    r = _run(["--period-ms", "5"], csv_path=csv_path)  # no --expect
    assert r.returncode == 1                              # legacy: periodic pattern = FAIL
    assert "forbidden periodic pattern present" in r.stdout


def test_expect_flag_surfaces_in_verdict_line(tmp_path):
    """Verdict line includes the --expect value so log readers can tell
    which semantic was in play."""
    samples = _gen_pulses(50_000.0, [], pulse_width_us=26.0, step_us=10.0)
    csv_path = tmp_path / "empty.csv"
    _write_csv(csv_path, samples)
    r = _run(["--expect", "absent"], csv_path=csv_path)
    assert "[--expect absent]" in r.stdout
    r2 = _run(["--expect", "present", "--period-ms", "5"], csv_path=csv_path)
    assert "[--expect present]" in r2.stdout
