"""ORGANIC #782 (R8C3) — rtl_hygiene_lint.py: TWO distinct multidriven/hygiene
defects fixed program-first, chip-AGNOSTICally.

REAL_GAP (binary_to_gray_0013 shape):
  (1) rule_undriven_and_unread missed a TOTALLY-DEAD reg/logic — its reg/logic
      arm guards on `name in lhs` (written-but-unread), so a `logic`/`reg`
      declared and NEITHER driven NOR read fell through entirely; only a dead
      WIRE was ever flagged (asymmetry). verilator -Wall reports UNUSEDSIGNAL.
      FIX: a TOTALLY-dead reg/logic arm emitting `unused-signal` (WARN; INFO
      carve-out for a memory ARRAY). The read test counts occurrences (a dead
      reg appears ONLY at its decl: tot_occ == 1) so a READ-BUT-UNDRIVEN signal
      is NOT mislabeled.
  (2) rule_multidriven_register short-circuits on <2 always blocks and models
      only always-vs-always races, so a net driven by BOTH a continuous `assign`
      AND a procedural `always` block (iverilog PROCASSWIRE / "not a valid
      l-value for a procedural assignment") was missed. FIX: new
      rule_continuous_vs_procedural_driver (per-module; excises the over-bounded
      last-block body's swallowed continuous `assign` statements before scanning
      procedural LHS) emitting `multidriven-continuous-procedural` ERROR.

FALSE_POSITIVE (sync_serial_communication_0052 shape):
  rule_multidriven_register's whole-file flat scan + bare-name reg_block_idx key
  collided same-named `bit_count`/`data_reg` across sibling tx_block/rx_block
  modules into a bogus cross-domain race even though verilator -Wall reports
  ZERO MULTIDRIVEN. FIX: new _module_regions() splitter + `region`-aware
  _iter_always_blocks so multidriven candidacy is confined to a SINGLE module
  scope.

§4.05 NO-LEAK (load-bearing — this relaxes one gate, the sibling-module FP, and
adds two): every genuine defect of the same class must STILL hard-block:
  * same-MODULE cross-domain (different-clocking) race -> WARN
  * genuine continuous+procedural on the same net in ONE module -> ERROR
  * genuine non-exhaustive / partial combinational case -> WARN
  * reset-less / forgot-reset free-running registered output -> WARN
  * same-domain reset-clear + unconditional datapath race -> WARN
  * genuinely dead scalar reg -> unused-signal WARN
  * READ-BUT-UNDRIVEN reg must NOT be mislabeled as unused-signal
  * legal `always @(*)` then `assign data_out=…` must NOT false-fire cont+proc
"""
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_LINT = _PROGRAMS / "rtl_hygiene_lint.py"


def _run(tmp_path, src, name="d.sv", severity="INFO"):
    p = tmp_path / name
    p.write_text(src)
    jp = tmp_path / (name + ".json")
    proc = subprocess.run(
        [sys.executable, str(_LINT), "--severity", severity,
         "--json", str(jp), str(p)],
        capture_output=True, text=True)
    findings = json.loads(jp.read_text()) if jp.exists() else []
    return proc, findings


def _rules(findings):
    return {f["rule"] for f in findings}


# ---------------------------------------------------------------------------
# REAL_GAP — binary_to_gray_0013 shape: BOTH defects in one module.
#   * `gray_out_d1` (logic) declared but NEITHER driven NOR read  -> dead
#   * `gray_out` driven by a continuous assign AND a procedural always -> cp
# Unpatched 1.0.92: rc=0 ('0 errors, 0 warnings, 0 info'). Fixed: rc=1.
# ---------------------------------------------------------------------------
_BIN_TO_GRAY = (
    "module binary_to_gray #(parameter WIDTH = 4) (\n"
    "    input  [WIDTH-1:0] i,\n"
    "    output [WIDTH-1:0] gray_out\n"
    ");\n"
    "    logic [WIDTH-1:0] gray_out_d1;\n"
    "    assign gray_out[WIDTH-1] = i[WIDTH-1];\n"
    "    always_ff @(*) begin\n"
    "        gray_out = i ^ (i >> 1);\n"
    "    end\n"
    "endmodule\n")


