"""issue #139 — 'extend, don't replace, given files' (functional-modification
clobber class): the deterministic half.

The general lesson (IC Expert DB class `functional-modification-delivery`):
when a modification task adds a new module to an EXISTING provided file, the
delivered file must preserve the original module(s) and add the new top
alongside — overwriting the file with only the new module deletes the very
definition the new logic instantiates and the design stops elaborating.

`file_extend_preserve_check.check_sets` flags ONLY the zero-false-positive
self-breaking sub-case (an overwritten definition the delivered set still
instantiates); the intent question (replacement vs deletion) is judgment and
stays advisory (why_not_bucket_a) — pinned by the negative fixtures here.
"""
import json
import subprocess
import sys
from pathlib import Path

import file_extend_preserve_check as F

PROGRAM = Path(F.__file__).resolve()

ORIG_MOD = """
module data_reduce #(parameter W = 8) (
    input  wire [W-1:0] a,
    input  wire [W-1:0] b,
    output wire [W-1:0] y
);
    assign y = a & b;
endmodule
"""

NEW_TOP_ONLY = """
module bit_diff_counter (
    input  wire [7:0] a,
    input  wire [7:0] b,
    output wire [7:0] cnt
);
    wire [7:0] y;
    data_reduce u_red (.a(a), .b(b), .y(y));
    assign cnt = ~y;
endmodule
"""

BOTH_MODULES = ORIG_MOD + NEW_TOP_ONLY


# ── the positive: the word-reducer-shaped self-breaking clobber ─────────────

def test_flags_overwrite_that_drops_instantiated_module():
    findings = F.check_sets(
        {"rtl/data_reduce.sv": ORIG_MOD},
        {"rtl/data_reduce.sv": NEW_TOP_ONLY})
    assert len(findings) == 1
    assert "data_reduce" in findings[0]
    assert "extend, don't replace" in findings[0]


def test_flags_when_surviving_original_file_instantiates_the_lost_module():
    # the dropped module is instantiated by an UNTOUCHED sibling context file
    sibling = "module top_wrap(); data_reduce u0 (.a(8'h0),.b(8'h0),.y()); endmodule"
    findings = F.check_sets(
        {"rtl/data_reduce.sv": ORIG_MOD, "rtl/top_wrap.sv": sibling},
        {"rtl/data_reduce.sv": "module unrelated(input wire x); endmodule"})
    assert len(findings) == 1 and "data_reduce" in findings[0]


# ── the negatives (the no-leak / judgment-residual pins) ────────────────────

def test_clean_when_delivery_preserves_original_alongside_new_top():
    assert F.check_sets(
        {"rtl/data_reduce.sv": ORIG_MOD},
        {"rtl/data_reduce.sv": BOTH_MODULES}) == []


def test_clean_when_dropped_module_is_not_instantiated_anywhere():
    # intended REPLACEMENT (nothing still instantiates the original) is the
    # judgment residual — deliberately NOT flagged (why_not_bucket_a).
    assert F.check_sets(
        {"rtl/data_reduce.sv": ORIG_MOD},
        {"rtl/data_reduce.sv": "module fresh_top(input wire x, output wire q);"
                               " assign q = ~x; endmodule"}) == []


def test_clean_when_new_file_instantiates_still_defined_module():
    # delivering the new top in a NEW file leaves the original definition
    # intact — the emit-alongside form the lesson asks for.
    assert F.check_sets(
        {"rtl/data_reduce.sv": ORIG_MOD},
        {"rtl/bit_diff_counter.sv": NEW_TOP_ONLY}) == []


def test_clean_when_definition_moves_to_another_delivered_file():
    assert F.check_sets(
        {"rtl/data_reduce.sv": ORIG_MOD},
        {"rtl/data_reduce.sv": NEW_TOP_ONLY,
         "rtl/data_reduce_impl.sv": ORIG_MOD}) == []


def test_comment_only_instantiation_does_not_count():
    commented = ("module fresh_top(input wire x);\n"
                 "// data_reduce u_red (.a(a), .b(b), .y(y));\n"
                 "/* data_reduce u2 (.a(a)); */\nendmodule\n")
    assert F.check_sets(
        {"rtl/data_reduce.sv": ORIG_MOD},
        {"rtl/data_reduce.sv": commented}) == []


def test_longer_identifier_prefix_is_not_an_instantiation():
    # `data_reduce_reg(...)` (a task/call on a LONGER name) must not read as
    # an instantiation of `data_reduce`.
    text = ("module fresh_top(input wire x);\n"
            "  initial data_reduce_reg(x);\n"
            "endmodule\n")
    assert not F.instantiates(text, "data_reduce")


def test_param_block_instantiation_is_detected():
    text = "module t(); data_reduce #(.W(16)) u_r (.a(a),.b(b),.y(y)); endmodule"
    assert F.instantiates(text, "data_reduce")


def test_module_declaration_is_not_an_instantiation():
    assert not F.instantiates(ORIG_MOD, "data_reduce")


# ── CLI roundtrip ───────────────────────────────────────────────────────────

def _run(before: Path, after: Path):
    return subprocess.run(
        [sys.executable, str(PROGRAM), "--before", str(before),
         "--after", str(after), "--json"],
        capture_output=True, text=True)


def test_cli_flags_and_exit_codes(tmp_path):
    before = tmp_path / "before" / "rtl"
    after = tmp_path / "after" / "rtl"
    before.mkdir(parents=True)
    after.mkdir(parents=True)
    (before / "data_reduce.sv").write_text(ORIG_MOD)
    (after / "data_reduce.sv").write_text(NEW_TOP_ONLY)
    r = _run(tmp_path / "before", tmp_path / "after")
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["pass"] is False and "data_reduce" in rep["findings"][0]

    # repaired delivery (both modules) → PASS, exit 0
    (after / "data_reduce.sv").write_text(BOTH_MODULES)
    r2 = _run(tmp_path / "before", tmp_path / "after")
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["pass"] is True


def test_cli_io_error_exit_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAM), "--before", str(tmp_path / "nope"),
         "--after", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 2
