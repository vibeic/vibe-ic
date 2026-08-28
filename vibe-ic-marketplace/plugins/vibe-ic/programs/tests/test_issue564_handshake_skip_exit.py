"""#564 — the JSON said SKIP and the exit code said success.

`handshake_livelock_result_stability_check` computes a `status` and publishes it:

    {"status": "SKIP-no-handshake", "n_findings": 0, "n_error": 0, ...}
    rc=0

`n_error` is 0 because nothing was examined, not because a handshake was checked
and found stable. rc 0 is what the P0 umbrella aggregates, so the SKIP in the
JSON never reached the verdict.

This one is different from the other #564 promotions in a way worth keeping: the
gate ALREADY distinguished. Measured over 60 corpus projects before the change —

    CHECKED             4    real work
    SKIP-no-handshake  31    examined nothing, exited 0   <- the defect
    (no targets)       25    already exited 2

— so the machinery to say "could not check" existed and one branch did not use
it. That is why this was safe to promote: the 4 CHECKED projects are the
evidence that rc 0 still means something after the change.

After: CHECKED -> 0 (4), SKIP-no-handshake -> 2 (31), no targets -> 2 (25).
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "handshake_livelock_result_stability_check.py"

#: A valid/ready handshake, so `check_paths` reports CHECKED rather than SKIP.
HANDSHAKE_RTL = """\
module h(input wire clk, input wire rst_n,
         input wire in_valid, output reg in_ready,
         output reg out_valid, input wire out_ready,
         output reg [7:0] result);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      in_ready  <= 1'b1;
      out_valid <= 1'b0;
      result    <= 8'd0;
    end else begin
      if (in_valid && in_ready) begin
        result    <= result + 8'd1;
        out_valid <= 1'b1;
        in_ready  <= 1'b0;
      end
      if (out_valid && out_ready) begin
        out_valid <= 1'b0;
        in_ready  <= 1'b1;
      end
    end
  end
endmodule
"""

PLAIN_RTL = "module p(input wire clk, output reg q);\nendmodule\n"


def _run(target):
    return _pr.run(
        [sys.executable, str(PROG), str(target)],
        capture_output=True, text=True)


def _status(proc):
    return json.loads(proc.stdout)["status"]


def test_skip_no_handshake_does_not_exit_zero(tmp_path):
    (tmp_path / "p.v").write_text(PLAIN_RTL, encoding="utf-8")
    proc = _run(tmp_path)
    assert _status(proc) == "SKIP-no-handshake", proc.stdout
    assert proc.returncode == 2, (
        f"status is SKIP and rc is {proc.returncode}; the JSON says one thing "
        f"and the exit code the umbrella reads says another")
    assert "VACUOUS_PASS" in proc.stderr


def test_a_real_handshake_still_exits_zero(tmp_path):
    """The accept case, and the reason this was safe to change.

    Without a CHECKED path that still returns 0, promoting the SKIP branch
    would make the gate incapable of passing anything.
    """
    (tmp_path / "h.v").write_text(HANDSHAKE_RTL, encoding="utf-8")
    proc = _run(tmp_path)
    assert _status(proc) == "CHECKED", proc.stdout
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VACUOUS_PASS" not in proc.stderr


def test_no_targets_still_exits_two(tmp_path):
    """The pre-existing could-not-check path must be unchanged."""
    proc = _run(tmp_path / "no-such-dir")
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_warn_only_still_suppresses(tmp_path):
    """`--warn-only` is advisory mode and must keep exiting 0.

    The new refusal is placed after it deliberately: a caller that asked for
    advisory output should not start getting rc 2.
    """
    (tmp_path / "p.v").write_text(PLAIN_RTL, encoding="utf-8")
    proc = _pr.run(
        [sys.executable, str(PROG), str(tmp_path), "--warn-only"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_status_and_the_exit_code_agree(tmp_path):
    """The property, stated once over both fixtures.

    Each assertion above pins one pair; this one pins the relationship, so a
    future third status cannot be added with a mismatched code and stay green
    on the two cases that exist today.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "p.v").write_text(PLAIN_RTL, encoding="utf-8")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "h.v").write_text(HANDSHAKE_RTL, encoding="utf-8")
    for sub, expected_rc in (("a", 2), ("b", 0)):
        proc = _run(tmp_path / sub)
        status = _status(proc)
        assert proc.returncode == expected_rc, (sub, status, proc.returncode)
        assert (status == "CHECKED") == (proc.returncode == 0), (
            f"{sub}: status={status} rc={proc.returncode} — a CHECKED status "
            f"must be the only one that exits 0")