def test_real_gap_dead_logic_and_cont_proc_now_block(tmp_path):
    proc, findings = _run(tmp_path, _BIN_TO_GRAY, "binary_to_gray.sv")
    # was rc=0 on unpatched 1.0.92; now hard-blocks.
    assert proc.returncode == 1, proc.stdout
    rules = _rules(findings)
    # (1) the totally-dead `logic` is now flagged.
    assert "unused-signal" in rules
    dead = [f for f in findings if f["rule"] == "unused-signal"]
    assert any(f["symbol"] == "gray_out_d1" and f["severity"] == "WARN"
               for f in dead)
    # (2) the continuous+procedural driver on `gray_out` is now an ERROR.
    assert "multidriven-continuous-procedural" in rules
    cp = [f for f in findings if f["rule"] == "multidriven-continuous-procedural"]
    assert any(f["symbol"] == "gray_out" and f["severity"] == "ERROR"
               for f in cp)


# ---------------------------------------------------------------------------
# FALSE_POSITIVE — sync_serial_communication_0052 shape: same-named regs in
# sibling modules, each driven by ONE always block in its own scope. verilator
# -Wall reports ZERO MULTIDRIVEN. Unpatched 1.0.92: rc=1 (bogus race). Fixed: 0.
# ---------------------------------------------------------------------------
_SIBLING_SAME_NAME = (
    "module tx_block (\n"
    "    input clk, input reset_n, input start,\n"
    "    output reg [7:0] data_reg, output reg [3:0] bit_count\n"
    ");\n"
    "    always @(posedge clk or negedge reset_n) begin\n"
    "        if (!reset_n) begin\n"
    "            data_reg  <= 8'd0;\n"
    "            bit_count <= 4'd0;\n"
    "        end else begin\n"
    "            data_reg  <= {data_reg[6:0], 1'b0};\n"
    "            bit_count <= bit_count + 4'd1;\n"
    "        end\n"
    "    end\n"
    "endmodule\n"
    "module rx_block (\n"
    "    input serial_clk, input reset_n, input rx_in,\n"
    "    output reg [7:0] data_reg, output reg [3:0] bit_count\n"
    ");\n"
    "    always @(posedge serial_clk or negedge reset_n) begin\n"
    "        if (!reset_n) begin\n"
    "            data_reg  <= 8'd0;\n"
    "            bit_count <= 4'd0;\n"
    "        end else begin\n"
    "            data_reg  <= {rx_in, data_reg[7:1]};\n"
    "            bit_count <= bit_count + 4'd1;\n"
    "        end\n"
    "    end\n"
    "endmodule\n"
    "module sync_serial_communication_top (\n"
    "    input clk, input serial_clk, input reset_n,\n"
    "    input start, input rx_in,\n"
    "    output [7:0] tx_data, output [7:0] rx_data\n"
    ");\n"
    "    tx_block u_tx (.clk(clk), .reset_n(reset_n), .start(start),\n"
    "                   .data_reg(tx_data), .bit_count());\n"
    "    rx_block u_rx (.serial_clk(serial_clk), .reset_n(reset_n), .rx_in(rx_in),\n"
    "                   .data_reg(rx_data), .bit_count());\n"
    "endmodule\n")


def test_false_positive_sibling_same_name_no_longer_blocks(tmp_path):
    proc, findings = _run(tmp_path, _SIBLING_SAME_NAME, "ssc_top.sv")
    # was rc=1 (two bogus multidriven WARNs) on unpatched 1.0.92; now clean.
    assert proc.returncode == 0, proc.stdout
    assert "multidriven-register" not in _rules(findings), findings


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK negatives — each genuine defect of the same class STILL blocks.
# ---------------------------------------------------------------------------
_NEG_SAME_MODULE_CROSS_DOMAIN = (
    "module dual_clk_race (\n"
    "    input clk_a, input clk_b, input reset_n, input d,\n"
    "    output reg q\n"
    ");\n"
    "    always @(posedge clk_a or negedge reset_n)\n"
    "        if (!reset_n) q <= 1'b0; else q <= d;\n"
    "    always @(posedge clk_b)\n"
    "        q <= ~q;\n"
    "endmodule\n")


def test_noleak_same_module_cross_domain_still_warns(tmp_path):
    proc, findings = _run(tmp_path, _NEG_SAME_MODULE_CROSS_DOMAIN, "n1.sv")
    assert proc.returncode == 1, proc.stdout
    assert any(f["rule"] == "multidriven-register" and f["symbol"] == "q"
               for f in findings), findings


