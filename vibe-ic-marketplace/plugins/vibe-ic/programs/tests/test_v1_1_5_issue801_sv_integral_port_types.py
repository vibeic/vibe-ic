"""ORGANIC #801 (extends #792) — the shared ANSI-port parser `_NET_QUAL_RE`
omitted the SystemVerilog integral/numeric DATA TYPES, so `input bit clk_in`
parsed as ('input','','bit') — the type `bit` eaten as the port name, the real
port `clk_in` dropped → a downstream latency TB emitted `reg bit;`/`.bit(bit)`
(reserved keyword + non-existent port) → rc=2 compile crash on spec-faithful RTL.

FIX: add bit|byte|int|integer|shortint|longint|time|real|shortreal|realtime to
the whole-word net-qual alternation. §4.05: all SV reserved keywords (never legal
port names), so a header with no SV data-type qualifier is byte-identical.
chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import reset_clock_variant_alias as V  # noqa: E402


@pytest.mark.parametrize("decl,want", [
    ("module m(input bit clk_in, output bit q); endmodule", ["clk_in", "q"]),
    ("module m(input byte d, input int cnt, output time t); endmodule",
     ["d", "cnt", "t"]),
    ("module m(input shortint a, input longint b, input integer c); endmodule",
     ["a", "b", "c"]),
    ("module m(input real r, input shortreal sr, input realtime rt); endmodule",
     ["r", "sr", "rt"]),
    # back-compat: no SV data type → byte-identical
    ("module m(input logic [7:0] data, output reg [3:0] q); endmodule",
     ["data", "q"]),
    ("module m(input clk, input tri1 rst_n); endmodule", ["clk", "rst_n"]),
])
def test_801_sv_integral_type_not_eaten_as_port_name(decl, want):
    got = [p[2] for p in V.parse_module_ports(decl, "m")]
    assert got == want, (decl, got)


def test_801_int_does_not_preempt_integer():
    # whole-word \b alternation must not let bare `int` swallow `integer`.
    got = [p[2] for p in V.parse_module_ports(
        "module m(input integer wide); endmodule", "m")]
    assert got == ["wide"]


# ── END-STATE: the `input bit <clk>` design no longer crashes the latency TB
#    (rc=2 "reg bit;" compile crash gone) — run the real program via subprocess. ─
import shutil    # noqa: E402
import subprocess  # noqa: E402

_IV = shutil.which("iverilog") and shutil.which("vvp")


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_801_endstate_bit_clock_no_latency_compile_crash(tmp_path):
    rtl = ("module fsm_seq(input bit clk, input rst_n, input din,"
           " output reg detected);\n"
           " always @(posedge clk or negedge rst_n)"
           " if(!rst_n) detected<=0; else detected<=din;\nendmodule")
    f = tmp_path / "fsm_seq.v"
    f.write_text(rtl)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "latency_conformance_check.py"),
         "--rtl", str(f), "--top", "fsm_seq", "--event", "din",
         "--output", "detected", "--expect", "1", "--allow-no-handshake"],
        capture_output=True, text=True)
    # the DEFECT was rc=2 (the `bit` type eaten → `reg bit;`/`.bit(bit)` compile
    # crash). The real port `clk` now parses, so it never compile-crashes.
    assert r.returncode != 2, (r.stdout + r.stderr)
    assert "Cannot" not in r.stderr and "reg bit" not in (r.stdout + r.stderr)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
