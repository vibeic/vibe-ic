"""Tests for scope_waveform_metrics.py.

Synthetic captures with KNOWN metrics:

  * A clean RC-style step (rising edge → settle) with a controllable
    overshoot for dc_level / rise_time / settling_time / overshoot.
  * A pure sine with a known frequency for freq / jitter.

All CSVs are written to tmp_path; no scope or third-party library is needed.
The bad-fixture cases (too-short, flat / no-edge, non-periodic) prove the
no-false-alert / graceful-degradation contract.
"""
from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "scope_waveform_metrics.py"


# ---------------------------------------------------------------------------
# CSV synthesisers
# ---------------------------------------------------------------------------
def _write_csv(path: Path, samples, header=("time", "voltage")):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        if header:
            w.writerow(header)
        for t, v in samples:
            w.writerow([f"{t:.9g}", f"{v:.9g}"])


def _gen_step(span_s=1.0e-3, n=2001, base=0.0, final=1.8,
              edge_frac=0.10, tau_frac=0.01, overshoot_frac=0.0):
    """Step response, first-order (no overshoot) or second-order (overshoot).

    Idle at ``base`` until ``edge_frac`` of the window. With
    ``overshoot_frac == 0`` it is a clean first-order ``1 - e^-x`` rise.
    With ``overshoot_frac > 0`` it is an under-damped second-order response
    whose first peak exceeds ``final`` by ~``overshoot_frac`` and which then
    rings down to ``final`` — so dc_level (tail mean) is still ``final``.
    """
    dt = span_s / (n - 1)
    edge_t = span_s * edge_frac
    tau = span_s * tau_frac
    step = final - base
    samples = []
    for i in range(n):
        t = i * dt
        if t < edge_t:
            v = base
        elif overshoot_frac <= 0:
            x = (t - edge_t) / tau
            v = base + step * (1.0 - math.exp(-x))
        else:
            # Second-order under-damped: y = final - step*e^{-z*wn*t}*
            # (cos wd t + (z/sqrt(1-z^2)) sin wd t). First peak overshoot
            # = exp(-pi*z/sqrt(1-z^2)). Pick z to hit overshoot_frac.
            z = -math.log(overshoot_frac) / math.sqrt(
                math.pi ** 2 + math.log(overshoot_frac) ** 2)
            wn = 1.0 / tau
            wd = wn * math.sqrt(1.0 - z * z)
            tt = t - edge_t
            env = math.exp(-z * wn * tt)
            v = base + step * (1.0 - env * (
                math.cos(wd * tt)
                + (z / math.sqrt(1.0 - z * z)) * math.sin(wd * tt)))
        samples.append((t, v))
    return samples


def _gen_sine(freq=1.0e6, span_s=1.0e-5, n=2001, amp=1.0, offset=1.5):
    """Pure sine: offset + amp*sin(2*pi*f*t). 10 cycles over 1e-5 s @ 1 MHz."""
    dt = span_s / (n - 1)
    samples = []
    for i in range(n):
        t = i * dt
        v = offset + amp * math.sin(2.0 * math.pi * freq * t)
        samples.append((t, v))
    return samples


def _run(csv_path, extra=None):
    cmd = [sys.executable, str(PROG), str(csv_path)]
    if extra:
        cmd += list(extra)
    return subprocess.run(cmd, capture_output=True, text=True)


