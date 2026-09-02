"""Everything the DUT needs, driven — measured against the real 131-file RTL.

Five things the generated testbench got wrong, each found by ELABORATING and
RUNNING against opentitan_aes's own RTL in the pinned image, not by reading:

  * an unconnected input is not a neutral default. `rst_shadowed_ni` left open
    read as 0 — a second reset held asserted forever — and the run HUNG;
  * a second CLOCK tied to 0 does not tick, and the interface behind it freezes;
  * an unbounded handshake wait cannot time out. The first hang produced no
    verdict at all because the wait for `a_ready` had no budget of its own;
  * a device that CHECKS request integrity rejects a host that does not
    generate it. Every read came back `ffffffff` — the bus package's own
    `DataWhenError` — with `d_error=1`, until the sequence drove through the
    design's own generator;
  * a SHADOWED control register takes effect only on the second identical
    write, and the register's own NAME says it is shadowed.

Bidirectional throughout: each rule fires only on the shape that carries it,
and a DUT without that shape is untouched.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v1_16_32_register_bus_vector_driver import (  # noqa: E402
    BUS_PKG, CASE, DOCS, _l4, _l15)

# (direction, width, name) — the order resolve_dut yields.
PORTS = [("input", "", "clk_i"), ("input", "", "rst_ni"),
         ("input", "", "rst_shadowed_ni"), ("input", "", "clk_edn_i"),
         ("input", "", "rst_edn_ni"), ("input", "", "lc_escalate_en_i"),
         ("input", "", "tl_i"), ("output", "", "tl_o")]

INTG_GEN = {"module": "tlul_cmd_intg_gen", "in": "tl_i", "out": "tl_o",
            "file": "input/vendor_rtl/tlul/tlul_cmd_intg_gen.sv"}


def _tb(**kw):
    import register_bus_driver_gen as D
    plan, why = D.resolve_register_plan(CASE, kw.pop("l4", None) or _l4(),
                                        _l15(), DOCS)
    assert plan, why
    bus, _ = D.bus_contract(BUS_PKG)
    return D.emit_sequence_tb(CASE, plan, bus, "chip_top", "tl_i", "tl_o",
                              "clk_i", "rst_ni", ports=PORTS, **kw)


def test_every_input_port_is_connected():
    """The load-bearing red: an open input is a value nobody chose."""
    body = _tb()
    inst = [l for l in body.splitlines() if "chip_top dut (" in l][0]
    for _d, _w, n in PORTS:
        if _d == "input":
            assert f".{n}(" in inst, (n, inst)


def test_a_second_reset_is_released_and_a_second_clock_ticks():
    body = _tb()
    assert "reg rst_shadowed_ni = 1'b0;" in body
    assert "rst_shadowed_ni = 1'b1;" in body, "the second reset is never released"
    assert ".clk_edn_i(clk_i)" in body, "a second clock is tied off and cannot tick"
    # and a port that is neither is tied to a literal, said so
    assert ".lc_escalate_en_i('0)" in body


def test_every_wait_has_its_own_budget():
    """A hang produces no verdict. Each handshake wait times out and FAILS."""
    body = _tb()
    waits = [l for l in body.splitlines() if "while (!" in l]
    assert len(waits) >= 3, waits
    assert body.count("stall > 20000") >= 3, body.count("stall > 20000")
    assert "never accepted a write" in body
    assert "never accepted a read" in body
    assert "never returned data" in body


def test_the_request_goes_through_the_designs_own_integrity_generator():
    body = _tb(intg_gen=INTG_GEN)
    assert "tlul_cmd_intg_gen u_intg (.tl_i(tl_i_raw), .tl_o(tl_i));" in body
    assert "tl_i_raw.a_valid" in body, "the sequence must drive the RAW signal"
    assert ".tl_i(tl_i)" in body, "the DUT must see the generated request"


def test_without_a_generator_the_sequence_drives_the_bus_directly():
    """Over-reach control: a bus with no integrity check is not wrapped."""
    body = _tb()
    assert "u_intg" not in body
    assert "tl_i.a_valid" in body


def test_a_shadowed_control_register_is_written_twice():
    import register_bus_driver_gen as D
    body = _tb()
    assert body.count("bus_write(32'h00000074") == 2, body
    assert "the register's own name says it is shadowed" in body
    # Over-reach control: a control register that is NOT shadowed is written once.
    l4 = _l4()
    for r in l4["registers"]:
        if r["name"] == "CTRL_SHADOWED":
            r["name"] = "CTRL"
    plan, why = D.resolve_register_plan(CASE, l4, _l15(), DOCS)
    assert plan, why
    assert plan["ctrl_shadowed"] is False
    bus, _ = D.bus_contract(BUS_PKG)
    once = D.emit_sequence_tb(CASE, plan, bus, "chip_top", "tl_i", "tl_o",
                              "clk_i", "rst_ni", ports=PORTS)
    assert once.count("bus_write(32'h00000074") == 1


def test_the_generator_is_found_by_what_it_does_not_by_its_name():
    """A pass-through alone is not a generator — `tlul_adapter_racl` has the
    same port shape and filters access. The discriminator is that the body
    instantiates an ECC encoder."""
    import register_bus_driver_gen as D
    racl = ("module tlul_adapter_racl (input bus_pkg::bus_h2d_t tl_h2d_i,"
            " output bus_pkg::bus_h2d_t tl_filtered_h2d_o); endmodule")
    gen = ("module the_gen (input bus_pkg::bus_h2d_t tl_i,"
           " output bus_pkg::bus_h2d_t tl_o);"
           " prim_secded_inv_64_57_enc u_enc (.data_i(x), .data_o(y));"
           " endmodule")
    found, why = D.find_host_intg_gen([("a.sv", racl)], "bus_pkg::bus_h2d_t")
    assert found is None, found
    assert "pass-through" in why, why
    found2, _ = D.find_host_intg_gen([("a.sv", racl), ("b.sv", gen)],
                                     "bus_pkg::bus_h2d_t")
    assert found2 and found2["module"] == "the_gen", found2
