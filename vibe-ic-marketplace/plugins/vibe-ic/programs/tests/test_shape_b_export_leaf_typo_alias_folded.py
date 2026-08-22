"""v1.1.34 clean-room (RTLLM fixed_point_substractor) — the Shape-B sample
export must FOLD IN a runner-emitted leaf-typo alias wrapper that lives in a
SEPARATE rtl-dir file, so the single-file benchmark sample carries BOTH spellings
the hidden TB might bind.

The runner's step_leaf_typo_aliases emits `fixed_point_subtractor.v` (a thin
canonical-spelling wrapper instantiating the leaf `fixed_point_substractor`) as a
SEPARATE file. resolve_tb_facing_file picks ONE file (the leaf's), so the alias
module was DROPPED from the exported sample → a TB instantiating the canonical
spelling hit `Unknown module type`. The export now folds the separate alias file
in (mirrors the #518 rcvar same-file completeness for the #517 separate-file case).

§4.05 no-leak: the fold fires ONLY for a genuine single-edit typo leaf
(detect_leaf_typo != None); a correctly-spelled leaf is a no-op.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import shape_b_sample_export as EX  # noqa: E402


def _module_names(txt):
    return set(EX._module_names(txt))


def _write(d: Path, name: str, body: str) -> Path:
    p = d / name
    p.write_text(body)
    return p


def test_separate_file_leaf_typo_alias_is_folded(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    # leaf (typo spelling) in one file
    _write(rtl, "fixed_point_substractor.v",
           "module fixed_point_substractor #(parameter Q=8, parameter N=16)\n"
           " (input [N-1:0] a, input [N-1:0] b, output [N-1:0] c);\n"
           "  assign c = a - b;\nendmodule\n")
    # canonical-spelling alias wrapper in a SEPARATE file (as the runner emits)
    _write(rtl, "fixed_point_subtractor.v",
           "module fixed_point_subtractor #(parameter Q=8, parameter N=16)\n"
           " (input [N-1:0] a, input [N-1:0] b, output [N-1:0] c);\n"
           "  fixed_point_substractor #(.Q(Q),.N(N)) u (.a(a),.b(b),.c(c));\n"
           "endmodule\n")
    samples = tmp_path / "samples"
    res = EX.export(rtl, "fixed_point_substractor", samples)
    assert res.get("verdict") == "PASS", res
    out = (samples / "fixed_point_substractor.v").read_text()
    mods = _module_names(out)
    assert "fixed_point_substractor" in mods
    assert "fixed_point_subtractor" in mods, \
        "the separate-file canonical-spelling alias must be folded into the sample"


def test_no_typo_leaf_is_a_noop(tmp_path):
    """§4.05 no-leak: a correctly-spelled leaf with an unrelated sibling file is
    NOT altered — the fold fires only for a genuine typo."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _write(rtl, "subtractor.v",
           "module subtractor (input [7:0] a, input [7:0] b, output [7:0] c);\n"
           "  assign c = a - b;\nendmodule\n")
    samples = tmp_path / "samples"
    res = EX.export(rtl, "subtractor", samples)
    assert res.get("verdict") == "PASS", res
    mods = _module_names((samples / "subtractor.v").read_text())
    assert mods == {"subtractor"}, "non-typo leaf must not pull in extra modules"


def test_unrelated_canonical_module_not_folded(tmp_path):
    """Step-2.7 (MED): detect_leaf_typo over-fires on some legitimate spellings,
    so the rtl_dir may hold a REAL unrelated module sharing the canonical name.
    It must NOT be folded — the genuine runner wrapper INSTANTIATES the leaf; a
    coincidental sibling does not. Injecting it would break the sample."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _write(rtl, "substractor.v",
           "module substractor (input [7:0] a, input [7:0] b, output [7:0] c);\n"
           "  assign c = a - b;\nendmodule\n")
    # a REAL, unrelated, self-contained module that happens to be named the
    # canonical spelling but does NOT instantiate the `substractor` leaf
    _write(rtl, "subtractor.v",
           "module subtractor (input [7:0] x, output [7:0] y);\n"
           "  assign y = ~x;\nendmodule\n")
    samples = tmp_path / "samples"
    res = EX.export(rtl, "substractor", samples)
    assert res.get("verdict") == "PASS", res
    mods = _module_names((samples / "substractor.v").read_text())
    assert "subtractor" not in mods, \
        "an unrelated module that does NOT instantiate the leaf must not be folded"
    assert mods == {"substractor"}


def test_multi_module_alias_file_no_duplicate(tmp_path):
    """Step-2.7 (LOW): the alias FILE may carry more than the wrapper. Folding it
    whole could re-declare a sub-module already in the sample → duplicate-module
    compile_error (iverilog-independent). The no-dup guard makes it a fail-safe
    no-op rather than shipping a duplicate."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _write(rtl, "substractor.v",
           "module substractor (input [7:0] a, input [7:0] b, output [7:0] c);\n"
           "  shared_helper h ();\nendmodule\n"
           "module shared_helper; endmodule\n")
    # wrapper + a shared_helper that ALSO exists in the leaf file
    _write(rtl, "subtractor.v",
           "module subtractor (input [7:0] a, input [7:0] b, output [7:0] c);\n"
           "  substractor u (.a(a), .b(b), .c(c));\nendmodule\n"
           "module shared_helper; endmodule\n")
    samples = tmp_path / "samples"
    res = EX.export(rtl, "substractor", samples)
    assert res.get("verdict") == "PASS", res
    out = (samples / "substractor.v").read_text()
    import re as _re
    decls = _re.findall(r"\bmodule\s+(\w+)", out)
    dups = [m for m in set(decls) if decls.count(m) > 1]
    assert not dups, f"fold must never create a duplicate module decl: {dups}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
