"""v1.3.43 candidate #5 — Category-D (tool-substitution gap) is FORK-FIXABLE,
NOT a terminal FLOOR (doctrine tightening).

Because we FORK the EDA tools (vibeic-eda), a "our OSS tool can't do X" fail is an
ENGINEERING BACKLOG item against the fork (FIX_STATUS.md), gated by the § 4.1
floor-proof (run the golden under a tool that DOES support the feature; if it
ALSO fails, re-triage as dataset/RTL). This pins:
  (a) tb_vcs_only_construct_detect.py now labels its FAIL disposition
      FORK-FIXABLE (+ fork_route + floor_proof_required), not a terminal floor;
  (b) the open-benchmark-methodology SKILL.md § 4 Category-D / § 9 T5 carry the
      FORK-FIXABLE + § 4.1-floor-proof doctrine tokens.
This is a TIGHTENING (removes the "tool limit" terminal excuse), so the detector
still FAILs on a real VCS-only construct (no leak).
"""
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_DETECT = _PROGRAMS / "tb_vcs_only_construct_detect.py"
_SKILL = (_PROGRAMS.parent / "skills" / "open-benchmark-methodology" / "SKILL.md")


def _run(tb_path: Path, json_out: Path):
    return subprocess.run(
        [sys.executable, str(_DETECT), str(tb_path), "--json", str(json_out)],
        capture_output=True, text=True)


def test_detector_marks_fork_fixable_not_terminal_floor(tmp_path):
    """A TB with a `break;` (iverilog-12 gap) still FAILs (detector fires) but is
    now dispositioned FORK-FIXABLE with a route to FIX_STATUS + a floor-proof
    requirement — NOT a permanent floor."""
    tb = tmp_path / "tb.sv"
    tb.write_text(
        "module tb;\n initial begin\n  for (int i=0;i<8;i++) begin\n"
        "   if (i==4) break;\n  end\n end\nendmodule\n")
    out = tmp_path / "r.json"
    cp = _run(tb, out)
    assert cp.returncode == 1, cp.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["category"] == "D"
    assert rep["disposition"] == "FORK-FIXABLE"
    assert "FIX_STATUS" in rep["fork_route"]
    assert "floor_proof_required" in rep
    # stderr no longer implies a terminal FLOOR-D verdict
    assert "FORK-FIXABLE" in cp.stderr
    assert "route to FIX_STATUS" in cp.stderr


def test_detector_no_leak_clean_tb_still_passes(tmp_path):
    """A plain Verilog TB with no VCS-only construct is NOT a Category-D gap
    (rc 0) — the tightening did not make the detector over-fire."""
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb;\n reg clk;\n initial begin clk=0; #10 $finish; end\n"
        " always #5 clk=~clk;\nendmodule\n")
    out = tmp_path / "r.json"
    cp = _run(tb, out)
    assert cp.returncode == 0, cp.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert "disposition" not in rep  # only a FAIL carries the fork disposition


def test_skill_category_d_and_t5_doctrine_tokens_present():
    txt = _SKILL.read_text()
    # § 4 Category-D reworded to FORK-FIXABLE
    assert "FORK-FIXABLE" in txt
    assert "tools/vibeic-eda/FIX_STATUS.md" in txt
    # the asyn_fifo worked example is grounded CORRECTLY (golden PASSES)
    assert "asyn_fifo" in txt
    # § 9 T5 tightened: a plain tool-gap is no longer T5 by default
    assert "no longer T5 by default" in txt.lower() or \
           "NO LONGER T5" in txt
    # the § 4.1 floor-proof gate for a Category-D reclassification
    assert "floor-proof" in txt.lower()
    # the over-fit prohibition is preserved (never patch a tool to pass a bench)
    assert 'pass benchmark X' in txt or "over-fit" in txt.lower()
