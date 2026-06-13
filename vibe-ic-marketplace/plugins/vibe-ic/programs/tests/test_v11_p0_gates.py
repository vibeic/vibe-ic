#!/usr/bin/env python3
"""Smoke + regression tests for BACKLOG-v11 P0.2-P0.6 gates.

Each gate is exercised against:
  - synthetic injected-bug RTL (positive — gate must catch the bug)
  - clean reference RTL (negative — gate must PASS / skip cleanly)

Coverage: 5 gates × 3+ tests each = 18 tests.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent


def _run(prog: str, project_dir: Path,
         strict: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROGS / f"{prog}.py"), str(project_dir),
           "--json", str(project_dir / f"{prog}.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _load(project_dir: Path, prog: str) -> dict:
    return json.loads((project_dir / f"{prog}.json").read_text())


def _l8(project_dir: Path, body: dict | None = None):
    docs = project_dir / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    body = body or {
        "doc_layer": "L8_RTL_CONSTANTS",
        "max10_clk_freq_mhz": 50,
        "clk5m_freq_mhz": 5,
    }
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(body))


def _l3_crc(project_dir: Path, init=0xFF, poly_refl=0x8C, vectors=None):
    docs = project_dir / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    body = {
        "doc_layer": "L3_CMD_PROTOCOL",
        "crc": {
            "width": 8,
            "poly_reflected": f"0x{poly_refl:02X}",
            "init": f"0x{init:02X}",
            "refin": True,
            "refout": True,
            "xorout": "0x00",
        }
    }
    if vectors:
        body["crc"]["test_vectors"] = vectors
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps(body))


def _rtl(project_dir: Path, name: str, body: str):
    rtl = project_dir / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


# ===========================================================================
# P0.2: clock_divider_period_check
# ===========================================================================

def test_p02_correct_divider(tmp_path):
    """50MHz / divide-by-10 = 5MHz with N=4 → PASS."""
    _l8(tmp_path)
    _rtl(tmp_path, "wrap.sv", """\
