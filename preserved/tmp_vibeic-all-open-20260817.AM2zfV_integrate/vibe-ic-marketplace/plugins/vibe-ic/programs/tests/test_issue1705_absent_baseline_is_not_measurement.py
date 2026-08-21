#!/usr/bin/env python3
"""vibe-ic#1705 — a ratchet cannot compare against a baseline it never read.

Both audits below derive their verdict from ``current - baseline``.  The
load-bearing distinction is therefore between an explicitly measured empty
set and no measurement at all:

* absent / unreadable / truncated baseline -> rc 2, NOT CHECKED, path named;
* an explicitly valid empty baseline -> a first offender is NEW and rc 1.

The pairs exercise the programs through their CLIs on small synthetic trees.
That keeps the control behavioural: before the fix the first half returns rc 1
and fabricates the pre-existing offender, while the second half already proves
the ratchet must keep its teeth.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
FLOW_AUDIT = PROGRAMS / "flow_gate_enforcement_audit.py"
WIRING_AUDIT = PROGRAMS / "checker_execution_wiring_audit.py"


def _baseline(path: Path, state: str) -> Path:
    if state == "unreadable":
        # A directory exists but cannot be read as the baseline artefact.  This
        # is deterministic under every test uid, unlike chmod-based fixtures.
        path.mkdir()
    elif state == "truncated":
        path.write_text('{"known": [', encoding="utf-8")
    elif state == "invalid_utf8":
        path.write_bytes(b'{"known": ["sample_check.py\xff"]}')
    elif state == "invalid_schema":
        path.write_text('{"known": [null]}', encoding="utf-8")
    else:
        assert state == "absent"
        assert not path.exists()
    return path


def _flow_tree(root: Path) -> tuple[Path, Path]:
    programs = root / "programs"
    programs.mkdir(parents=True)
    (programs / "sample_check.py").write_text(
        '"""No enforcement declaration."""\n', encoding="utf-8")
    flow = root / "flow.yaml"
    flow.write_text(
        "steps:\n"
        "  - gate:\n"
        "      program_exit_zero: sample_check.py\n",
        encoding="utf-8")
    return flow, programs


def _wiring_tree(root: Path) -> None:
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for rel in ("programs/tests", "flow", "skills", "agents", "commands",
                "tests"):
        (plugin / rel).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "tools").mkdir()
    (plugin / "programs" / "sample_check.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8")
    (plugin / "programs" / "tests" / "test_sample_check.py").write_text(
        "import sample_check\n", encoding="utf-8")


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *argv], capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    "state", ("absent", "unreadable", "truncated", "invalid_utf8",
              "invalid_schema"))
def test_flow_enforcement_audit_refuses_a_baseline_it_cannot_read(
        tmp_path: Path, state: str) -> None:
    flow, programs = _flow_tree(tmp_path)
    baseline = _baseline(tmp_path / "flow-baseline.json", state)

    got = _run(str(FLOW_AUDIT), "--flow", str(flow), "--programs",
               str(programs), "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert str(baseline) in transcript, transcript
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, transcript


def test_flow_enforcement_audit_keeps_an_explicit_empty_measurement_blocking(
        tmp_path: Path) -> None:
    flow, programs = _flow_tree(tmp_path)
    baseline = tmp_path / "flow-baseline.json"
    baseline.write_text(json.dumps({
        "known": [], "undeclared_known": [],
    }), encoding="utf-8")

    got = _run(str(FLOW_AUDIT), "--flow", str(flow), "--programs",
               str(programs), "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 1, transcript
    assert "[FAIL]" in transcript and "sample_check.py" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_flow_enforcement_audit_does_not_overwrite_a_truncated_measurement(
        tmp_path: Path) -> None:
    flow, programs = _flow_tree(tmp_path)
    baseline = tmp_path / "flow-baseline.json"
    truncated = '{"known": ['
    baseline.write_text(truncated, encoding="utf-8")

    got = _run(str(FLOW_AUDIT), "--flow", str(flow), "--programs",
               str(programs), "--baseline", str(baseline), "--write-baseline")
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript and str(baseline) in transcript, transcript
    assert baseline.read_text(encoding="utf-8") == truncated


@pytest.mark.parametrize(
    "state", ("absent", "unreadable", "truncated", "invalid_utf8",
              "invalid_schema"))
def test_checker_wiring_audit_refuses_a_baseline_it_cannot_read(
        tmp_path: Path, state: str) -> None:
    _wiring_tree(tmp_path)
    baseline = _baseline(tmp_path / "wiring-baseline.json", state)

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert str(baseline) in transcript, transcript
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, transcript


def test_checker_wiring_audit_keeps_an_explicit_empty_measurement_blocking(
        tmp_path: Path) -> None:
    _wiring_tree(tmp_path)
    baseline = tmp_path / "wiring-baseline.json"
    baseline.write_text(json.dumps({"known": []}), encoding="utf-8")

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 1, transcript
    assert "[FAIL]" in transcript and "sample_check.py" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_checker_wiring_audit_does_not_overwrite_a_truncated_measurement(
        tmp_path: Path) -> None:
    _wiring_tree(tmp_path)
    baseline = tmp_path / "wiring-baseline.json"
    truncated = '{"known": ['
    baseline.write_text(truncated, encoding="utf-8")

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline), "--write-baseline")
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript and str(baseline) in transcript, transcript
    assert baseline.read_text(encoding="utf-8") == truncated
