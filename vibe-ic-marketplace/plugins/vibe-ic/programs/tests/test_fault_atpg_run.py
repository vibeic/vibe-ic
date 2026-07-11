"""Unit tests for fault_atpg_run.py.

Fault runs inside a Docker container so the heavy integration path cannot
be unit-tested without the image. These tests cover:
  - Argument parsing and PDK config validation
  - IO-error handling (missing project dir, missing netlist, bad pdk)

Full end-to-end Fault-in-Docker run is validated by the aon_timer pilot
(see reports/dft/coverage.json); no need to re-run in unit tests.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fault_atpg_run.py"
assert SCRIPT.exists()


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_missing_project_dir(tmp_path):
    r = _run(str(tmp_path / "nope"), "--clock", "clk")
    assert r.returncode == 2
    assert "not a directory" in r.stderr.lower()


def test_missing_netlist(tmp_path):
    r = _run(str(tmp_path), "--netlist", "synth/missing.v", "--clock", "clk")
    assert r.returncode == 2
    assert "netlist not found" in r.stderr.lower()


def test_unsupported_pdk(tmp_path):
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "synth" / "netlist.v").write_text("module top; endmodule\n")
    r = _run(str(tmp_path), "--clock", "clk", "--pdk", "nonexistent_pdk")
    # Program imports fine and gets to run_fault which returns exit 2 for bad pdk
    assert r.returncode in (1, 2)


def test_clock_arg_required(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode != 0
    assert "clock" in r.stderr.lower() or "required" in r.stderr.lower()


# --- image-resolution pinning ------------------------------------------------
# The fork fallback tags must be PINNED (vibeic-eda:X.Y.Z), never :latest — a
# floating tag can silently resolve to a stale local image whose tool behavior
# no longer matches what the plugin was verified against. The pinned value is
# kept in sync with tools/vibeic-eda/VERSION by sync_image_version.py (this
# file is registered in its INSTALL_DOC_CANDIDATES).

def _find_version_file():
    for up in Path(__file__).resolve().parents:
        c = up / "tools" / "vibeic-eda" / "VERSION"
        if c.is_file():
            return c
    return None


def test_no_floating_fork_image_tag():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "vibeic-eda:latest" not in src, (
        "fork image fallback must be pinned to vibeic-eda:X.Y.Z, not :latest"
    )
    # the pinned fork tags must still be present (resolver not gutted)
    assert re.search(r"ghcr\.io/vibeic/vibeic-eda:\d+\.\d+\.\d+", src)


def test_pinned_tag_matches_version_source_of_truth():
    vf = _find_version_file()
    if vf is None:
        pytest.skip("tools/vibeic-eda/VERSION not present (packaged plugin)")
    version = vf.read_text(encoding="utf-8").strip()
    src = SCRIPT.read_text(encoding="utf-8")
    tags = re.findall(r"vibeic-eda:(\d+\.\d+\.\d+)", src)
    assert tags, "expected pinned vibeic-eda:X.Y.Z tags in fault_atpg_run.py"
    assert set(tags) == {version}, (
        f"pinned tags {sorted(set(tags))} drifted from VERSION={version}; "
        "run tools/vibeic-eda/sync_image_version.py --set/--bump"
    )


def test_env_override_wins_over_pinned_candidates():
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); "
         "import fault_atpg_run as f; print(f.DOCKER_IMAGE)",
         str(SCRIPT.parent)],
        capture_output=True, text=True,
        env={**os.environ, "VIBEIC_EDA_IMAGE": "example/override:9.9.9"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "example/override:9.9.9"
