"""Step-2.7 §4.05 guard for PR #18 waveform_table_conformance_check.

The gate's Envelope-B replay uses the NBA `@(posedge) a<=val` convention, which
leaves the registered output X at the FIRST posedge. Step-2.7 reproduced a MED
FALSE-BLOCK: a CORRECT posedge design (`q<=~a`) whose published table is
internally self-consistent under the SAME-EDGE sampling convention (output
already concrete at the first posedge) was BLOCKED because the gate replayed it
as NBA without verifying the convention.

FIX: classify() detects the same-edge signature (a concrete 0/1 output at the
first posedge, where NBA always has X) and SKIPs (rc 0, never blocks). This
converts the false-block into a SKIP WITHOUT introducing a false-pass (it never
PASSes the same-edge table) and keeps the canonical NBA tables (X at first
posedge) in Envelope B so a genuine extra-stage / wrong-logic design still
BLOCKS.

chip-AGNOSTIC; the end-to-end case needs iverilog/vvp (skipped otherwise).
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import waveform_table_conformance_check as W  # noqa: E402

_HAVE = shutil.which("iverilog") and shutil.which("vvp")

_SAME_EDGE_TABLE = (
    "time  clk a   q\n"
    "0ns   0   0   x\n"
    "5ns   1   0   1\n"     # concrete output at the FIRST posedge => same-edge
    "10ns  0   0   1\n"
    "15ns  1   1   0\n"
    "20ns  0   1   0\n"
    "25ns  1   0   1\n"
    "30ns  0   0   1\n")

# canonical NBA table: output is X at the first posedge(s) (the NBA signature).
_NBA_TABLE = (
    "time  clk a   q\n"
    "0ns   0   x   x\n"
    "5ns   1   0   x\n"     # X at the first posedge => NBA, Envelope B keeps block
    "10ns  0   0   x\n"
    "15ns  1   0   1\n"
    "20ns  0   0   1\n"
    "25ns  1   1   1\n"
    "30ns  0   1   1\n"
    "35ns  1   1   0\n"
    "40ns  0   1   0\n")

_CORRECT = ("module TopModule(input clk, input a, output reg q);\n"
            "  always @(posedge clk) q <= ~a;\nendmodule\n")


def _classify(table, rtl):
    cols, rows = W.parse_table(table)
    ins, outs = W.module_ports(rtl)
    return W.classify(cols, rows, ins, outs, rtl)


def test_same_edge_table_is_skipped_not_envelope_b():
    env, _out, _in, reason = _classify(_SAME_EDGE_TABLE, _CORRECT)
    assert env is None
    assert reason == "same_edge_output_convention"


def test_nba_table_stays_in_envelope_b():
    env, _out, _in, _reason = _classify(_NBA_TABLE, _CORRECT)
    assert env == "B"          # canonical NBA table keeps its blocking power


def _run(tmp_path, table, rtl):
    tf = tmp_path / "t.txt"; tf.write_text(table)
    rf = tmp_path / "r.sv"; rf.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "waveform_table_conformance_check.py"),
         "--prompt", str(tf), "--rtl", str(rf), "--top", "TopModule"],
        capture_output=True, text=True)


@pytest.mark.skipif(not _HAVE, reason="iverilog/vvp required")
def test_correct_design_under_same_edge_table_not_false_blocked(tmp_path):
    r = _run(tmp_path, _SAME_EDGE_TABLE, _CORRECT)
    assert r.returncode == 0, r.stdout + r.stderr     # SKIP, never blocked
    assert "WTC_SKIP_same_edge_output_convention" in r.stdout


@pytest.mark.skipif(not _HAVE, reason="iverilog/vvp required")
def test_no_false_pass_genuine_bug_under_nba_table_still_blocks(tmp_path):
    # q<=a (missing inversion) under the canonical NBA table must still BLOCK —
    # the SKIP rule must not have weakened genuine in-envelope blocking.
    bug = ("module TopModule(input clk, input a, output reg q);\n"
           "  always @(posedge clk) q <= a;\nendmodule\n")
    r = _run(tmp_path, _NBA_TABLE, bug)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WTC_FAIL" in r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
