#!/usr/bin/env python3
r"""Tests for rtl_interface_recover — recovering a module's PORT INTERFACE from
RTL text, and from a prompt's "Updated Interface" prose.

The measured defect this program answers is `top_ports=[]` on RTL whose header
was sitting right there, which SKIPped every downstream testbench generator. So
these arms assert the PORTS THEMSELVES — names, directions and widths — for the
header shapes real RTL uses:

  * ANSI header with Verilog's inheritance rule (`input [N-1:0] a, b` makes BOTH
    N-bit; a chunk that states a NEW direction and no range is scalar again);
  * parameter-driven widths, including a derived `$clog2(N)` default;
  * the non-ANSI header (bare name list + separate `input [3:0] d;` declarations);
  * the NO-CHEAT BOUNDARY — the body is never read, so a `reg` declared inside
    `always` never becomes a port;
  * `recover_from_dir` defaulting to the first module declared, and labelling its
    source honestly when the header does not parse;
  * `recover_interface_from_prompt`, where a RETIRED port ("no longer present")
    must NOT come back as live (vibe-ic#712) and a description saying
    "bidirectional" overrides the enclosing Inputs/Outputs heading.
"""
import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import rtl_interface_recover as R  # noqa: E402


ANSI_RTL = """
// a leading comment that is not a module
module alu #(parameter N = 8, parameter NW = $clog2(N)) (
    input clk,
    input rst_n,
    input [N-1:0] a, b,          // b inherits a's width
    input [3:0] op,
    output [N-1:0] result,
    output reg zero,             // new direction with no range -> scalar
    output [NW-1:0] shamt
);
    reg [7:0] internal_accumulator;
    always @(posedge clk) begin
        internal_accumulator <= a + b;
    end
endmodule
"""

NONANSI_RTL = """
module legacy (clk, d, q, qbar);
    input clk;
    input [3:0] d;
    output [3:0] q;
    output qbar;
    reg [3:0] q;
    always @(posedge clk) q <= d;
    task load;                   // a task's own `input d` is NOT the port `d`
        input [7:0] d;
        begin q <= d[3:0]; end
    endtask
endmodule
"""

PROMPT_WITH_INTERFACE = """Modify the design as follows.

## Input/Output Interface

- **Inputs**:
  - `clk` : system clock
  - `data_in[7:0]` : payload
  - `ready` : this port is no longer present
- **Outputs**:
  - `data_out[7:0]` : result
  - `busy` : bidirectional handshake line

## Notes
Nothing here is a port.
"""


def _by_name(ports):
    return {p["name"]: p for p in ports}


# --------------------------------------------------------------------------- #
# ANSI header
# --------------------------------------------------------------------------- #
def test_ansi_header_recovers_every_port_in_declaration_order():
    ports = R.recover_interface_from_text(ANSI_RTL, "alu")
    assert [p["name"] for p in ports] == [
        "clk", "rst_n", "a", "b", "op", "result", "zero", "shamt"]
    assert [p["dir"] for p in ports] == [
        "input", "input", "input", "input", "input",
        "output", "output", "output"]


def test_a_continuation_chunk_inherits_the_previous_width():
    """Verilog's ANSI rule: `input [N-1:0] a, b` declares TWO N-bit ports. A
    reader that gave `b` width 1 would bind a wrong interface."""
    ports = _by_name(R.recover_interface_from_text(ANSI_RTL, "alu"))
    assert ports["a"]["width"] == 8
    assert ports["b"]["width"] == 8


def test_a_new_direction_without_a_range_is_scalar_not_inherited():
    ports = _by_name(R.recover_interface_from_text(ANSI_RTL, "alu"))
    assert ports["zero"]["width"] == 1


def test_parameter_and_derived_parameter_widths_resolve():
    ports = _by_name(R.recover_interface_from_text(ANSI_RTL, "alu"))
    assert ports["result"]["width"] == 8       # N = 8
    assert ports["shamt"]["width"] == 3        # NW = $clog2(8)


def test_the_body_is_never_read():
    """NO-CHEAT BOUNDARY: parsing stops at the port list, so a register declared
    in the body is not a port and no functional answer can leak through."""
    names = {p["name"] for p in R.recover_interface_from_text(ANSI_RTL, "alu")}
    assert "internal_accumulator" not in names


