"""test_bsdl_escaped_identifier_ports.py — BSDL must not silently drop the
IEEE-1364 §3.7.1 ESCAPED identifier ports that a gate-level netlist is made of.

WHY THIS IS NOT A CORNER CASE
-----------------------------
`yosys ... splitnets -ports; write_verilog` emits every bus bit of the top
module as an escaped identifier — `\\gpio_io[3] ` — because `gpio_io[3]` is not
a legal plain Verilog identifier. That is the ORDINARY shape of the netlist
step 11 hands to `bsdl_emit`, not an exotic input.

`bsdl_emit.parse_top_ports` matched port names with `[A-Za-z_]\\w*`, which
cannot match a leading backslash, so every escaped port was dropped BEFORE the
boundary register was built. MEASURED on a real sky130-mapped OpenTitan AES
cipher core (30 926 cells): the netlist declares 1995 top ports and the parser
returned 14.

The failure mode is the dangerous one — not a crash and not a FAIL, but a
confident `verdict: PASS` carrying a boundary register that is missing exactly
the pads boundary scan exists to test. A BSDL whose boundary length disagrees
with silicon invalidates every EXTEST / SAMPLE interconnect test run against
it, and `dft_signoff_check` scores it `bsdl: PASS` on the way through.

NEGATIVE CONTROL: `test_padded_bus_pads_are_all_in_the_boundary_register` is
the bidirectional one — against the pre-fix parser it FAILS with
boundary_length 3 (clk_i, rst_ni, plain_out_o — i.e. every real pad missing),
and only the fix makes it 15.

chip-AGNOSTIC: the fixture is a synthetic 4-bit GPIO pad ring; nothing here is
specific to AES, sky130 or any design.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import bsdl_emit as bsdl  # noqa: E402


# A pad ring whose pads are bus BITS, i.e. escaped identifiers — the shape
# `splitnets -ports` produces. One plain-identifier port of each direction is
# kept alongside so the test also pins that plain names still work.
_PADDED_NETLIST = r"""
module chip_top(clk_i, rst_ni, \gpio_io[0] , \gpio_io[1] , \gpio_io[2] ,
                \gpio_io[3] , plain_out_o);
  input clk_i;
  input rst_ni;
  inout \gpio_io[0] ;
  inout \gpio_io[1] ;
  inout \gpio_io[2] ;
  inout \gpio_io[3] ;
  output plain_out_o;
  sky130_fd_io__top_gpiov2 pad0 (.PAD(\gpio_io[0] ));
  sky130_fd_io__top_gpiov2 pad1 (.PAD(\gpio_io[1] ));
  sky130_fd_io__top_gpiov2 pad2 (.PAD(\gpio_io[2] ));
  sky130_fd_io__top_gpiov2 pad3 (.PAD(\gpio_io[3] ));
endmodule
"""


def _emit(tmp_path: Path, netlist: str) -> dict:
    proj = tmp_path / "proj"
    (proj / "phase2" / "stage2" / "dft").mkdir(parents=True)
    (proj / "reports" / "phase2" / "dft").mkdir(parents=True)
    nl = proj / "netlist.v"
    nl.write_text(netlist)
    out = proj / "reports" / "phase2" / "dft" / "bsdl_plan.json"
    subprocess.run(
        [sys.executable, str(PROG_DIR / "bsdl_emit.py"), str(proj),
         "--netlist", "netlist.v", "--top", "chip_top",
         "--json", str(out)],
        capture_output=True, text=True, cwd=str(proj))
    assert out.exists(), "bsdl_emit wrote no plan at all"
    return json.loads(out.read_text())


# ════════════════════════════════════════════════════════════════════════
# The parser
# ════════════════════════════════════════════════════════════════════════

def test_escaped_identifier_ports_are_parsed_not_dropped():
    """An escaped bus-bit port is a port. Pre-fix this returned 3 of 7."""
    ports = bsdl.parse_top_ports(_PADDED_NETLIST, "chip_top")
    names = {p.name for p in ports}
    assert "gpio_io" in names, (
        f"escaped bus-bit pads dropped by the port parser; got {sorted(names)}")
    assert {"clk_i", "rst_ni", "plain_out_o"} <= names, (
        "the fix must not cost the plain-identifier ports")


def test_split_bits_are_coalesced_into_one_vector_port():
    """`\\gpio_io[0..3]` is ONE 4-bit inout, so the BSDL port declaration is
    legal VHDL (`bit_vector(3 downto 0)`) rather than `gpio_io[3] : inout
    bit`."""
    ports = {p.name: p for p in bsdl.parse_top_ports(_PADDED_NETLIST,
                                                     "chip_top")}
    g = ports["gpio_io"]
    assert (g.direction, g.width, g.msb, g.lsb) == ("inout", 4, 3, 0)


def test_incomplete_bit_range_is_not_folded_into_invented_pads():
    """Over-counting a boundary register is the same class of error as
    under-counting it: a gappy index set stays as the bits actually declared
    and is never widened into a contiguous range."""
    gappy = r"""
module chip_top(\d[0] , \d[3] );
  inout \d[0] ;
  inout \d[3] ;
  sky130_fd_io__top_gpiov2 p0 (.PAD(\d[0] ));
endmodule
"""
    names = [p.name for p in bsdl.parse_top_ports(gappy, "chip_top")]
    assert names == ["d[0]", "d[3]"], (
        f"gappy range must not become a 4-bit vector; got {names}")


# ════════════════════════════════════════════════════════════════════════
# End-to-end: the boundary register the ATE actually shifts
# ════════════════════════════════════════════════════════════════════════

def test_padded_bus_pads_are_all_in_the_boundary_register(tmp_path):
    """THE NEGATIVE CONTROL. 4 inout pads (3 BSCs each) + clk_i + rst_ni +
    plain_out_o (1 each) = 15. The pre-fix parser produced 3 — a PASS verdict
    on a boundary register containing none of the pads."""
    plan = _emit(tmp_path, _PADDED_NETLIST)
    assert plan["classification"] == "PADDED"
    assert plan["verdict"] == "PASS"
    assert plan["boundary_length"] == 15, (
        f"boundary register is wrong length: {plan['boundary_length']} "
        f"(pins={plan.get('boundary_scan_pins')})")
    scanned = plan["boundary_scan_pins"]
    for i in range(4):
        assert f"gpio_io[{i}]" in scanned, (
            f"pad gpio_io[{i}] absent from the boundary register — the BSDL "
            f"would not match silicon; got {scanned}")


def test_bsdl_file_declares_the_pad_bus(tmp_path):
    """The emitted .bsdl text itself must carry the pad bus, not just the
    JSON plan."""
    _emit(tmp_path, _PADDED_NETLIST)
    bsdl_files = list((tmp_path / "proj").rglob("*.bsdl"))
    assert bsdl_files, "no .bsdl emitted for a padded design"
    text = bsdl_files[0].read_text()
    assert "gpio_io" in text, "pad bus missing from the BSDL entity"
    assert "bit_vector(3 downto 0)" in text, (
        "pad bus must be declared as a vector, not per-bit illegal names")


def test_bare_core_with_escaped_ports_is_still_honest_n_a(tmp_path):
    """The fix must not turn a bare core into a padded one: no pad cells and
    no inout means N_A, escaped identifiers or not."""
    bare = r"""
module chip_top(clk_i, \d_o[0] , \d_o[1] );
  input clk_i;
  output \d_o[0] ;
  output \d_o[1] ;
endmodule
"""
    plan = _emit(tmp_path, bare)
    assert plan["classification"] == "BARE"
    assert plan["verdict"] == "N_A"
