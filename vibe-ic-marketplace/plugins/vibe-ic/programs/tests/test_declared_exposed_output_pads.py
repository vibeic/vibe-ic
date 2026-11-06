"""A declared reused-IP output split must reach the chip pad wrapper.

The actual consumer is the Phase-3 core-connection backstop. It rejected a
wrapper whose L9 list omitted two implementation-chosen subports, even though
the SOURCE_MANIFEST had already declared the split to Phase 2.
"""
import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

import test_io_pad_chip_top_gen as IO  # noqa: E402

GEN = PROGRAMS / "io_pad_chip_top_gen.py"
DOC = """# L3 — External Interface
The I/O cell library is delegated to the PDK i/o pad defaults.
## Physical Pad Placement
| Pad side | signals |
|---|---|
| **North (N)** | memory data bus |
| **South (S)** | memory addr + control(cyc) |
| **East (E)** | `clk` / `rst` |
| **West (W)** | status pin(s) |
"""
PORTS = [
    {"name": "clk", "direction": "input", "width": 1},
    {"name": "rst", "direction": "input", "width": 1},
    {"name": "o_status", "direction": "output", "width": 1},
    {"name": "o_memory_data", "direction": "output", "width": 2},
    {"name": "o_memory_addr", "direction": "output", "width": 2},
    {"name": "o_memory_cyc", "direction": "output", "width": 1},
]
SPEC = {"top_module": "core", "top_ports": PORTS}
NETLIST = """module core(clk,rst,o_status,o_memory_data,o_memory_addr,o_memory_cyc,o_memory_waddr,o_memory_ren);
input clk;
input rst;
output o_status;
output o_memory_cyc;
output o_memory_ren;
output [1:0] o_memory_data;
output [1:0] o_memory_addr;
output [1:0] o_memory_waddr;
endmodule
"""
SPLITS = [
    {"l9": "o_memory_addr", "rtl": ["o_memory_waddr"],
     "rationale": "Separate same-width read and write addresses on this memory."},
    {"l9": "o_memory_cyc", "rtl": ["o_memory_ren"],
     "rationale": "The chosen bus exposes read-enable beside cycle."},
]


def _case(tmp_path, *, splits=SPLITS, reused=True, netlist=NETLIST):
    proj = IO._project(tmp_path, doc=DOC, spec=SPEC)
    synth = proj / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / "core_synth.v").write_text(netlist)
    rtl = proj / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(
        {"reused_ip": reused, "flattened_outputs": splits}))
    pdk = IO._pdk(tmp_path / "pdk")
    result = IO._run(GEN, proj, pdk)
    return proj, result




def test_unmeasured_or_unmatched_split_cannot_mint_a_pad(tmp_path):
    wrong_width = NETLIST.replace(
        "output [1:0] o_memory_waddr;",
        "output [2:0] o_memory_waddr;")
    proj, result = _case(tmp_path, netlist=wrong_width)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "EXPOSED_OUTPUT_SPLIT_INVALID" in result.stdout + result.stderr
    assert not (proj / "phase3/stage3/pnr/chip_top_io.v").exists()
