"""ORGANIC #728 — spec_example_smoke_tb.py: execute the prompt's own golden rows.

The gate extracts the prompt's worked-example input->output rows, auto-generates
a directed smoke TB, runs it with iverilog, and BLOCKs on a real mismatch. It is
blind (prompt-only) and scorer-independent, and — per §4.05 — only ever BLOCKs on
a REAL extracted-example mismatch (never false-blocks when there is no golden
example to run, or when iverilog is unavailable).

Cases:
  (a) the 驗收 always-0 RTL FAILs (rc != 0);
  (b) a correct add2 passes (rc == 0);
  (c) §4.05: a prompt with NO example rows -> exit 0 (not-applicable), no block;
  (d) iverilog-absent -> graceful exit 0 (not-applicable).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "spec_example_smoke_tb.py"

_PROMPT = ("Module add2. Example: a=3,b=4 -> sum=7. "
           "Inputs a[7:0],b[7:0]; output sum[8:0].\n")
_RTL_WRONG = ("module add2(input [7:0] a,b, output [8:0] sum); "
              "assign sum=8'd0; endmodule\n")
_RTL_OK = ("module add2(input [7:0] a,b, output [8:0] sum); "
           "assign sum=a+b; endmodule\n")

_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


def _write(tmp_path, prompt, rtl):
    p = tmp_path / "s.txt"
    r = tmp_path / "s.sv"
    p.write_text(prompt)
    r.write_text(rtl)
    return p, r


def _run(prompt_path, rtl_path, top="add2", env=None):
    return subprocess.run(
        [sys.executable, str(_PROG), "--prompt", str(prompt_path),
         "--rtl", str(rtl_path), "--top", top],
        capture_output=True, text=True, env=env)


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_a_acceptance_always_zero_rtl_blocks(tmp_path):
    """驗收 (verbatim END-STATE): the always-0 RTL FAILs the a=3,b=4->sum=7
    golden row -> rc != 0 (BLOCK)."""
    p, r = _write(tmp_path, _PROMPT, _RTL_WRONG)
    cp = _run(p, r)
    assert cp.returncode != 0, cp.stdout + cp.stderr
    assert "BLOCK" in cp.stdout
    assert "SPEC_EXAMPLE_FAIL" in cp.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_b_correct_adder_passes(tmp_path):
    """END-STATE: a CORRECT adder satisfies the golden row -> rc == 0 (PASS)."""
    p, r = _write(tmp_path, _PROMPT, _RTL_OK)
    cp = _run(p, r)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "PASS" in cp.stdout


def test_c_no_example_rows_not_applicable(tmp_path):
    """§4.05: a prompt with NO golden example rows -> exit 0 (not-applicable),
    NEVER blocks — even against the always-0 RTL."""
    no_example = ("Module add2. Inputs a[7:0],b[7:0]; output sum[8:0]. "
                  "No worked example is stated here.\n")
    p, r = _write(tmp_path, no_example, _RTL_WRONG)
    cp = _run(p, r)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "NOT-APPLICABLE" in cp.stdout


def test_c2_unresolvable_names_not_applicable(tmp_path):
    """§4.05: an example whose names don't resolve to RTL ports is DROPPED
    (conservative) -> not-applicable, never a false block."""
    foreign = ("Module add2. Example: x=3,y=4 -> z=7. "
               "Inputs a[7:0],b[7:0]; output sum[8:0].\n")
    p, r = _write(tmp_path, foreign, _RTL_WRONG)
    cp = _run(p, r)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "NOT-APPLICABLE" in cp.stdout


def test_d_iverilog_absent_graceful(tmp_path):
    """§4.05: iverilog absent -> exit 0 (not-applicable). Simulated by a PATH
    that contains python but no iverilog/vvp; the program is invoked by its
    absolute interpreter so only the child's tool lookup is affected."""
    p, r = _write(tmp_path, _PROMPT, _RTL_WRONG)
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    # provide python3 on the sabotaged PATH (some shells need it) but NOT iverilog
    real_py = shutil.which("python3") or sys.executable
    try:
        os.symlink(real_py, fakebin / "python3")
    except OSError:
        pass
    env = dict(os.environ)
    env["PATH"] = str(fakebin)
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--prompt", str(p), "--rtl", str(r),
         "--top", "add2"],
        capture_output=True, text=True, env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "NOT-APPLICABLE" in cp.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_e_markdown_table_rows(tmp_path):
    """A markdown example table whose header cells name RTL ports is extracted
    and executed: wrong RTL BLOCKs, correct RTL passes."""
    tbl = ("Module add2. Inputs a[7:0],b[7:0]; output sum[8:0].\n\n"
           "| a | b | sum |\n|---|---|-----|\n| 3 | 4 | 7 |\n| 10 | 5 | 15 |\n")
    p_wrong, r_wrong = _write(tmp_path, tbl, _RTL_WRONG)
    cp = _run(p_wrong, r_wrong)
    assert cp.returncode != 0, cp.stdout + cp.stderr
    assert "extracted 2" in cp.stdout

    ok = tmp_path / "ok.sv"
    ok.write_text(_RTL_OK)
    cp2 = _run(p_wrong, ok)
    assert cp2.returncode == 0, cp2.stdout + cp2.stderr


def test_f_missing_files_argerror(tmp_path):
    """Bad input paths -> rc 2 (arg/IO error), not a false BLOCK."""
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--prompt", str(tmp_path / "nope.txt"),
         "--rtl", str(tmp_path / "nope.sv"), "--top", "add2"],
        capture_output=True, text=True)
    assert cp.returncode == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
