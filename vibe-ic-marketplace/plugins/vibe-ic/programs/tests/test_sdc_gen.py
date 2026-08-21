"""Smoke tests for sdc_gen.py (Wave 72; renamed Wave 73 / v0.128)."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAM = Path(__file__).resolve().parent.parent / "sdc_gen.py"


def _scaffold(tmp_path: Path, with_wrapper: bool = False,
              clock_mhz: int = 50) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)

    l8 = {"clock_mhz": clock_mhz}
    l9 = {
        "top_module": "chip_top",
        "top_module_pins": [
            {"name": "clk",     "mode": "input"},
            {"name": "reset_n", "mode": "input"},
            {"name": "id_bus",  "mode": "inout"},
        ],
    }
    (proj / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    (proj / "phase2" / "stage1" / "rtl" / "chip_top.sv").write_text(
        "module chip_top(input wire clk, input wire reset_n, "
        "inout wire id_bus); endmodule\n")
    if with_wrapper:
        (proj / "phase2" / "stage1" / "rtl" / "de10lite_top.sv").write_text(textwrap.dedent("""\
            module de10lite_top (
              input  wire CLOCK_50,
              input  wire [1:0] KEY,
              inout  wire [35:0] GPIO_0
            ); endmodule
        """))
    return proj


def test_sdc_gen_l9_only(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=False, clock_mhz=50)
    cp = subprocess.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "chip_top.sdc"
    assert sdc.is_file()
    text = sdc.read_text()
    assert "create_clock" in text
    assert "20" in text  # 1000/50 = 20 ns
    assert "[get_ports {clk}]" in text
    # reset_n + id_bus async → false_path
    assert "false_path" in text
    assert "reset_n" in text or "id_bus" in text


def test_sdc_gen_with_wrapper(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=True)
    cp = subprocess.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "de10lite_top.sdc"
    assert sdc.is_file()
    text = sdc.read_text()
    assert "[get_ports {CLOCK_50}]" in text
    # KEY[*] and GPIO_0[*] should appear as false_path groups
    assert "KEY[*]" in text
    assert "GPIO_0[*]" in text


def test_sdc_period_from_clock_mhz(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=False, clock_mhz=100)
    cp = subprocess.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "chip_top.sdc"
    text = sdc.read_text()
    # 1000 / 100 = 10
    assert "-period 10" in text
