"""v0.3.27 — ORGANIC #533: rtl_hygiene_lint --fix structural compile-
neutrality safety net (verify-and-revert).

#530 fixed two SPECIFIC fixer bugs that broke a compiling design under the
ENFORCED --fix; this pins the STRUCTURAL net: a file that compiled before
--fix must still compile after, else ALL fixes are reverted with a named
WARN (fix-reverted-noncompiling). A pre-broken file keeps the old behavior
(fix attempted, never reverted).

The POSITIVE case injects a deliberately-breaking mock autofix (monkeypatch)
— the net must catch ANY future fixer bug, not just the #530 shapes.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

CLEAN_FIXABLE = """\
module pup(input wire clk, output wire q);
  reg st;
  always @(posedge clk) st <= ~st;
  assign q = st;
endmodule
"""

PRE_BROKEN = """\
module b(input wire clk, output reg q)
  always @(posedge clk q <= ~q;
endmodule
"""


def _run_fix(path, monkey=None):
    """Drive main() in-process so a monkeypatched autofix is visible."""
    argv = sys.argv
    sys.argv = ["rtl_hygiene_lint.py", "--fix", str(path)]
    try:
        return H.main()
    finally:
        sys.argv = argv


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_breaking_mock_autofix_is_reverted(tmp_path, monkeypatch, capsys):
    # POSITIVE (#533 acceptance): a future-bug-shaped autofix that corrupts
    # a compiling design → ALL changes reverted + named WARN.
    f = tmp_path / "ok.v"
    f.write_text(CLEAN_FIXABLE)

    def breaking_fix(p):
        p.write_text(p.read_text() + "\nthis is not verilog at all\n")
        return 1, ["st"]
    monkeypatch.setattr(H, "autofix_uninit_registered_output", breaking_fix)
    rc = _run_fix(f)
    assert rc == 0
    assert f.read_text() == CLEAN_FIXABLE          # fully reverted
    err = capsys.readouterr().err
    assert "fix-reverted-noncompiling" in err
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", str(f)],
                       capture_output=True)
    assert r.returncode == 0


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_normal_fix_still_applied(tmp_path, capsys):
    # NEGATIVE no-leak: a correct fix (still compiles) is NOT reverted.
    f = tmp_path / "ok.v"
    f.write_text(CLEAN_FIXABLE)
    rc = _run_fix(f)
    assert rc == 0
    body = f.read_text()
    assert "st = 0" in body                        # fix kept
    assert "fix-reverted-noncompiling" not in capsys.readouterr().err
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", str(f)],
                       capture_output=True)
    assert r.returncode == 0


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_prebroken_file_not_reverted(tmp_path, monkeypatch, capsys):
    # NEGATIVE no-leak: pre-fix non-compiling design → fix behavior
    # unchanged (attempted, never reverted — the fixer didn't break it).
    f = tmp_path / "broken.v"
    f.write_text(PRE_BROKEN)

    def touching_fix(p):
        p.write_text(p.read_text() + "\n// touched by fixer\n")
        return 1, ["q"]
    monkeypatch.setattr(H, "autofix_uninit_registered_output", touching_fix)
    rc = _run_fix(f)
    assert rc == 0
    assert "touched by fixer" in f.read_text()     # NOT reverted
    assert "fix-reverted-noncompiling" not in capsys.readouterr().err
