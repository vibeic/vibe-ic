"""ORGANIC #749 [P2] — two-part gshare PHT reset-placement fix.

(LINT, rtl_hygiene_lint) rule_array_reset_loop_idiom RECOGNISES an array-reset
loop inside an async-reset clocked block (blocking `arr[i]=val` in a `for` under
the ASSERTED `if(reset)` branch) as an INTENDED idiom, reporting it at INFO
(advisory/auto-waive, NON-blocking). §4.05: it does NOT fire (so never waives)
on a combinational loop, nor on a non-reset blocking-in-sequential array write.

(LESSONS, agents/ic-expert-agent.md) the gshare/branch-predictor section now
states the weakly-not-taken (2'b01) PHT init must be re-applied INSIDE the reset
block on every async reset (NOT once in `initial`), generalised to any
array/memory with a reset spec, with the BLKLOOPINIT/BLKSEQ → WAIVE directive.
The lessons-corpus consistency checker still PASSes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PLUGIN = Path(__file__).resolve().parents[2]
_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_LINT = _PROGRAMS / "rtl_hygiene_lint.py"
_LESSONS = _PLUGIN / "agents" / "ic-expert-agent.md"


def _idiom(tmp_path, text):
    p = tmp_path / "dut.sv"
    p.write_text(text)
    return [f for f in H.lint_file(p) if f.rule == "array-reset-loop-idiom"]


def _rc(tmp_path, text):
    p = tmp_path / "rc.sv"
    p.write_text(text)
    r = subprocess.run([sys.executable, str(_LINT), str(p)],
                       capture_output=True, text=True)
    return r.returncode


# ── LINT: async-reset PHT init loop recognised as INTENDED (INFO, non-block) ─
_GSHARE = (
    "module gshare(input clk, input areset, input [3:0] idx, "
    "output reg predict);\n"
    "  reg [1:0] pht [0:15];\n"
    "  integer i;\n"
    "  always @(posedge clk or posedge areset) begin\n"
    "    if (areset) begin\n"
    "      predict <= 1'b0;\n"
    "      for (i = 0; i < 16; i = i + 1)\n"
    "        pht[i] = 2'b01;\n"
    "    end else begin\n"
    "      predict <= pht[idx][1];\n"
    "    end\n"
    "  end\nendmodule\n"
)


def test_array_reset_loop_recognised_as_idiom(tmp_path):
    f = _idiom(tmp_path, _GSHARE)
    assert len(f) == 1
    assert f[0].severity == "INFO"          # advisory / auto-waive
    assert f[0].symbol == "pht"
    assert "do NOT evict" in f[0].message
    assert "WAIVE" in f[0].message


def test_idiom_is_non_blocking(tmp_path):
    """END-STATE: with the output reset too, only the INFO idiom remains → rc=0."""
    assert _rc(tmp_path, _GSHARE) == 0


def test_generalises_to_any_named_array(tmp_path):
    """Not gshare-specific — a scoreboard/regfile reset loop is recognised too."""
    src = (
        "module sb(input clk, input arst, input [2:0] a, input [7:0] d);\n"
        "  reg [7:0] scoreboard [0:7];\n"
        "  integer k;\n"
        "  always @(posedge clk or posedge arst) begin\n"
        "    if (arst) for (k=0;k<8;k=k+1) scoreboard[k] = 8'h00;\n"
        "    else scoreboard[a] <= d;\n"
        "  end\nendmodule\n"
    )
    f = _idiom(tmp_path, src)
    assert len(f) == 1 and f[0].symbol == "scoreboard"


# ── §4.05: do NOT waive a genuine COMBINATIONAL loop ────────────────────────
def test_combinational_loop_not_recognised(tmp_path):
    """A pure combinational for-loop has no edge in its sensitivity list, so it
    is NOT a reset idiom and must NOT be waived."""
    src = (
        "module comb(input [3:0] sel, output reg [15:0] oh);\n"
        "  integer i;\n"
        "  always @(*) begin\n"
        "    for (i = 0; i < 16; i = i + 1)\n"
        "      oh[i] = (sel == i);\n"
        "  end\nendmodule\n"
    )
    assert _idiom(tmp_path, src) == []


# ── §4.05: do NOT waive a non-reset blocking-in-sequential array write ──────
def test_nonreset_blocking_in_sequential_not_recognised(tmp_path):
    src = (
        "module nrs(input clk, input [3:0] idx, input [7:0] din);\n"
        "  reg [7:0] mem [0:15];\n"
        "  integer i;\n"
        "  always @(posedge clk) begin\n"
        "    if (idx == 0) begin\n"
        "      for (i = 0; i < 16; i = i + 1)\n"
        "        mem[i] = din;\n"
        "    end\n"
        "  end\nendmodule\n"
    )
    assert _idiom(tmp_path, src) == []


def test_deasserted_reset_branch_not_recognised(tmp_path):
    """A loop under the DEASSERT (`!areset`) branch is normal operation, not a
    reset re-init → not waived."""
    src = (
        "module g(input clk, input areset, input [7:0] d);\n"
        "  reg [7:0] mem [0:7];\n"
        "  integer i;\n"
        "  always @(posedge clk or posedge areset) begin\n"
        "    if (!areset) for (i=0;i<8;i=i+1) mem[i] = d;\n"
        "  end\nendmodule\n"
    )
    assert _idiom(tmp_path, src) == []


# ── LESSONS: the gshare section carries the reset-placement directive ───────
def test_lessons_section_states_reset_placement():
    txt = _LESSONS.read_text()
    assert "Reset placement" in txt
    assert "INSIDE the reset" in txt
    # must steer AWAY from initial-block eviction
    assert "do NOT" in txt and "initial" in txt
    assert "BLKLOOPINIT" in txt and "WAIVE" in txt
    # generalised beyond gshare
    assert "scoreboard" in txt or "regfile" in txt


def test_lessons_corpus_consistency_still_passes():
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "lessons_corpus_consistency_check.py"),
         str(_LESSONS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
