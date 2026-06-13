"""Tests for the aid_class_sdc_gen.py backwards-compat shim (Wave 73 / v0.128).

aid_class_sdc_gen.py is a thin compat shim: it (1) emits a DeprecationWarning
on import, (2) re-exports sdc_gen's public API via `from sdc_gen import *`
(library callers), and (3) forwards `python3 aid_class_sdc_gen.py ...` to
sdc_gen.main() (CLI callers). These tests pin that the forwarding is REAL —
the shim's main() must be sdc_gen.main, the CLI must produce the same SDC
artifact, and the same defect guard (missing L8/L9 -> exit 1) must fire
THROUGH the shim. We mirror the subprocess-scaffold style of the sibling
test_sdc_gen.py for the PASS/FAIL CLI paths.
"""
import json
import subprocess
import sys
import warnings
from pathlib import Path

SHIM = Path(__file__).resolve().parent.parent / "aid_class_sdc_gen.py"


def _scaffold(tmp_path: Path, clock_mhz: int = 50, with_l_docs: bool = True) -> Path:
    """Minimal valid project: L8/L9 generated_docs + a chip_top RTL file."""
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)

    (proj / "phase2" / "stage1" / "rtl" / "chip_top.sv").write_text(
        "module chip_top(input wire clk, input wire reset_n, "
        "inout wire id_bus); endmodule\n")

    if with_l_docs:
        l8 = {"clock_mhz": clock_mhz}
        l9 = {
            "top_module": "chip_top",
            "top_module_pins": [
                {"name": "clk",     "mode": "input"},
                {"name": "reset_n", "mode": "input"},
                {"name": "id_bus",  "mode": "inout"},
            ],
        }
        gd = proj / "phase1" / "generated_docs"
        (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
        (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    return proj


# ---------------------------------------------------------------------------
# PASS fixture — the shim CLI forwards to sdc_gen.main() and emits the SDC.
# ---------------------------------------------------------------------------
def test_shim_cli_forwards_and_emits_sdc(tmp_path):
    proj = _scaffold(tmp_path, clock_mhz=50)
    cp = subprocess.run([sys.executable, str(SHIM), str(proj)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "chip_top.sdc"
    assert sdc.is_file(), "shim CLI must forward to sdc_gen.main and emit the SDC"
    text = sdc.read_text()
    # Pin the forwarded generator's real output: 1000/50 = 20 ns clock period
    # on the clk port, with async pins (reset_n / id_bus) cut as false_path.
    assert "create_clock" in text
    assert "[get_ports {clk}]" in text
    assert "-period 20" in text
    assert "false_path" in text


def test_shim_cli_matches_clock_mhz(tmp_path):
    # 1000 / 100 MHz = 10 ns — proves the shim really runs sdc_gen logic,
    # not a stub that ignores L8.clock_mhz.
    proj = _scaffold(tmp_path, clock_mhz=100)
    cp = subprocess.run([sys.executable, str(SHIM), str(proj)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "chip_top.sdc"
    assert "-period 10" in sdc.read_text()


# ---------------------------------------------------------------------------
# FAIL fixture — the guarded defect (missing L8/L9 spec) must surface THROUGH
# the shim exactly as sdc_gen.main does it: exit 1, "FAIL: missing L8 or L9".
# ---------------------------------------------------------------------------
def test_shim_cli_missing_l_docs_fails(tmp_path):
    proj = _scaffold(tmp_path, with_l_docs=False)  # RTL present, no L8/L9
    cp = subprocess.run([sys.executable, str(SHIM), str(proj)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 1, (cp.returncode, cp.stdout, cp.stderr)
    assert "missing L8 or L9" in cp.stdout + cp.stderr


# ---------------------------------------------------------------------------
# Edge — absent/garbage project path: not-a-directory must return exit 2
# (sdc_gen's own contract), proving the shim does not swallow the error.
# ---------------------------------------------------------------------------
def test_shim_cli_nonexistent_project_returns_2(tmp_path):
    missing = tmp_path / "does_not_exist"
    cp = subprocess.run([sys.executable, str(SHIM), str(missing)],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 2, (cp.returncode, cp.stdout, cp.stderr)
    assert "not a directory" in cp.stdout + cp.stderr


# ---------------------------------------------------------------------------
# Library-import forwarding + DeprecationWarning emission (the shim's two
# remaining responsibilities beyond the CLI).
# ---------------------------------------------------------------------------
def test_shim_emits_deprecation_warning_on_import():
    # Import in a fresh subprocess so the module is not already cached, then
    # turn the DeprecationWarning into an error to prove it is actually raised.
    code = (
        "import warnings; warnings.simplefilter('error', DeprecationWarning)\n"
        "import sys; sys.path.insert(0, %r)\n"
        "try:\n"
        "    import aid_class_sdc_gen\n"
        "    print('NO_WARNING')\n"
        "except DeprecationWarning as e:\n"
        "    assert 'sdc_gen' in str(e), str(e)\n"
        "    print('WARNING_FIRED')\n"
    ) % str(SHIM.parent)
    cp = subprocess.run([sys.executable, "-c", code],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    assert "WARNING_FIRED" in cp.stdout, cp.stdout


def test_shim_reexports_sdc_gen_main():
    # `main` must be the SAME object as sdc_gen.main — i.e. the shim is a true
    # passthrough, not a divergent reimplementation.
    sys.path.insert(0, str(SHIM.parent))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import aid_class_sdc_gen as shim
        import sdc_gen
    assert shim.main is sdc_gen.main
    # A representative public symbol from the underlying generator must also
    # be visible through the shim (proves `from sdc_gen import *` ran).
    assert hasattr(shim, "main")
