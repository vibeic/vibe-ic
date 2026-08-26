#!/usr/bin/env python3
"""No consumer of the MCP result manifest may read `INCONCLUSIVE` as a pass.

The manifest `status` field became three-state — PASS / FAIL / INCONCLUSIVE —
when `writeManifest` started refusing to record a PASS whose proving metrics are
absent (mcp-eda/src/lib/manifest_metrics.mjs). Introducing a third state moves
the defect rather than fixing it unless every reader is updated: a reader that
tests `status != "FAIL"` to mean "passed" now silently accepts a run that
measured nothing, which is exactly the bug the third state was added to stop.

Two programs read that manifest. This file pins both, at both poles, plus a
source-level guard that a future reader cannot reintroduce the `!= "FAIL"`
shape in either of them.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
VERIFY = PROGRAMS / "mcp_execution_verify.py"
ATTEST = PROGRAMS / "fpga_program_chain_attest_check.py"


def _ts(hours_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _manifest(tmp_path: Path, entries: list) -> Path:
    p = tmp_path / "latest_results.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return p


def _verify(manifest: Path, steps: str):
    r = subprocess.run(
        [sys.executable, str(VERIFY), "--manifest", str(manifest),
         "--require-steps", steps],
        capture_output=True, text=True, timeout=120)
    return r.returncode, json.loads(r.stdout)


def _attest(manifest: Path):
    r = subprocess.run(
        [sys.executable, str(ATTEST), "--manifest", str(manifest)],
        capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


# ── consumer 1: mcp_execution_verify.py ────────────────────────────────────

def test_verify_inconclusive_is_not_a_pass(tmp_path: Path) -> None:
    """RED POLE. The STA step ran, reported success, and recorded no wns/tns.
    That must not earn a pass."""
    m = _manifest(tmp_path, [
        {"timestamp": _ts(1), "step": "sta", "status": "INCONCLUSIVE",
         "tool": "OpenSTA", "wns": None, "tns": None,
         "missing_metrics": ["wns", "tns"]},
    ])
    rc, rep = _verify(m, "sta")
    assert rc == 1
    assert rep["summary"]["verdict"] != "PASS"
    assert rep["summary"]["found_pass"] == 0
    assert rep["summary"]["found_inconclusive"] == 1
    assert rep["results"][0]["status"] == "FOUND_INCONCLUSIVE"


def test_verify_inconclusive_is_not_a_failure_either(tmp_path: Path) -> None:
    """...and it must not be reported as a failing design. Unmeasured is its
    own answer; calling it FAIL is the same lie pointed the other way."""
    m = _manifest(tmp_path, [
        {"timestamp": _ts(1), "step": "sta", "status": "INCONCLUSIVE"},
    ])
    rc, rep = _verify(m, "sta")
    assert rep["summary"]["verdict"] == "INCONCLUSIVE"
    assert rep["summary"]["found_fail"] == 0
    assert rc == 1  # still not permission to proceed


def test_verify_a_clean_run_is_still_a_pass(tmp_path: Path) -> None:
    """GREEN POLE — the control that proves this is not a refusal machine."""
    m = _manifest(tmp_path, [
        {"timestamp": _ts(2), "step": "synthesis", "status": "PASS",
         "tool": "Yosys", "cells": 2827},
        {"timestamp": _ts(1), "step": "sta", "status": "PASS",
         "tool": "OpenSTA", "wns": 0.0, "tns": 0.0},
    ])
    rc, rep = _verify(m, "synthesis,sta")
    assert rc == 0
    assert rep["summary"]["verdict"] == "PASS"
    assert rep["summary"]["found_inconclusive"] == 0


def test_verify_a_real_failure_is_still_a_failure(tmp_path: Path) -> None:
    """CONTROL — adding a third state must not blind the second one."""
    m = _manifest(tmp_path, [
        {"timestamp": _ts(1), "step": "drc", "status": "FAIL",
         "tool": "KLayout", "violations": 41},
    ])
    rc, rep = _verify(m, "drc")
    assert rc == 1
    assert rep["summary"]["verdict"] == "FAIL"
    assert rep["results"][0]["status"] == "FOUND_FAIL"


def test_verify_a_mixed_run_reports_the_failure(tmp_path: Path) -> None:
    """A FAIL anywhere outranks an INCONCLUSIVE: the run is known-bad."""
    m = _manifest(tmp_path, [
        {"timestamp": _ts(2), "step": "sta", "status": "INCONCLUSIVE"},
        {"timestamp": _ts(1), "step": "drc", "status": "FAIL", "violations": 3},
    ])
    rc, rep = _verify(m, "sta,drc")
    assert rc == 1
    assert rep["summary"]["verdict"] == "FAIL"
    assert rep["summary"]["found_inconclusive"] == 1


# ── consumer 2: fpga_program_chain_attest_check.py ─────────────────────────

def _chain(compile_status: str, program_status: str) -> list:
    sid = "sess-1"
    return [
        {"timestamp": _ts(3), "step": "fpga_compile", "status": compile_status,
         "session_id": sid, "compiled_artifact_sha256": "a" * 64},
        {"timestamp": _ts(2), "step": "fpga_program", "status": program_status,
         "session_id": sid, "programmed_artifact_sha256": "a" * 64,
         "compile_artifact_sha256": "a" * 64, "program_matches_compile": True},
    ]


def test_attest_inconclusive_compile_does_not_link_the_chain(
        tmp_path: Path) -> None:
    """RED POLE. An unproven compile is not a compile: it may not carry a
    hardware-attestation claim."""
    m = _manifest(tmp_path, _chain("INCONCLUSIVE", "PASS"))
    rc, out = _attest(m)
    assert rc != 0
    assert "INCONCLUSIVE" in out


def test_attest_a_real_chain_still_passes(tmp_path: Path) -> None:
    """GREEN POLE — the control."""
    m = _manifest(tmp_path, _chain("PASS", "PASS"))
    rc, out = _attest(m)
    assert rc == 0, out


# ── the guard: neither reader may use the two-state shape ──────────────────

FORBIDDEN = ('!= "FAIL"', "!= 'FAIL'", '!== "FAIL"', "not in (\"FAIL\"",
             "not in ('FAIL'")


def _executable_lines(path: Path):
    """(lineno, source) for lines that are executable code — docstrings and
    comments stripped, so prose ABOUT the forbidden shape does not trip the
    guard while code USING it does."""
    src = path.read_text()
    tree = ast.parse(src)
    prose = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            prose.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    for n, line in enumerate(src.splitlines(), 1):
        if n in prose:
            continue
        yield n, line.split("#", 1)[0]


def test_no_manifest_reader_treats_non_fail_as_a_pass() -> None:
    """Source guard on every program that reads latest_results.jsonl. With a
    three-state status, `!= "FAIL"` means "PASS or INCONCLUSIVE", i.e. it reads
    an unmeasured run as a passing one. Test `== "PASS"` instead.

    Scope note: this guard covers the MCP result-manifest readers only. Other
    verdict systems in this repo carry their own vocabularies and never receive
    a value written by writeManifest."""
    readers = [VERIFY, ATTEST]
    for reader in readers:
        assert reader.is_file(), reader
        for n, line in _executable_lines(reader):
            for bad in FORBIDDEN:
                assert bad not in line, (
                    f"{reader.name}:{n} tests {bad} — with a three-state "
                    f"manifest that reads INCONCLUSIVE as a pass: {line!r}")


def test_the_reader_set_is_the_whole_set() -> None:
    """The guard above is only as good as its list of readers. Every program
    that names the manifest file must be one of them (or be the producer-side
    shell test), so adding a new reader without adding it here goes red."""
    root = PROGRAMS.parent
    named = set()
    for path in root.rglob("*.py"):
        if "latest_results" in path.read_text(errors="ignore"):
            named.add(path.resolve())
    known = {VERIFY.resolve(), ATTEST.resolve()}
    tests_dir = (PROGRAMS / "tests").resolve()
    extra = {p for p in named
             if p not in known and tests_dir not in p.parents
             and p.parent.name != "test"}
    assert not extra, (
        "new reader(s) of latest_results.jsonl are not covered by the "
        f"non-FAIL guard: {sorted(str(p) for p in extra)}")
