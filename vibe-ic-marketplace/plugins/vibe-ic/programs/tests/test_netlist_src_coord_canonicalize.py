"""Tests for netlist_src_coord_canonicalize.py
(ORGANIC-20260531-yosys-write-verilog-nondeterministic-line-tagged-net-names).

The core property: a synthesised netlist that differs ONLY by the absolute
source path / line embedded in yosys auto-names must canonicalise to a
byte-identical result, so the provenance sha256 is reproducible.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import netlist_src_coord_canonicalize as canon  # noqa: E402

_A = (
    "module top(input a, output y);\n"
    "  wire $func$/home/runA/rtl/design.v:42$3 ;\n"
    "  \\mux$/abs/path/foo.v:118 .Y(y);\n"
    "  assign y = a;\n"
    "endmodule\n"
)
# Same logic, synthesised from a different absolute dir + different line numbers.
_B = (
    "module top(input a, output y);\n"
    "  wire $func$/tmp/other/run-7/design.v:99$3 ;\n"
    "  \\mux$/different/dir/foo.v:7 .Y(y);\n"
    "  assign y = a;\n"
    "endmodule\n"
)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def test_path_line_invariant():
    ca, cb = canon.canonicalize(_A), canon.canonicalize(_B)
    assert ca == cb, "netlists differing only by src path/line must canonicalise equal"
    assert _sha(ca) == _sha(cb)


def test_no_coordinate_survives():
    for src in (_A, _B):
        out = canon.canonicalize(src)
        assert not canon.has_coordinate(out), out


def test_coordinate_free_unchanged():
    clean = ("module m(input a, output y);\n"
             "  assign y = ~a;\n"
             "  wire _0_ ;\n"
             "endmodule\n")
    assert canon.canonicalize(clean) == clean


def test_idempotent():
    once = canon.canonicalize(_A)
    assert canon.canonicalize(once) == once


def test_distinct_basenames_preserved():
    out = canon.canonicalize("$func$/x/foo.v:1$  $func$/y/bar.v:2$")
    assert "foo.v" in out and "bar.v" in out
    assert not canon.has_coordinate(out)


def test_no_slash_coordinate_stripped():
    out = canon.canonicalize("$func$design.v:42$")
    assert out == "$func$design.v$"


def test_cli_in_place_and_check(tmp_path):
    f = tmp_path / "netlist.v"
    f.write_text(_A)
    # --check on a not-yet-canonical file exits 1
    assert canon.main([str(f), "--check"]) == 1
    # --in-place rewrites
    assert canon.main([str(f), "--in-place"]) == 0
    # now --check passes
    assert canon.main([str(f), "--check"]) == 0
    assert not canon.has_coordinate(f.read_text())


def test_cli_missing_file_rc2(tmp_path):
    assert canon.main([str(tmp_path / "nope.v")]) == 2
