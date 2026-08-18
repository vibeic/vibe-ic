"""tests/test_wave80_mixed_signal_otp_aid_acceptance.py — Wave 80 (v0.135).

Wave 80 extends the Wave 73 self-guard in `aid_class_rtl_gen.py` so that
projects whose `ic_class` is `mixed_signal_otp` (analog blocks present in
L5) BUT which also carry EXAMPLE_PROTOCOL-class half-duplex protocol markers in L2/L3
(half_duplex / single-wire / opcodes / crc_parameters) are accepted.

Diagnostic context (v0121-vendor): two classifiers disagree —
  - phase23_one_shot_runner.detect_ic_class (L2/L3 keyword path)
        → "aid_class_half_duplex"
  - ic_class_profile.detect_ic_class (L5.analog_blocks path used by guard)
        → "mixed_signal_otp"
Both labels are correct for EXAMPLE_CHIP (EXAMPLE_PROTOCOL protocol on top of 11 analog
blocks).  The Wave 73 strict-prefix test refused the project; Wave 80
adds an _APPLICABLE_CLASSES allow-list + an L2/L3 protocol-marker probe
to accept the project while preserving the Wave 73 intent that
pure-analog / pure-non-EXAMPLE_PROTOCOL projects still REFUSE.

Cases:
  1. mixed_signal_otp + EXAMPLE_PROTOCOL protocol markers       -> accepted (no REFUSE)
  2. pure-analog (L5 only, no L2/L3 protocol)      -> REFUSE preserved
  3. EXAMPLE_PROTOCOL class + pure-digital (no analog blocks)   -> Wave 73 baseline
  4. unknown class lacking EXAMPLE_PROTOCOL markers             -> REFUSE
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAM = (
    Path(__file__).resolve().parent.parent / "aid_class_rtl_gen.py"
)


def _write(project: Path, rel: str, body: dict) -> None:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body))


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAM), str(project)],
        capture_output=True, text=True, timeout=60,
    )


def _evidence(label: str) -> dict:
    return {
        "extraction_evidence": {
            "vendor.pdf": [{"literal": f"sentinel-{label}",
                            "label": label}]
        }
    }


def _aid_l2(half_duplex: bool = True, wire_count: int = 1) -> dict:
    return {
        **_evidence("L2"),
        "ic_name": "EXAMPLE_PROTOCOL-IC",
        "protocol_overview": {
            "half_duplex": half_duplex,
            "wire_count": wire_count,
            "byte_order": "LSB-first",
            "wake_required_pre_command": True,
        },
    }


def _aid_l3() -> dict:
    return {
        **_evidence("L3"),
        "ic_name": "EXAMPLE_PROTOCOL-IC",
        "opcodes": [
            {"opcode": "0x74", "name": "GET_ID"},
            {"opcode": "0x72", "name": "GET_STATE"},
        ],
        "crc_parameters": {
            "polynomial_hex": "0x8C",
            "init_hex": "0x00",
            "bit_order": "LSB-first",
        },
    }


def _analog_l5() -> dict:
    return {
        **_evidence("L5"),
        "ic_name": "EXAMPLE_PROTOCOL-IC",
        "analog_blocks": [
            {"name": "OSC_50M",   "type": "oscillator"},
            {"name": "BG_REF",    "type": "bandgap"},
            {"name": "LDO_DIG",   "type": "ldo"},
            {"name": "POR",       "type": "por"},
            {"name": "PULL_DOWN", "type": "pull_down"},
            {"name": "ESD_PAD",   "type": "esd"},
            {"name": "CHARGE_P",  "type": "charge_pump"},
            {"name": "TRIM_VBG",  "type": "trim_register"},
            {"name": "TRIM_LDO",  "type": "trim_register"},
            {"name": "TRIM_OSC",  "type": "trim_register"},
            {"name": "LEVEL_SHF", "type": "level_shifter"},
        ],
    }


def _refused(cp: subprocess.CompletedProcess) -> bool:
    return cp.returncode == 2 and "REFUSE" in cp.stderr


# ---------------------------------------------------------------------
# Case 1 — mixed_signal_otp + EXAMPLE_PROTOCOL protocol -> accepted (Wave 80 fix).
# ---------------------------------------------------------------------
def test_mixed_signal_otp_with_aid_protocol_accepted(tmp_path: Path) -> None:
    project = tmp_path / "mixed_aid"
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"), "ic_name": "MIXED-IC",
        "interface": "Apple ID Bus + analog",
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", _aid_l2())
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", _aid_l3())
    _write(project, "phase1/generated_docs/L5_ADI_SPEC.json", _analog_l5())
    cp = _run(project)
    assert not _refused(cp), (
        "mixed_signal_otp + EXAMPLE_PROTOCOL protocol must NOT be REFUSED:\n"
        f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    )


# ---------------------------------------------------------------------
# Case 2 — pure analog (no EXAMPLE_PROTOCOL protocol markers) -> REFUSE preserved.
# ---------------------------------------------------------------------
def test_pure_analog_no_protocol_rejected(tmp_path: Path) -> None:
    project = tmp_path / "pure_analog"
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"), "ic_name": "PMIC",
        "interface": "analog only",
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"), "ic_name": "PMIC",
        # Empty protocol overview — no half_duplex / single-wire markers.
        "protocol_overview": {},
    })
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", {
        **_evidence("L3"), "ic_name": "PMIC",
        # No opcodes, no CRC.
    })
    _write(project, "phase1/generated_docs/L5_ADI_SPEC.json", _analog_l5())
    cp = _run(project)
    assert _refused(cp), (
        "pure-analog (no EXAMPLE_PROTOCOL protocol) must be REFUSED — Wave 73 intent:\n"
        f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    )


# ---------------------------------------------------------------------
# Case 3 — EXAMPLE_PROTOCOL-class pure-digital (no L5) -> Wave 73 baseline accept.
# ---------------------------------------------------------------------
def test_aid_class_pure_digital_accepted(tmp_path: Path) -> None:
    project = tmp_path / "pure_aid"
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"), "ic_name": "EXAMPLE_PROTOCOL-IC",
        "interface": "Apple ID Bus",
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"), "ic_name": "EXAMPLE_PROTOCOL-IC",
        # Wave 73 baseline relies on L2.protocol_type → ic_class_profile
        # mapping to aid_class_half_duplex.  Both legacy field name and
        # protocol_overview path are populated for robustness.
        "protocol_type": "Apple ID Bus",
        "protocol_overview": {"half_duplex": True, "wire_count": 1},
    })
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", _aid_l3())
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text(
        "module chip_top(input wire clk, input wire reset_n,\n"
        "                inout wire id_bus); endmodule\n"
    )
    cp = _run(project)
    assert not _refused(cp), (
        "EXAMPLE_PROTOCOL-class pure-digital must NOT be REFUSED (Wave 73 baseline):\n"
        f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    )


# ---------------------------------------------------------------------
# Case 4 — unknown class lacking EXAMPLE_PROTOCOL markers -> REFUSE (fail-closed).
# ---------------------------------------------------------------------
def test_unknown_class_rejected(tmp_path: Path) -> None:
    project = tmp_path / "unknown"
    # Empty project: no L docs at all -> ic_class=unknown, no EXAMPLE_PROTOCOL markers.
    project.mkdir(parents=True, exist_ok=True)
    cp = _run(project)
    assert _refused(cp), (
        "unknown class (no EXAMPLE_PROTOCOL markers) must be REFUSED (fail-closed):\n"
        f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    )
