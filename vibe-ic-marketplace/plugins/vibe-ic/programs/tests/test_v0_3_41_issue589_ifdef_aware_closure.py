"""ORGANIC #589 — sv_package_closure_check scanned `include / pkg::
references textually with no conditional-compilation awareness: the
canonical assertion-macro header (`ifdef VERILATOR / `elsif SYNTHESIS /
`else → include a sim-only macros file, plus an `ifdef UVM arm importing
a UVM package) produced 5 missing-definition FAILs on a fully-consistent
closure — every flagged target lives in a branch the synthesis
define-set never takes.

Fix: _annotate_conditionals() walks `ifdef/`ifndef/`elsif/`else/`endif;
with --define NAME (repeatable) unreachable branches are excluded
entirely; without --define, findings inside ANY conditional branch
downgrade to WARN with the guarding condition named. Unconditional
missing references still FAIL (negative no-leak).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sv_package_closure_check as C  # noqa: E402

# The canonical assertion-macro header shape from the issue.
_ASSERT_HEADER = """\
`ifndef PRIM_ASSERT_SV
`define PRIM_ASSERT_SV

`ifdef VERILATOR
  `include "prim_assert_dummy_macros.svh"
`elsif SYNTHESIS
  `include "prim_assert_dummy_macros.svh"
`elsif YOSYS
  `include "prim_assert_yosys_macros.svh"
`else
  `include "prim_assert_standard_macros.svh"
`endif

`ifdef UVM
  import uvm_pkg::*;
`endif

`endif
"""


def _files(**kw):
    return dict(kw)


def test_synthesis_define_takes_elsif_branch():
    """驗收正向: zero FAIL under --define SYNTHESIS — only the taken
    branch's include is required."""
    report = C.audit(_files(
        **{"prim_assert.svh": _ASSERT_HEADER,
           "prim_assert_dummy_macros.svh": "// dummy macros\n"}),
        defines={"SYNTHESIS"})
    assert report["verdict"] == "PASS", report["findings"]
    assert report["missing_includes"] == []
    assert "uvm_pkg" not in report["missing_packages"]


def test_no_define_set_downgrades_conditional_to_warn():
    """Without --define every conditional-branch finding is WARN with
    the guard named — verdict PASS (advisory), not 5 hard FAILs."""
    report = C.audit(_files(
        **{"prim_assert.svh": _ASSERT_HEADER}), defines=None)
    assert report["verdict"] == "PASS", report["findings"]
    warns = [f for f in report["findings"] if f["severity"] == "WARN"]
    assert warns, "conditional-branch findings must surface as WARN"
    assert any("inside conditional branch" in f["message"] for f in warns)
    assert any("`elsif" in f["message"] or "`ifdef" in f["message"]
               or "`else" in f["message"] for f in warns)


def test_unconditional_missing_include_still_fails():
    """NEGATIVE no-leak: a genuinely-missing unconditional include FAILs
    under any define-set."""
    src = '`include "missing_header.svh"\nmodule m; endmodule\n'
    for defines in (None, {"SYNTHESIS"}):
        report = C.audit(_files(**{"m.sv": src}), defines=defines)
        assert report["verdict"] == "FAIL", (defines, report)
        assert "missing_header.svh" in report["missing_includes"]


def test_taken_branch_missing_include_fails_with_defines():
    """With --define SYNTHESIS the SYNTHESIS branch is REAL build input:
    its missing include is a hard FAIL."""
    report = C.audit(_files(
        **{"prim_assert.svh": _ASSERT_HEADER}), defines={"SYNTHESIS"})
    assert report["verdict"] == "FAIL"
    assert "prim_assert_dummy_macros.svh" in report["missing_includes"]


def test_untaken_uvm_import_excluded_with_defines():
    report = C.audit(_files(
        **{"prim_assert.svh": _ASSERT_HEADER,
           "prim_assert_dummy_macros.svh": "// ok\n"}),
        defines={"SYNTHESIS"})
    assert "uvm_pkg" not in report["imported_packages"]


def test_ifndef_include_guard_does_not_hide_content():
    """The standard `ifndef X / `define X include-guard wraps the WHOLE
    file — its content must stay visible under an empty define-set."""
    report = C.audit(_files(
        **{"pkg.sv": "`ifndef PKG_SV\n`define PKG_SV\n"
                     "package my_pkg; endpackage\n`endif\n",
           "use.sv": "import my_pkg::*;\nmodule m; endmodule\n"}),
        defines=set())
    assert report["verdict"] == "PASS", report["findings"]


def test_cli_define_flag_end_state(tmp_path):
    """End-state via the real CLI: --define SYNTHESIS on the issue's
    header shape exits 0 (pre-fix: rc=1 with 5 FAILs)."""
    import subprocess
    (tmp_path / "prim_assert.svh").write_text(_ASSERT_HEADER)
    (tmp_path / "prim_assert_dummy_macros.svh").write_text("// macros\n")
    r = subprocess.run(
        [sys.executable, str(PROG / "sv_package_closure_check.py"),
         str(tmp_path), "--define", "SYNTHESIS"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout
    assert "verdict: PASS" in r.stdout