def _load_json(path: Path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------------------
# Basic CLI
# ---------------------------------------------------------------------------
def test_help_does_not_crash():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout.lower()
    assert "scope" in out
    assert "--spec" in r.stdout
    assert "dc" in out and "rise" in out and "jitter" in out


# ---------------------------------------------------------------------------
# Step waveform — dc_level / rise_time / settling_time / overshoot
# ---------------------------------------------------------------------------
def test_step_dc_level_known(tmp_path):
    """Final value 1.8 V → dc_level (mean of last 20%) ≈ 1.8."""
    samples = _gen_step(final=1.8)
    p = tmp_path / "step.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    r = _run(p, ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    res = _load_json(out)
    assert abs(res["metrics"]["dc_level"] - 1.8) < 0.01


def test_step_rise_time_positive_and_reasonable(tmp_path):
    """A fast tau gives a small positive 10-90% rise time (< window)."""
    samples = _gen_step(span_s=1.0e-3, final=1.8, tau_frac=0.01)
    p = tmp_path / "step.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    r = _run(p, ["--json", str(out)])
    rt = _load_json(out)["metrics"]["rise_time"]
    assert rt is not None
    # 10-90% of a first-order step is ln(9)*tau ≈ 2.197*tau; tau = 1e-5 s.
    expected = math.log(9) * 1.0e-5
    assert abs(rt - expected) < 0.2 * expected, f"rise={rt} expected≈{expected}"


def test_step_settling_time_present(tmp_path):
    """A clean settling step reaches and stays within ±2% → finite settle."""
    samples = _gen_step(final=1.8, tau_frac=0.01)
    p = tmp_path / "step.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    _run(p, ["--json", str(out)])
    st = _load_json(out)["metrics"]["settling_time"]
    assert st is not None and st > 0


def test_step_overshoot_known(tmp_path):
    """~10% overshoot bump → overshoot metric near 10%."""
    samples = _gen_step(final=1.8, tau_frac=0.02, overshoot_frac=0.10)
    p = tmp_path / "os.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    _run(p, ["--json", str(out)])
    ov = _load_json(out)["metrics"]["overshoot"]
    assert ov is not None
    assert 3.0 < ov < 12.0, f"overshoot={ov}"


def test_step_no_overshoot_near_zero(tmp_path):
    """Monotonic step (no overshoot) → overshoot ≈ 0 (peak == final)."""
    samples = _gen_step(final=1.8, tau_frac=0.01, overshoot_frac=0.0)
    p = tmp_path / "mono.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    _run(p, ["--json", str(out)])
    ov = _load_json(out)["metrics"]["overshoot"]
    assert ov is not None and ov < 0.5


# ---------------------------------------------------------------------------
# Sine waveform — freq / jitter
# ---------------------------------------------------------------------------
def test_sine_frequency_known(tmp_path):
    """1 MHz sine over 10 cycles → freq metric ≈ 1e6."""
    samples = _gen_sine(freq=1.0e6, span_s=1.0e-5, n=4001)
    p = tmp_path / "sine.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    r = _run(p, ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    freq = _load_json(out)["metrics"]["freq"]
    assert freq is not None
    assert abs(freq - 1.0e6) < 0.02e6, f"freq={freq}"


def test_sine_jitter_small_for_clean_sine(tmp_path):
    """An ideal sine has near-zero period jitter."""
    samples = _gen_sine(freq=1.0e6, span_s=1.0e-5, n=8001)
    p = tmp_path / "sine.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    _run(p, ["--json", str(out)])
    jit = _load_json(out)["metrics"]["jitter"]
    assert jit is not None
    # jitter should be a tiny fraction of the 1 µs period.
    assert jit < 0.05e-6, f"jitter={jit}"


def test_sine_offset_does_not_break_frequency(tmp_path):
    """A large DC offset must not change frequency (mean-crossing based)."""
    samples = _gen_sine(freq=2.0e6, span_s=1.0e-5, n=8001, offset=5.0)
    p = tmp_path / "sineoff.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    _run(p, ["--json", str(out)])
    freq = _load_json(out)["metrics"]["freq"]
    assert freq is not None and abs(freq - 2.0e6) < 0.05e6


# ---------------------------------------------------------------------------
# Spec grading — PASS / FAIL / SKIP
# ---------------------------------------------------------------------------
def test_spec_pass(tmp_path):
    samples = _gen_step(final=1.8, tau_frac=0.01)
    p = tmp_path / "step.csv"
    _write_csv(p, samples)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "dc_level": {"min": 1.75, "max": 1.85, "unit": "V"},
    }))
    r = _run(p, ["--spec", str(spec)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VERDICT: PASS" in r.stdout
    assert "[PASS] dc_level" in r.stdout


def test_spec_fail(tmp_path):
    samples = _gen_step(final=1.8, tau_frac=0.01)
    p = tmp_path / "step.csv"
    _write_csv(p, samples)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "dc_level": {"min": 3.0, "max": 3.5, "unit": "V"},  # 1.8 < 3.0
    }))
    r = _run(p, ["--spec", str(spec)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VERDICT: FAIL" in r.stdout
    assert "[FAIL] dc_level" in r.stdout


def test_spec_on_missing_metric_is_skip_not_fail(tmp_path):
    """A flat (no-edge) capture has null rise_time; a rise_time spec must
    grade SKIP, never a false FAIL."""
    # Flat line: enough samples, but no rising edge → rise_time MISSING.
    samples = [(i * 1e-6, 1.8) for i in range(200)]
    p = tmp_path / "flat.csv"
    _write_csv(p, samples)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "rise_time": {"max": 5e-6, "unit": "s"},
    }))
    r = _run(p, ["--spec", str(spec)])
    assert r.returncode == 0, r.stdout + r.stderr  # no FAIL
    assert "[SKIP] rise_time" in r.stdout


