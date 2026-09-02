#!/usr/bin/env python3
"""Step 5 reached no engine because the READ aborted, and three things caused it.

MEASURED, opentitan_aes at plugin v1.15.66, pinned image
ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...:

    base: aes.sv:10: ERROR: syntax error, unexpected TOK_IMPORT,
          expecting '#' or '(' or ';'
    base: task failed. ERROR.
    DONE (ERROR, rc=16) ... engine_0 did not return a status

Both sby tasks died before an engine started, and the step reported a FORMAL
capability gap the host did not have — `read_slang` was installed the whole
time and phase-2 synth was reading the same sources through it.

Probing the pinned image over the same 131-file `[files]` list turned up three
defects stacked behind one another, each hidden by the one in front:

  1. THE FRONTEND SPLIT. `read_verilog -sv` does not accept a package import
     in a module header. `read_slang --single-unit` elaborates every OpenTitan
     source.
  2. THE HARNESS NAMED THE TYPE, NOT THE PORT. With the read fixed, slang said
     "port 'alert_rx_t' does not exist in 'prim_alert_sender'": the ANSI port
     parser stripped only the BUILT-IN net keywords, so a user-defined type
     survived and was taken as the port name. `input alert_rx_t alert_rx_i`
     became a port called `alert_rx_t`. `read_verilog` never got far enough to
     notice.
  3. SVA vs THE SV FRONTEND. slang then refused the harness's concurrent
     assertions ("SVA unsupported"). The two frontends are COMPLEMENTARY, so
     the assertion FORM has to follow the frontend; the immediate form is the
     exact equivalence `emit_harness` states in its own comment.

With all three closed, the same .sby that had produced rc=16 produces:

    SBY [slang_safety] engine_0: Property proved.
    SBY [slang_safety] DONE (PASS, rc=0)
    SBY [slang_bmc]    DONE (PASS, rc=0)
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import formal_harness_gen as H  # noqa: E402
import formal_property_run as F  # noqa: E402


# The measured shape, reduced: a typed port pair, and a header import.
TYPED_DUT = """
module prim_alert_sender
  import prim_alert_pkg::*;
#(
  parameter bit IsFatal = 1'b0
) (
  input             clk_i,
  input             rst_ni,
  input             alert_req_i,
  output logic      alert_state_o,
  input alert_rx_t  alert_rx_i,
  output alert_tx_t alert_tx_o
);
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) alert_state_o <= 1'b0;
    else         alert_state_o <= alert_req_i;
  end
endmodule
"""

PLAIN_DUT = """
module plain (
  input        clk_i,
  input        rst_ni,
  input        d_i,
  output logic q_o
);
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) q_o <= 1'b0;
    else         q_o <= d_i;
  end
