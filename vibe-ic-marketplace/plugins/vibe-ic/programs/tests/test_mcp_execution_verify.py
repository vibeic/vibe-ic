"""Unit tests for mcp_execution_verify.py.

Tests verify correct detection of MCP tool execution via JSONL manifest,
including happy path, missing steps, FAIL status, stale entries, empty/missing
manifests, duplicate entries, partial matching, and case insensitivity.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "mcp_execution_verify.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import mcp_execution_verify as mev  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_ago: float = 2.0) -> str:
    """Generate an ISO 8601 timestamp `hours_ago` hours before _now()."""
    dt = _now() - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _real_ts(hours_ago: float = 1.0) -> str:
    """Generate an ISO 8601 timestamp `hours_ago` hours before REAL wall-clock now.

    Use this in CLI tests that invoke `mev.main()`, which always reads the real
    clock and would otherwise reject a fixed _now()-based timestamp as stale
    after 168 hours. Unit tests that pass `now=_now()` should keep using `_ts`.
    """
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_manifest(tmp_path: Path, entries: list) -> Path:
    """Write JSONL manifest to a temp file."""
    manifest = tmp_path / "latest_results.jsonl"
    lines = [json.dumps(e) for e in entries]
    manifest.write_text("\n".join(lines) + "\n")
    return manifest


# ---------------------------------------------------------------------------
# Test 1: All steps PASS (happy path)
# ---------------------------------------------------------------------------
def test_all_steps_pass(tmp_path):
    entries = [
        {"timestamp": _ts(2), "step": "synthesis", "status": "PASS", "tool": "Yosys", "cells": 2827},
        {"timestamp": _ts(1.5), "step": "sta", "status": "PASS", "tool": "OpenSTA"},
        {"timestamp": _ts(1), "step": "pnr", "status": "PASS", "tool": "OpenROAD"},
        {"timestamp": _ts(0.5), "step": "gds", "status": "PASS", "tool": "KLayout"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["synthesis", "sta", "pnr", "gds"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis", "sta", "pnr", "gds"], results)

    assert report["summary"]["verdict"] == "PASS"
    assert report["summary"]["found_pass"] == 4
    assert report["summary"]["not_found"] == 0
    assert report["summary"]["found_fail"] == 0
    assert report["summary"]["stale"] == 0


# ---------------------------------------------------------------------------
# Test 2: Missing step -> FAIL
# ---------------------------------------------------------------------------
def test_missing_step_fail(tmp_path):
    entries = [
        {"timestamp": _ts(2), "step": "synthesis", "status": "PASS", "tool": "Yosys"},
        {"timestamp": _ts(1), "step": "sta", "status": "PASS", "tool": "OpenSTA"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["synthesis", "sta", "pnr"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis", "sta", "pnr"], results)

    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["not_found"] == 1
    # Check the missing step is pnr
    pnr_result = next(r for r in report["results"] if r["step"] == "pnr")
    assert pnr_result["status"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Test 3: Step with status FAIL -> FAIL
# ---------------------------------------------------------------------------
def test_step_with_fail_status(tmp_path):
    entries = [
        {"timestamp": _ts(2), "step": "synthesis", "status": "PASS", "tool": "Yosys"},
        {"timestamp": _ts(1), "step": "sta", "status": "FAIL", "tool": "OpenSTA"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["synthesis", "sta"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis", "sta"], results)

    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["found_fail"] == 1
    sta_result = next(r for r in report["results"] if r["step"] == "sta")
    assert sta_result["status"] == "FOUND_FAIL"


# ---------------------------------------------------------------------------
# Test 4: Stale entry (old timestamp) -> STALE
# ---------------------------------------------------------------------------
def test_stale_entry(tmp_path):
    entries = [
        {"timestamp": _ts(200), "step": "synthesis", "status": "PASS", "tool": "Yosys"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    # max_age_hours=168 (1 week), entry is 200 hours old
    results = mev.verify_steps(parsed, ["synthesis"], max_age_hours=168, now=_now())
    report = mev.build_report(str(manifest), ["synthesis"], results)

    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["stale"] == 1
    synth_result = report["results"][0]
    assert synth_result["status"] == "STALE"
    assert synth_result["age_hours"] == 200.0


# ---------------------------------------------------------------------------
# Test 5: Manifest file missing -> all NOT_FOUND
# ---------------------------------------------------------------------------
def test_manifest_missing(tmp_path):
    missing = tmp_path / "nonexistent.jsonl"

    parsed = mev.parse_manifest(missing)
    assert parsed == []

    results = mev.verify_steps(parsed, ["synthesis", "sta"], now=_now())
    report = mev.build_report(str(missing), ["synthesis", "sta"], results)

    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["not_found"] == 2
    assert report["summary"]["total_required"] == 2


# ---------------------------------------------------------------------------
# Test 6: Empty manifest -> all NOT_FOUND
# ---------------------------------------------------------------------------
def test_empty_manifest(tmp_path):
    manifest = tmp_path / "latest_results.jsonl"
    manifest.write_text("")

    parsed = mev.parse_manifest(manifest)
    assert parsed == []

    results = mev.verify_steps(parsed, ["synthesis"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis"], results)

    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["not_found"] == 1


# ---------------------------------------------------------------------------
# Test 7: Multiple entries for same step -> use latest
# ---------------------------------------------------------------------------
def test_multiple_entries_uses_latest(tmp_path):
    entries = [
        {"timestamp": _ts(10), "step": "synthesis", "status": "FAIL", "tool": "Yosys"},
        {"timestamp": _ts(2), "step": "synthesis", "status": "PASS", "tool": "Yosys"},
        {"timestamp": _ts(5), "step": "synthesis", "status": "FAIL", "tool": "Yosys"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["synthesis"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis"], results)

    # Latest entry (2 hours ago) has status PASS
    assert report["summary"]["verdict"] == "PASS"
    assert report["summary"]["found_pass"] == 1
    synth_result = report["results"][0]
    assert synth_result["status"] == "FOUND_PASS"
    assert synth_result["age_hours"] == 2.0


# ---------------------------------------------------------------------------
# Test 8: Partial step name match ("synth" matches "synthesis")
# ---------------------------------------------------------------------------
def test_partial_step_name_match(tmp_path):
    entries = [
        {"timestamp": _ts(2), "step": "synthesis", "status": "PASS", "tool": "Yosys"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["synth"], now=_now())
    report = mev.build_report(str(manifest), ["synth"], results)

    assert report["summary"]["verdict"] == "PASS"
    assert report["summary"]["found_pass"] == 1


# ---------------------------------------------------------------------------
# Test 9: Case insensitive matching
# ---------------------------------------------------------------------------
def test_case_insensitive_matching(tmp_path):
    entries = [
        {"timestamp": _ts(2), "step": "Synthesis", "status": "PASS", "tool": "Yosys"},
        {"timestamp": _ts(1), "step": "STA", "status": "PASS", "tool": "OpenSTA"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["synthesis", "sta"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis", "sta"], results)

    assert report["summary"]["verdict"] == "PASS"
    assert report["summary"]["found_pass"] == 2


# ---------------------------------------------------------------------------
# Test 10: Single step required
# ---------------------------------------------------------------------------
def test_single_step_required(tmp_path):
    entries = [
        {"timestamp": _ts(1), "step": "lint", "status": "PASS", "tool": "Verilator"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["lint"], now=_now())
    report = mev.build_report(str(manifest), ["lint"], results)

    assert report["summary"]["verdict"] == "PASS"
    assert report["summary"]["total_required"] == 1
    assert report["summary"]["found_pass"] == 1


# ---------------------------------------------------------------------------
# Test 11: CLI exit code 0 on PASS
# ---------------------------------------------------------------------------
def test_cli_exit_code_pass(tmp_path):
    entries = [
        {"timestamp": _real_ts(2), "step": "synthesis", "status": "PASS", "tool": "Yosys"},
        {"timestamp": _real_ts(1), "step": "sta", "status": "PASS", "tool": "OpenSTA"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    rc = mev.main([
        "--manifest", str(manifest),
        "--require-steps", "synthesis,sta",
    ])
    assert rc == 0


# ---------------------------------------------------------------------------
# Test 12: CLI exit code 1 on FAIL
# ---------------------------------------------------------------------------
def test_cli_exit_code_fail(tmp_path):
    entries = [
        {"timestamp": _real_ts(2), "step": "synthesis", "status": "PASS", "tool": "Yosys"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    rc = mev.main([
        "--manifest", str(manifest),
        "--require-steps", "synthesis,sta,pnr",
    ])
    assert rc == 1


# ---------------------------------------------------------------------------
# Test 13: CLI --out-dir creates report file
# ---------------------------------------------------------------------------
def test_cli_out_dir(tmp_path):
    entries = [
        {"timestamp": _real_ts(1), "step": "drc", "status": "PASS", "tool": "Magic"},
    ]
    manifest = _write_manifest(tmp_path, entries)
    out_dir = tmp_path / "output"

    rc = mev.main([
        "--manifest", str(manifest),
        "--require-steps", "drc",
        "--out-dir", str(out_dir),
    ])
    assert rc == 0

    report_file = out_dir / "mcp_execution_verify_report.json"
    assert report_file.exists()
    report = json.loads(report_file.read_text())
    assert report["summary"]["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Test 14: Unknown status treated as FAIL
# ---------------------------------------------------------------------------
def test_unknown_status_treated_as_fail(tmp_path):
    entries = [
        {"timestamp": _ts(1), "step": "synthesis", "status": "UNKNOWN", "tool": "Yosys"},
    ]
    manifest = _write_manifest(tmp_path, entries)

    parsed = mev.parse_manifest(manifest)
    results = mev.verify_steps(parsed, ["synthesis"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis"], results)

    assert report["summary"]["verdict"] == "FAIL"
    assert report["summary"]["found_fail"] == 1


# ---------------------------------------------------------------------------
# Test 15: Malformed JSONL lines are skipped
# ---------------------------------------------------------------------------
def test_malformed_jsonl_skipped(tmp_path):
    manifest = tmp_path / "latest_results.jsonl"
    lines = [
        "this is not json",
        json.dumps({"timestamp": _ts(1), "step": "synthesis", "status": "PASS", "tool": "Yosys"}),
        "{bad json",
    ]
    manifest.write_text("\n".join(lines) + "\n")

    parsed = mev.parse_manifest(manifest)
    assert len(parsed) == 1

    results = mev.verify_steps(parsed, ["synthesis"], now=_now())
    report = mev.build_report(str(manifest), ["synthesis"], results)

    assert report["summary"]["verdict"] == "PASS"
