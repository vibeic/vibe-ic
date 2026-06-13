"""ORGANIC #623 [HIGH] — Phase-3 auto-SDC `create_clock ... [get_ports <port>]`
bound a hardcoded canonical `clk` that did not match the synthesizable netlist
top clock port (e.g. `i_clk`), so TritonCTS reported CTS-0008 (0 clock nets) /
CTS-0082 and built no clock tree.

Fix: the resolver reads the ACTUAL post-synth netlist top module port list
(the literal artefact OpenROAD/CTS resolve `get_ports` against) and binds to
its real clock port, ranked above the L8/L9/RTL/SDC chain.

POSITIVE: a synth netlist whose top clock port is `i_clk` / `clk_i` / `wb_clk_i`
resolves to that exact port (resolution_path == 'post_synth_netlist_top_port'),
and the emitted SDC binds `[get_ports <that port>]`.

NEGATIVE no-leak:
  - no netlist on disk -> netlist reader returns None, the resolver falls
    through to the existing chain unchanged (fallback_literal_clk).
  - an explicit config.json CLOCK_PORT still WINS over the netlist read
    (#554 (b) preserved — a deliberate board-fact pin is not overridden).
  - a SUB-module's clock port does not leak in when the named top module is
    present but (hypothetically) carries no clock port surface we accept.

chip-AGNOSTIC: pure Verilog grammar + clock-port name regex; keyed on the
netlist's own clock port, never a fixed name literal.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase3_one_shot_runner as P  # noqa: E402


def _mk_soc(tmp_path, clk_port="i_clk", fname="chip_top_synth.v", top="chip_top"):
    synth = tmp_path / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / fname).write_text(
        f"module {top}({clk_port}, i_rst, o_gpio);\n"
        f"  input {clk_port};\n  input i_rst;\n  output [7:0] o_gpio;\n"
        f"  sky130_fd_sc_hd__clkbuf_4 _b0_ (.A({clk_port}), .X(_n0_));\n"
        f"endmodule\n")
    return tmp_path


def test_netlist_clock_port_wins(tmp_path):
    proj = _mk_soc(tmp_path, clk_port="i_clk")
    assert P._v1_6_623_extract_clock_port_from_netlist(proj, top="chip_top") == "i_clk"
    name, path = P._v1_6_595_resolve_clock_port_name(proj, top="chip_top")
    assert (name, path) == ("i_clk", "post_synth_netlist_top_port")
    _period, port = P._resolve_clock_spec(proj, top="chip_top")
    assert port == "i_clk", "the SDC create_clock must bind the netlist port"


def test_other_clock_naming_conventions(tmp_path):
    # Wishbone / suffix-i conventions all read from the netlist top port.
    for i, clk in enumerate(("clk_i", "wb_clk_i", "sys_clk")):
        sub = tmp_path / f"p{i}"
        sub.mkdir()
        proj = _mk_soc(sub, clk_port=clk)
        assert P._v1_6_623_extract_clock_port_from_netlist(proj, top="chip_top") == clk


def test_canonical_netlist_filenames(tmp_path):
    # netlist.v / netlist_yosys.v (no <top>_synth.v) are also consumed.
    for i, fname in enumerate(("netlist.v", "netlist_yosys.v")):
        sub = tmp_path / f"f{i}"
        sub.mkdir()
        proj = _mk_soc(sub, clk_port="i_clk", fname=fname)
        assert P._v1_6_623_extract_clock_port_from_netlist(proj, top="chip_top") == "i_clk"


def test_no_netlist_falls_through_unchanged(tmp_path):
    # No netlist, no L8/L9/RTL/SDC/config -> legacy fallback, reader None.
    assert P._v1_6_623_extract_clock_port_from_netlist(tmp_path, top="chip_top") is None
    name, path = P._v1_6_595_resolve_clock_port_name(tmp_path, top="chip_top")
    assert (name, path) == ("clk", "fallback_literal_clk")


def test_explicit_config_clock_port_still_wins(tmp_path):
    # #554 (b): a deliberate config CLOCK_PORT pin must NOT be overridden by
    # the netlist read, even when the netlist top port differs.
    proj = _mk_soc(tmp_path, clk_port="i_clk")
    (proj / "config.json").write_text(
        json.dumps({"CLOCK_PORT": "clk", "CLOCK_PERIOD": 10.0}))
    _period, port = P._resolve_clock_spec(proj, top="chip_top")
    assert port == "clk", "explicit config CLOCK_PORT must win (#554 b no-leak)"


def test_submodule_clock_does_not_leak(tmp_path):
    # The named top module is present and DOES carry a clock; a sub-module
    # listed afterwards must not be the one we return.
    synth = tmp_path / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text(
        "module chip_top(i_clk, i_rst);\n  input i_clk;\n  input i_rst;\n"
        "  core u_core(.clk_i(i_clk));\n"
        "endmodule\n"
        "module core(clk_i);\n  input clk_i;\nendmodule\n")
    # top module's own clock port (i_clk) wins, not the sub-module's clk_i.
    assert P._v1_6_623_extract_clock_port_from_netlist(tmp_path, top="chip_top") == "i_clk"


def test_text_helper_empty_and_garbage():
    assert P._v1_6_623_clock_port_in_netlist_text("", top="x") is None
    assert P._v1_6_623_clock_port_in_netlist_text("not verilog", top="x") is None
    # A module with no clock-matching port returns None (no false positive).
    assert P._v1_6_623_clock_port_in_netlist_text(
        "module m(d, q); input d; output q; endmodule", top="m") is None
