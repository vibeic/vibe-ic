"""ORGANIC #709 — the #679 RUNTIME golden-fails-own-TB audit
(`_golden_ref_fails_own_tb_runtime`) compiled the golden VERBATIM, with NO
module-name canonicalization — unlike its #690 COMPILE-level sibling
(`_golden_ref_compiles_with_tb_shape_b`) which aliases the golden module name to
the canonical DUT name the TB instantiates.

For the standard Shape-B `verified_*.v` convention the golden module is named
`verified_<X>` while the TB instantiates `<X>` (the spec `Module name:`), so the
verbatim compile ALWAYS fails elaboration (`Unknown module type: <X>`), the
helper hits its `returncode!=0` branch and returns None — NO dataset-defect flag
is set, and a genuine golden-fails-own-TB dataset defect is silently CHARGED TO
THE MODEL as no_pass_marker. (The original #679 test masked this because its
fixture named the golden module `dut` == the canonical DUT name, so no alias was
needed.)

FIX: a shared `_aliased_golden_srcs` helper aliases the golden's top-module name
to the canonical DUT name, used by BOTH the #690 compile audit and the #679
runtime audit so they can never drift again.

§4.05 NO-LEAK: only flag when the golden ACTUALLY runtime-fails its own TB; a
satisfiable golden (passes its own TB) + a wrong model sample must stay a model
FAIL. Aliasing changes only the module NAME, never the golden's behaviour.

chip-AGNOSTIC: registry layout.ref_glob/tb_filename + the spec's Module-name
line; every fixture synthetic, no design/vendor literal.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_iverilog_tb_709", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _need_tools():
    if not (shutil.which("iverilog") and shutil.which("vvp")):
        pytest.skip("iverilog/vvp not installed")


LAYOUT = {
    "prompt_filename": "design_description.txt",
    "tb_filename": "testbench.v",
    "ref_glob": "verified_*.v",
}
ARGS = {
    "pass_regex": r"Your Design Passed",
    "fail_regex": r"Test failed|Your Design Failed",
    "cwd_design_dir": True,
}

# The real Shape-B convention: spec Module-name = `myalu`; golden file is
# `verified_myalu.v` declaring `module verified_myalu`; the TB instantiates the
# CANONICAL `myalu`. (Positional bind: out = a + b.)
_SPEC = "Module name:\n  myalu\n"
_TB = (
    "module testbench;\n"
    "  reg [3:0] a=4'd2, b=4'd3; wire [4:0] s;\n"
    "  myalu uut(a, b, s);\n"
    "  initial begin #1;\n"
    "    if (s===5'd5) $display(\"=========== Your Design Passed ===========\");\n"
    "    else $display(\"Your Design Failed: got %0d\", s);\n"
    "    $finish; end\n"
    "endmodule\n")
# golden that COMPILES but FAILs its own TB at runtime (outputs a-b, not a+b):
_GOLDEN_BAD = (
    "module verified_myalu(input [3:0] a, input [3:0] b, output [4:0] s);\n"
    "  assign s = a - b;\n"  # wrong (a-b not a+b) → TB prints no pass marker
    "endmodule\n")
# golden that PASSes its own TB (correct a+b):
_GOLDEN_GOOD = (
    "module verified_myalu(input [3:0] a, input [3:0] b, output [4:0] s);\n"
    "  assign s = a + b;\n"
    "endmodule\n")


def _mk(tmp_path, golden_text, spec=_SPEC, tb=_TB, ref_name="verified_myalu.v"):
    dataset = tmp_path / "ds"
    ddir = dataset / "Arithmetic" / "myalu"
    ddir.mkdir(parents=True)
    (ddir / "design_description.txt").write_text(spec)
    (ddir / "testbench.v").write_text(tb)
    (ddir / ref_name).write_text(golden_text)
    return dataset, "Arithmetic/myalu"


# ── the #709 fix: the verified_<X> mismatch path is now resolved ─────────────
def test_aliased_golden_srcs_renames_to_canonical(tmp_path):
    """The shared helper renames `verified_myalu` -> `myalu` (the TB's name)."""
    m = _load()
    dataset, design = _mk(tmp_path, _GOLDEN_BAD)
    refs = sorted((dataset / design).glob("verified_*.v"))
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        srcs, ports = m._aliased_golden_srcs(design, dataset, LAYOUT, refs, td)
        assert srcs is not None
        aliased_text = Path(srcs[0]).read_text()
        assert "module myalu" in aliased_text
        assert "verified_myalu" not in aliased_text
        assert ports == {"a", "b", "s"}


def test_runtime_audit_flags_defect_on_verified_convention(tmp_path):
    """THE #709 REPRO: a golden named verified_<X> that COMPILES but FAILs its
    own TB at runtime is now correctly flagged (was None before the fix because
    the verbatim compile failed `Unknown module type: myalu`)."""
    _need_tools()
    m = _load()
    dataset, design = _mk(tmp_path, _GOLDEN_BAD)
    res = m._golden_ref_fails_own_tb_runtime(design, dataset, LAYOUT, ARGS)
    assert res is True, res  # golden runtime-fails its own TB -> dataset defect


# ── §4.05 NO-LEAK ────────────────────────────────────────────────────────────
def test_noleak_satisfiable_golden_passes_stays_model_fail(tmp_path):
    """A golden (verified_<X>) that PASSes its own TB at runtime must NOT be
    flagged — the design is satisfiable, so a wrong model sample stays a model
    FAIL (helper returns False)."""
    _need_tools()
    m = _load()
    dataset, design = _mk(tmp_path, _GOLDEN_GOOD)
    res = m._golden_ref_fails_own_tb_runtime(design, dataset, LAYOUT, ARGS)
    assert res is False, res


def test_noleak_unresolvable_golden_module_returns_none(tmp_path):
    """A golden ref carrying no `module` declaration at all -> None (no
    determination, no flag): the audit never fabricates a defect it cannot
    substantiate."""
    m = _load()
    dataset, design = _mk(tmp_path, "wire dangling;\nassign dangling = 1'b0;\n")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        refs = sorted((dataset / design).glob("verified_*.v"))
        srcs, _ = m._aliased_golden_srcs(design, dataset, LAYOUT, refs, td)
        assert srcs is None  # golden has no module decl -> unresolvable


def test_both_audits_share_the_alias_helper(tmp_path):
    """#709 anti-drift: the #690 compile audit and #679 runtime audit both go
    through `_aliased_golden_srcs` — the compile audit now ALSO elaborates the
    verified_<X> golden (was the only one that canonicalized; now they share)."""
    _need_tools()
    m = _load()
    dataset, design = _mk(tmp_path, _GOLDEN_GOOD)
    compiles, ports = m._golden_ref_compiles_with_tb_shape_b(
        design, dataset, LAYOUT)
    assert compiles is True  # verified_myalu(aliased)+TB elaborates
    assert ports == {"a", "b", "s"}


def test_chip_agnostic_guard():
    import sys
    prog = (Path(__file__).resolve().parents[1] / "source_chip_agnostic_check.py")
    r = _pr.run([sys.executable, str(prog),
                        str(Path(__file__).resolve().parents[1].parent)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-400:]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