def test_a_module_name_is_matched_on_a_word_boundary():
    assert R.recover_interface_from_text(ANSI_RTL, "alu_wrapper") == []
    assert R.recover_interface_from_text(ANSI_RTL, "al") == []


# --------------------------------------------------------------------------- #
# non-ANSI header
# --------------------------------------------------------------------------- #
def test_a_nonansi_body_declaration_never_overrides_a_port():
    """Declaration scanning STOPS at the first behavioural construct. The task in
    this fixture re-uses the name `d` for an 8-bit argument; reading past the cut
    would rebind the 4-bit port to it."""
    ports = _by_name(R.recover_interface_from_text(NONANSI_RTL, "legacy"))
    assert ports["d"]["width"] == 4


def test_nonansi_header_takes_direction_and_width_from_the_declarations():
    ports = R.recover_interface_from_text(NONANSI_RTL, "legacy")
    assert [(p["name"], p["dir"], p["width"]) for p in ports] == [
        ("clk", "input", 1),
        ("d", "input", 4),
        ("q", "output", 4),
        ("qbar", "output", 1)]


# --------------------------------------------------------------------------- #
# file / directory entry points
# --------------------------------------------------------------------------- #
def test_recover_from_dir_defaults_to_the_first_module_declared(tmp_path):
    (tmp_path / "alu.v").write_text(ANSI_RTL)
    res = R.recover_from_dir(tmp_path)
    assert res["top_module"] == "alu"
    assert res["source"] == "rtl_header"
    assert _by_name(res["top_ports"])["op"]["width"] == 4


def test_recover_from_dir_says_so_when_the_named_module_is_absent(tmp_path):
    (tmp_path / "alu.v").write_text(ANSI_RTL)
    res = R.recover_from_dir(tmp_path, "not_present")
    assert res["top_ports"] == []
    assert res["source"] == "header-unparsed"


def test_recover_from_files_reports_no_module_found(tmp_path):
    (tmp_path / "notes.v").write_text("// only a comment\n")
    res = R.recover_from_files([tmp_path / "notes.v"])
    assert res == {"top_module": None, "top_ports": [], "source": "no-module-found"}


# --------------------------------------------------------------------------- #
# prompt-stated interface
# --------------------------------------------------------------------------- #
def test_prompt_interface_section_is_recovered_with_directions():
    ports = _by_name(R.recover_interface_from_prompt(PROMPT_WITH_INTERFACE))
    assert ports["clk"]["dir"] == "input"
    assert ports["data_in"] == {"name": "data_in", "dir": "input", "width": 8}
    assert ports["data_out"] == {"name": "data_out", "dir": "output", "width": 8}


def test_a_retired_port_is_not_recovered_as_live():
    """vibe-ic#712 — a prompt lists a REMOVED port as readily as a live one, and
    this function feeds interface recovery, so a phantom here becomes a port on
    the generated module."""
    names = {p["name"] for p in R.recover_interface_from_prompt(PROMPT_WITH_INTERFACE)}
    assert "ready" not in names


def test_a_bidirectional_description_overrides_the_section_heading():
    ports = _by_name(R.recover_interface_from_prompt(PROMPT_WITH_INTERFACE))
    assert ports["busy"]["dir"] == "inout"


def test_a_prompt_without_an_interface_section_recovers_nothing():
    assert R.recover_interface_from_prompt("Just prose about a design.\n") == []
    assert R.recover_interface_from_prompt({"input": {"prompt": "no section"}}) == []
    assert R.recover_interface_from_prompt(None) == []


def test_a_record_dict_is_accepted_as_well_as_bare_prompt_text():
    rec = {"input": {"prompt": PROMPT_WITH_INTERFACE}}
    assert R.recover_interface_from_prompt(rec) == \
        R.recover_interface_from_prompt(PROMPT_WITH_INTERFACE)


def test_the_result_is_json_serialisable():
    # the CLI writes this out; a non-serialisable width would fail there, not here.
    json.dumps(R.recover_interface_from_text(ANSI_RTL, "alu"))
