"""PR #28 / Step-2.7 S4-OVM1 round-2 — `_portlist_prefix_len` must be §4.05-SAFE.

PR #28 bounded #27's truncated-header fallback in `_specrtl_common._module_port_region`
(unbalanced `(`, no body-boundary keyword) so prose stops leaking as phantom ports.
A Step-2.7 multi-lens adversarial review found the bound, as first written, traded
#27's false-FIRE residual (a prose phantom — the §4.05-SAFE direction) for a
false-SKIP residual: it DROPPED real direction-declared ports, and one inline-
described port CASCADE-dropped every clean port after it. A dropped spec port makes
the downstream conformance gate FALSE-SKIP a genuinely-missing RTL port — the worst
§4.05 direction (an invisible missed defect, not a visible spurious fail).

These regression tests pin the corrected, §4.05-safe contract — exercising the REAL
gate program end-to-end where possible (the defect artifact is a truncated-header
markdown spec + an RTL that is genuinely missing some of its ports; the gate MUST
flag the missing ports, proving they were not false-skipped):

  * a real direction-declared port is NEVER dropped (no cascade);
  * a real port whose NAME collides with the prose-noun blacklist is kept (the
    direction keyword anchors it, exactly as parse_verilog_ports harvests it);
  * an inline `//` / `/* */` comment inside a truncated port list does not cut the
    region mid-list (the bound is comment-aware, aligned with parse_verilog_ports);
  * a copula sentence (`input is …`) and pure no-direction prose still yield NO port;
  * the verb residual (`enables`/`drives`) is BOUNDED to the port-list region (one
    token), never #27's unbounded document-wide scrape.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(os.environ.get(
    "VIBE_PROGRAMS", str(Path(__file__).resolve().parent.parent)))
SPEC_CONF = PROGRAMS / "spec_conformance_check.py"
sys.path.insert(0, str(PROGRAMS))

import _specrtl_common as SRC          # noqa: E402


def _ports(txt: str, prefer: str = "TopModule"):
    region = SRC._module_port_region(txt, prefer=prefer)
    return {p.name for p in SRC.parse_verilog_ports(region or "")}


# --------------------------------------------------------------------------- #
# End-to-end through the REAL gate: a missing real port MUST be caught          #
# --------------------------------------------------------------------------- #
def _run_gate(tmp_path, spec_md: str, dut_v: str, top: str):
    spec = tmp_path / "spec.md"
    dut = tmp_path / "dut.v"
    spec.write_text(spec_md)
    dut.write_text(dut_v)
    proc = subprocess.run(
        [sys.executable, str(SPEC_CONF), str(dut), "--spec", str(spec), "--top", top],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def test_e2e_truncated_header_missing_ports_are_caught_not_false_skipped(tmp_path):
    """The §4.05 end-state: a TRUNCATED-header spec (unbalanced `(`, no body keyword)
    declares gray/rst/bin/valid; the RTL is genuinely MISSING bin + valid. The gate
    MUST FAIL with port-missing for BOTH — proving the bound did not drop them from
    the spec contract (the pre-fix bound dropped bin+valid, so the gate false-PASSed
    a real missing-port defect)."""
    spec_md = (
        "# gray_to_bin\n\n"
        "Converts a 4-bit Gray code input to binary.\n\n"
        "module gray_to_bin (\n"
        "    input  [3:0] gray,\n"
        "    input        rst the active reset signal,\n"   # inline description (no body kw)
        "    output [3:0] bin,\n"
        "    output       valid\n"
    )
    dut_v = (
        "module gray_to_bin (\n"
        "    input  [3:0] gray,\n"
        "    input        rst\n"
        ");\nendmodule\n"
    )
    rc, out = _run_gate(tmp_path, spec_md, dut_v, "gray_to_bin")
    assert rc == 1, out                                 # gate FAILs (defect caught)
    assert "port-missing" in out
    assert "'bin'" in out and "'valid'" in out, out      # BOTH real ports flagged


def test_e2e_cascade_poison_does_not_mask_later_missing_ports(tmp_path):
    """An inline-described port mid-list (`input rst the reset`) must not cascade-
    drop the clean ports after it. Spec declares clk/rst/valid/data; RTL missing
    valid+data -> the gate MUST flag both (pre-fix kept only clk, masking them)."""
    spec_md = (
        "# core\n\nmodule TopModule (\n"
        "    input        clk,\n"
        "    input        rst the synchronous reset,\n"
        "    output       valid,\n"
        "    output [7:0] data\n"
    )
    dut_v = (
        "module TopModule (\n"
        "    input clk,\n"
        "    input rst\n"
        ");\nendmodule\n"
    )
    rc, out = _run_gate(tmp_path, spec_md, dut_v, "TopModule")
    assert rc == 1, out
    assert "'valid'" in out and "'data'" in out, out


# --------------------------------------------------------------------------- #
# Unit: the bound keeps every real direction-declared port                      #
# --------------------------------------------------------------------------- #
def test_cascade_poison_keeps_all_real_ports():
    txt = ("module TopModule ( input clk, input rst the reset, "
           "output valid, output [7:0] data")
    assert {"clk", "rst", "valid", "data"} <= _ports(txt)


def test_blacklist_named_real_port_kept_when_direction_anchored():
    # `value` is in _NL_PORT_PROSE_NAMES but is here a real direction-declared port
    assert {"clk", "value", "q"} <= _ports("module TopModule ( input clk, input value, output q")


def test_inline_line_comment_does_not_cut_truncated_portlist():
    assert {"a", "b"} <= _ports("module TopModule (input a, // the clock\n output b")


def test_inline_block_comment_does_not_cut_truncated_portlist():
    assert {"a", "b"} <= _ports("module foo (\n input a, /* clk */\n output b", prefer="foo")


def test_single_letter_port_a_not_dropped_as_function_word():
    # `a`/`an` are coordinating function words but ALSO common single-letter ports;
    # the direction keyword anchors them — they must not be dropped.
    assert {"a", "b"} <= _ports("module TopModule (input a, output b")
    assert {"an", "b"} <= _ports("module TopModule (input an, output b")


def test_trailing_sentence_keeps_real_last_port():
    assert {"a", "result"} <= _ports(
        "module TopModule (\n  input a,\n  output result holds the final value")


def test_blank_line_grouped_ports_not_dropped_after_described_port():
    """Round-3 §4.05: a blank line is a legitimate visual grouping of a newline-
    separated port list. A described port (`input clk system clock`) followed by a
    BLANK LINE and then more real ports must keep them all — the resync crosses the
    blank line (a paragraph-break bound here false-SKIPped the grouped reset/output
    ports rst_n + valid, the worst §4.05 direction)."""
    txt = ("module TopModule (\n"
           "  input  clk      system clock\n"
           "\n"
           "  input  rst_n    active-low reset\n"
           "  output valid    result valid\n")
    assert {"clk", "rst_n", "valid"} <= _ports(txt, prefer="TopModule")


def test_port_position_resync_keeps_real_ports_across_separators():
    """The resync reaches a real later port across any plain port-list separator
    after a same-line description: comma, multi-space-comma, CRLF, tab-indented
    newline, and a one-port-per-line newline (no comma)."""
    for txt in (
        "module TopModule ( input clk the clock,\r\n output valid",     # CRLF
        "module TopModule (\n\tinput clk the clk,\n\toutput valid",     # tab indent
        "module TopModule ( input clk the clock,    output valid",      # multi-space
        "module TopModule (\n    input clk the clock\n    output valid",  # newline, no comma
    ):
        assert {"clk", "valid"} <= _ports(txt, prefer="TopModule"), txt


# --------------------------------------------------------------------------- #
# Unit: phantom-kill preserved; verb residual bounded                           #
# --------------------------------------------------------------------------- #
def test_no_direction_prose_yields_no_port():
    assert _ports("module TopModule (Gray is computed by inverting the bits") == set()


def test_copula_after_direction_yields_no_port():
    assert _ports("module TopModule (input is high when ready") == set()


def test_ambiguous_verb_residual_is_bounded_to_one_token():
    # an ambiguous verb after a direction keyword may remain (§4.05-safe false-FIRE,
    # lexically a port name) but the harvest is BOUNDED — never the unbounded
    # document-wide scrape #27 did.
    for txt in (
        "module M ( output wire enables the chip and lots more prose follows here\n",
        "module M ( input drives the select line across the whole sentence tail\n",
    ):
        assert len(_ports(txt, prefer="M")) <= 1, txt


def test_balanced_and_body_keyword_paths_untouched():
    # the new branch fires ONLY on the truncated-no-keyword path; the paths real
    # corpus designs reach are unchanged.
    assert _ports("module TopModule (input a, output b);\n assign b=a;\nendmodule") == {"a", "b"}
    assert _ports("module TopModule (input a, output b\n  logic x;") == {"a", "b"}


def test_mask_comments_len_preserves_length():
    for s in ("input a, /* clk */ output b", "input a, // c\n output b", "x // tail"):
        assert len(SRC._mask_comments_len(s)) == len(s), s


def test_bound_terminates_fast_on_pathological_whitespace():
    """The walk skips inter-token whitespace manually, so a truncated `(` followed
    by thousands of blank lines cannot trigger O(n^2) regex backtracking (the two
    `\\s*` groups of _PORTLIST_SEG would otherwise backtrack catastrophically)."""
    import time
    for s in ("(" + "\n" * 8000, "(" + " " * 8000 + "input a", "(input a output b " * 1500):
        t = time.time()
        SRC._portlist_prefix_len(s)
        assert time.time() - t < 0.5, (len(s), time.time() - t)
