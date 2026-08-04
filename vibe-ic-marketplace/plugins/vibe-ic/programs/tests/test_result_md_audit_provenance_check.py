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


# ── Freshness (STALE rule) must not depend on how many times the compliance
#    flow has run. The flow re-stamps its OWN output tree (`reports/`) on every
#    invocation, so a freshness reference that counts `reports/` made this
#    gate's verdict flip PASS->FAIL between run 1 and run 2 of the SAME tree
#    (measured: subservient_gf180mcuD, plugin 1.9.76). These two tests are a
#    bidirectional control: (1) the flow's own re-stamped reports must NOT be
#    read as a newer design round; (2) a genuinely newer DESIGN artefact must
#    still be caught. Test (1) FAILS against the pre-fix program and PASSES
#    after; test (2) holds on both — proving the rule is anchored, not neutered.
import os  # noqa: E402


def _run_tree(tmp_path: Path, doc_mtime: float):
    """A minimal run tree: a RESULT.md that quotes a compliance tally (so the
    STALE branch is walked) but does NOT claim PASS (so citation rules SKIP and
    only the freshness rule is under test), plus a `reports/` output file and a
    `phase2/` design artefact."""
    (tmp_path / "RESULT.md").write_text(
        "# Compliance run (in progress)\n\n"
        "Structural tally: PASS=7 FAIL=5 MISSING=0\n"
    )
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "gate.json").write_text("{}\n")
    (tmp_path / "phase2").mkdir()
    (tmp_path / "phase2" / "netlist.v").write_text("module top(); endmodule\n")
    os.utime(tmp_path / "RESULT.md", (doc_mtime, doc_mtime))


def test_freshness_ignores_flow_own_reports(tmp_path):
    """The flow re-stamping its OWN `reports/` tree far past the RESULT.md
    mtime must NOT be read as a newer design round. FAILS pre-fix (reports/ was
    in the freshness reference), PASSES post-fix."""
    doc_m = 1_000_000.0
    _run_tree(tmp_path, doc_m)
    # design artefact stays older than the doc; only the flow's own report is
    # stamped far in the future — exactly what an extra umbrella run does.
    os.utime(tmp_path / "phase2" / "netlist.v", (doc_m - 100, doc_m - 100))
    os.utime(tmp_path / "reports" / "gate.json",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "STALE" not in r.stdout, r.stdout


def test_freshness_still_catches_stale_design_artefact(tmp_path):
    """A genuinely newer DESIGN artefact (phase2/) past the grace still trips
    RESULT_MD_STALE_VS_EVIDENCE — the rule is anchored, not neutered."""
    doc_m = 1_000_000.0
    _run_tree(tmp_path, doc_m)
    os.utime(tmp_path / "phase2" / "netlist.v",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_STALE_VS_EVIDENCE" in r.stdout, r.stdout


def test_newest_evidence_excludes_flow_output_root(tmp_path):
    """Directly: `_newest_evidence` must ignore the flow's own `reports/`
    output root, so its result is invariant to the flow re-stamping reports."""
    sys.path.insert(0, str(PROG.parent))
    import result_md_audit_provenance_check as chk
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "gate.json").write_text("{}\n")
    (tmp_path / "phase2").mkdir()
    (tmp_path / "phase2" / "netlist.v").write_text("x\n")
    os.utime(tmp_path / "phase2" / "netlist.v", (1000.0, 1000.0))
    os.utime(tmp_path / "reports" / "gate.json", (9000.0, 9000.0))
    m, p = chk._newest_evidence(tmp_path)
    assert p == "phase2/netlist.v", (m, p)
    assert m == 1000.0, (m, p)
