"""#564 — four gates that scanned zero files and returned success.

All four printed the same line over a project path that does not exist:

    Files: 0  Errors: 0  Warnings: 0  Result: PASS      rc=0

They do not share an implementation — each has its own scanner and its own
`result.stats['files_scanned']` — but they share a verdict expression,
`return 0 if result.passed else 1`. `passed` is true because nothing
contradicted the rule, and rc 0 is what the P0 umbrella aggregates, so a path
with no RTL under it was certified as free of the defect each gate looks for.

They were surfaced by the honest-zero census added to
`gate_discloses_denominator_check` in v1.8.89, not by hand. That is the census
doing its job: the first three instances of this shape
(`interface_encoding_audit`, `fpga_qsf_lint`, `oe_pattern_check`) each cost a
separate manual probe.

MEASURED BEFORE LANDING, over the 107 tracked corpus rtl directories: all four
answer rc 0 on every one, and none reaches the zero-file path (`Files:` counts
run 1..2 and track the project). So the refusal cannot redden a real project —
the second half of the #492 bar — and the counts are real rather than constant.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]

GATES = (
    "bitwidth_consistency_check",
    "crc_residual_check",
    "device_response_no_br_check",
    "gap_reset_granularity_check",
)

#: Minimal but real RTL — enough that each gate's scanner finds a file to read.
RTL = """\
module top(input wire clk, input wire rst_n, output reg [7:0] q);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= 8'd0;
    else        q <= q + 8'd1;
  end
endmodule
"""


def _run(gate: str, project) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(_PROGRAMS / f"{gate}.py"), str(project)],
        capture_output=True, text=True)


@pytest.mark.parametrize("gate", GATES)
def test_absent_project_refuses(gate, tmp_path):
    proc = _run(gate, tmp_path / "no-such-project")
    assert proc.returncode == 2, (
        f"{gate} exited {proc.returncode} for a path that does not exist; "
        f"rc 0 is what the umbrella aggregates as a pass")
    assert "VACUOUS_PASS" in proc.stderr, proc.stderr


@pytest.mark.parametrize("gate", GATES)
def test_project_with_no_rtl_refuses(gate, tmp_path):
    """The directory exists and holds nothing scannable — same verdict.

    A gate that only guarded the missing-directory case would still certify an
    empty project.
    """
    (tmp_path / "rtl").mkdir(parents=True)
    proc = _run(gate, tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "0 files scanned" in proc.stderr, proc.stderr


@pytest.mark.parametrize("gate", GATES)
def test_a_project_with_rtl_still_passes(gate, tmp_path):
    """The accept case, per gate.

    Every change here makes a gate refuse more, so without this a program that
    refused everything would satisfy the two tests above.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(RTL, encoding="utf-8")
    proc = _run(gate, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VACUOUS_PASS" not in proc.stderr


@pytest.mark.parametrize("gate", GATES)
def test_the_file_count_is_measured_not_constant(gate, tmp_path):
    """`files_scanned` must track the input.

    A denominator that reports the same number regardless of what is there
    would satisfy the refusal test while disclosing nothing.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "a.v").write_text(RTL, encoding="utf-8")
    one = _run(gate, tmp_path)
    (rtl / "b.v").write_text(RTL.replace("top", "second"), encoding="utf-8")
    two = _run(gate, tmp_path)

    def count(proc):
        m = re.search(r"Files:\s*(\d+)", proc.stdout)
        assert m, f"{gate} does not state a file count: {proc.stdout!r}"
        return int(m.group(1))

    assert count(two) > count(one), (count(one), count(two))
