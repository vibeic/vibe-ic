"""Tests for clock_scale_consistency_check.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

SCRIPT = Path(__file__).parent.parent / "clock_scale_consistency_check.py"
assert SCRIPT.exists()


def _run(*args):
    return _pr.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


def _write(tmp: Path, data):
    p = tmp / "consts.json"
    p.write_text(json.dumps(data))
    return p


def test_missing_clock_fields_fails(tmp_path):
    f = _write(tmp_path, {
        "rx_thresholds": [
            {"name": "H1_MIN", "value": 1, "unit": "ticks"},
        ]
    })
    r = _run(str(f))
    assert r.returncode == 1


def test_same_domain_no_scale_needed(tmp_path):
    f = _write(tmp_path, {
        "rx_thresholds": [
            {"name": "H1_MIN", "value": 1, "unit": "ticks",
             "domain_clock": "sys_clk_2p5m",
             "source_clock": "sys_clk_2p5m"},
        ]
    })
    r = _run(str(f))
    assert r.returncode == 0


def test_different_clocks_missing_scale_factor_fails(tmp_path):
    f = _write(tmp_path, {
        "t": [{"name": "X", "value": 5, "unit": "ticks",
               "domain_clock": "clk_a", "source_clock": "clk_b"}]
    })
    r = _run(str(f))
    assert r.returncode == 1


def test_wrong_scale_factor_detected(tmp_path):
    f = _write(tmp_path, {
        "t": [{"name": "X", "value": 5, "unit": "ticks",
               "domain_clock": "clk_a", "source_clock": "clk_b",
               "scale_factor": 10}]
    })
    clocks = tmp_path / "clocks.json"
    clocks.write_text(json.dumps({"clk_a": 2_500_000, "clk_b": 50_000_000}))
    # True scale = 50M/2.5M = 20, claimed 10 → fail
    r = _run(str(f), "--clocks", str(clocks))
    assert r.returncode == 1


def test_correct_scale_passes(tmp_path):
    f = _write(tmp_path, {
        "t": [{"name": "H1_MIN", "value": 4, "unit": "ticks",
               "domain_clock": "clk_25", "source_clock": "clk_50",
               "scale_factor": 20,
               "physical_value_us": 1.6}]
    })
    clocks = tmp_path / "clocks.json"
    clocks.write_text(json.dumps({"clk_25": 2_500_000, "clk_50": 50_000_000}))
    r = _run(str(f), "--clocks", str(clocks))
    assert r.returncode == 0


def test_physical_value_mismatch_detected(tmp_path):
    """Classic IC-A bug: value=192 ticks at 2.5MHz = 76.8us but claim 1.6us."""
    f = _write(tmp_path, {
        "t": [{"name": "H1_MAX", "value": 192, "unit": "ticks",
               "domain_clock": "clk_25", "source_clock": "clk_25",
               "physical_value_us": 1.6}]
    })
    clocks = tmp_path / "clocks.json"
    clocks.write_text(json.dumps({"clk_25": 2_500_000}))
    r = _run(str(f), "--clocks", str(clocks))
    assert r.returncode == 1
    assert "20x-scale class bug" in (r.stdout + r.stderr) or "physical-value-mismatch" in (r.stdout + r.stderr)
