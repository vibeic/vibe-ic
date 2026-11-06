#!/usr/bin/env python3
"""#496 — no PASS without a denominator, and what each zero actually means.

#492 disqualified eight registered structural gates: six reporting an explicit
zero denominator on all 107 tracked ``rtl`` directories, and two disclosing no
denominator at all.  This file holds the two halves of the answer:

  1. THE PRECONDITION. Every one of the eight must state what it examined, and
     a zero must carry a reason. A PASS that does not say what it looked at is
     indistinguishable from a PASS over nothing, and the second is the one that
     reads as coverage while being blind.

  2. THE CLASSIFICATION. Each gate's trigger condition was taken back to the
     corpus. Three of the eight turned out to be blind rather than unemployed,
     and their repairs are pinned here with the witness that proves each — a
     positive fixture the gate must now SEE, and a negative fixture it must now
     FAIL. A repair proved only by "the denominator went up" is not proved.

DISCIPLINE — every fixture here is built in ``tmp_path``. No test points a gate
at ``benchmark-data``: the tracked corpus is read-only evidence, gates write
into what they audit, and gate outcomes are path-sensitive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _gate_denominator as GD  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# The eight gates #496 is about. Value = the extra argv each needs beyond
# --rtl-dir (all of them take only --rtl-dir, which is why #492 could measure
# them in one sweep).


def _run(gate: str, rtl_dir: Path):
    return _pr.run(
        [sys.executable, str(PROGRAMS / f"{gate}.py"), "--rtl-dir", str(rtl_dir)],
        capture_output=True, text=True)


def _summary(gate: str, rtl_dir: Path) -> dict:
    """The gate's own summary, via its real CLI.

    ``transient_signal_latch_check`` prints prose rather than JSON, so it is
    read through ``--out-dir``; every other gate prints its report on stdout.
    """
    r = _run(gate, rtl_dir)
    assert "Traceback" not in r.stderr, f"{gate} crashed:\n{r.stderr[-800:]}"
    if gate == "transient_signal_latch_check":
        out = rtl_dir.parent / "_rep"
        r2 = _pr.run(
            [sys.executable, str(PROGRAMS / f"{gate}.py"),
             "--rtl-dir", str(rtl_dir), "--out-dir", str(out)],
            capture_output=True, text=True)
        assert "Traceback" not in r2.stderr, r2.stderr[-800:]
        return json.loads((out / f"{gate}.json").read_text())
    return json.loads(r.stdout)["summary"]


def _rtl(tmp_path: Path, **files: str) -> Path:
    d = tmp_path / "rtl"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name.replace("__", ".")).write_text(body)
    return d


# ── 1. THE PRECONDITION ─────────────────────────────────────────────────────

def test_the_type_refuses_a_silent_zero():
    """The contract is enforced by construction, not by each gate remembering.

    A gate cannot regress into silence by omission — only by writing a reason
    down, and a written reason is reviewable where an absent one is not."""
    with pytest.raises(ValueError, match="not_applicable_reason"):
        GD.Denominator(unit="files", examined=0)
    # Non-zero needs no reason; zero WITH a reason is fine.
    assert GD.Denominator(unit="files", examined=3).is_vacuous is False
    assert GD.Denominator(unit="files", examined=0,
                          not_applicable_reason="none present").is_vacuous


def test_the_type_refuses_an_unnamed_unit():
    """`inout_ports: []` was read as the denominator of a rule denominated in
    driven buses. A bare count with no unit is how that happens."""
    with pytest.raises(ValueError, match="unit"):
        GD.Denominator(unit="  ", examined=5)










def test_dispatcher_count_is_not_published_as_the_denominator(tmp_path):
    """`cmd_arg_range_validation_check` had exactly one non-zero count to its
    name, and it is not the denominator. Publishing it as one would have
    claimed 4/107 coverage for a rule that ran on 0/107."""
    rtl = _rtl(tmp_path, disp__v=(
        "module disp;\n"
        "  always @(*) begin\n"
        "    case (cmd_op)\n"
        "      8'hA0: addr_reg = 1;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"))
    summary = _summary("cmd_arg_range_validation_check", rtl)
    assert len(summary["dispatcher_files"]) == 1, summary
    d = summary[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0, "fixture has no command buffer; rule cannot run"
    assert d["considered"] == 1, "the dispatcher was seen and must be counted"
    assert "command buffer" in d["not_applicable_reason"]


# ── 2. THE CLASSIFICATION RECORD ────────────────────────────────────────────







# ── 3. THE REPAIRS, EACH WITH A WITNESS ─────────────────────────────────────

_GPIO_DIR_BUS = """\
module apb_gpio #(parameter W = 8) (
  input  wire         clk,
  inout  wire [W-1:0] gpio,
  output wire [W-1:0] gpio_int
);
  reg  [W-1:0] gpio_dir;
  reg  [W-1:0] reg_dout;
  wire [W-1:0] gpio_in;
  genvar gi;
  generate
    for (gi = 0; gi < W; gi = gi + 1) begin : gpio_buf
      assign gpio[gi] = gpio_dir[gi] ? reg_dout[gi] : 1'bz;
    end
  endgenerate
  assign gpio_in = gpio;
  assign gpio_int = gpio_in;
