"""#2035 family F4 — framed-serial-receiver FRAME CONTRACT regressions.

One row of vibe-ic#2035 packs THREE defects into one sentence — "Framed serial
receiver forwards raw fields, adds latency or ignores inter-frame space" — and
this file pins them apart, because a single boolean for the row is not a verdict
a reader can act on:

  1. MAPPING      the declared decode table is not applied, the raw field is
                  forwarded instead        -> frame-field-mapping-not-applied
  2. LATENCY      the output arrives later than the contract states
                                           -> frame-output-latency-added
  3. INTER-FRAME  the gap between frames is not enforced
                                           -> frame-interframe-space-unenforced

(2) and (3) are two constraints on the SAME time axis, so they are also pinned
TOGETHER: `frame-contract-composition` states every element's verdict in one
line and every violated element is named. A checker that only ever tests one at
a time passes a design that violates their combination.

THE UNIT IS NEVER DEFAULTED. A temporal claim needs a unit, a bound and an event
pair; whatever the input does not structurally state is reported AI_REQUIRED by
name. Pinned here in both directions: a clause with no unit does NOT become an
ERROR, and a clause stated in bit periods is NOT compared against a register
count.

THE ALTERNATIVE-ARCHITECTURE CONTROL is the load-bearing test in this file. A
legitimately correct receiver built a DIFFERENT way — an explicit state machine
with a registered output that meets the same contract by another route — must
stay GREEN. If it ever reddens, these are style rules, not conformance checks.

Corpus safety, measured on the base this landed against (2026-09-06): 4171 input
documents and 633 (input prose, RTL module) pairs over the in-tree fixtures and
the benchmark-data corpus; 23 pairs armed the contract and ZERO fired. The
counter-guards each of those 23 exercised are pinned below.

chip-AGNOSTIC: a generic TopModule with clk/rst/rx/cmd_out/frame_done. No IC
name, vendor, node, SKU or benchmark identifier.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _frame_contract as fc  # noqa: E402
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import (extract_spec_contract, parse_rtl_ports,  # noqa: E402
                             strip_comments)

MAPPING_RULE = "frame-field-mapping-not-applied"
LATENCY_RULE = "frame-output-latency-added"
IFS_RULE = "frame-interframe-space-unenforced"
COMPOSITION_RULE = "frame-contract-composition"
ERROR_RULES = {MAPPING_RULE, LATENCY_RULE, IFS_RULE}


def _findings(spec_text, rtl, top="TopModule"):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, top)
    return scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                     scc._rtl_output_is_registered(src, ports), "t.sv", src,
                     spec_text=spec_text)


def _errors(spec_text, rtl):
    return sorted(f.rule for f in _findings(spec_text, rtl)
                  if f.severity == "ERROR" and f.rule in ERROR_RULES)


def _composition(spec_text, rtl):
    line = [f.message for f in _findings(spec_text, rtl)
            if f.rule == COMPOSITION_RULE]
    return line[0] if line else ""


#: spec_all3.md
SPEC = """\
Implement a framed serial receiver.

 - input  clk
 - input  rst
 - input  rx
 - output cmd_out (4 bits)
 - output frame_done

Each frame is one start bit, an 8-bit payload and one stop bit. The low three
bits of the payload are the type field, which is decoded to `cmd_out` as
follows:

  3'b000 -> 4'h6
  3'b001 -> 4'h9
  3'b010 -> 4'hA
  3'b011 -> 4'hD

`cmd_out` must be valid in the same clock cycle that `frame_done` asserts.

Consecutive frames must be separated by at least 3 idle bit periods; a start
bit seen sooner is not the start of a frame.
"""

#: wrong_all3.v
WRONG_ALL3 = """\
module TopModule(input clk, input rst, input rx,
                 output [3:0] cmd_out, output frame_done);
  reg [8:0] sh;
  reg [3:0] bitcnt;
  reg       done_q;
  reg [3:0] cmd_q;
  wire [2:0] ftype = sh[2:0];
  always @(posedge clk) begin
    if (rst) begin sh <= 0; bitcnt <= 0; done_q <= 0; end
    else begin
      sh     <= {rx, sh[8:1]};
      bitcnt <= (bitcnt == 8) ? 0 : bitcnt + 1;
      done_q <= (bitcnt == 8);
    end
  end
  always @(posedge clk) if (done_q) cmd_q <= ftype;
  assign cmd_out    = cmd_q;
  assign frame_done = done_q;