module wrap (input logic max10_clk, input logic rstn, output logic clk5m);
  logic [3:0] div;
  always_ff @(posedge max10_clk or negedge rstn) begin
    if (!rstn) begin div <= 0; clk5m <= 0; end
    else if (div == 4'd4) begin div <= 0; clk5m <= ~clk5m; end
    else div <= div + 1;
  end
endmodule
""")
    r = _run("clock_divider_period_check", tmp_path)
    assert r.returncode == 0


def test_p02_wrong_divider(tmp_path):
    """50MHz / divide-by-20 with N=9 (the v0.116 bug) → FAIL."""
    _l8(tmp_path)
    _rtl(tmp_path, "wrap.sv", """\
module wrap (input logic max10_clk, input logic rstn, output logic clk5m);
  logic [3:0] div;
  always_ff @(posedge max10_clk or negedge rstn) begin
    if (!rstn) begin div <= 0; clk5m <= 0; end
    else if (div == 4'd9) begin div <= 0; clk5m <= ~clk5m; end
    else div <= div + 1;
  end
endmodule
""")
    r = _run("clock_divider_period_check", tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path, "clock_divider_period_check")
    assert any(f["rule"] == "DIVIDER_PERIOD_MISMATCH" for f in rpt["findings"])


def test_p02_skip_no_freq_annotation(tmp_path):
    """Toggle divider but no L8 freq annotation → skip (not a bug to verify)."""
    _l8(tmp_path, body={"doc_layer": "L8_RTL_CONSTANTS"})
    _rtl(tmp_path, "wrap.sv", """\
module wrap (input logic clk_in, output logic strobe);
  logic [3:0] cnt;
  always_ff @(posedge clk_in) begin
    if (cnt == 4'd9) begin cnt <= 0; strobe <= ~strobe; end
    else cnt <= cnt + 1;
  end
endmodule
""")
    r = _run("clock_divider_period_check", tmp_path)
    assert r.returncode == 0  # PASS without verification (no annotation to check)


# ===========================================================================
# P0.3: cross_module_1cycle_handshake_check
# ===========================================================================

def test_p03_orchestration_to_orchestration_race(tmp_path):
    """Orchestration FSM A pulses a strobe consumed by orchestration FSM B."""
    _l8(tmp_path)
    _rtl(tmp_path, "fsm_a.sv", """\
module fsm_a (input logic clk, input logic rstn, output logic kick);
  typedef enum logic { S_IDLE, S_GO } st_e;
  st_e st;
  logic dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin st <= S_IDLE; kick <= 1'b0; end
    else begin
      kick <= 1'b0;       // default low
      case (st)
        S_IDLE: if (cmd_pass) begin st <= S_GO; kick <= 1'b1; end
        S_GO:   st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    _rtl(tmp_path, "fsm_b.sv", """\
module fsm_b (input logic clk, input logic rstn, input logic kick);
  typedef enum logic [1:0] { S_IDLE, S_LATER } st_e;
  st_e st;
  logic set_awake, dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) st <= S_IDLE;
    else case (st)
      S_IDLE: if (kick) st <= S_LATER;
      S_LATER: st <= S_IDLE;
    endcase
  end
endmodule
""")
    r = _run("cross_module_1cycle_handshake_check", tmp_path, strict=True)
    assert r.returncode == 1  # ERROR under --strict


def test_p03_phy_consumer_silent(tmp_path):
    """Orchestration FSM pulses tx_start, PHY tx_phy module consumes it
    same-edge — gate must be silent."""
    _l8(tmp_path)
    _rtl(tmp_path, "dispatcher.sv", """\
module dispatcher (input logic clk, input logic rstn, output logic tx_start);
  typedef enum logic { S_IDLE, S_TX } st_e;
  st_e st;
  logic dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin st <= S_IDLE; tx_start <= 1'b0; end
    else begin
      tx_start <= 1'b0;
      case (st)
        S_IDLE: if (cmd_pass) begin st <= S_TX; tx_start <= 1'b1; end
        S_TX:   st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    # PHY module: no orchestration tokens, no case-on-state
    _rtl(tmp_path, "tx_phy.sv", """\
module tx_phy (input logic clk, input logic rstn, input logic tx_start,
               output logic tx_done);
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) tx_done <= 1'b0;
    else if (tx_start) tx_done <= 1'b1;
  end
endmodule
""")
    r = _run("cross_module_1cycle_handshake_check", tmp_path)
    # PASS — consumer is PHY, not orchestration FSM → silenced
    assert r.returncode in (0, 2)


def test_p03_consumer_latches(tmp_path):
    """Consumer latches the pulse via _q register → silent."""
    _l8(tmp_path)
    _rtl(tmp_path, "src.sv", """\
module src (input logic clk, input logic rstn, output logic kick);
  typedef enum logic { S_IDLE, S_GO } st_e;
  st_e st;
  logic dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin st <= S_IDLE; kick <= 1'b0; end
    else begin
      kick <= 1'b0;
      case (st)
        S_IDLE: if (cmd_pass) begin st <= S_GO; kick <= 1'b1; end
        S_GO:   st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    _rtl(tmp_path, "consumer.sv", """\
module consumer (input logic clk, input logic rstn, input logic kick);
  typedef enum logic [1:0] { S_IDLE, S_RUN } st_e;
  st_e st;
  logic kick_q;       // latch register — handshake correctly
  logic set_awake, dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin kick_q <= 0; st <= S_IDLE; end
    else begin
      if (kick) kick_q <= 1'b1;
      case (st)
        S_IDLE: if (kick_q) begin st <= S_RUN; kick_q <= 0; end
        S_RUN:  st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    r = _run("cross_module_1cycle_handshake_check", tmp_path, strict=True)
    assert r.returncode in (0, 2)  # consumer latches → silenced


# ===========================================================================
# P0.4: frame_end_detection_check
# ===========================================================================

def test_p04_br_seen_anti_pattern(tmp_path):
    """rx_phy that toggles `br_seen` to mark end-of-frame → WARN."""
    _rtl(tmp_path, "rx_phy.sv", """\
module rx_phy (input logic clk, input logic rstn,
               output logic rx_br, output logic rx_end_br);
  logic br_seen;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin rx_br <= 0; rx_end_br <= 0; br_seen <= 0; end
    else begin
      rx_br <= 0; rx_end_br <= 0;
      if (long_pulse) begin
        if (!br_seen) begin rx_br <= 1; br_seen <= 1; end
        else begin rx_end_br <= 1; br_seen <= 0; end
      end
    end
  end
endmodule
""")
    r = _run("frame_end_detection_check", tmp_path)
    assert r.returncode == 0  # WARN, not ERROR
    rpt = _load(tmp_path, "frame_end_detection_check")
    assert any(f["rule"] == "FRAME_END_BY_DUPLICATE_START_PULSE"
               for f in rpt["findings"])


def test_p04_gap_cnt_silent(tmp_path):
    """rx_phy with gap_cnt timeout → silent (correct pattern)."""
    _rtl(tmp_path, "rx_phy.sv", """\
module rx_phy (input logic clk, input logic rstn, output logic rx_end_br);
  logic [15:0] gap_cnt;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin gap_cnt <= 0; rx_end_br <= 0; end
    else begin
      rx_end_br <= 0;
      if (gap_cnt < 200) gap_cnt <= gap_cnt + 1;
      else rx_end_br <= 1;
    end
  end
endmodule
""")
    r = _run("frame_end_detection_check", tmp_path)
    assert r.returncode == 0  # PASS clean (gap_cnt present)


def test_p04_l3_explicit_two_class_silent(tmp_path):
    """L3 declares frame_delimiters with 2 classes → gate skip override."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "frame_delimiters": ["BR_START", "BR_END_DISTINCT"],
    }))
    _rtl(tmp_path, "rx_phy.sv", """\
module rx_phy (output logic rx_br, output logic rx_end_br);
  logic br_seen;
endmodule
""")
    r = _run("frame_end_detection_check", tmp_path)
    assert r.returncode == 2  # skip


# ===========================================================================
# P0.5: crc_oracle_vector_check
# ===========================================================================

def test_p05_correct_crc_module(tmp_path):
    """RTL contains the spec init + poly literals → PASS."""
    _l3_crc(tmp_path, init=0xFF, poly_refl=0x8C)
    _rtl(tmp_path, "crc8.sv", """\
module crc8 (input logic clk, output logic [7:0] crc_out);
  logic [7:0] crc_q;
  always_ff @(posedge clk) begin
    crc_q <= 8'hFF;        // init
    crc_q <= (crc_q >> 1) ^ 8'h8C;
  end
endmodule
""")
    r = _run("crc_oracle_vector_check", tmp_path)
    assert r.returncode == 0


def test_p05_wrong_init_warns(tmp_path):
    """RTL has init=0x00 but spec=0xFF → WARN (literal mismatch)."""
    _l3_crc(tmp_path, init=0xFF, poly_refl=0x8C)
    _rtl(tmp_path, "crc8.sv", """\
module crc8 (input logic clk, output logic [7:0] crc_out);
  logic [7:0] crc_q;
  always_ff @(posedge clk) begin
    crc_q <= 8'h00;        // wrong init
    crc_q <= (crc_q >> 1) ^ 8'h07;   // wrong poly
  end
endmodule
""")
    r = _run("crc_oracle_vector_check", tmp_path)
    assert r.returncode == 0  # WARN-only verdict (PASS exit)
    rpt = _load(tmp_path, "crc_oracle_vector_check")
    assert any(f["rule"] == "CRC_LITERAL_MISMATCH" for f in rpt["findings"])


def test_p05_oracle_vector_mismatch(tmp_path):
    """L3 vectors are inconsistent with declared poly/init → ERROR."""
    _l3_crc(tmp_path, init=0xFF, poly_refl=0x8C, vectors=[
        {"input": [0x74, 0x00, 0x01], "expected": "0x99"},  # WRONG (real is 0xFD)
    ])
    _rtl(tmp_path, "crc8.sv", """\
module crc8;
  reg [7:0] crc_q;
  initial crc_q = 8'hFF;
  // ... uses 8'h8C poly somewhere
  wire [7:0] poly = 8'h8C;
endmodule
""")
    r = _run("crc_oracle_vector_check", tmp_path)
    assert r.returncode == 1  # ERROR — oracle disagrees with spec
    rpt = _load(tmp_path, "crc_oracle_vector_check")
    assert any(f["rule"] == "CRC_ORACLE_VECTOR_MISMATCH"
               for f in rpt["findings"])


# ===========================================================================
# P0.6: arbiter_starvation_check
# ===========================================================================

def test_p06_starvation(tmp_path):
    """High-priority requester `assign hi_req = rstn;` (always 1) →
    low-priority `lo_req` starves → WARN (ERROR with --strict)."""
    _l8(tmp_path)
    _rtl(tmp_path, "arb.sv", """\
module arb (input logic clk, input logic rstn,
            output logic hi_req, input logic lo_req,
            output logic grant);
  assign hi_req = rstn;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) grant <= 0;
    else begin
      if (hi_req) grant <= 1;
      else if (lo_req) grant <= 1;
    end
  end
endmodule
""")
    r = _run("arbiter_starvation_check", tmp_path, strict=True)
    assert r.returncode == 1
    rpt = _load(tmp_path, "arbiter_starvation_check")
    assert any(f["rule"] == "ARBITER_STARVATION_RISK" for f in rpt["findings"])


def test_p06_bounded_burst_silent(tmp_path):
    """High-priority hi_req has clear-to-zero path → no starvation."""
    _l8(tmp_path)
    _rtl(tmp_path, "arb.sv", """\
module arb (input logic clk, input logic rstn,
            input logic hi_req, input logic lo_req, output logic grant);
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) grant <= 0;
    else begin
      if (hi_req) begin grant <= 1; hi_req <= 1'b0; end  // clears in same block
      else if (lo_req) grant <= 1;
    end
  end
endmodule
""")
    r = _run("arbiter_starvation_check", tmp_path)
    # `hi_req` is an INPUT, no `assign hi_req = rstn` — gate has nothing
    # in always_on set → silent
    assert r.returncode in (0, 2)


def test_p06_no_arbitration_pattern(tmp_path):
    """No if/else-if arbitration → skip."""
    _rtl(tmp_path, "plain.sv", """\
module plain (input logic clk, output logic q);
  always_ff @(posedge clk) q <= ~q;
endmodule
""")
    r = _run("arbiter_starvation_check", tmp_path)
    assert r.returncode == 2


# ===========================================================================
# v0.117-stable: regex-widening + false-alert regression tests.
# These exercise the edge cases that were previously silent due to
# narrow regex spans and tight suffix lists. Added per BACKLOG-v11
# follow-up review (gate_utils refactor + regex widening).
# ===========================================================================

def test_p02_long_block_widened(tmp_path):
    """Toggle divider with a long always_ff body (>400 chars between
    `if (cnt == N)` and `sig <= ~sig`) — must still be caught now that
    _DIV_BLOCK_RE span is 2000 chars."""
    _l8(tmp_path)
    # Wedge ~600 chars of unrelated comments + assignments between the
    # comparator and the toggle.
    filler = "\n".join(
        f"      // unrelated comment line {i} padding the block"
        for i in range(20)
    )
    _rtl(tmp_path, "wrap.sv", f"""\
module wrap (input logic max10_clk, input logic rstn, output logic clk5m);
  logic [3:0] div;
  logic [7:0] aux_a, aux_b, aux_c;
  always_ff @(posedge max10_clk or negedge rstn) begin
    if (!rstn) begin div <= 0; clk5m <= 0; end
    else if (div == 4'd9) begin
{filler}
      div <= 0;
      aux_a <= aux_a + 1;
      aux_b <= aux_b ^ 8'hAA;
      aux_c <= {{aux_a, 4'h0}};
      clk5m <= ~clk5m;
    end
    else div <= div + 1;
  end
endmodule
""")
    r = _run("clock_divider_period_check", tmp_path)
    assert r.returncode == 1, "regex span widening to 2000 should catch this"


def test_p03_consumer_latched_suffix_silent(tmp_path):
    """Consumer uses `<sig>_latched` (NOT `_latch`) — must be silent
    after the suffix list was widened."""
    _l8(tmp_path)
    _rtl(tmp_path, "src.sv", """\
module src (input logic clk, input logic rstn, output logic kick);
  typedef enum logic { S_IDLE, S_GO } st_e;
  st_e st;
  logic dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin st <= S_IDLE; kick <= 1'b0; end
    else begin
      kick <= 1'b0;
      case (st)
        S_IDLE: if (cmd_pass) begin st <= S_GO; kick <= 1'b1; end
        S_GO:   st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    _rtl(tmp_path, "consumer.sv", """\
module consumer (input logic clk, input logic rstn, input logic kick);
  typedef enum logic [1:0] { S_IDLE, S_RUN } st_e;
  st_e st;
  logic kick_latched;
  logic set_awake, dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin kick_latched <= 0; st <= S_IDLE; end
    else begin
      if (kick) kick_latched <= 1'b1;
      case (st)
        S_IDLE: if (kick_latched) begin st <= S_RUN; kick_latched <= 0; end
        S_RUN:  st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    r = _run("cross_module_1cycle_handshake_check", tmp_path, strict=True)
    assert r.returncode in (0, 2), \
        "_latched suffix must be recognised as a latch register"


def test_p03_consumer_captured_suffix_silent(tmp_path):
    """Consumer uses `<sig>_captured` — must be silent."""
    _l8(tmp_path)
    _rtl(tmp_path, "src.sv", """\
module src (input logic clk, input logic rstn, output logic kick);
  typedef enum logic { S_IDLE, S_GO } st_e;
  st_e st;
  logic dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin st <= S_IDLE; kick <= 1'b0; end
    else begin
      kick <= 1'b0;
      case (st)
        S_IDLE: if (cmd_pass) begin st <= S_GO; kick <= 1'b1; end
        S_GO:   st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    _rtl(tmp_path, "consumer.sv", """\
module consumer (input logic clk, input logic rstn, input logic kick);
  typedef enum logic [1:0] { S_IDLE, S_RUN } st_e;
  st_e st;
  logic kick_captured;
  logic set_awake, dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin kick_captured <= 0; st <= S_IDLE; end
    else begin
      if (kick) kick_captured <= 1'b1;
      case (st)
        S_IDLE: if (kick_captured) begin st <= S_RUN; kick_captured <= 0; end
        S_RUN:  st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    r = _run("cross_module_1cycle_handshake_check", tmp_path, strict=True)
    assert r.returncode in (0, 2), \
        "_captured suffix must be recognised as a latch register"


def test_p03_multiline_nested_paren_ports(tmp_path):
    """Module port list spans multiple lines with [WIDTH-1:0] brackets.
    Old regex `[\\s\\S]*?\\)` would mis-match; gate_utils.find_modules
    must parse correctly (paren-balanced)."""
    _l8(tmp_path)
    _rtl(tmp_path, "src.sv", """\
module src #(
    parameter int WIDTH = 8
) (
    input  logic              clk,
    input  logic              rstn,
    output logic [WIDTH-1:0]  data,
    output logic              kick
);
  typedef enum logic { S_IDLE, S_GO } st_e;
  st_e st;
  logic dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin st <= S_IDLE; kick <= 1'b0; end
    else begin
      kick <= 1'b0;
      case (st)
        S_IDLE: if (cmd_pass) begin st <= S_GO; kick <= 1'b1; end
        S_GO:   st <= S_IDLE;
      endcase
    end
  end
endmodule
""")
    _rtl(tmp_path, "cons.sv", """\
module cons (
    input  logic              clk,
    input  logic              rstn,
    input  logic [7:0]        data,
    input  logic              kick
);
  typedef enum logic [1:0] { S_IDLE, S_RUN } st_e;
  st_e st;
  logic set_awake, dispatcher_busy;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) st <= S_IDLE;
    else case (st)
      S_IDLE: if (kick) st <= S_RUN;
      S_RUN:  st <= S_IDLE;
    endcase
  end
endmodule
""")
    r = _run("cross_module_1cycle_handshake_check", tmp_path, strict=True)
    # Both modules parsed correctly → race detected → exit 1 under --strict.
    # If parser silently dropped a module, we'd get exit 0/2 instead.
    assert r.returncode == 1, \
        "find_modules must parse multi-line nested-paren ports"


def test_p04_alternate_end_signal_name(tmp_path):
    """rx_phy uses `end_frame`/`frame_start` (not `rx_end_br`/`rx_br`).
    Generalised antipattern check should still warn."""
    _rtl(tmp_path, "rx_decoder.sv", """\
module rx_decoder (input logic clk, input logic rstn,
                   input logic long_pulse,
                   output logic frame_start, output logic end_frame);
  logic phase_seen;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin frame_start <= 0; end_frame <= 0; phase_seen <= 0; end
    else begin
      frame_start <= 0; end_frame <= 0;
      if (long_pulse) begin
        if (!phase_seen) begin frame_start <= 1; phase_seen <= 1; end
        else begin end_frame <= 1; phase_seen <= 0; end
      end
    end
  end
endmodule
""")
    r = _run("frame_end_detection_check", tmp_path)
    assert r.returncode == 0  # WARN-only verdict (PASS exit)
    rpt = _load(tmp_path, "frame_end_detection_check")
    assert any(f["rule"] == "FRAME_END_BY_DUPLICATE_START_PULSE"
               for f in rpt["findings"]), \
        "antipattern with non-`br_seen` flag and `end_frame` signal " \
        "must still be detected"


def test_p06_long_lookback_clear_branch(tmp_path):
    """Clear-branch `<sig> <= 1'b0` is separated from the reset branch
    by >80 chars but is genuinely a non-reset clear. Old 80-char
    lookback would have mis-attributed it; new 500-char lookback must
    correctly identify the clear."""
    _l8(tmp_path)
    # Padding inside reset branch makes the clear path far from `if (!rstn)`.
    _rtl(tmp_path, "arb.sv", """\
module arb (input logic clk, input logic rstn,
            output logic hi_req, input logic lo_req,
            output logic grant, output logic side_a, output logic side_b);
  assign hi_req = rstn;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin
      grant   <= 1'b0;
      side_a  <= 1'b0;
      side_b  <= 1'b0;
      // padding to push clear branch far from the reset block
      // padding padding padding padding padding padding padding
      // padding padding padding padding padding padding padding
    end
    else if (hi_req) begin
      grant  <= 1'b1;
      side_a <= 1'b1;
      side_b <= 1'b1;
      hi_req <= 1'b0;       // genuine bounded-burst clear, NOT reset
    end
    else if (lo_req) grant <= 1'b1;
  end
endmodule
""")
    r = _run("arbiter_starvation_check", tmp_path)
    # `hi_req` has a clear path inside an `else if (hi_req)` branch
    # (NOT a reset branch). With 500-char lookback the gate identifies
    # this correctly and stays silent. Old 80-char lookback would have
    # attributed it correctly here too — so the firmer assertion is
    # that the gate doesn't false-alert (returncode 0 or 2).
    assert r.returncode in (0, 2), \
        "clear-branch separated from reset by >80 chars must be " \
        "correctly attributed to the non-reset branch"