# ---------------------------------------------------------------------------
# Graceful degradation / no-false-alert
# ---------------------------------------------------------------------------
def test_too_short_capture_all_skipped(tmp_path):
    """Below the length floor → all metrics MISSING, exit 0, no FAIL."""
    samples = [(i * 1e-6, float(i)) for i in range(4)]  # 4 < default 8
    p = tmp_path / "tiny.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    r = _run(p, ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    res = _load_json(out)
    assert res["too_short"] is True
    assert all(res["metrics"][k] is None for k in res["metrics"])
    assert any("too short" in n.lower() for n in res["notes"])


def test_too_short_with_spec_does_not_fail(tmp_path):
    """Short capture + spec → no grading, exit 0 (no false FAIL)."""
    samples = [(i * 1e-6, float(i)) for i in range(4)]
    p = tmp_path / "tiny.csv"
    _write_csv(p, samples)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"dc_level": {"min": 99.0, "max": 100.0}}))
    r = _run(p, ["--spec", str(spec)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_flat_waveform_no_edge_freq_missing(tmp_path):
    """A DC line is not periodic → freq/jitter MISSING, no crash."""
    samples = [(i * 1e-6, 1.8) for i in range(500)]
    p = tmp_path / "dc.csv"
    _write_csv(p, samples)
    out = tmp_path / "m.json"
    r = _run(p, ["--json", str(out)])
    assert r.returncode == 0
    res = _load_json(out)
    assert res["metrics"]["freq"] is None
    assert res["metrics"]["jitter"] is None
    assert res["metrics"]["dc_level"] is not None  # DC still measurable


def test_missing_csv_returns_2(tmp_path):
    r = _run(tmp_path / "nope.csv")
    assert r.returncode == 2


def test_empty_csv_returns_2(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("time,voltage\n")
    r = _run(p)
    assert r.returncode == 2


def test_garbage_rows_dropped_gracefully(tmp_path):
    """Junk rows are skipped, not fatal — capture degrades gracefully."""
    p = tmp_path / "dirty.csv"
    rows = ["time,voltage"]
    for i in range(200):
        if i % 25 == 0:
            rows.append("###,broken")  # junk
        else:
            t = i * 1e-6
            v = 0.0 if t < 50e-6 else 1.8
            rows.append(f"{t:.9g},{v}")
    p.write_text("\n".join(rows) + "\n")
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MISSING" in r.stdout or "dc_level" in r.stdout


def test_no_header_csv(tmp_path):
    """Headerless numeric CSV still parses (first row is data)."""
    samples = _gen_step(final=1.8)
    p = tmp_path / "noheader.csv"
    _write_csv(p, samples, header=None)
    out = tmp_path / "m.json"
    r = _run(p, ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert _load_json(out)["metrics"]["dc_level"] is not None


def test_bad_spec_json_returns_2(tmp_path):
    samples = _gen_step(final=1.8)
    p = tmp_path / "step.csv"
    _write_csv(p, samples)
    spec = tmp_path / "spec.json"
    spec.write_text("{not valid json")
    r = _run(p, ["--spec", str(spec)])
    assert r.returncode == 2


def test_deterministic_same_input_same_output(tmp_path):
    """Two runs on the same CSV produce identical metric JSON."""
    samples = _gen_step(final=1.8, tau_frac=0.01, overshoot_frac=0.1)
    p = tmp_path / "step.csv"
    _write_csv(p, samples)
    o1 = tmp_path / "a.json"
    o2 = tmp_path / "b.json"
    _run(p, ["--json", str(o1)])
    _run(p, ["--json", str(o2)])
    assert _load_json(o1)["metrics"] == _load_json(o2)["metrics"]