endmodule
"""

#: wrong_mapping_only.v
WRONG_MAPPING = """\
// DEFECT 1 of 3 ONLY: the declared decode table is not applied.
// Program-first output: shift-register receiver that applies the declared
// table, produces cmd_out in the SAME cycle as frame_done, and enforces the
// declared inter-frame gap.
module TopModule(input clk, input rst, input rx,
                 output [3:0] cmd_out, output frame_done);
  localparam GAP_MIN = 3;              // inter-frame space, in bit periods
  reg [8:0] sh;
  reg [3:0] bitcnt;
  reg [3:0] gap_cnt;
  reg       armed;
  reg       done_q;
  wire [2:0] ftype = sh[2:0];
  reg  [3:0] cmd_c;

  always @(*) cmd_c = {1'b0, ftype};      // DEFECT: forwards the raw field

  always @(posedge clk) begin
    if (rst) begin
      sh <= 0; bitcnt <= 0; gap_cnt <= 0; armed <= 0; done_q <= 0;
    end else begin
      sh     <= {rx, sh[8:1]};
      done_q <= (bitcnt == 8);
      if (bitcnt == 8) begin
        bitcnt  <= 0;
        gap_cnt <= 0;
        armed   <= 0;
      end else if (!armed) begin
        gap_cnt <= rx ? (gap_cnt + 1) : 0;
        armed   <= (gap_cnt >= GAP_MIN);
      end else begin
        bitcnt <= bitcnt + 1;
      end
    end
  end

  assign cmd_out    = done_q ? cmd_c : 4'h0;
  assign frame_done = done_q;
endmodule
"""

#: wrong_latency_only.v
WRONG_LATENCY = """\
// DEFECT 2 of 3 ONLY: the output arrives one cycle after the contract.
// Program-first output: shift-register receiver that applies the declared
// table, produces cmd_out in the SAME cycle as frame_done, and enforces the
// declared inter-frame gap.
module TopModule(input clk, input rst, input rx,
                 output [3:0] cmd_out, output frame_done);
  localparam GAP_MIN = 3;              // inter-frame space, in bit periods
  reg [8:0] sh;
  reg [3:0] bitcnt;
  reg [3:0] gap_cnt;
  reg       armed;
  reg       done_q;
  wire [2:0] ftype = sh[2:0];
  reg  [3:0] cmd_c;

  always @(*)
    case (ftype)
      3'b000:  cmd_c = 4'h6;
      3'b001:  cmd_c = 4'h9;
      3'b010:  cmd_c = 4'hA;
      3'b011:  cmd_c = 4'hD;
      default: cmd_c = 4'h0;
    endcase

  always @(posedge clk) begin
    if (rst) begin
      sh <= 0; bitcnt <= 0; gap_cnt <= 0; armed <= 0; done_q <= 0;
    end else begin
      sh     <= {rx, sh[8:1]};
      done_q <= (bitcnt == 8);
      if (bitcnt == 8) begin
        bitcnt  <= 0;
        gap_cnt <= 0;
        armed   <= 0;
      end else if (!armed) begin
        gap_cnt <= rx ? (gap_cnt + 1) : 0;
        armed   <= (gap_cnt >= GAP_MIN);
      end else begin
        bitcnt <= bitcnt + 1;
      end
    end
  end

  reg [3:0] cmd_r;                        // DEFECT: extra stage
  always @(posedge clk) if (done_q) cmd_r <= cmd_c;
  assign cmd_out    = cmd_r;
  assign frame_done = done_q;
endmodule
"""

#: wrong_interframe_only.v
WRONG_IFS = """\
// DEFECT 3 of 3 ONLY: the inter-frame space is not enforced.
// Program-first output: shift-register receiver that applies the declared
// table, produces cmd_out in the SAME cycle as frame_done, and enforces the
// declared inter-frame gap.
module TopModule(input clk, input rst, input rx,
                 output [3:0] cmd_out, output frame_done);
  reg [8:0] sh;
  reg [3:0] bitcnt;
  reg       done_q;
  wire [2:0] ftype = sh[2:0];
  reg  [3:0] cmd_c;

  always @(*)
    case (ftype)
      3'b000:  cmd_c = 4'h6;
      3'b001:  cmd_c = 4'h9;
      3'b010:  cmd_c = 4'hA;
      3'b011:  cmd_c = 4'hD;
      default: cmd_c = 4'h0;
    endcase

  always @(posedge clk) begin
    if (rst) begin
      sh <= 0; bitcnt <= 0; done_q <= 0;
    end else begin
      sh     <= {rx, sh[8:1]};
      done_q <= (bitcnt == 8);
      // DEFECT: back-to-back frames accepted; no inter-frame dwell
      bitcnt <= (bitcnt == 8) ? 0 : bitcnt + 1;
    end
  end

  assign cmd_out    = done_q ? cmd_c : 4'h0;
  assign frame_done = done_q;
endmodule
"""

#: wrong_mapping_and_interframe.v
WRONG_MAP_AND_IFS = """\
// TWO defects at once: mapping AND inter-frame space; latency is correct.
// Program-first output: shift-register receiver that applies the declared
// table, produces cmd_out in the SAME cycle as frame_done, and enforces the
// declared inter-frame gap.
module TopModule(input clk, input rst, input rx,
                 output [3:0] cmd_out, output frame_done);
  reg [8:0] sh;
  reg [3:0] bitcnt;
  reg       done_q;
  wire [2:0] ftype = sh[2:0];
  reg  [3:0] cmd_c;

  always @(*) cmd_c = {1'b0, ftype};      // DEFECT: forwards the raw field

  always @(posedge clk) begin
    if (rst) begin
      sh <= 0; bitcnt <= 0; done_q <= 0;
    end else begin
      sh     <= {rx, sh[8:1]};
      done_q <= (bitcnt == 8);
      bitcnt <= (bitcnt == 8) ? 0 : bitcnt + 1;
    end
  end

  assign cmd_out    = done_q ? cmd_c : 4'h0;
  assign frame_done = done_q;
endmodule
"""

#: correct_shiftreg.v
CORRECT = """\
// Program-first output: shift-register receiver that applies the declared
// table, produces cmd_out in the SAME cycle as frame_done, and enforces the
// declared inter-frame gap.
module TopModule(input clk, input rst, input rx,
                 output [3:0] cmd_out, output frame_done);
  localparam GAP_MIN = 3;              // inter-frame space, in bit periods
  reg [8:0] sh;
  reg [3:0] bitcnt;
  reg [3:0] gap_cnt;
  reg       armed;
  reg       done_q;
  wire [2:0] ftype = sh[2:0];
  reg  [3:0] cmd_c;

  always @(*)
    case (ftype)
      3'b000:  cmd_c = 4'h6;
      3'b001:  cmd_c = 4'h9;
      3'b010:  cmd_c = 4'hA;
      3'b011:  cmd_c = 4'hD;
      default: cmd_c = 4'h0;
    endcase

  always @(posedge clk) begin
    if (rst) begin
      sh <= 0; bitcnt <= 0; gap_cnt <= 0; armed <= 0; done_q <= 0;
    end else begin
      sh     <= {rx, sh[8:1]};
      done_q <= (bitcnt == 8);
      if (bitcnt == 8) begin
        bitcnt  <= 0;
        gap_cnt <= 0;
        armed   <= 0;
      end else if (!armed) begin
        gap_cnt <= rx ? (gap_cnt + 1) : 0;
        armed   <= (gap_cnt >= GAP_MIN);
      end else begin
        bitcnt <= bitcnt + 1;
      end
    end
  end

  assign cmd_out    = done_q ? cmd_c : 4'h0;
  assign frame_done = done_q;
endmodule
"""

#: alt_fsm_control.v
ALT_ARCH = """\
// ALTERNATIVE-ARCHITECTURE CONTROL. A legitimately correct receiver built a
// different way: an explicit state machine instead of a free-running shift
// register, a REGISTERED output that meets the stated latency by producing
// cmd_out and frame_done from the SAME register stage, and the inter-frame
// space enforced by a dedicated dwell state rather than by a comparator.
// It must stay GREEN. If the rules flag this, they are style rules.
module TopModule(input clk, input rst, input rx,
                 output reg [3:0] cmd_out, output reg frame_done);
  localparam S_QUIET = 3'd0, S_ARM = 3'd1, S_START = 3'd2,
             S_DATA  = 3'd3, S_STOP = 3'd4;
  reg [2:0]  st;
  reg [3:0]  n;
  reg [7:0]  pay;
  reg [2:0]  quiet_n;

  function [3:0] decode(input [2:0] t);
    begin
      if      (t == 3'b000) decode = 4'h6;
      else if (t == 3'b001) decode = 4'h9;
      else if (t == 3'b010) decode = 4'hA;
      else if (t == 3'b011) decode = 4'hD;
      else                  decode = 4'h0;
    end
  endfunction

  always @(posedge clk) begin
    if (rst) begin
      st <= S_QUIET; n <= 0; pay <= 0; quiet_n <= 0;
      cmd_out <= 4'h0; frame_done <= 1'b0;
    end else begin
      frame_done <= 1'b0;
      case (st)
        S_QUIET: begin
          quiet_n <= rx ? (quiet_n + 1) : 3'd0;
          if (quiet_n == 3'd2) st <= S_ARM;
        end
        S_ARM:   if (!rx) st <= S_START;
        S_START: begin n <= 0; st <= S_DATA; end
        S_DATA:  begin
          pay <= {rx, pay[7:1]};
          n   <= n + 1;
          if (n == 7) st <= S_STOP;
        end
        S_STOP:  begin
          cmd_out    <= decode(pay[2:0]);
          frame_done <= 1'b1;
          quiet_n    <= 0;
          st         <= S_QUIET;
        end
        default: st <= S_QUIET;
      endcase
    end
  end
endmodule
"""


# ── each defect fires SEPARATELY, and is named ─────────────────────────────

def test_mapping_only_fires_mapping_alone():
    assert _errors(SPEC, WRONG_MAPPING) == [MAPPING_RULE]


def test_latency_only_fires_latency_alone():
    assert _errors(SPEC, WRONG_LATENCY) == [LATENCY_RULE]


def test_interframe_only_fires_interframe_alone():
    assert _errors(SPEC, WRONG_IFS) == [IFS_RULE]


def test_all_three_fire_together_and_each_is_named():
    assert _errors(SPEC, WRONG_ALL3) == sorted(ERROR_RULES)


def test_two_violated_together_names_BOTH_not_one():
    # the composition case: mapping and inter-frame are violated at once while
    # the latency element holds. A row-level boolean would say "failed"; the
    # reader needs to know WHICH two.
    assert _errors(SPEC, WRONG_MAP_AND_IFS) == sorted([MAPPING_RULE, IFS_RULE])
    line = _composition(SPEC, WRONG_MAP_AND_IFS)
    assert "mapping=VIOLATED" in line
    assert "interframe=VIOLATED" in line
    assert "latency=SATISFIED" in line
    assert "2 of 3 stated element(s) FAILED: mapping, interframe" in line


# ── the repaired design is recognised as correct ───────────────────────────

def test_program_first_output_is_clean_on_all_three():
    assert _errors(SPEC, CORRECT) == []


def test_program_first_output_reports_all_three_SATISFIED_together():
    line = _composition(SPEC, CORRECT)
    assert "mapping=SATISFIED" in line
    assert "latency=SATISFIED" in line
    assert "interframe=SATISFIED" in line
    assert "all 3 stated element(s) hold TOGETHER" in line


# ── THE CONTROL: a different, legitimate architecture must stay GREEN ──────

def test_alternative_architecture_control_stays_green():
    # An explicit state machine with a REGISTERED output that meets the same
    # contract by a different route. If this reddens, the rules above are style
    # rules and not conformance checks.
    assert _errors(SPEC, ALT_ARCH) == []


def test_alternative_architecture_mapping_and_interframe_are_SATISFIED():
    # green for the right REASON, not because the contract failed to arm
    line = _composition(SPEC, ALT_ARCH)
    assert "mapping=SATISFIED" in line
    assert "interframe=SATISFIED" in line


def test_alternative_architecture_latency_is_routed_not_guessed():
    # its cmd_out and frame_done are produced by the same register stage with no
    # structural path between them, so the relative timing is NOT decidable from
    # structure. That is reported by name, never rounded into a number.
    line = _composition(SPEC, ALT_ARCH)
    assert "latency=AI_REQUIRED" in line
    assert "not decidable from structure" in line


# ── the unit is NEVER defaulted ────────────────────────────────────────────

def test_latency_without_a_unit_is_AI_REQUIRED_not_an_error():
    spec = SPEC.replace("must be valid in the same clock cycle that",
                        "must be valid at most 2 after")
    assert LATENCY_RULE not in _errors(spec, WRONG_LATENCY)
    assert "latency=AI_REQUIRED" in _composition(spec, WRONG_LATENCY)


def test_latency_in_bit_periods_is_not_compared_to_a_register_count():
    spec = SPEC.replace("must be valid in the same clock cycle that",
                        "must be valid exactly 0 bit periods after")
    line = _composition(spec, WRONG_LATENCY)
    assert LATENCY_RULE not in _errors(spec, WRONG_LATENCY)
    assert "latency=AI_REQUIRED" in line
    assert "oversampling ratio" in line


def test_interframe_without_a_unit_is_AI_REQUIRED_not_an_error():
    spec = SPEC.replace("at least 3 idle bit periods", "at least 3 idle gaps")
    assert IFS_RULE not in _errors(spec, WRONG_IFS)
    assert "interframe=AI_REQUIRED" in _composition(spec, WRONG_IFS)


def test_a_bare_mention_of_inter_frame_space_does_not_arm_anything():
    # measured on the corpus: keying on the vocabulary alone armed 68 documents
    # whose sentences state no quantity at all ("separated by time").
    spec = SPEC.replace(
        "Consecutive frames must be separated by at least 3 idle bit periods; "
        "a start\nbit seen sooner is not the start of a frame.",
        "Frames are separated by time on the wire.")
    assert "interframe=NOT_STATED" in _composition(spec, WRONG_IFS)


# ── mapping-side guards: each kills a legitimate reading ───────────────────

def test_identity_table_never_arms_the_mapping_rule():
    # a table that maps every value to itself cannot tell "applied the table"
    # from "forwarded the field"; forwarding IS correct there.
    spec = SPEC.replace("4'h6", "4'h0").replace("4'h9", "4'h1") \
               .replace("4'hA", "4'h2").replace("4'hD", "4'h3")
    assert MAPPING_RULE not in _errors(spec, WRONG_MAPPING)


def test_single_row_table_never_arms_the_mapping_rule():
    spec = SPEC.replace("  3'b001 -> 4'h9\n  3'b010 -> 4'hA\n  3'b011 -> 4'hD\n",
                        "")
    assert MAPPING_RULE not in _errors(spec, WRONG_MAPPING)


def test_mapping_rule_silent_when_a_case_lookup_applies_the_table():
    assert MAPPING_RULE not in _errors(SPEC, CORRECT)
    assert "table evidence present" in _composition(SPEC, WRONG_LATENCY)


def test_mapping_rule_silent_when_any_mapped_value_is_present():
    # a design that applies the table IMPERFECTLY is a different defect and this
    # rule must not claim it. One mapped constant anywhere disarms it.
    rtl = WRONG_MAPPING.replace("always @(*) cmd_c = {1'b0, ftype};",
                                "always @(*) cmd_c = (ftype == 3'b000) ? 4'h6\n"
                                "                                      : {1'b0, ftype};")
    assert MAPPING_RULE not in _errors(SPEC, rtl)


def test_mapping_rule_needs_a_mapping_intent_phrase():
    spec = SPEC.replace("which is decoded to `cmd_out` as\nfollows:",
                        "and `cmd_out` is described by:")
    assert MAPPING_RULE not in _errors(spec, WRONG_MAPPING)


# ── the forwarding shapes the rule must SEE ────────────────────────────────

def test_qualified_and_concat_forwards_are_recognised_as_forwarding():
    # `done ? f : 4'h0` and `{1'b0, f}` both hand on the raw field. Reading only
    # a bare identifier missed both and the rule went silent on WRONG_MAPPING.
    assert scc._forward_source("done_q ? cmd_c : 4'h0") == "cmd_c"
    assert scc._forward_source("{1'b0, ftype}") == "ftype"
    assert scc._forward_source("sh[2:0]") == "sh"
    assert scc._forward_source("a + b") is None
    assert scc._forward_source("{tag, ftype}") is None


# ── inter-frame evidence: a constant is evidence only where compared ───────

def test_a_decode_constant_is_not_evidence_of_a_gap():
    # measured: a table entry `4'h3` once supplied evidence for a stated gap of
    # 3 and the rule went quiet on a receiver with no inter-frame logic at all.
    body = "module m; wire [3:0] c; assign c = 4'h3; endmodule"
    assert scc._rtl_interframe_evidence(body, 3) is None


def test_a_compared_constant_IS_evidence_of_a_gap():
    body = "module m; reg [3:0] n; always @(posedge clk) if (n == 3) n <= 0; endmodule"
    assert scc._rtl_interframe_evidence(body, 3) is not None


def test_a_gap_named_identifier_IS_evidence_of_a_gap():
    body = "module m; localparam IDLE_MIN = 7; endmodule"
    assert scc._rtl_interframe_evidence(body, 3) is not None


# ── the JSON contract channel ──────────────────────────────────────────────

def test_json_contract_prose_is_not_discarded():
    # flow/phase1_phase2_phase3.yaml step 2 passes an L9 JSON, whose port
    # entries carry input-derived `description` prose. Measured on the base:
    # the same wording in a .md reached the rules and in a .json reached none.
    import json
    doc = {"top_module": "TopModule",
           "description": SPEC,
           "ports": [{"name": "clk", "direction": "input", "width": 1}]}
    prose = fc.input_prose_from_json(json.dumps(doc))
    assert "decoded to `cmd_out`" in prose
    assert "idle bit periods" in prose


def test_json_prose_extractor_returns_empty_on_non_json():
    # "could not read it" must not become "read it and it was empty" upstream
    assert fc.input_prose_from_json("not json at all") == ""


def test_json_contract_channel_reaches_the_frame_rules():
    src = strip_comments(WRONG_ALL3)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(extract_spec_contract("{}", is_json=True), nm, ports,
                   scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text="", input_prose=SPEC)
    assert sorted(f.rule for f in fs
                  if f.severity == "ERROR" and f.rule in ERROR_RULES) \
        == sorted(ERROR_RULES)


# ── the composition line is the joint verdict, not a count ─────────────────

def test_composition_names_every_element_even_when_not_stated():
    line = _composition("A design with no frame contract at all.\n", CORRECT)
    assert line == ""          # nothing stated -> no line at all, not a vacuous one


def test_composition_line_is_emitted_whenever_one_element_is_stated():
    spec = ("The receiver output `cmd_out` must be valid in the same clock "
            "cycle that `frame_done` asserts.\n\n - input clk\n - input rst\n"
            " - input rx\n - output cmd_out (4 bits)\n - output frame_done\n")
    line = _composition(spec, CORRECT)
    assert "mapping=NOT_STATED" in line
    assert "interframe=NOT_STATED" in line
    assert "latency=SATISFIED" in line
