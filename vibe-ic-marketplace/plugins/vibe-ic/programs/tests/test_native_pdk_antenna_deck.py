"""A PDK native antenna rule must be measured on the delivered GDS."""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import eda_report_audit as audit  # noqa: E402
import _klayout_launch as launch  # noqa: E402


def test_real_native_rdb_calibration_pair():
    samples = PROGRAMS / "calibration"
    dirty = (samples / "native_antenna_violation.lyrdb").read_text()
    clean = (samples / "native_antenna_clean.lyrdb").read_text()
    assert audit._antenna_klayout_count(dirty) == 1
    assert audit._antenna_klayout_count(clean) == 0
    assert "Executing rule ANT.1" in (samples / "native_antenna_violation.log").read_text()
    assert "Executing rule ANT.1" in (samples / "native_antenna_clean.log").read_text()


def test_host_native_runner_enforces_memory_and_keeps_progressing():
    runner = launch.HostRunner(sys.executable, ())
    cmd = [sys.executable, "-c", (
        "import resource,time\n"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0], flush=True)\n"
        "end=time.monotonic()+0.8\n"
        "while time.monotonic()<end: pass\n"
    )]
    result = runner.run_argv_supervised(
        cmd, {}, stall_grace_s=0.3, memory_limit_mb=256)
    assert result.outcome == "natural", result
    assert result.rc == 0, result
    assert result.elapsed_s > 0.3
    assert result.out.strip() == str(256 * 1024 * 1024)
