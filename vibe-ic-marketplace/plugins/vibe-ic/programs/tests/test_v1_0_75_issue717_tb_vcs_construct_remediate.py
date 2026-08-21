"""ORGANIC #717 — semantics-preserving VCS-only-TB-construct REMEDIATOR.

`tb_vcs_only_construct_detect` only DETECTS+FLOORS break;/continue; (FLOOR-D);
there was no remediation, so a TB iverilog rejects ONLY for a mechanically-
remediable VCS-ism was abandoned even when a remediated TB would let a correct
design PASS. This adds `tb_vcs_only_construct_remediate`: a deterministic,
semantics-preserving rewrite of the CLOSED safe subset (break;→labelled-block
disable, continue;→inner-block disable, drop unique/priority), to a `*_iv.v`
SIDECAR (original untouched), refusing the no-deterministic-equivalent set.

§4.05 NEGATIVE NO-LEAK (load-bearing — the remediator RELAXES a FLOOR to a
runnable TB): the rewritten TB retains FULL discriminating power — a WRONG
design STILL FAILs it (proven below with iverilog), and the golden_still_passes
guard REJECTS any TB-weakening rewrite. The refuse-class constructs
(std::randomize / $urandom_range / join_none / queue ops) stay FLOOR-D, and a
residual `'{…}` (not in the safe subset) is refused.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import tb_vcs_only_construct_remediate as R  # noqa: E402

_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None

# A break;-using scoring TB whose discrimination depends on the loop stopping
# at the right iteration — exactly the asyn_fifo-class shape from the issue.
_TB_BREAK = """\
module testbench;
  integer i; reg [31:0] cnt;
  dut u (.n(cnt));
  initial begin
    cnt = 0;
    for (i = 0; i < 100; i = i + 1) begin
      cnt = cnt + 1;
      if (i == 15) break;
    end
    #1;
    if (u.ok) $display("===========Your Design Passed===========");
    else $display("===========Error===========");
    $finish;
  end