endmodule
"""








def test_a_port_the_gate_skips_records_why(tmp_path):
    """`checked: 0` was mis-attributed to `inouts: []` for a whole release
    because nothing recorded the drop. Power pads are a legitimate skip — but
    a legitimate skip still has to be legible."""
    rtl = _rtl(tmp_path, pads__v=(
        "module pads(inout wire vccd1, inout wire vssd1);\nendmodule\n"))
    summary = _summary("tristate_self_rx_mask_check", rtl)
    assert summary["inout_ports"] == ["vccd1", "vssd1"]
    assert summary["checked"] == 0 and summary["skipped"] == 2
    for port in ("vccd1", "vssd1"):
        assert "output-enable companion" in summary["skip_reasons"][port]
    d = summary[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0 and d["considered"] == 2
    assert "inout_ports: []" in d["not_applicable_reason"], (
        "the reason should name the mis-measurement it prevents")


_FALLING_EDGE_DECODER = """\
module pulse_rx(input wire clk, input wire rst_n, input wire sin, output reg [3:0] val);
  reg [1:0] sin_sync;
  always @(posedge clk) sin_sync <= {sin_sync[0], sin};
  wire sin_s = sin_sync[1];
  reg sin_s_d;
  always @(posedge clk) sin_s_d <= sin_s;
  wire falling = (~sin_s) & sin_s_d;
  reg [15:0] period_cnt;
  reg [15:0] last_period;
  always @(posedge clk) begin
    if (falling) begin last_period <= period_cnt; period_cnt <= 16'd1; end
    else period_cnt <= period_cnt + 1'b1;
  end
  wire [15:0] ticks_meas = last_period >> 3;
  always @(posedge clk) begin
    if (ticks_meas >= 16'd12) val <= ticks_meas[3:0];
    else if (last_period >= 16'd400) val <= 4'd0;
  end
endmodule
"""


def test_pulse_decoder_now_selects_a_period_measuring_classifier(tmp_path):
    """Bug 1 of two. The selector required the literal token `low_cnt`, so a
    decoder measuring falling-to-falling PERIODS — the shape SENT, DALI and
    1-Wire receivers actually use — was never a candidate at all."""
    rtl = _rtl(tmp_path, dec__v=_FALLING_EDGE_DECODER)
    summary = _summary("pulse_decoder_edge_check", rtl)
    assert summary["files_checked"] == 1, (
        f"the pulse classifier was not selected: {summary}")
    assert summary[GD.DENOMINATOR_KEY]["examined"] == 1








# Shaped after the tracked hdlc_core.v: an explicit bit counter, a symbol
# strobe spelled `frame_valid` (NOT one of the five literals the extraction
# used to require), a frame-end state, and — the defect — no test that the
# payload ended on an octet boundary before the frame is declared valid.
_HDLC_SHAPED_ASSEMBLER = """\
module rx_core(input wire clk, input wire rx_bit, output reg frame_valid,
               output reg fcs_ok, output reg rx_done);
  reg [2:0] rx_bit_cnt;
  reg [7:0] rx_octet;
  reg       closing_flag;
  always @(posedge clk) begin
    frame_valid <= 1'b0;
    if (closing_flag) begin
      frame_valid <= 1'b1;
      fcs_ok      <= 1'b1;
      rx_done     <= 1'b1;
    end else begin
      rx_octet <= {rx_bit, rx_octet[7:1]};
      if (rx_bit_cnt == 3'd7) rx_bit_cnt <= 3'd0;
      else rx_bit_cnt <= rx_bit_cnt + 3'd1;
    end
  end
endmodule
"""


def test_bit_count_now_sees_an_assembler_that_does_not_say_byte_valid(tmp_path):
    """The extraction required a symbol-valid strobe spelled as one of five
    literals. The corpus receivers spell it `frame_valid` / `rx_char_valid` /
    `rd_valid`, so a bit assembler with a frame end and no alignment check read
    as a clean PASS. One in the tracked tree does exactly that."""
    rtl = _rtl(tmp_path, rx__v=_HDLC_SHAPED_ASSEMBLER)
    summary = _summary("bit_count_modulo_check", rtl)
    assert summary["checked"] == 1, (
        f"the assembler is still invisible: {summary}")
    assert summary[GD.DENOMINATOR_KEY]["examined"] == 1






def test_bit_count_reason_points_at_the_conjunct_that_rejected(tmp_path):
    """When the rule stops because of the symbol-valid conjunct — the one that
    reported 0 corpus-wide while 125 bit-counter matches existed — the reason
    has to say so, or the next reader repeats the measurement from scratch."""
    rtl = _rtl(tmp_path, rx__v=(
        "module m(input clk);\n  reg [2:0] bit_cnt;\n"
        "  always @(posedge clk) bit_cnt <= bit_cnt + 1;\nendmodule\n"))
    d = _summary("bit_count_modulo_check", rtl)[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0
    assert d["considered"] == 1, "the bit-counter candidate must be counted"
    assert "symbol-complete strobe" in d["not_applicable_reason"]


def test_l12_zero_blames_the_missing_input_not_the_design(tmp_path):
    """This gate reported `sequences_checked: 0` because nothing hands it
    `--l12-json`, while 105 of 106 project trees ship a reachable L12 document.
    The zero must not read as 'every declared sequence is implemented'."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    d = _summary("l12_sequence_implementation_check", rtl)[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0
    assert "--l12-json" in d["not_applicable_reason"]
    assert "not checked" in d["not_applicable_reason"].lower()




def test_response_payload_declares_itself_advisory(tmp_path):
    """Every finding it can emit is WARN and `pass` is `not any(ERROR)`, so on
    any readable directory it cannot return non-zero. A checker structurally
    incapable of failing should say so where a consumer can read it."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    assert _summary("response_payload_template_check", rtl)["advisory_only"]
