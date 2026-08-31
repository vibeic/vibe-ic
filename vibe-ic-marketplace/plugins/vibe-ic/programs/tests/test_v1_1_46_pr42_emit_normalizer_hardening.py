"""Step-2.7 §4.05 hardening of PR #42 cvdp_gate emit-normalizers (gatekeeper
remediation). The DANGER direction for an emit-normalizer is CORRUPTION: turning
a completion the harness would decode (or a tolerated doc answer) into a WRONG or
broken artifact. Step-2.7 reproduced five corruptions; each is pinned here.

CHANGE 1 — flat file-map recovery (json_code_files):
  * HIGH false-BLOCK: a doc/prose/explanation answer (or an in-string ``` fence
    under a non-path key) whose text merely contains `module … endmodule` was
    mis-recovered as code and force-compiled → BLOCK of the tolerated doc_only
    path. FIX: recover ONLY code-suffix KEYS whose VALUE is real Verilog source.
  * MED: a `.vh`/`.svh` value that is documentation (not source) was pulled into
    the compile payload by key-suffix alone. FIX: value must look like Verilog.

CHANGE 2 — multi-file blob split (_parse_modules / _split_blob_to_expected /
_emit_or_split):
  * HIGH truncate: `endmodule` inside a // comment / string truncated a block.
  * HIGH re-key: a comment naming `module <other>` overwrote a good block.
  * HIGH preamble-drop: a `package`/`import` preamble was dropped from the split.
  * MED basename-collision: two expected paths sharing a basename duplicated the
    same module into both → the `already declared` error the splitter prevents.
  FIX: boundary detection on a length-preserving comment/string mask; preamble
  prepended to the first file; collision → no per-module split; and a multi-file
  problem ALWAYS emits the {"code":[…]} envelope (never a bare blob), falling
  back to a LOSSLESS all-in-first-file emit so each module appears EXACTLY once.

chip-AGNOSTIC. Thirteen of these are pure string structure and need no EDA
tool; `test_flat_multifile_emit_carries_hygiene_fix` drives the FULL
`gate_record` verdict and therefore needs a real iverilog AND yosys — it is
guarded, because "the toolchain is absent" is not evidence about the emit.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

_MOD_FOO = "module foo(input a, output y); assign y = a; endmodule"
_MOD_BAR = "module bar(input b, output z); assign z = ~b; endmodule"


# ── Change 1: flat-map false-recovery (the HIGH false-BLOCK) ──────────────────
def test_doc_prose_answer_with_module_tokens_not_recovered():
    # tokens `module foo … endmodule` in PROSE under a non-path key must NOT be
    # mis-recovered (would force-compile → false BLOCK of the doc_only PASS).
    for key in ("explanation", "answer", "spec", "description", "reasoning",
                "review_notes"):
        comp = json.dumps({key: "The module foo connects to the submodule and "
                                "then endmodule closes it."})
        assert G.json_code_files(comp) is None, key


def test_in_string_code_fence_under_non_path_key_not_recovered():
    comp = json.dumps({"answer": "```verilog\n" + _MOD_FOO + "\n```"})
    assert G.json_code_files(comp) is None


def test_prose_vh_value_excluded_real_rtl_still_recovered():
    # MED: a .vh value that is documentation must be excluded, the real rtl PASS.
    comp = json.dumps({"rtl/foo.sv": _MOD_FOO,
                       "docs/notes.vh": "Implementation notes: the module is "
                                        "reset-active-low. See spec section 3."})
    files = G.json_code_files(comp)
    assert files is not None and set(files) == {"rtl/foo.sv"}


def test_intended_flat_map_and_package_map_still_recover():
    assert "rtl/foo.sv" in (G.json_code_files(json.dumps({"rtl/foo.sv": _MOD_FOO})) or {})
    pkgmap = G.json_code_files(json.dumps({
        "rtl/pkg.sv": "package p; typedef logic[7:0] b_t; endpackage",
        "rtl/foo.sv": _MOD_FOO}))
    assert pkgmap is not None and set(pkgmap) == {"rtl/pkg.sv", "rtl/foo.sv"}


def test_prose_module_extends_or_import_not_recovered():
    # Step-2.7 re-review: a real module never `extends`, and a package-import
    # header is `import pkg::*` (has `::`). Prose "module X extends/import …"
    # must NOT be recovered (else a doc answer is force-compiled → false BLOCK).
    assert G.json_code_files(json.dumps({
        "rtl/design.sv": "This module fifo extends the base buffer to depth 64. "
                         "the synthesized result ends with endmodule."})) is None
    assert G.json_code_files(json.dumps({
        "rtl/x.sv": "the module fetch import stage 2 then endmodule"})) is None
    # but a genuine package-import module header IS recovered
    assert "rtl/foo.sv" in (G.json_code_files(json.dumps({
        "rtl/foo.sv": "module foo import mypkg::*; (input a, output y); "
                      "assign y=a; endmodule"})) or {})


def test_mid_sentence_directive_in_doc_vh_excluded():
    # a doc .vh whose prose mentions a backtick directive MID-LINE must not be
    # pulled into the compile payload (line-anchored _looks_like_verilog).
    r = G.json_code_files(json.dumps({
        "rtl/alu.sv": "module alu(input [3:0] a, input [3:0] b, output [3:0] y);\n"
                      " assign y = a & b;\nendmodule\n",
        "rtl/defs.vh": "Remember to `include this header before instantiating the alu module."}))
    assert r is not None and set(r) == {"rtl/alu.sv"}
    # a REAL line-anchored `define header IS kept alongside the module
    r2 = G.json_code_files(json.dumps({
        "rtl/defs.vh": "`define WIDTH 8\n`define DEPTH 64\n", "rtl/foo.sv": _MOD_FOO}))
    assert r2 is not None and set(r2) == {"rtl/defs.vh", "rtl/foo.sv"}


# ── Change 2: split boundary / preamble / collision corruptions ───────────────
def test_endmodule_inside_comment_does_not_truncate():
    foo = ("module foo(input wire a, output wire y);\n"
           "  // ends before the endmodule keyword below\n"
           "  assign y = a;\nendmodule")
    sp = G._split_blob_to_expected(foo + "\n\n" + _MOD_BAR,
                                   ["rtl/foo.sv", "rtl/bar.sv"])
    assert sp is not None
    assert "assign y = a;" in sp["rtl/foo.sv"]
    assert sp["rtl/foo.sv"].rstrip().endswith("endmodule")


def test_comment_naming_other_module_does_not_corrupt():
    mux = ("module mux(input [4:0] d, input sel, output [4:0] o);\n"
           "  assign o = sel ? d : 5'b0;\nendmodule")
    adder = ("module adder(input [3:0] a, input [3:0] b, output [4:0] s);\n"
             "  // see module mux for the pattern\n  assign s = a + b;\nendmodule")
    sp = G._split_blob_to_expected(mux + "\n\n" + adder,
                                   ["rtl/mux.sv", "rtl/adder.sv"])
    assert sp is not None
    assert "assign o = sel" in sp["rtl/mux.sv"]
    assert "assign s = a + b;" in sp["rtl/adder.sv"]


def test_package_preamble_preserved_in_split():
    pre = "package mypkg; typedef logic[7:0] byte_t; endpackage\nimport mypkg::*;\n"
    sp = G._split_blob_to_expected(pre + _MOD_FOO + "\n\n" + _MOD_BAR,
                                   ["rtl/foo.sv", "rtl/bar.sv"])
    assert sp is not None
    assert "package mypkg" in sp["rtl/foo.sv"]
    assert "import mypkg" in sp["rtl/foo.sv"]


def test_same_basename_collision_returns_none():
    sp = G._split_blob_to_expected(_MOD_FOO + "\n\n" + _MOD_BAR,
                                   ["rtl/foo.sv", "sub/foo.sv", "rtl/bar.sv"])
    assert sp is None


def test_multifile_emit_is_always_lossless_envelope():
    # collision case → all-in-first lossless fallback (never a bare blob); each
    # module appears exactly once across the emitted file set.
    em = json.loads(G._emit_or_split(_MOD_FOO + "\n\n" + _MOD_BAR,
                                     ["rtl/foo.sv", "sub/foo.sv", "rtl/bar.sv"]))
    assert "code" in em and isinstance(em["code"], list)
    allsrc = "\n".join(list(d.values())[0] for d in em["code"])
    assert allsrc.count("module foo") == 1 and allsrc.count("module bar") == 1
    # name != basename → cannot per-module split → lossless all-in-first, package kept
    pre = "package mypkg; endpackage\n"
    em2 = json.loads(G._emit_or_split(pre + "module top(input a,output y); assign y=a; endmodule",
                                      ["rtl/aaa.sv", "rtl/bbb.sv"]))
    src2 = "".join(list(d.values())[0] for d in em2["code"])
    assert "package mypkg" in src2 and src2.count("module top") == 1


def test_single_file_emit_unchanged():
    assert G._emit_or_split(_MOD_FOO, None) == _MOD_FOO
    assert G._emit_or_split(_MOD_FOO, ["rtl/only.sv"]) == _MOD_FOO


def test_pure_package_interface_map_recovered():
    # Step-2.7 re-review false-EXCLUDE: a legitimate no-top-level-module
    # deliverable (only a package + an interface) must be recovered, not dropped
    # (else the raw JSON is emitted verbatim → line-1 `{` syntax error).
    comp = json.dumps({
        "rtl/config_pkg.sv": "package config_pkg; typedef logic[7:0] byte_t; "
                             "localparam int DEPTH=16; endpackage",
        "rtl/axi_if.sv": "interface axi_if(input clk); logic[31:0] addr; "
                         "logic valid; modport master(output addr, valid); endinterface"})
    r = G.json_code_files(comp)
    assert r is not None and set(r) == {"rtl/config_pkg.sv", "rtl/axi_if.sv"}
    # a doc map with the head xor end keyword is still rejected
    assert G.json_code_files(json.dumps(
        {"explanation": "the module foo and package bar are described"})) is None


_HAS_TOOLCHAIN = (shutil.which("iverilog") is not None
                  and shutil.which("yosys") is not None)


@pytest.mark.skipif(not _HAS_TOOLCHAIN,
                    reason="drives the full gate_record verdict: needs a real "
                           "iverilog AND yosys. Without them the gate honestly "
                           "reports CANNOT ENFORCE, which is not evidence "
                           "about the emitted bytes this test is asserting on.")
def test_flat_multifile_emit_carries_hygiene_fix(tmp_path):
    # Step-2.7 re-review HIGH: a FLAT file-map multi-file completion whose bodies
    # hygiene --fix changed must emit the FIXED bytes (compile-equals-emit), not
    # the original un-fixed JSON (the writeback used to handle only "code" keys).
    foo = "module foo(input clk, output reg q); always @(posedge clk) q<=~q; endmodule"
    bar = "module bar(input clk, output reg r); always @(posedge clk) r<=~r; endmodule"
    comp = json.dumps({"rtl/foo.sv": foo, "rtl/bar.sv": bar})
    ok, out_rec, entry = G.gate_record(
        {"id": "x", "completion": comp}, tmp_path,
        response_files=["rtl/foo.sv", "rtl/bar.sv"])
    assert ok and entry["verdict"] == "PASS", entry
    emit = out_rec["completion"]
    # the power-up-determinism `initial` block --fix inserts must reach the emit
    assert "initial" in emit
    assert emit.lstrip().startswith("{")          # still a decodable JSON envelope


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