endmodule
"""
# golden: ok iff exactly 16 counts arrived (correct break semantics)
_GOLDEN = "module dut(input [31:0] n); wire ok = (n == 16); endmodule\n"
# wrong design: ok iff n==100 (would only pass if break were DROPPED)
_WRONG = "module dut(input [31:0] n); wire ok = (n == 100); endmodule\n"


def _compile_run(tb: Path, rtl: Path, tmp: Path):
    vvp = tmp / "a.vvp"
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(tb),
                         str(rtl)], capture_output=True, text=True)
    if cp.returncode != 0:
        return cp.returncode, cp.stderr
    cp = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


def test_original_break_tb_rejected_by_iverilog(tmp_path):
    """The original VCS TB genuinely fails iverilog (FLOOR-D precondition)."""
    if not _HAVE_IV:
        pytest.skip("iverilog not available")
    tb = tmp_path / "testbench.v"
    tb.write_text(_TB_BREAK)
    g = tmp_path / "dut.v"
    g.write_text(_GOLDEN)
    rc, out = _compile_run(tb, g, tmp_path)
    if rc == 0:
        # Precondition probe, not assumption: newer iverilog builds accept
        # procedural `break;` in a plain `for`, so the VCS-only-construct REJECT
        # floor this reproduces does not exist on this toolchain. Skip the
        # reproduce (nothing to remediate here) — the remediator's real value is
        # still gated by test_break_remediation_compiles_and_golden_passes.
        pytest.skip("this iverilog build accepts procedural `break;` — the "
                    "VCS-reject floor this reproduces is not present here")
    assert rc != 0 and "break" in out.lower()


def test_break_remediation_compiles_and_golden_passes(tmp_path):
    """END-STATE: after remediation the GOLDEN compiles rc=0 + PASSES (break
    semantics preserved — exactly 16 counts)."""
    if not _HAVE_IV:
        pytest.skip("iverilog not available")
    tb = tmp_path / "testbench.v"
    tb.write_text(_TB_BREAK)
    rc = R.main([str(tb), "--out", str(tmp_path / "tb_iv.v")])
    assert rc == 0
    iv = tmp_path / "tb_iv.v"
    assert iv.is_file()
    rc, out = _compile_run(iv, _write(tmp_path, "g.v", _GOLDEN), tmp_path)
    assert rc == 0 and "passed" in out.lower()
    # ORIGINAL is untouched
    assert tb.read_text() == _TB_BREAK


def test_noleak_wrong_design_still_fails_remediated_tb(tmp_path):
    """§4.05 LOAD-BEARING: a WRONG design (only passes if break were dropped)
    STILL FAILs the remediated TB — the rewrite did not weaken discrimination."""
    if not _HAVE_IV:
        pytest.skip("iverilog not available")
    tb = tmp_path / "testbench.v"
    tb.write_text(_TB_BREAK)
    R.main([str(tb), "--out", str(tmp_path / "tb_iv.v")])
    rc, out = _compile_run(tmp_path / "tb_iv.v",
                           _write(tmp_path, "wrong.v", _WRONG), tmp_path)
    assert rc == 0
    assert "error" in out.lower() and "passed" not in out.lower()


def test_golden_guard_rejects_when_golden_fails(tmp_path):
    """golden_still_passes returns False for a design that fails the remediated
    TB (the guard that rejects a TB-weakening rewrite)."""
    if not _HAVE_IV:
        pytest.skip("iverilog not available")
    tb = tmp_path / "testbench.v"
    tb.write_text(_TB_BREAK)
    R.main([str(tb), "--out", str(tmp_path / "tb_iv.v")])
    iv = tmp_path / "tb_iv.v"
    assert R.golden_still_passes(_write(tmp_path, "g.v", _GOLDEN), iv) is True
    assert R.golden_still_passes(_write(tmp_path, "w.v", _WRONG), iv) is False


def test_continue_remediation_semantics(tmp_path):
    """continue;→inner-block disable preserves continue semantics."""
    if not _HAVE_IV:
        pytest.skip("iverilog not available")
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; integer i; reg [31:0] s;\n"
        "initial begin s=0;\n"
        "  for (i=0;i<10;i=i+1) begin\n"
        "    if (i % 2 == 0) continue;\n"
        "    s = s + i;\n"
        "  end\n"
        "  if (s==25) $display(\"PASS\"); else $display(\"ERROR\");\n"
        "  $finish; end\nendmodule\n")
    rc = R.main([str(tb), "--out", str(tmp_path / "tb_iv.v")])
    assert rc == 0
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "c.vvp"),
                         str(tmp_path / "tb_iv.v")], capture_output=True,
                        text=True)
    assert cp.returncode == 0, cp.stderr
    out = subprocess.run(["vvp", str(tmp_path / "c.vvp")],
                         capture_output=True, text=True).stdout
    assert "PASS" in out


@pytest.mark.parametrize("snippet", [
    "std::randomize(x);",
    "x = $urandom_range(0, 7);",
    "fork foo(); join_none",
    "q.push_back(3);",
])
def test_refuse_no_deterministic_equivalent(tmp_path, snippet):
    """§4.05: refuse-class constructs have NO deterministic equivalent → REFUSE,
    no sidecar (stays FLOOR-D)."""
    tb = tmp_path / "tb.v"
    tb.write_text(f"module tb; initial begin {snippet} end endmodule\n")
    out, report = R.remediate_text(tb.read_text())
    assert out is None and report["refused"] is True


def test_refuse_residual_assignment_pattern(tmp_path):
    """A `'{…}` assignment-pattern is NOT in the safe subset; if present the
    remediation is refused rather than shipping a partially-fixed TB."""
    src = ("module tb; int a[2]; integer i;\n"
           "initial begin a = '{1, 2};\n"
           "  for (i=0;i<2;i=i+1) begin if (i==1) break; end\nend endmodule\n")
    out, report = R.remediate_text(src)
    assert out is None
    assert "assignment_pattern" in report["residual"]


def test_unique_priority_qualifier_dropped():
    """unique/priority case → plain case (qualifier dropped, branch unchanged)."""
    src = ("module tb; reg [1:0] s; integer i;\n"
           "initial begin unique case (s) 0: i=0; default: i=9; endcase end\n"
           "endmodule\n")
    out, report = R.remediate_text(src)
    assert out is not None
    assert "unique case" not in out and "case (s)" in out
    assert report["rewrites"]["unique_priority"] == 1


def test_clean_tb_passes_through_unchanged():
    """A TB with none of the handled constructs is returned unchanged."""
    src = "module tb; initial begin $display(\"hi\"); $finish; end endmodule\n"
    out, report = R.remediate_text(src)
    assert out == src and report["refused"] is False


def _write(d: Path, name: str, content: str) -> Path:
    p = d / name
    p.write_text(content)
    return p


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
