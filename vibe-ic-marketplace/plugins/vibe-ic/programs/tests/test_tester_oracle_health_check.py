"""Unit tests for tester_oracle_health_check.py.

Covers both PASS and FAIL paths plus config-schema errors. Subprocess
execution is exercised via a tiny python helper fixture so we stay in
stdlib and independent of the host tester toolchain.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tester_oracle_health_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import tester_oracle_health_check as chk  # noqa: E402


def _run(args, **kwargs):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, **kwargs,
    )


# ---------------------------------------------------------------------------
# --help must work
# ---------------------------------------------------------------------------
def test_help_works():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "tester oracle" in r.stdout.lower() or "oracle" in r.stdout.lower()


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
def test_missing_config_exits_2(tmp_path):
    r = _run(["--config", str(tmp_path / "no-such.json")])
    assert r.returncode == 2


def test_invalid_json_exits_2(tmp_path):
    cfg = tmp_path / "oracle.json"
    cfg.write_text("not valid json {")
    r = _run(["--config", str(cfg)])
    assert r.returncode == 2


def test_missing_required_key_exits_2(tmp_path):
    cfg = tmp_path / "oracle.json"
    cfg.write_text(json.dumps({
        "known_good_sof": "a.sof",
        "burn_command": "echo {sof}",
        # tester_command missing
        "pass_fingerprint": "OK",
        "fail_fingerprint": "FAIL",
    }))
    r = _run(["--config", str(cfg)])
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------
def _good_config(tmp_path: Path, pass_fp="OK", fail_fp="FAIL",
                 burn_cmd="true {sof}", tester_cmd="true") -> Path:
    cfg = tmp_path / "oracle.json"
    cfg.write_text(json.dumps({
        "known_good_sof": str(tmp_path / "known.sof"),
        "burn_command": burn_cmd,
        "tester_command": tester_cmd,
        "pass_fingerprint": pass_fp,
        "fail_fingerprint": fail_fp,
        "timeout_seconds": 10,
    }))
    return cfg


def test_dry_run_passes_with_valid_config(tmp_path):
    cfg = _good_config(tmp_path)
    r = _run(["--config", str(cfg), "--dry-run"])
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# PASS path — real subprocess returns the PASS fingerprint
# ---------------------------------------------------------------------------
def test_oracle_returns_pass_fingerprint(tmp_path):
    # burn_command: `true` (always succeeds)
    # tester_command: python prints "byte[6]=0xF2"
    printer = tmp_path / "print_pass.py"
    printer.write_text("print('byte[6]=0xF2')\n")
    cfg = _good_config(
        tmp_path,
        pass_fp=r"byte\[6\]=0xF2",
        fail_fp=r"byte\[6\]=0x02",
        burn_cmd="true {sof}",
        tester_cmd=f"{sys.executable} {printer}",
    )
    r = _run(["--config", str(cfg)])
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["summary"]["pass"] is True
    assert any(f["category"] == "ORACLE_PASS" for f in out["findings"])


# ---------------------------------------------------------------------------
# FAIL path — oracle returns FAIL fingerprint on known-good SOF
# ---------------------------------------------------------------------------
def test_oracle_returns_fail_fingerprint_exits_1(tmp_path):
    printer = tmp_path / "print_fail.py"
    printer.write_text("print('byte[6]=0x02')\n")
    cfg = _good_config(
        tmp_path,
        pass_fp=r"byte\[6\]=0xF2",
        fail_fp=r"byte\[6\]=0x02",
        burn_cmd="true {sof}",
        tester_cmd=f"{sys.executable} {printer}",
    )
    r = _run(["--config", str(cfg)])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["summary"]["pass"] is False
    cats = [f["category"] for f in out["findings"]]
    assert "ORACLE_BROKEN" in cats


# ---------------------------------------------------------------------------
# Unknown response
# ---------------------------------------------------------------------------
def test_oracle_unknown_response_exits_1(tmp_path):
    printer = tmp_path / "print_unknown.py"
    printer.write_text("print('somehting-else=0xAA')\n")
    cfg = _good_config(
        tmp_path,
        pass_fp=r"byte\[6\]=0xF2",
        fail_fp=r"byte\[6\]=0x02",
        burn_cmd="true {sof}",
        tester_cmd=f"{sys.executable} {printer}",
    )
    r = _run(["--config", str(cfg)])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    cats = [f["category"] for f in out["findings"]]
    assert "UNKNOWN_RESPONSE" in cats


# ---------------------------------------------------------------------------
# Burn failure surfaces
# ---------------------------------------------------------------------------
def test_burn_nonzero_exit_is_flagged(tmp_path):
    cfg = _good_config(
        tmp_path,
        burn_cmd="false",    # always exits 1
        tester_cmd="true",
    )
    r = _run(["--config", str(cfg)])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    cats = [f["category"] for f in out["findings"]]
    assert "BURN_FAIL" in cats


# ---------------------------------------------------------------------------
# --json report is written
# ---------------------------------------------------------------------------
def test_json_report_written(tmp_path):
    cfg = _good_config(tmp_path)
    out_json = tmp_path / "out.json"
    r = _run(["--config", str(cfg), "--dry-run", "--json", str(out_json)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out_json.exists()
    data = json.loads(out_json.read_text())
    assert data["program"] == "tester_oracle_health_check"