_NEG_GENUINE_CONT_PROC = (
    "module cp_bug (input clk, input d, output y);\n"
    "    assign y = d;\n"
    "    always @(posedge clk) y = ~d;\n"
    "endmodule\n")


def test_noleak_genuine_cont_proc_still_errors(tmp_path):
    proc, findings = _run(tmp_path, _NEG_GENUINE_CONT_PROC, "n2.sv")
    assert proc.returncode == 1, proc.stdout
    assert any(f["rule"] == "multidriven-continuous-procedural"
               and f["symbol"] == "y" and f["severity"] == "ERROR"
               for f in findings), findings


_NEG_PARTIAL_CASE = (
    "module part_case (input [1:0] sel, output reg [1:0] o);\n"
    "    always @(*)\n"
    "        case (sel)\n"
    "            2'b00: o = 2'b01;\n"
    "            2'b01: o = 2'b10;\n"
    "        endcase\n"
    "endmodule\n")


def test_noleak_partial_combinational_case_still_warns(tmp_path):
    proc, findings = _run(tmp_path, _NEG_PARTIAL_CASE, "n3.sv")
    assert proc.returncode == 1, proc.stdout
    assert any(f["rule"] == "case-no-default" for f in findings), findings


_NEG_RESETLESS_OUTPUT = (
    "module free_run (input clk, output reg q);\n"
    "    always @(posedge clk) q <= ~q;\n"
    "endmodule\n")


def test_noleak_resetless_free_running_output_still_warns(tmp_path):
    proc, findings = _run(tmp_path, _NEG_RESETLESS_OUTPUT, "n4.sv")
    assert proc.returncode == 1, proc.stdout
    assert any(f["rule"] == "uninit-registered-output" for f in findings), findings


_NEG_SAME_DOMAIN_RACE = (
    "module sd_race (input clk, input rst, input d, output reg q);\n"
    "    always @(posedge clk) if (rst) q <= 1'b0;\n"
    "    always @(posedge clk) q <= d;\n"
    "endmodule\n")


def test_noleak_same_domain_reset_clear_race_still_warns(tmp_path):
    # the same-MODULE race must survive the module-region partition (no leak).
    proc, findings = _run(tmp_path, _NEG_SAME_DOMAIN_RACE, "n5.sv")
    assert proc.returncode == 1, proc.stdout
    assert any(f["rule"] == "multidriven-register" and f["symbol"] == "q"
               for f in findings), findings


_NEG_DEAD_SCALAR_REG = (
    "module dead (input clk, input d, output reg q);\n"
    "    reg unused_scratch;\n"
    "    always @(posedge clk) q <= d;\n"
    "endmodule\n")


def test_noleak_genuine_dead_scalar_reg_still_warns(tmp_path):
    proc, findings = _run(tmp_path, _NEG_DEAD_SCALAR_REG, "n6.sv")
    assert proc.returncode == 1, proc.stdout
    assert any(f["rule"] == "unused-signal" and f["symbol"] == "unused_scratch"
               and f["severity"] == "WARN" for f in findings), findings


# READ-BUT-UNDRIVEN reg `q` (`w_ptr <= q;`) must NOT be mislabeled as dead by the
# new totally-dead arm (the occurrence-count guard distinguishes it).
_NEG_READ_BUT_UNDRIVEN = (
    "module rbu (input clk, output reg [7:0] w_ptr);\n"
    "    reg [7:0] q;\n"
    "    always @(posedge clk) w_ptr <= q;\n"
    "endmodule\n")


def test_noleak_read_but_undriven_reg_not_mislabeled_dead(tmp_path):
    _proc, findings = _run(tmp_path, _NEG_READ_BUT_UNDRIVEN, "n7.sv")
    # `q` is read once (it is the RHS) so it must NOT be flagged unused-signal.
    assert not any(f["rule"] == "unused-signal" and f["symbol"] == "q"
                   for f in findings), findings


# A legal `always @(*)` then `assign data_out = t;` must NOT false-fire the new
# continuous+procedural rule (the last-block over-bounded-body trap).
_LEGAL_ALWAYS_THEN_ASSIGN = (
    "module legal_a (input [3:0] a, output [3:0] data_out);\n"
    "    reg [3:0] t;\n"
    "    always @(*) t = a + 1;\n"
    "    assign data_out = t;\n"
    "endmodule\n")


