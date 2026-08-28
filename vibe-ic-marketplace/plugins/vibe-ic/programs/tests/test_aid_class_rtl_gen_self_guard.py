"""tests/test_aid_class_rtl_gen_self_guard.py — Wave 73 (v0.128) S1.

Defense-in-depth: aid_class_rtl_gen.py is invoked through the orchestrator
(phase23_one_shot_runner.py) which already class-guards. But a manual
`python3 aid_class_rtl_gen.py --project_dir ./foo` would otherwise
blindly produce EXAMPLE_PROTOCOL-class RTL regardless of detected ic_class.

This test asserts the __main__ block refuses to run on:
  1. spi-class (digital_cmd_driven via L2 protocol_type=SPI) -> rc=2 + REFUSE
  2. aid_class fixture (rtl/ has `inout id_bus`)              -> rc=0
  3. unknown class (empty project, no L docs / no RTL)        -> rc=2 (fail-closed)

Note: case 2 only validates the guard does not block — full RTL emission
is covered by the orchestrator-level smoke tests.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAM = (
    Path(__file__).resolve().parent.parent / "aid_class_rtl_gen.py"
)


def _write(project: Path, rel: str, body: dict) -> None:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body))


def _run(project: Path) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROGRAM), str(project)],
        capture_output=True, text=True)


def _evidence(label: str) -> dict:
    return {
        "extraction_evidence": {
            "vendor.pdf": [{"literal": f"sentinel-{label}",
                            "label": label}]
        }
    }


# -------------------------------------------------------------------------
# Case 1 — spi-class fixture: __main__ guard must REFUSE.
# -------------------------------------------------------------------------
def _build_spi_class(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"), "ic_name": "SPI-IC", "interface": "SPI",
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"), "ic_name": "SPI-IC", "protocol_type": "SPI",
    })
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", {
        **_evidence("L3"), "ic_name": "SPI-IC",
        "command_count": 2,
        "commands": [
            {"opcode": "0x01", "name": "READ"},
            {"opcode": "0x02", "name": "WRITE"},
        ],
    })


def test_spi_class_refused(tmp_path: Path) -> None:
    project = tmp_path / "spi_proj"
    _build_spi_class(project)
    cp = _run(project)
    assert cp.returncode == 2, (
        f"expected rc=2 REFUSE, got rc={cp.returncode}\n"
        f"stdout={cp.stdout}\nstderr={cp.stderr}"
    )
    assert "REFUSE" in cp.stderr, cp.stderr
    assert "aid_class_rtl_gen.py is EXAMPLE_PROTOCOL-class only" in cp.stderr


# -------------------------------------------------------------------------
# Case 2 — aid_class fixture: __main__ guard must allow.
# -------------------------------------------------------------------------
def _build_aid_class(project: Path) -> None:
    """Minimal EXAMPLE_PROTOCOL-class fixture: detect_ic_class needs L1+L2+L3
    plus an `inout id_bus` in rtl/ to set protocol_class=aid_class."""
    project.mkdir(parents=True, exist_ok=True)
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"), "ic_name": "EXAMPLE_PROTOCOL-IC",
        "interface": "Apple ID Bus",
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"), "ic_name": "EXAMPLE_PROTOCOL-IC",
        "protocol_type": "Apple ID Bus",
    })
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", {
        **_evidence("L3"), "ic_name": "EXAMPLE_PROTOCOL-IC",
        "command_count": 1,
        "commands": [{"opcode": "0x74", "name": "GET_ID"}],
    })
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text(
        "module chip_top(input wire clk, input wire reset_n,\n"
        "                inout wire id_bus); endmodule\n"
    )


def test_aid_class_allowed(tmp_path: Path) -> None:
    project = tmp_path / "aid_proj"
    _build_aid_class(project)
    cp = _run(project)
    # Guard must NOT refuse (rc != 2 with REFUSE message). gen() may
    # still error on missing L4..L9 or similar; what matters is the
    # guard didn't block at the front door.
    refused = (cp.returncode == 2) and ("REFUSE" in cp.stderr)
    assert not refused, (
        f"EXAMPLE_PROTOCOL-class fixture was wrongly REFUSED:\n"
        f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    )


# -------------------------------------------------------------------------
# Case 3 — unknown class (empty / pre-Phase-2a project): fail-closed.
# -------------------------------------------------------------------------
def test_unknown_class_refused(tmp_path: Path) -> None:
    project = tmp_path / "empty_proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run(project)
    assert cp.returncode == 2, (
        f"expected rc=2 REFUSE for unknown class (fail-closed), "
        f"got rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    )
    assert "REFUSE" in cp.stderr, cp.stderr
