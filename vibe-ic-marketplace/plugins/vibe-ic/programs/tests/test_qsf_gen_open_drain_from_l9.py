"""Wave 73 (v0.128) S3 — open-drain from L9 port flag.

Pre-Wave-73 the open-drain set was a hard-coded list including the
chip-internal port name "id_bus". This made qsf_gen.py implicitly
EXAMPLE_PROTOCOL-class biased: any other chip whose half-duplex port wasn't
literally named "id_bus" would silently lose its OUTPUT_OPEN_DRAIN
attribute. Wave 73 drives open-drain from L9
top_module_pins[i].open_drain instead, while keeping the board-side
GPIO_0[0] entry (a physical DE10-Lite pin attribute).

These tests pin the new contract.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAM = (
    Path(__file__).resolve().parent.parent / "qsf_gen.py"
)


def _scaffold(tmp_path: Path, port_specs: list,
              data_port_name: str = "id_bus") -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    l9 = {
        "schema_version": 2,
        "ic_name": "TEST_IC",
        "top_module": "chip_top",
        "top_module_pins": port_specs,
    }
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(l9))
    (proj / "phase2" / "stage1" / "rtl" / "chip_top.sv").write_text(
        f"module chip_top(input wire clk, input wire reset_n, "
        f"inout wire {data_port_name}); endmodule\n")
    return proj


def _run(proj: Path) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROGRAM), str(proj)],
        capture_output=True, text=True)


def test_l9_open_drain_flag_emits_output_open_drain(tmp_path):
    """An L9 entry with open_drain=true must produce
    `set_instance_assignment -name OUTPUT_OPEN_DRAIN ON -to <sig>`.

    Uses id_bus port name (mapped to GPIO_0[0] by the IC-namespace
    convention) to keep the test focused on the open_drain flag, not
    on board-pin allocation.
    """
    proj = _scaffold(tmp_path, [
        {"name": "clk",     "mode": "input",  "io": "1.8V"},
        {"name": "reset_n", "mode": "input",  "io": "1.8V"},
        {"name": "id_bus",  "mode": "inout",  "io": "1.8V",
         "open_drain": True},
    ])
    cp = _run(proj)
    assert cp.returncode == 0, cp.stderr
    qsf = (proj / "phase2" / "stage1" / "fpga" / "chip_top.qsf").read_text()
    # id_bus maps to GPIO_0[0] via _ic_port_to_board_signal.
    assert "OUTPUT_OPEN_DRAIN ON -to GPIO_0[0]" in qsf, qsf


def test_no_open_drain_flag_does_not_emit_output_open_drain(tmp_path):
    """A normal inout without open_drain flag and without an
    'open-drain' io string must NOT get OUTPUT_OPEN_DRAIN.

    Uses 'data' port (also mapped to GPIO_0[0]) so we exercise the
    path where _build_port_assignments_from_l9 sees an inout and must
    decide whether to set output_open_drain. Pre-Wave-73 the
    hard-coded list would have leaked open-drain onto any port named
    'id_bus'; now only an explicit L9 flag does so.
    """
    proj = _scaffold(tmp_path, [
        {"name": "clk",     "mode": "input",  "io": "1.8V"},
        {"name": "reset_n", "mode": "input",  "io": "1.8V"},
        # plain inout, no open_drain flag, no "open-drain" io string.
        {"name": "data",    "mode": "inout",  "io": "1.8V"},
    ], data_port_name="data")
    cp = _run(proj)
    assert cp.returncode == 0, cp.stderr
    qsf = (proj / "phase2" / "stage1" / "fpga" / "chip_top.qsf").read_text()
    assert "OUTPUT_OPEN_DRAIN" not in qsf, (
        "OUTPUT_OPEN_DRAIN must only appear when L9 explicitly says so "
        "or io=open-drain; otherwise board-only GPIO_0[0] would "
        "leak open-drain semantics onto chip-internal nets.\n" + qsf
    )
    # weak pull-up on inout is still legacy-OK
    assert "WEAK_PULL_UP_RESISTOR ON -to GPIO_0[0]" in qsf
