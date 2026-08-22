#!/usr/bin/env python3
"""Step 39 — a WAIVED on_board_pass.json may not waive ITSELF.

Defect (HIGH, dimension 6 (skip discipline)): `fpga_on_board_attestation_check.main` short-
circuited to `[PASS] ... return 0` when the manifest it audits declared
`verdict in {WAIVED, SKIP}` plus `all_scenarios_passed` / `review_required` /
`waiver_ticket`. All four fields live inside that ONE file, so a four-line
hand-written JSON cleared the entire hardware sign-off with no .sof, no Quartus
programmer log and no evidence artefact — and `flow_compliance_check` then
reported step 39 "FPGA final sign-off" as a whole-step PASS with `reasons: []`.

The gate now cross-references the project's `waivers.json` (the same
`_load_waivers` / `_step_waived` contract the sibling
`final_test_attestation_check.py` uses), so the waiver has to come from OUTSIDE
the artefact under audit.

Direction-1 guards (must hold on BOTH the pre-fix and post-fix trees) are
marked `guard_`; they pin the behaviour that must NOT change — real hardware
evidence still PASSes, a bare self-attesting JSON still FAILs, and a genuinely
board-less project carrying the machinery-materialised ENV_UNAVAILABLE waiver
still resolves WAIVED (rc=0) rather than FAIL.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "fpga_on_board_attestation_check.py"
assert SCRIPT.is_file()

_MANIFEST = "reports/phase2/fpga/on_board_pass.json"


def _run(project: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(project), *extra],
        capture_output=True, text=True, timeout=60,
    )


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2) + "\n")
    else:
        path.write_text(payload)


def _self_waiving_manifest(project: Path, verdict: str = "WAIVED") -> None:
    """The exact shape that used to buy a free PASS: verdict + three sibling
    fields, all inside the audited manifest, and nothing else on disk."""
    _write(project / _MANIFEST, {
        "verdict": verdict,
        "all_scenarios_passed": True,
        "review_required": True,
        "waiver_ticket": "TICKET-SELF-ATTESTED-001",
    })


def _materialised_waiver(project: Path, step_id=39) -> None:
    """What waivers_materialize.py writes for a disclosed no-board project."""
    _write(project / "waivers.json", {
        "_schema_version": "1",
        "_generator": "waivers_materialize.py",
        "waived_steps": [{
            "id": step_id,
            "reason": "ENV_UNAVAILABLE (fpga-board-prototype cap-gap): the "
                      "runner honestly self-reports a deliberate FPGA skip.",
            "approver": "field-agent-attest (fpga-board cap-gap tier)",
            "ticket": "fpga-board-prototype-capgap-v1.0.18",
            "verdict_tier": "ENV_UNAVAILABLE",
            "review_required": True,
            "evidence": ["reports/phase2/fpga/quartus_map_audit.json"],
            "_env_unavailable": True,
            "_fpga_skip": True,
        }],
    })


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _real_hardware_evidence(project: Path) -> None:
    """All four evidence classes — the genuine on-board sign-off."""
    sof = project / "phase2/stage1/fpga/final/design.sof"
    sof.parent.mkdir(parents=True, exist_ok=True)
    sof.write_bytes(b"MOCK_BITSTREAM" * 500)
    _write(project / _MANIFEST, {
        "all_scenarios_passed": True,
        "bitstream_path": "phase2/stage1/fpga/final/design.sof",
        "bitstream_sha": _sha(sof.read_bytes()),
        "board": "DE10-Lite 10M50DAF484C7G",
        "programmed_at": "2026-04-22T10:00:00Z",
        "scenarios": [{"name": f"scen{i}", "result": "pass"} for i in range(4)],
    })
    _write(project / "reports/phase2/fpga/quartus_pgm.log",
           "Quartus Prime Programmer was successful\n"
           "Info: JTAG chain detected: USB-Blaster\n"
           "Info: Configuration succeeded\n")
    _write(project / "reports/phase2/fpga/on_board_evidence/led_pass.log",
           "t=0 LED=0x01\nt=1 LED=0x02\n")


# ── discriminators: these FAIL on the pre-fix program ──────────────────────

def test_self_declared_waived_without_waivers_json_is_refused(tmp_path):
    """The reported defect, verbatim: manifest-only WAIVED must not exit 0."""
    _self_waiving_manifest(tmp_path, "WAIVED")
    r = _run(tmp_path)
    assert r.returncode != 0, (
        "a WAIVED manifest with NO waivers.json entry still bought a PASS:\n"
        + r.stdout + r.stderr)
    combined = r.stdout + r.stderr
    assert "waivers.json" in combined
    # the evidence inspection must actually have run
    assert "no-hardware-evidence" in combined


def test_skip_manifest_is_not_a_waiver_tier(tmp_path):
    """SKIP is what the runner writes when the board test did not happen.
    It never was a waiver tier and must not short-circuit even WITH a waiver."""
    _self_waiving_manifest(tmp_path, "SKIP")
    _materialised_waiver(tmp_path)
    r = _run(tmp_path)
    assert r.returncode != 0, (
        "a SKIP manifest short-circuited the hardware sign-off:\n"
        + r.stdout + r.stderr)


def test_waived_short_circuit_still_writes_the_declared_json_report(tmp_path):
    """Step 39's gate declares `--json reports/phase2/fpga/on_board_attestation.json`.
    The old short-circuit returned BEFORE writing it, so the declared audit
    artefact silently never landed on exactly the runs that took the shortcut."""
    _self_waiving_manifest(tmp_path, "WAIVED")
    _materialised_waiver(tmp_path)
    out = tmp_path / "reports/phase2/fpga/on_board_attestation.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file(), "declared --json report was not written"
    assert json.loads(out.read_text())["overall"] == "WAIVED"


def test_waiver_for_a_different_step_does_not_cover_step_39(tmp_path):
    """Step 6 (early prototype) and step 39 (final sign-off) are distinct."""
    _self_waiving_manifest(tmp_path, "WAIVED")
    _materialised_waiver(tmp_path, step_id=6)
    r = _run(tmp_path)
    assert r.returncode != 0, r.stdout + r.stderr


# ── direction-1 guards: these must PASS on BOTH trees ─────────────────────

def guard_real_hardware_evidence_still_passes(tmp_path):
    _real_hardware_evidence(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def guard_materialised_env_unavailable_waiver_still_resolves(tmp_path):
    """The sanctioned no-rig route: a disclosed FPGA-skip project carrying the
    machinery-written ENV_UNAVAILABLE waiver must NOT become a hard FAIL."""
    _self_waiving_manifest(tmp_path, "WAIVED")
    _materialised_waiver(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def guard_pure_json_self_attestation_still_fails(tmp_path):
    """The original 2026-04-22 hardening: a full-schema manifest with no .sof,
    no programmer log and no evidence artefact is still a FAIL."""
    _write(tmp_path / _MANIFEST, {
        "all_scenarios_passed": True,
        "bitstream_path": "phase2/stage1/fpga/final/design.sof",
        "bitstream_sha": "sha256:fake",
        "board": "DE10-Lite",
        "programmed_at": "2026-04-22T10:00:00Z",
        "scenarios": [{"name": "s1", "result": "pass"}],
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


def guard_missing_manifest_still_fails(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "missing-pass-json" in (r.stdout + r.stderr)


def guard_not_a_directory_is_rc2(tmp_path):
    r = _run(tmp_path / "nope")
    assert r.returncode == 2


# pytest collects `test_*`; run the guards under the same names so a normal
# `pytest <file>` exercises both sets.
test_guard_real_hardware_evidence_still_passes = guard_real_hardware_evidence_still_passes
test_guard_materialised_env_unavailable_waiver_still_resolves = \
    guard_materialised_env_unavailable_waiver_still_resolves
test_guard_pure_json_self_attestation_still_fails = guard_pure_json_self_attestation_still_fails
test_guard_missing_manifest_still_fails = guard_missing_manifest_still_fails
test_guard_not_a_directory_is_rc2 = guard_not_a_directory_is_rc2