def test_legal_always_then_assign_no_false_cont_proc(tmp_path):
    proc, findings = _run(tmp_path, _LEGAL_ALWAYS_THEN_ASSIGN, "legal.sv")
    assert proc.returncode == 0, proc.stdout
    assert "multidriven-continuous-procedural" not in _rules(findings), findings


# A dead UNPACKED MEMORY ARRAY must be advisory INFO (carve-out), never block.
_LEGAL_DEAD_MEM_ARRAY = (
    "module legal_mem (input clk, input [3:0] addr, input [7:0] wd, input we);\n"
    "    reg [7:0] mem [0:15];\n"
    "    always @(posedge clk) if (we) mem[addr] <= wd;\n"
    "endmodule\n")


def test_legal_dead_memory_array_advisory_only(tmp_path):
    proc, findings = _run(tmp_path, _LEGAL_DEAD_MEM_ARRAY, "mem.sv")
    assert proc.returncode == 0, proc.stdout
    # no WARN/ERROR for `mem`; only advisory INFO (unread-reg memory carve-out).
    blocking = [f for f in findings
                if f["symbol"] == "mem" and f["severity"] in ("WARN", "ERROR")]
    assert not blocking, findings


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── r2 Step-2.7 §4.05 remediation: _module_regions walked over comment-stripped
# (but NOT string-blanked) source, so an `endmodule`/`module` token inside a
# `$display`/`$error` string truncated the region and MASKED a genuine
# same-module multidriven / continuous-procedural defect. The blanked-string
# walk must keep flagging both. ──
import subprocess as _sp2
import sys as _sys2
import json as _json2
from pathlib import Path as _Path2

_RH2 = _Path2(__file__).resolve().parents[1] / "rtl_hygiene_lint.py"


def _rules_at(tmp_path, src, severity):
    p = tmp_path / "d.sv"; p.write_text(src)
    jp = tmp_path / "o.json"
    r = _sp2.run([_sys2.executable, str(_RH2), "--severity", severity,
                  "--json", str(jp), str(p)], capture_output=True, text=True)
    fs = _json2.loads(jp.read_text()) if jp.exists() else []
    return r.returncode, [(f["severity"], f["rule"]) for f in fs]


def test_782r2_noleak_endmodule_in_string_does_not_mask_multidriven(tmp_path):
    # genuine same-module cross-clock race on `flag`; an `endmodule` token sits
    # inside a $error string between the two writers.
    src = (
        "module ctrl(input clk_sys, input clk_aux, input rst_n, input d,\n"
        " output reg flag);\n"
        " always @(posedge clk_sys or negedge rst_n)\n"
        "  if (!rst_n) flag <= 1'b0; else flag <= d;\n"
        ' initial $error("flag glitched before endmodule completed");\n'
        " always @(posedge clk_aux or negedge rst_n)\n"
        "  if (!rst_n) flag <= 1'b0; else flag <= ~d;\n"
        "endmodule\n")
    rc, rules = _rules_at(tmp_path, src, "WARN")
    assert rc == 1, rules
    assert any(r == "multidriven-register" for _s, r in rules), rules


def test_782r2_noleak_endmodule_in_string_does_not_mask_cont_proc(tmp_path):
    # illegal continuous + procedural drive of `y`; an `endmodule` token sits in
    # a $display string between the two drivers.
    src = (
        "module dut(input d, output y);\n"
        " assign y = d;\n"
        ' initial $display("note: y settles before endmodule");\n'
        " always @(*) y = d;\n"
        "endmodule\n")
    rc, rules = _rules_at(tmp_path, src, "ERROR")
    assert rc == 1, rules
    assert any(r == "multidriven-continuous-procedural" for _s, r in rules), rules


def test_782r2_blank_string_literals_preserves_offsets():
    import rtl_hygiene_lint as _R
    s = 'a "module x endmodule" b'
    blanked = _R._blank_string_literals(s)
    assert len(blanked) == len(s)               # length preserved (offset-safe)
    assert "module" not in blanked and "endmodule" not in blanked
    assert blanked.startswith('a "') and blanked.endswith('" b')
