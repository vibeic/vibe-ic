"""Round-13 cluster R13C1 regression — spec_coverage_check.py signedness/byte_order
prose-heuristic corroboration.

ROOT CAUSE (v1.1.10): spec_coverage_check.run()'s #770 provenance-corroboration
loop had downgrade branches for reset/latency/handshake/enum_set/worked_example
but NONE for `signedness` (or `byte_order`). So for a prose-only signedness item
`corr` stayed _prov.UNKNOWN and is_block_eligible(PROSE_HEURISTIC, UNKNOWN)=True,
hard-blocking (--strict rc=1) correct UNSIGNED RTL whose prose merely says
"unsigned integers" (Verilog's default; the RTL has no `signed` keyword). There is
no behavioral gap a faithful TB could cover — the BLOCK was unclearable on every
spec-faithful unsigned design (cvdp_copilot_montgomery_0001; reproduced on an
independent minimal unsigned adder).

FIX: add a corroboration branch for kind in {signedness, byte_order} mirroring
handshake — corroborate against whether the RTL STRUCTURALLY declares `signed`:
  * RTL declares no `signed` (unsigned-by-default)  -> NO_CORROBORATION -> advisory (rc 0)
  * RTL genuinely declares `signed` (e.g. 16qam)     -> CORROBORATED    -> still BLOCK
  * no RTL supplied                                  -> UNKNOWN          -> still BLOCK

This test asserts (a) the POSITIVE unsigned design now passes --strict, and
(b) a §4.05 NEGATIVE genuinely-signed design with an uncovered signedness item
STILL hard-blocks (no-leak).
"""
import subprocess
import sys
from pathlib import Path

import pytest

# Resolve the programs/ dir. In CI the test lives at programs/tests/, so
# parent.parent IS the programs dir; VIBE_PROGRAMS overrides for staged runs.
import os
_HERE = Path(__file__).resolve()
_CANDIDATES = [Path(os.environ["VIBE_PROGRAMS"])] if os.environ.get("VIBE_PROGRAMS") else []
_CANDIDATES += [_HERE.parent.parent, _HERE.parent]
PROGRAMS = next((p for p in _CANDIDATES if (p / "spec_coverage_check.py").exists()), None)
assert PROGRAMS is not None, f"spec_coverage_check.py not found in {_CANDIDATES}"
GATE = PROGRAMS / "spec_coverage_check.py"


def _run_strict(tmp_path, spec_md, rtl_sv, tb_sv, rtl_name="dut.sv"):
    spec = tmp_path / "spec.md"
    rtl = tmp_path / rtl_name
    tb = tmp_path / "tb.sv"
    spec.write_text(spec_md)
    rtl.write_text(rtl_sv)
    tb.write_text(tb_sv)
    proc = subprocess.run(
        [sys.executable, str(GATE), "--prompt", str(spec),
         "--rtl", str(rtl), "--tb", str(tb), "--strict"],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


# --- POSITIVE: correct UNSIGNED RTL (Verilog default), no `signed` keyword ---
_UNSIGNED_SPEC = """# adder — unsigned add
The module efficiently computes modular arithmetic of **unsigned integers**.

## Ports
- input  wire [7:0] a
- input  wire [7:0] b
- output wire [8:0] y
"""
_UNSIGNED_RTL = """module dut(
    input  wire [7:0] a,
    input  wire [7:0] b,
    output wire [8:0] y
);
    assign y = a + b;
endmodule
"""
_UNSIGNED_TB = """module tb;
  reg [7:0] a, b;
  wire [8:0] y;
  dut u(.a(a), .b(b), .y(y));
  initial begin a=8'd3; b=8'd4; #1; if (y!==9'd7) $display("FAIL"); $finish; end
endmodule
"""

# --- NEGATIVE (§4.05 no-leak): genuinely SIGNED RTL, signedness UNCOVERED -----
# The RTL declares `signed` ports/ops (genuinely signed). The prose says signed.
# The TB drives the design but never echoes the literal token 'signed', so the
# signedness item is an uncovered, genuine coverage gap that MUST keep blocking.
_SIGNED_SPEC = """# qam_mapper — signed I/Q mapper
The module maps input bits to **signed** two's complement amplitudes.

## Ports
- input  wire [3:0] data_in
- output wire signed [7:0] amp_out
"""
_SIGNED_RTL = """module dut(
    input  wire [3:0]        data_in,
    output wire signed [7:0] amp_out
);
    assign amp_out = $signed(data_in[1:0]) * 8'sd3;
endmodule
"""
_SIGNED_TB = """module tb;
  reg [3:0] data_in;
  wire [7:0] amp_out;
  dut u(.data_in(data_in), .amp_out(amp_out));
  initial begin data_in = 4'b0110; #1; $finish; end
endmodule
"""


def test_positive_unsigned_default_no_longer_blocks(tmp_path):
    """Correct unsigned-by-default RTL with prose 'unsigned integers' must NOT
    hard-block under --strict (rc 0); the signedness item is advisory."""
    rc, out = _run_strict(tmp_path, _UNSIGNED_SPEC, _UNSIGNED_RTL, _UNSIGNED_TB)
    assert rc == 0, f"unsigned-default design hard-blocked (rc={rc}):\n{out}"
    # the signedness item should now be reported as advisory, not a blocking GAP
    assert "ADVISORY" in out and "signedness" in out.lower(), out
    assert "[STRICT/sole-emit] BLOCK" not in out, out


def test_negative_genuinely_signed_uncovered_still_blocks(tmp_path):
    """§4.05 no-leak: a genuinely-signed RTL (declares `signed`) whose signedness
    item is uncovered by the TB MUST still hard-block under --strict (rc!=0)."""
    rc, out = _run_strict(tmp_path, _SIGNED_SPEC, _SIGNED_RTL, _SIGNED_TB)
    assert rc != 0, f"genuinely-signed uncovered design LEAKED (rc={rc}):\n{out}"
    assert "[STRICT/sole-emit] BLOCK" in out, out
    assert "signedness" in out.lower() and "UNCOVERED" in out, out


def test_signed_detector_tristate():
    """Unit-level: _rtl_declares_signed is True for signed RTL, False for plain
    unsigned RTL, None when no RTL is supplied (the corroboration tri-state)."""
    sys.path.insert(0, str(PROGRAMS))
    import spec_coverage_check as scc
    assert scc._rtl_declares_signed(_SIGNED_RTL) is True
    assert scc._rtl_declares_signed(_UNSIGNED_RTL) is False
    assert scc._rtl_declares_signed(None) is None
    # the bare `unsigned` keyword must NOT be read as a signed declaration
    assert scc._rtl_declares_signed(
        "module m(input wire unsigned [7:0] a, output wire [7:0] y);"
        "assign y=a; endmodule") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
