#!/usr/bin/env python3
"""A package function header and a macro definition were reported as missing modules.

MEASURED DEFECT (vibe-ic#2093)
==============================
``_INST_FULL_RE`` matches ``<id> <id> (`` anywhere in a file, and two
non-instantiation constructs have exactly that shape::

    `define TEST_UNLOCKED(idx)              a compiler directive
    function automatic mubi4_t mubi4_and(x) a function header

On a staged OpenTitan-AES set (131 files, 126 scanned) the preflight
returned 36 FAIL rows. ONE was a real dangling module reference
(``aes_sbox_dom``, correctly classified ``generate_branch_default``); the
other 35 were SV package typedefs returned by function headers
(``mubi4_t``, ``secded_39_32_t``, ``tl_h2d_cmd_intg_t``, ...), one function
header inside a module generate block (``matrix_col_t``), and the token
``define``. Each printed::

    module 'mubi4_t' is instantiated outside any generate conditional and
    is NOT in the staged closure - genuine hole.

which is a confident instruction to stage a type that no tool can stage,
and it buried the one row that was true. The same rows fed
CATALOG_GLUE_CLOSURE #778's "32 of 130 staged files unreachable".

WHY THE FIX IS POSITIONAL AND NOT A NAME LIST
=============================================
Blacklisting ``define`` and ``*_t`` would pass this fixture and fail the
next vendor package, whose types are named by another convention. A module
instantiation is a MODULE ITEM: the innermost enclosing region has to be a
module. That is decidable from the grammar and does not enumerate anything.

DIRECTIONS PINNED HERE
======================
POSITIVE  a genuine dangling reference inside a module still reads
          "genuine hole" -- the check must keep its teeth.
NEGATIVE  a function header in a package, a function header inside a
          module, and a macro definition produce nothing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import staged_rtl_closure_preflight as PF  # noqa: E402

#: The measured shape, reduced: a package whose function headers return
#: typedefs, a module carrying a macro definition and a local function, and
#: one real dangling instantiation.
_PKG = """\
package prim_mubi_pkg;
  typedef enum logic [3:0] { MuBi4True = 4'h6 } mubi4_t;
  typedef enum logic [7:0] { MuBi8True = 8'h96 } mubi8_t;
  function automatic mubi4_t mubi4_and(mubi4_t a, mubi4_t b);
    return mubi4_t'(a & b);
  endfunction
  function automatic mubi8_t mubi8_and(mubi8_t a, mubi8_t b);
    return mubi8_t'(a & b);
  endfunction
endpackage
"""

_MOD_LOCAL_FN = """\
module prim_lfsr (input logic clk_i, output logic q_o);
  `define TEST_UNLOCKED(idx)  \\
     (idx == 0)
  typedef logic [3:0] matrix_col_t;
  function automatic matrix_col_t lrotcol(matrix_col_t col, integer shift);
    return col;
  endfunction
  assign q_o = clk_i;
endmodule
"""

_REAL_HOLE = """\
module top (input logic clk_i, output logic q_o);
  missing_core u_core (.clk_i(clk_i), .q_o(q_o));
endmodule
"""


def _audit(tmp_path, **files):
    d = tmp_path / "rtl"
    d.mkdir()
    for name, text in files.items():
        (d / f"{name}.sv").write_text(text)
    return PF.audit([str(d)])


def test_package_function_headers_are_not_missing_modules(tmp_path):
    report = _audit(tmp_path, prim_mubi_pkg=_PKG)
    assert report["verdict"] == "PASS", (
        "a package function header returning a typedef was reported as a "
        f"missing module: {[f['module_ref'] for f in report['findings']]}")


def test_a_macro_and_a_module_local_function_are_not_missing_modules(tmp_path):
    report = _audit(tmp_path, prim_lfsr=_MOD_LOCAL_FN)
    assert report["verdict"] == "PASS", (
        "a macro definition or a function header inside a module was "
        f"reported as a missing module: "
        f"{[f['module_ref'] for f in report['findings']]}")


def test_a_genuine_dangling_reference_is_still_reported(tmp_path):
    """The teeth. Without this the fix could be 'report nothing'."""
    report = _audit(tmp_path, top=_REAL_HOLE)
    refs = [f["module_ref"] for f in report["findings"]]
    assert refs == ["missing_core"], refs
    assert report["findings"][0]["rule"] == "unconditional_dangling_ref"
    assert "genuine hole" in report["findings"][0]["message"]


def test_the_real_row_survives_alongside_the_false_ones(tmp_path):
    """MEMBERSHIP, not count: the same tree that carried 35 false rows must
    now carry exactly the one that was true."""
    report = _audit(tmp_path, prim_mubi_pkg=_PKG,
                    prim_lfsr=_MOD_LOCAL_FN, top=_REAL_HOLE)
    assert {f["module_ref"] for f in report["findings"]} == {"missing_core"}


def test_an_unmatched_end_token_does_not_promote_candidates(tmp_path):
    """A file this scanner cannot follow drops its candidates rather than
    reporting them; degrade quietly here, never loudly and wrongly."""
    report = _audit(tmp_path, broken="endmodule\nfoo_t bar(x);\n")
    assert report["findings"] == [], report["findings"]
