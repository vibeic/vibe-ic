"""Native electrical terminals and document-owned pad groups."""
import json
import shutil
import subprocess

import pytest

import flow_chip_inputs as chip


def _wrapper(ports, terminal_direction="inout"):
    chosen = {}
    cells = {}
    for port in ports:
        master = "receiver" if port["direction"] == "input" else "driver"
        core_pin = "SENSE" if master == "receiver" else "DRIVE"
        cells[master] = {"BOND": {"direction": terminal_direction}}
        for bit in chip._bits(port):
            chosen[f"pad_{len(chosen)}"] = {"master": master, "port": bit,
                "terminal": "BOND", "core_pin": core_pin}
    native = {"SYNTH_TIEHI_CELL": "hi/Y", "SYNTH_TIELO_CELL": "lo/Y"}
    return chip._wrapper("core", "chip_top", ports, chosen, {"N": list(chosen)}, [],
                         native, {"cells": cells, "verilog": [], "pg_pins": {}})


def _port(name, direction, width=1):
    return {"name": name, "direction": direction, "width": width,
            "indexed": width > 1, "msb": width - 1, "lsb": 0}


def test_synthesis_retains_a_selected_pad_with_unused_core_input(tmp_path):
    yosys = shutil.which("yosys")
    if not yosys:
        pytest.skip("native Yosys required")
    # An input-only pad is legal too; an unused core input does not remove
    # the physical pad named in PAD_NORTH and its power connections.
    ports = [_port("unused", "input")]
    (tmp_path / "design.v").write_text(_wrapper(ports, "input") +
                                      "module core(input unused); endmodule\n")
    (tmp_path / "models.v").write_text(
        "(* blackbox *) module receiver(input BOND, output SENSE); endmodule\n")
    run = subprocess.run([yosys, "-Q", "-T", "-p",
        "read_verilog -lib models.v; read_verilog design.v; synth -top chip_top; write_json result.json"],
        cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    cells = json.loads((tmp_path / "result.json").read_text())["modules"]["chip_top"]["cells"]
    assert cells["pad_0"]["type"] == "receiver"


@pytest.mark.parametrize("control_note", ["", " (we / cyc)"])
def test_group_sides_follow_interface_descriptions_without_manifest(tmp_path, control_note):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "L3_interface.md").write_text("""
| Port | Width | Direction | Description |
|---|---|---|---|
| `o_cache_addr` | 5 | output | Cache address |
| `o_cache_data` (or `o_cache_wdata`) | 8 | output | Cache write data |
| `i_cache_data` (or `i_cache_rdata`) | 8 | input | Cache read data |
| `o_cache_we` | 1 | output | Cache write enable |
| `o_cache_cyc` | 1 | output | Cache cycle active |
| `o_flags` | 1 | output | General purpose GPIO output |
""")
    (docs / "L9_floorplan.md").write_text(f"""
## Pad placement
| Side | Signal group |
|---|---|
| North | Cache data bus |
| South | Cache addr + control{control_note} |
| East | `clock` |
| West | GPIO pins |
""")
    groups = {"N": [_port("o_cache_wdata", "output", 8), _port("i_cache_rdata", "input", 8)],
              "S": [_port("o_cache_waddr", "output", 5), _port("o_cache_raddr", "output", 5),
                    _port("o_cache_wen", "output"), _port("o_cache_cyc", "output")],
              "E": [_port("clock", "input")], "W": [_port("o_flags", "output")]}
    ports = [port for group in groups.values() for port in group]
    sides, _, _ = chip._side_ports(tmp_path, ports)
    assert {side: set(nets) for side, nets in sides.items()} == {
        side: {bit for port in group for bit in chip._bits(port)} for side, group in groups.items()}


def test_unrecognized_pad_group_stays_unresolved(tmp_path):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "L9_floorplan.md").write_text("""
## Pad placement
| Side | Signal group |
|---|---|
| North | Optical link lanes |
""")
    with pytest.raises(ValueError, match="Unresolved pad placement groups"):
        chip._side_ports(tmp_path, [_port("clock", "input")])
