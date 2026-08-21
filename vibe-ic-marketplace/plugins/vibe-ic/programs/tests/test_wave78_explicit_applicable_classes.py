#!/usr/bin/env python3
"""Wave 78 — explicit `_APPLICABLE_CLASSES` retrofit tests.

The 5 Wave-58 gates listed below now declare an explicit
`_APPLICABLE_CLASSES` tuple AND short-circuit with a SKIP message
when `detect_ic_class(project)` returns a non-applicable class.

Per-gate applicability (matches the source-of-truth tuples):

  crc_validation_present              : aid_class_half_duplex,
                                        digital_cmd_driven,
                                        mixed_signal_otp
  dispatch_handler_completeness       : same as above
  rig_firmware_capability_check       : same + unknown (fail-closed)
  scope_reply_preamble_check          : aid_class_half_duplex only
  wake_gen_silence_gate               : same as crc + has_wake_gating

These tests build a minimal project that triggers `pure_analog` (no
L1/L2/L3, only L5.analog_blocks), confirm each gate prints
`SKIP — not applicable to ic_class=pure_analog`, AND confirm an
`unknown` project is NOT skipped (fail-closed contract).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
import pytest

PROGRAMS = (
    Path(__file__).resolve().parent.parent
)


def _write_pure_analog(project: Path) -> None:
    """Build a project that detects as `pure_analog`."""
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    # L5 with analog_blocks → has_analog=True
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "doc_class": "analog_spec",
        "analog_blocks": [{"name": "bandgap"}],
    }))
    # L1 minimal so detect_ic_class reaches the class-assignment block
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "doc_class": "datasheet",
        "ic_name": "PURE_ANALOG_FIXTURE",
    }))


def _write_bare_fpga(project: Path) -> None:
    """Build a project that detects as `bare_fpga`."""
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "doc_class": "datasheet",
        "ic_name": "BARE_FPGA_FIXTURE",
    }))


def _run(prog: str, project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / prog), str(project)],
        capture_output=True, text=True,
    )


# ─── Per-gate: SKIP on pure_analog ───────────────────────────────
GATES_SKIP_ON_PURE_ANALOG = [
    "crc_validation_present.py",
    "dispatch_handler_completeness.py",
    "scope_reply_preamble_check.py",
    "wake_gen_silence_gate.py",
]


@pytest.mark.parametrize("gate", GATES_SKIP_ON_PURE_ANALOG)
def test_gate_skips_when_ic_class_is_pure_analog(tmp_path, gate):
    """Wave 78 — explicit class gate must SKIP on pure_analog and the
    SKIP message must include `not applicable to ic_class=pure_analog`."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_pure_analog(project)
    r = _run(gate, project)
    assert r.returncode == 0, (
        f"{gate}: returncode={r.returncode}; stdout={r.stdout!r}"
    )
    assert "SKIP" in r.stdout, f"{gate} stdout: {r.stdout!r}"
    assert "pure_analog" in r.stdout, (
        f"{gate} did not name the non-applicable class: {r.stdout!r}"
    )


def test_rig_firmware_capability_check_includes_unknown_in_applicable():
    """rig_firmware_capability_check must NOT skip on `unknown`
    (fail-closed: an unclassified project that ships rig blockers
    still must be audited). With no rig_capabilities.json + no
    blocker reports, the gate should SKIP for a different reason
    (no triggers), NOT 'not applicable to ic_class=unknown'.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        project = Path(td) / "proj"
        project.mkdir(parents=True, exist_ok=True)
        # No L docs at all → unknown
        r = _run("rig_firmware_capability_check.py", project)
        assert r.returncode == 0
        assert "not applicable to ic_class=unknown" not in r.stdout, (
            "rig_firmware_capability_check should NOT skip-by-class on "
            f"unknown (fail-closed): {r.stdout!r}"
        )


def test_unknown_does_not_skip_for_crc_and_dispatch_and_wake(tmp_path):
    """Fail-closed contract: when ic_class=unknown the gate must
    fall through to its existing FAIL/SKIP logic, not short-circuit
    on the new applicability check."""
    # Minimal "unknown" project: no L docs, no facts.yaml, no rtl/.
    project = tmp_path / "unknown_proj"
    project.mkdir(parents=True, exist_ok=True)
    # No L docs → ic_class falls to the empty-path branch which
    # returns "unknown".
    for gate in (
        "crc_validation_present.py",
        "dispatch_handler_completeness.py",
        "wake_gen_silence_gate.py",
        "scope_reply_preamble_check.py",
    ):
        r = _run(gate, project)
        assert "not applicable to ic_class=unknown" not in r.stdout, (
            f"{gate} skipped on unknown — should fail-through to "
            f"existing logic: {r.stdout!r}"
        )


def test_all_5_gates_declare_applicable_classes_constant():
    """Source-of-truth check: every retrofit gate MUST declare the
    `_APPLICABLE_CLASSES` constant. Catches an accidental constant
    deletion in a future PR."""
    gates = [
        "crc_validation_present.py",
        "dispatch_handler_completeness.py",
        "rig_firmware_capability_check.py",
        "scope_reply_preamble_check.py",
        "wake_gen_silence_gate.py",
    ]
    for g in gates:
        text = (PROGRAMS / g).read_text()
        assert "_APPLICABLE_CLASSES = " in text, (
            f"{g} missing _APPLICABLE_CLASSES constant"
        )
        assert "from ic_class_profile import detect_ic_class" in text, (
            f"{g} missing detect_ic_class import"
        )
