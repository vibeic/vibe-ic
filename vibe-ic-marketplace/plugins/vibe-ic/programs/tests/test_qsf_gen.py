"""Smoke tests for qsf_gen.py (Wave 72; renamed Wave 73 / v0.128)."""
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAM = Path(__file__).resolve().parent.parent / "qsf_gen.py"


def _scaffold(tmp_path: Path, with_wrapper: bool = False) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)

    l9 = {
        "schema_version": 2,
        "ic_name": "TEST_IC",
        "top_module": "chip_top",
        "top_module_pins": [
            {"name": "clk",     "mode": "input",  "io": "1.8V"},
            {"name": "reset_n", "mode": "input",  "io": "1.8V"},
            # Wave 73: explicit open_drain flag is the canonical source.
            {"name": "id_bus",  "mode": "inout",  "io": "open-drain",
             "open_drain": True},
        ],
    }
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(l9))
    (proj / "phase2" / "stage1" / "rtl" / "chip_top.sv").write_text(
        "module chip_top(input wire clk, input wire reset_n, "
        "inout wire id_bus); endmodule\n")
    if with_wrapper:
        (proj / "phase2" / "stage1" / "rtl" / "de10lite_top.sv").write_text(textwrap.dedent("""\
            module de10lite_top (
              input  wire CLOCK_50,
              input  wire [1:0] KEY,
              inout  wire [35:0] GPIO_0
            );
              chip_top u (
                .clk(CLOCK_50),
                .reset_n(KEY[0]),
                .id_bus(GPIO_0[0])
              );
            endmodule
        """))
    return proj


def test_qsf_gen_l9_only(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=False)
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    qsf = proj / "phase2" / "stage1" / "fpga" / "chip_top.qsf"
    assert qsf.is_file()
    text = qsf.read_text()
    assert "TOP_LEVEL_ENTITY          chip_top" in text
    # IC-namespace clk/reset_n/id_bus → CLOCK_50/KEY[0]/GPIO_0[0]
    assert "PIN_P11 -to CLOCK_50" in text
    assert "PIN_B8 -to KEY[0]" in text
    assert "PIN_V10 -to GPIO_0[0]" in text
    # Open-drain inout → weak pull-up
    assert "WEAK_PULL_UP_RESISTOR ON -to GPIO_0[0]" in text
    # SDC reference
    assert "SDC_FILE                  chip_top.sdc" in text
    # Family/device
    assert "10M50DAF484C7G" in text


def test_qsf_gen_with_wrapper(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=True)
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    # Wrapper picked as top
    qsf = proj / "phase2" / "stage1" / "fpga" / "de10lite_top.qsf"
    assert qsf.is_file()
    text = qsf.read_text()
    assert "TOP_LEVEL_ENTITY          de10lite_top" in text
    # Full GPIO_0 vector mapped
    for i in range(36):
        assert f"-to GPIO_0[{i}]" in text


def test_qsf_skip_when_same_name_present(tmp_path):
    """QSF gen SKIPs when its target file already exists (per-name)."""
    proj = _scaffold(tmp_path)
    fpga = proj / "phase2" / "stage1" / "fpga"
    fpga.mkdir(parents=True, exist_ok=True)
    # Same name as the would-be output → SKIP
    (fpga / "chip_top.qsf").write_text("# existing\n")
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0
    assert "SKIP" in cp.stdout
    assert (fpga / "chip_top.qsf").read_text() == "# existing\n"


def test_qsf_force_overwrites(tmp_path):
    proj = _scaffold(tmp_path)
    fpga = proj / "phase2" / "stage1" / "fpga"
    fpga.mkdir(parents=True, exist_ok=True)
    (fpga / "chip_top.qsf").write_text("# existing\n")
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj), "--force"],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    assert "PASS" in cp.stdout
    assert "PIN_P11" in (fpga / "chip_top.qsf").read_text()
