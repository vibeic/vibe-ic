"""ORGANIC #795 — latency_conformance_check datapath_mode false-TIMEOUTed a
decoder/LUT/ROM, plus _reset_is_active_low mis-read a `*_in` suffix as
active-low.

CVDP round-10 blind: decoder_8b10b_0001. Two compounding bugs:
 (1) datapath_mode drove a multi-bit --event input to blind ALL-ONES, which for
     a decoder is an INVALID/no-op codeword mapping to the reset baseline, so the
     `out !== out_rstval` change-detect never fired → false rc=1 LATENCY-TIMEOUT.
 (2) _reset_is_active_low("reset_in") returned True (bare trailing `n` of `_in`
     mis-read as an active-low marker) → the TB held reset_in=1 throughout
     measurement, pinning the output and forcing a TIMEOUT.

FIX: (1) on a datapath TIMEOUT with a multi-bit event, retry with distinct
codewords — the RTL's OWN width-matched sized literals first, then a generic
spread — held STEADY; adopt the first that cleanly measures. (2) a bare trailing
n/b is a polarity marker ONLY when attached to a reset/clear stem.

§4.05 no-leak: the retry can ONLY relax a TIMEOUT to a measurement — a genuinely
non-responsive bus still TIMEs out; a real 2-cycle datapath vs spec=1 still
MISMATCHes. chip-AGNOSTIC: RTL sized-literal grammar; no chip literal.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import latency_conformance_check as L  # noqa: E402

_IV = shutil.which("iverilog") and shutil.which("vvp")


# ── (2) reset-polarity classification ───────────────────────────────────────
@pytest.mark.parametrize("name", ["reset_in", "rst_in", "data_in", "din",
                                  "scan_in", "reset", "rst", "clk"])
def test_795_active_high_names_not_misread_low(name):
    assert L._reset_is_active_low(name) is False, name


@pytest.mark.parametrize("name", ["rst_n", "reset_n", "rstn", "resetn",
                                  "rstb", "nrst", "clrn", "reset_b"])
def test_795_genuine_active_low_still_detected(name):
    assert L._reset_is_active_low(name) is True, name


# ── (1) RTL event-value candidate extraction ────────────────────────────────
def test_795_rtl_event_value_candidates_width_matched_only():
    rtl = ("case (decoder_in)\n 10'b0011000000: x=1;\n 10'b0100100000: x=2;\n"
           " 8'hFF: y=0;\n default: x=0;\nendcase")
    cands = L._rtl_event_value_candidates(rtl, 10)
    assert 192 in cands and 288 in cands       # the two width-10 codewords
    assert 255 not in cands                     # 8'hFF is the wrong width
    # all-ones / zero are skipped (cannot relax the timeout).
    assert 0 not in cands and 1023 not in cands


def test_795_rtl_event_value_candidates_scalar_event_empty():
    assert L._rtl_event_value_candidates("1'b1 1'b0", 1) == []


# ── END-TO-END: the decoder no longer false-TIMEOUTs ────────────────────────
_DECODER = """\
module decoder_8b10b (input clk, input rst, input [9:0] decoder_in,
                      output reg [7:0] decoder_out);
  always @(posedge clk) begin
    if (rst) decoder_out <= 8'd0;
    else case (decoder_in)
      10'b0011000000: decoder_out <= 8'h1;
      10'b0100100000: decoder_out <= 8'h2;
      default:        decoder_out <= 8'd0;   // all-ones is invalid -> baseline
    endcase
  end
endmodule
"""

# §4.05 no-leak: a genuinely non-responsive bus (never changes for ANY code).
_STUCK = """\
module decoder_8b10b (input clk, input rst, input [9:0] decoder_in,
                      output reg [7:0] decoder_out);
  always @(posedge clk) decoder_out <= 8'd0;   // never responds
endmodule
"""


def _run(tmp_path, rtl, expect, name="decoder_8b10b"):
    f = tmp_path / f"{name}.v"
    f.write_text(rtl)
    jp = tmp_path / "r.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "latency_conformance_check.py"),
         "--rtl", str(f), "--top", name, "--event", "decoder_in",
         "--output", "decoder_out", "--expect", str(expect),
         "--json", str(jp)], capture_output=True, text=True)
    import json
    return r.returncode, json.loads(jp.read_text())


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_795_decoder_all_ones_baseline_now_measures(tmp_path):
    rc, rep = _run(tmp_path, _DECODER, 1)
    assert rc == 0, rep                          # was false rc=1 TIMEOUT
    assert rep["verdict"] == "PASS"
    assert rep.get("measured_under_datapath_event_value") in (192, 288)


# §4.05 LEAK (Step-2.7) — adopting the FIRST clean probe masks a bug on another
# codeword. The retry must probe ALL candidates and take the WORST (MAX) latency.
_MASK = """\
module dec_mask (input clk, input rst_n, input [7:0] code, output reg [7:0] dout);
    reg [7:0] a,b,c,d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin dout<=8'd0; a<=8'd0; b<=8'd0; c<=8'd0; d<=8'd0; end
        else begin
            if (code == 8'h01) begin
                a <= 8'h11;
                if (a == 8'h11) dout <= 8'h22;        // incidental: 2 cycles
            end else if (code == 8'hA5) begin
                b <= 8'hB0; c <= b; d <= c;
                if (d == 8'hB0) dout <= 8'h5A;          // PRIMARY: BUG, 4 cycles
            end
        end
    end
endmodule
"""


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_795_noleak_first_clean_probe_does_not_mask_slow_codeword(tmp_path):
    f = tmp_path / "dec_mask.v"
    f.write_text(_MASK)
    jp = tmp_path / "r.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "latency_conformance_check.py"),
         "--rtl", str(f), "--top", "dec_mask", "--event", "code",
         "--output", "dout", "--expect", "2", "--json", str(jp)],
        capture_output=True, text=True)
    import json
    rep = json.loads(jp.read_text())
    # the 0x01 path measures 2 (== expect) but 0xA5 measures 4 (the bug): the
    # gate must surface the MAX (4) and MISMATCH, not PASS off the decoy.
    assert r.returncode == 1, rep
    assert rep["verdict"] == "MISMATCH"
    assert rep.get("measured_latency") == 4


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_795_noleak_stuck_bus_still_times_out(tmp_path):
    rc, rep = _run(tmp_path, _STUCK, 1)
    # a bus that never changes under ANY probe still BLOCKs (no false PASS).
    assert rc == 1, rep
    assert rep["verdict"] in ("TIMEOUT", "MISMATCH")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
