#!/usr/bin/env python3
"""Tests for result_md_audit_provenance_check.py (Wave 33, v0.119.65)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "result_md_audit_provenance_check.py"
)


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True,
        text=True,
    )


def test_no_result_md_skip(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout, r.stdout


def test_result_md_with_provenance_pass(tmp_path):
    """RESULT.md claims PASS and cites all three required pieces."""
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n\n"
        "## Burn provenance\n"
        "audit_sha256: sha256:" + "0" * 64 + "\n"
        "audit_verdict: PASS\n"
        "program_response: {success: true, guard_invoked: true, "
        "error_code: program_succeeded}\n"
        "Hardware verdict: byte[6]=0xF2 across 5/5 connect_test runs.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    assert "Provenance verifiable" in r.stdout, r.stdout


def test_result_md_missing_audit_sha_fail(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "audit_verdict: PASS\n"
        "program_response: {success: true}\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_SHA" in r.stdout, r.stdout


def test_result_md_missing_program_response_fail(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "audit_sha256: sha256:" + "a" * 64 + "\n"
        "audit_verdict: PASS\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_PROGRAM_RESPONSE" in r.stdout, r.stdout


def test_result_md_missing_audit_verdict_fail(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "audit_sha256: sha256:" + "b" * 64 + "\n"
        "program_response: {success: true}\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_VERDICT" in r.stdout, r.stdout


def test_result_md_claiming_fail_skips(tmp_path):
    """RESULT.md that honestly reports FAIL must SKIP — agent isn't
    claiming a passing burn so provenance citation isn't required."""
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 outcome — FAIL\n\n"
        "Hardware verdict byte[6]=0x02 across 5/5 connect_test runs.\n"
        "Phase 2a 100% but real silicon FAIL.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout, r.stdout


def test_pass_with_waivers_accepted(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS_WITH_WAIVERS\n"
        "audit_sha256: sha256:" + "c" * 64 + "\n"
        "audit_verdict: PASS_WITH_WAIVERS\n"
        "program_response: {success: true}\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVERS" in r.stdout or "PASS" in r.stdout


def test_waiver_silences_failure(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "Hardware byte[6]=0xF2.\n"
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "result_md_audit_provenance_intentional":
            "Test rig generated provenance separately; RESULT.md "
            "narrative is summary-only with provenance JSON archived "
            "outside the project tree (see lab journal entry).",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout, r.stdout


def test_burn_provenance_json_reference_accepted(tmp_path):
    """A reference to `burn_provenance.json` carrying success-class
    markers is accepted as program_response evidence."""
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "Burn provenance: see `reports/burn_provenance.json`\n"
        "  audit_sha256: sha256:" + "d" * 64 + "\n"
        "  audit_verdict: PASS\n"
        "  guard_invoked: true\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
