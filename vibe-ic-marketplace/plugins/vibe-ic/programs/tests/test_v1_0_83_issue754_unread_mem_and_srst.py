"""ORGANIC #754 [P2] — two rtl_hygiene_lint false-blocks on correct RTL:

(1) rule_undriven_and_unread WARN-blocked a write-only UNPACKED MEMORY ARRAY
    (`reg [W-1:0] NAME [DEPTH]`, indexed-write-only) as `unread-reg`. Such an
    array is a legitimate single-port-RAM storage pattern whose read port lives
    in a sibling/future module → demoted to INFO (advisory, NON-blocking). A
    genuinely-dead SCALAR reg still WARNs/blocks.

(2) `_RESET_NAME_RE` omitted the SYNC prefix, so canonical `srst`/`sreset` were
    unmatched and an `if(srst) out<=0;` output was mis-classified reset-less,
    falsely tripping rule_uninit_registered_output. The async-only `a?` prefix
    is widened to `[as]?` so srst/sreset/arst/areset all match.

§4.05 no-leak: dead scalar reg still WARN/blocks; reset-less output still
flagged; fake-reset-by-`start` still flagged; 21 non-reset names DON'T match.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_LINT = _PROGRAMS / "rtl_hygiene_lint.py"


def _lint(tmp_path, text, rule=None):
    p = tmp_path / "dut.sv"
    p.write_text(text)
    fs = H.lint_file(p)
    return [f for f in fs if rule is None or f.rule == rule]


def _rc(tmp_path, text):
    p = tmp_path / "rc.sv"
    p.write_text(text)
    r = subprocess.run([sys.executable, str(_LINT), str(p)],
                       capture_output=True, text=True)
    return r.returncode


# ── (1) write-only memory array → INFO (advisory, non-blocking) ─────────────
_MEM = (
    "module mshr(input clk, input [7:0] idx, input [31:0] din);\n"
    "  reg [31:0] data_ram_q [0:255];\n"
    "  always @(posedge clk) data_ram_q[idx] <= din;\n"
    "endmodule\n"
)


def test_write_only_mem_array_demoted_to_info(tmp_path):
    f = _lint(tmp_path, _MEM, rule="unread-reg")
    assert len(f) == 1
    assert f[0].severity == "INFO"           # advisory, NOT WARN
    assert f[0].symbol == "data_ram_q"
    assert "memory array" in f[0].message


def test_write_only_mem_array_does_not_block(tmp_path):
    """END-STATE: rc=0 — INFO does not block (was rc=1 before the fix)."""
    assert _rc(tmp_path, _MEM) == 0


# ── §4.05: a genuinely-dead SCALAR reg STILL WARNs/blocks ───────────────────
_DEAD_SCALAR = (
    "module d(input clk, input din);\n"
    "  reg dead_q;\n"
    "  always @(posedge clk) dead_q <= din;\n"
    "endmodule\n"
)


def test_dead_scalar_reg_still_warns_and_blocks(tmp_path):
    f = _lint(tmp_path, _DEAD_SCALAR, rule="unread-reg")
    assert len(f) == 1
    assert f[0].severity == "WARN"           # scalar dead reg still blocks
    assert _rc(tmp_path, _DEAD_SCALAR) == 1


# ── (2) srst/sreset now recognised — uninit-registered-output no longer fires ─
_SRST = (
    "module muller(input clk, input srst, input a, output reg out);\n"
    "  always @(posedge clk) begin\n"
    "    if (srst) out <= 1'b0;\n"
    "    else out <= a;\n"
    "  end\n"
    "endmodule\n"
)


def test_srst_output_no_longer_falsefires(tmp_path):
    f = _lint(tmp_path, _SRST, rule="uninit-registered-output")
    assert f == []
    assert _rc(tmp_path, _SRST) == 0


def test_sreset_also_recognised(tmp_path):
    src = _SRST.replace("srst", "sreset")
    f = _lint(tmp_path, src, rule="uninit-registered-output")
    assert f == []


# ── §4.05: reset-LESS output STILL flagged (regex widen didn't over-match) ──
def test_resetless_output_still_flagged(tmp_path):
    f = _lint(tmp_path,
              "module rl(input clk, input a, output reg out);\n"
              "  always @(posedge clk) out <= a;\n"
              "endmodule\n",
              rule="uninit-registered-output")
    assert len(f) == 1


# ── §4.05: a fake "reset" named `start` must NOT count as a reset ───────────
def test_fake_reset_by_start_still_flagged(tmp_path):
    f = _lint(tmp_path,
              "module fr(input clk, input start, input a, output reg out);\n"
              "  always @(posedge clk) begin\n"
              "    if (start) out <= 1'b0;\n"
              "    else out <= a;\n"
              "  end\nendmodule\n",
              rule="uninit-registered-output")
    assert len(f) == 1


# ── regex recognition table ─────────────────────────────────────────────────
def test_reset_regex_matches_canonical_sync_and_async_spellings():
    for nm in ("srst", "sreset", "srst_n", "srstn", "arst", "areset",
               "rst", "reset", "rst_n", "resetn", "nreset", "por",
               "sclr", "aclr"):
        assert H._RESET_NAME_RE.search(nm), nm


def test_reset_regex_zero_false_match_on_nonreset_names():
    for nm in ("start", "status", "strobe", "store", "state", "select",
               "strict", "stream", "setup", "sample", "arvalid", "awsize",
               "arsize", "master", "slave", "address", "asize", "assert",
               "strb", "sout", "stage"):
        assert not H._RESET_NAME_RE.search(nm), nm
