"""ORGANIC #804 (extends #786) — fsm_error_invariant hard-blocked the canonical
APB bad-address response `default: pslverr <= 1'b1;` in an address-decode
`case(paddr)`. `pslverr` matches the error-name regex via `err`, and the
`default:` branch inherited the prior numeric case label (8'h0f) so the
numeric-aware fault-state exemption did not cover it.

FIX: reset current_state_label + flag the default branch on entry (incl. the
single-line `default: <body>` form); exempt a standard bus-protocol error
RESPONSE (PSLVERR/SLVERR/BRESP/RRESP/HRESP/ERR_O/DECERR) asserted in the
`default:` of an ADDRESS-DECODE (*addr*/*adr*) case.

§4.05: a generic error in the addr default, a bus-resp in a non-addr case, a
bus-resp in a mapped (non-default) branch, and any mid-FSM error all still fire.
chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fsm_error_invariant as F  # noqa: E402


def _fires(src):
    return len(F.find_error_assertions(src, "d.v")) > 0


_POS = """\
module apb(input [7:0] paddr, output reg pslverr);
  always @(*) begin
    case (paddr)
      8'h00:   pslverr <= 1'b0;
      8'h0f:   pslverr <= 1'b0;
      default: pslverr <= 1'b1;
    endcase
  end
endmodule
"""

_POS_MULTILINE = """\
module apb(input [7:0] haddr, output reg hresp);
  always @(*) begin
    case (haddr)
      8'h00: hresp <= 1'b0;
      default: begin
        hresp <= 1'b1;
      end
    endcase
  end
endmodule
"""

_NEG_GENERIC = """\
module apb(input [7:0] paddr, output reg error_flag);
  always @(*) begin
    case (paddr)
      8'h00:   error_flag <= 1'b0;
      default: error_flag <= 1'b1;
    endcase
  end
endmodule
"""

_NEG_NONADDR = """\
module m(input [3:0] state, output reg pslverr);
  always @(*) begin
    case (state)
      4'h0:    pslverr <= 1'b0;
      default: pslverr <= 1'b1;
    endcase
  end
endmodule
"""

_NEG_MAPPED = """\
module m(input [7:0] paddr, output reg pslverr);
  always @(*) begin
    case (paddr)
      8'h00:   pslverr <= 1'b1;
      default: pslverr <= 1'b0;
    endcase
  end
endmodule
"""


def test_804_pslverr_in_addr_decode_default_is_exempt():
    assert _fires(_POS) is False


def test_804_hresp_multiline_addr_default_is_exempt():
    assert _fires(_POS_MULTILINE) is False


def test_804_noleak_generic_error_in_addr_default_still_fires():
    assert _fires(_NEG_GENERIC) is True


def test_804_noleak_pslverr_in_nonaddr_default_still_fires():
    assert _fires(_NEG_NONADDR) is True


def test_804_noleak_pslverr_in_mapped_branch_still_fires():
    assert _fires(_NEG_MAPPED) is True


# ── Step-2.7 §4.05 — the exemption must NOT swallow a genuine functional-error
#    flag (crc_err_o/parity_err_o) in a FIFO-pointer case, nor an addr-substring
#    word (squadron). ───────────────────────────────────────────────────────
@pytest.mark.parametrize("sig", ["crc_err_o", "parity_err_o", "rx_err_out",
                                 "timeout_err_o", "fifo_err_o"])
def test_804_noleak_functional_error_flag_in_pointer_case_still_fires(sig):
    src = (f"module rx(input clk, input [2:0] rd_addr, output reg {sig});\n"
           " always @(posedge clk) begin\n   case (rd_addr)\n"
           f"     3'd0: {sig} <= 1'b0;\n     3'd1: {sig} <= 1'b0;\n"
           f"     default: {sig} <= 1'b1;\n   endcase\n end\nendmodule")
    assert _fires(src) is True


def test_804_noleak_addr_substring_word_selector_still_fires():
    # `squadron` merely CONTAINS 'adr' as a substring — NOT an address decode.
    src = ("module m(input [3:0] squadron, output reg pslverr);\n"
           " always @(*) begin\n   case (squadron)\n"
           "     4'h0: pslverr <= 1'b0;\n     default: pslverr <= 1'b1;\n"
           "   endcase\n end\nendmodule")
    assert _fires(src) is True


def test_804_bare_wishbone_err_o_in_addr_default_still_exempt():
    src = ("module wb(input [7:0] adr_i, output reg err_o);\n"
           " always @(*) begin\n   case (adr_i)\n"
           "     8'h00: err_o <= 1'b0;\n     default: err_o <= 1'b1;\n"
           "   endcase\n end\nendmodule")
    assert _fires(src) is False


def test_804_noleak_mid_fsm_error_in_numbered_state_still_fires():
    src = ("module m(input clk, output reg err);\n reg [1:0] st;\n"
           " always @(posedge clk) case (st)\n"
           "   2'd0: err <= 1'b0;\n   2'd1: err <= 1'b1;\n"
           "   default: st <= 2'd0;\n endcase\nendmodule")
    assert _fires(src) is True


# ── END-STATE: the real fsm_error_invariant program exits 0 (exempt) on the APB
#    pslverr addr-decode default, but exits 1 on a genuine functional error. ────
import subprocess  # noqa: E402


def test_804_endstate_apb_pslverr_exempt_via_program(tmp_path):
    # the issue 現象 (fan_controller_0005): `default: pslverr <= 1'b1;` in an
    # address-decode case(paddr) — the canonical APB bad-address response.
    rtl = ("module apb(input [7:0] paddr, output reg pslverr);\n"
           "  always @(*) begin\n    case (paddr)\n"
           "      8'h00:   pslverr <= 1'b0;\n"
           "      8'h0f:   pslverr <= 1'b0;\n"
           "      default: pslverr <= 1'b1;\n"
           "    endcase\n  end\nendmodule\n")
    (tmp_path / "apb.v").write_text(rtl)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "fsm_error_invariant.py"),
         str(tmp_path / "apb.v")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout       # exempt → no findings → rc 0


def test_804_endstate_functional_error_still_blocks_via_program(tmp_path):
    src = ("module rx(input clk, input [2:0] rd_addr, output reg crc_err_o);\n"
           " always @(posedge clk) begin\n   case (rd_addr)\n"
           "     3'd0: crc_err_o <= 1'b0;\n     3'd1: crc_err_o <= 1'b0;\n"
           "     default: crc_err_o <= 1'b1;\n   endcase\n end\nendmodule")
    f = tmp_path / "rx.v"
    f.write_text(src)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "fsm_error_invariant.py"), str(f)],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout       # genuine functional error still fires


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