endmodule
"""

# The transcript this whole change was measured from.
ABORT_LOG = (
    "SBY 8:34:27 [formal_bmc] base: aes.sv:10: ERROR: syntax error, "
    "unexpected TOK_IMPORT, expecting '#' or '(' or ';'\n"
    "SBY 8:34:27 [formal_bmc] base: task failed. ERROR.\n"
    "SBY 8:34:27 [formal_bmc] DONE (ERROR, rc=16)\n"
    "SBY 8:34:27 [formal_bmc] engine_0 did not return a status\n"
)


def _iface(text: str, name: str):
    return H.parse_module(text, name)


# ── 2. the port name, not the type ────────────────────────────────────────
def test_a_typed_port_yields_the_name_not_the_type():
    ports = {p.name: p for p in _iface(TYPED_DUT, "prim_alert_sender").ports}
    assert "alert_rx_i" in ports, sorted(ports)
    assert "alert_tx_o" in ports, sorted(ports)
    assert "alert_rx_t" not in ports, "the TYPE was taken as a port name"
    assert ports["alert_rx_i"].data_type == "alert_rx_t"
    assert ports["alert_tx_o"].data_type == "alert_tx_t"


def test_a_plain_port_is_unchanged():
    """REGRESSION CONTROL. A design with no typed port must parse exactly as
    before, data_type empty."""
    ports = {p.name: p for p in _iface(PLAIN_DUT, "plain").ports}
    assert set(ports) == {"clk_i", "rst_ni", "d_i", "q_o"}
    assert all(p.data_type == "" for p in ports.values())


def test_the_harness_connects_and_declares_the_typed_port_by_its_own_type():
    iface = _iface(TYPED_DUT, "prim_alert_sender")
    clk = H.classify_clock(iface.ports)
    rst, low = H.classify_reset(iface.ports, iface.body)
    h = H.emit_harness(iface, clk, rst, low,
                       H.derive_reset_props(iface, rst, low))
    assert ".alert_rx_i(alert_rx_i)" in h
    assert ".alert_rx_t(" not in h
    # A struct-typed port mirrored as a bare `wire` connects a 1-bit net to a
    # struct; the DUT's own declaration is the only statement of its shape.
    assert "alert_rx_t alert_rx_i;" in h
    # …and the type is only visible in a scope that imports its package.
    assert "import prim_alert_pkg::*;" in h


def test_a_design_whose_header_imports_nothing_emits_no_import():
    """REGRESSION CONTROL."""
    iface = _iface(PLAIN_DUT, "plain")
    clk = H.classify_clock(iface.ports)
    rst, low = H.classify_reset(iface.ports, iface.body)
    h = H.emit_harness(iface, clk, rst, low,
                       H.derive_reset_props(iface, rst, low))
    assert "import " not in h
    assert "wire q_o;" in h


# ── 3. the assertion form follows the frontend ────────────────────────────
def test_the_immediate_form_carries_the_same_property():
    iface = _iface(PLAIN_DUT, "plain")
    clk = H.classify_clock(iface.ports)
    rst, low = H.classify_reset(iface.ports, iface.body)
    props = H.derive_reset_props(iface, rst, low)
    assert props, "fixture must produce at least one reset property"
    conc = H.emit_harness(iface, clk, rst, low, props)
    imm = H.emit_harness(iface, clk, rst, low, props,
                         assertion_form="immediate")
    assert "assert property" in conc and "property p_reset_safety_1;" in conc
    assert "assert property" not in imm and "endproperty" not in imm
    # Same guard, same output, same value — the equivalence, not a weakening.
    assert "if (f_past_valid && rst_active)" in imm
    assert "a_reset_safety_1: assert (q_o == '0);" in imm
    assert "(q_o == '0)" in conc


def test_the_default_form_is_concurrent():
    """REGRESSION CONTROL. Every design that parses today keeps its concurrent
    properties; the immediate form is only for the slang arm."""
    iface = _iface(PLAIN_DUT, "plain")
    clk = H.classify_clock(iface.ports)
    rst, low = H.classify_reset(iface.ports, iface.body)
    props = H.derive_reset_props(iface, rst, low)
    assert H.emit_harness(iface, clk, rst, low, props) == \
        H.emit_harness(iface, clk, rst, low, props,
                       assertion_form="concurrent")


# ── 1. the frontend, and the predicate that selects it ────────────────────
def test_emit_sby_default_is_byte_identical_to_read_verilog():
    """REGRESSION CONTROL — the change is a retry, not a new default."""
    txt = F.emit_sby(["a.sv"], "h.sv", "t")
    assert "read_verilog -formal -sv" in txt
    assert "read_slang" not in txt


def test_emit_sby_slang_arm_reads_every_source_as_one_unit():
    txt = F.emit_sby(["a.sv", "b.sv"], "h.sv", "t", frontend="read_slang")
    assert "read_slang --single-unit" in txt
    assert "read_verilog" not in txt
    # No `--formal`: read_slang has no such flag and keeps formal statements
    # by default (probed: `--ignore-assertions` is the opt-OUT).
    assert "--formal" not in txt
    # Both tasks, and the design's own defines, are carried across.
    assert txt.count("read_slang") == 2
    assert "-DSPM_SAFETY_ONLY" in txt and "-DSPM_RESET_AT_T0" in txt


def test_the_measured_abort_selects_the_retry():
    assert F.frontend_aborted_the_read(ABORT_LOG) is True


def test_an_inconclusive_proof_does_not_select_the_retry():
    """DIRECTIONAL CONTROL. A proof that ran and did not close is not a parse
    problem, and re-running it under another frontend would burn the budget
    twice and could report a bound as a capability gap."""
    ran = ("SBY 9:02:11 [formal_bmc] engine_0: Unreached bound.\n"
           "SBY 9:02:11 [formal_bmc] summary: engine_0 (abc bmc3) returned "
           "UNKNOWN\nSBY 9:02:11 [formal_bmc] DONE (UNKNOWN, rc=4)\n")
    assert F.frontend_aborted_the_read(ran) is False


def test_a_failed_proof_does_not_select_the_retry():
    """DIRECTIONAL CONTROL. A counterexample is evidence, not a read error."""
    cex = ("SBY [formal_bmc] engine_0: Assert failed in formal_t: "
           "a_reset_safety_1\nSBY [formal_bmc] DONE (FAIL, rc=2)\n")
    assert F.frontend_aborted_the_read(cex) is False


def test_an_empty_transcript_does_not_select_the_retry():
    assert F.frontend_aborted_the_read("") is False
