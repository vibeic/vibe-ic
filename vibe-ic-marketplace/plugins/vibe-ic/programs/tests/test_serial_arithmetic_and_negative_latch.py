"""Public generic issue3216 classifier and issue3209 log advice controls."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures/phase1_local/serial_arithmetic_and_negative_latch"


def classify(tmp_path, text):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"description": text}))
    (docs / "L2_FRS.json").write_text("{}\n")
    result = subprocess.run([sys.executable, str(PROGRAMS / "ic_class_profile.py"), str(tmp_path)], text=True, capture_output=True)
    (tmp_path / "CLI_RESULT.json").write_text(json.dumps({"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}, indent=2))
    assert result.returncode == 0, result.stdout + result.stderr
    profile = json.loads(result.stdout)
    assert json.loads((tmp_path / "reports/ic_class.json").read_text()) == profile
    return profile


@pytest.mark.parametrize("surface", ["", "\nThe design has 8 external pins for its parallel register interface. An internal clock divider feeds the multiplier datapath.\n"])
def test_internal_serial_arithmetic_is_not_a_serial_peripheral(tmp_path, surface):
    profile = classify(tmp_path, (FIXTURES / "internal_serial_arithmetic.md").read_text() + surface)
    assert profile["ic_class"] == "crypto_accelerator"


@pytest.mark.parametrize("text", [
    "A UART peripheral provides a serial transmitter and receiver, shift registers and a baud rate generator. It can carry payload AES encryption with secret keys.",
    "An SPI serial peripheral acts as controller and target. It uses a shift register, clock generator, chip select and a data line. Optional payload AES encryption uses a block cipher.",
    "A serial transmitter and receiver use shift registers. A start bit and a stop bit frame each transfer on the external serial data line at a programmable bit rate. The payload can contain incidental AES encrypted data.",
])
def test_real_serial_protocol_with_incidental_crypto_stays_serial(tmp_path, text):
    assert classify(tmp_path, text)["ic_class"] == "serial_peripheral_protocol"
