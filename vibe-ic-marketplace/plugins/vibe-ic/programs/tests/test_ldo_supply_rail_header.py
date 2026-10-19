"""Native L5 and ordinary consumer distinguish rail headers from circuits."""
from pathlib import Path
import json
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as docs

INTAKE = Path(__file__).parent / "fixtures/phase1_local/neutral_pvt_supply_rail/pvt_supply_rail.md"
HEADER = "| Point | Core VCCD/VCCHIB | I/O VDDIO/VDDIO_Q/VDDA/VSWITCH | Temperature |"
TABLE = HEADER + "\n|---|---|---|---|\n| Nominal | 1.8 V | 3.3 V | 25 C |\n"


def project(tmp_path, text):
    source = tmp_path / "input/docs/power.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    result = docs.gen_l5_adi_spec(tmp_path, {source.name: text})
    return Path(result.path)


def gate(tmp_path):
    return subprocess.run([sys.executable, str(PROGRAMS / "analog_content_detected_must_emit_l5_check.py"),
                           str(tmp_path)], capture_output=True, text=True)


@pytest.mark.parametrize("text", [
    INTAKE.read_text(), TABLE,
    TABLE.replace("Point", "PVT point").replace("Temperature", "Temperature (C)"),
    TABLE.replace("VDDIO/VDDIO_Q/VDDA/VSWITCH", "`VDDA`"),
])
def test_supply_header_does_not_invent_an_ldo_requirement(tmp_path, text):
    l5 = project(tmp_path, text)
    payload = json.loads(l5.read_text())
    assert payload["analog_blocks"] == []
    assert payload["analog_blocks_detected"] is False
    before = l5.read_bytes()
    result = gate(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "[SKIP]" in result.stdout
    assert l5.read_bytes() == before


@pytest.mark.parametrize("declaration", [
    "An on-chip LDO supplies VDDA at 1.8 V.",
    "An on-chip regulator supplies a regulated output at 1.8 V.",
])
def test_real_regulator_before_or_after_table_remains_required(tmp_path, declaration):
    l5 = project(tmp_path, declaration + "\n\n" + TABLE + "\n" + declaration)
    payload = json.loads(l5.read_text())
    assert any(row["type"] == "ldo" for row in payload["analog_blocks"])
    assert gate(tmp_path).returncode == 0
    payload["analog_blocks"] = []
    l5.write_text(json.dumps(payload))  # isolated missing-real-block negative control
    result = gate(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ldo" in result.stdout.lower()


@pytest.mark.parametrize("text", [
    "The VDDA output supplies 1.8 V.",
    "The VREG output supplies 1.8 V.",
    "The VDD_LDO output supplies 1.8 V.",
    TABLE.replace("I/O VDDIO/VDDIO_Q/VDDA/VSWITCH", "I/O VDDA output"),
    TABLE.replace("|---|---|---|---|\n", ""),
    TABLE.replace("Point", "Signal"),
])
def test_output_or_ambiguous_context_is_not_an_external_rail_exemption(tmp_path, text):
    l5 = project(tmp_path, text)
    payload = json.loads(l5.read_text()); payload["analog_blocks"] = []
    l5.write_text(json.dumps(payload))
    result = gate(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ldo" in result.stdout.lower()
