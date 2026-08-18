#!/usr/bin/env python3
"""ORGANIC #762 [P2, chip-AGNOSTIC] — iface_conformance_v2 emits false
MISSING-PORT findings for INTERNAL register/net names because two prose
direction-proximity regexes in extract_prompt_iface mis-attribute a port
direction to an internal-net backtick name.

Two distinct mis-reads (both reproduced on shipped 1.0.84):

  (1) _DIR_NEAR_BEFORE_RE treats the ATTRIBUTIVE ADJECTIVE in
      "the output data register (`reg_out`)" as a port-direction tag for the
      internal net reg_out (apb_gpio). 'output' modifies the head noun
      "register"; the backticked name is that register's name, not a port.
      FIX: `_ATTRIBUTIVE_NOUN_GAP_RE` — skips a BEFORE-rule record whose gap is
      a MULTI-WORD attributive noun-phrase (a modifier + head noun) that opens
      the parenthetical wrapping the name ("output data register (`reg_out`)").
      The single-noun role-label paren form "input data (`x`)" AND the bare
      appositive role-label "output signal `done_o`" / "input clock `clk_i`"
      (where the backtick IS that noun) are deliberately preserved — a real
      internal net is protected by the given-code-internal-net mask, NOT by
      prose grammar (#762r2: the prior bare-trailing-head-noun arm over-fired on
      the dominant legitimate "output signal `x`" form, an §4.05 leak).

  (2) _DIR_NEAR_AFTER_RE coincidentally binds 'output' from a SEPARATE clause
      ("the pointer (`r_ptr`) decrements, and the data is output") to the
      internal net r_ptr (async_filo). FIX: `_AFTER_NEW_SUBJECT_RE` — skips an
      AFTER-rule record whose gap ends in a NEW SUBJECT (determiner + noun
      immediately before the consumed copula), so the direction predicates that
      new subject, not the backtick name. A parenthetical annotation
      ("(active high) ") or an adverbial subordinate ("when asserted, ") does
      NOT end in a determiner+noun, so "`s_ready` (active high) is an output" is
      preserved (#762r2: the prior broad clause-break form over-fired on these,
      an §4.05 leak).

§4.05 NO-LEAK: a GENUINE interface port declared WITH an explicit direction
(table OR prose "an input `data_valid`" OR bare appositive "output signal `x`")
that is absent from / reversed in the RTL ports must STILL fire
MISSING-PORT / PORT-DIRECTION — the guards relax only WEAK re-targeted /
attributive prose, never authoritative table / given-code / wavedrom sources nor
a genuine bare appositive role-label.

chip-AGNOSTIC: pure English noun-phrase + clause grammar; no chip/vendor/SKU
literal as detection logic.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
PROG = PROGRAMS / "iface_conformance_v2.py"
sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as M  # noqa: E402


def _kinds(rid, prompt, rtl, context=None):
    return {f.kind for f in M.check_conformance(rid, prompt, rtl, context)}


def _dir(prompt, name):
    return M.extract_prompt_iface(prompt).ports.get(name)


def _run_cli(tmp_path, rtl, prompt, rid=None, strict=False):
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.txt"
    rp.write_text(rtl)
    pp.write_text(prompt)
    cmd = [sys.executable, str(PROG), "--prompt", str(pp), "--rtl", str(rp)]
    if rid is not None:
        cmd += ["--id", rid]
    if strict:
        cmd += ["--strict"]
    return subprocess.run(cmd, capture_output=True, text=True)


# the two affected round-6 shapes, embedded verbatim
_APB_GPIO_PROMPT = (
    "The APB GPIO peripheral exposes the bus interface. "
    "The GPIO is driven by the output data register (`reg_out`).")
_APB_GPIO_RTL = (
    "module apb_gpio(input pclk, input presetn, input [31:0] paddr, "
    "output [7:0] gpio_out); endmodule")

_ASYNC_FILO_PROMPT = (
    "The async FILO buffers data. When the read pointer (`r_ptr`) "
    "decrements, and the data is output to the bus.")
_ASYNC_FILO_RTL = (
    "module async_filo(input wclk, input rclk, input [7:0] din, "
    "output [7:0] dout); endmodule")


# ── (a) NEW-PATH: the wrongly-flagged internal nets now pass ─────────────────
def test_attributive_noun_internal_net_not_a_port():
    """'the output data register (`reg_out`)' — 'output' is an attributive
    adjective of 'register'; reg_out is the internal register's name, not a
    port. It must NOT be extracted as a prose port (so NOT charged MISSING)."""
    assert _dir(_APB_GPIO_PROMPT, "reg_out") is None
    assert "MISSING-PORT" not in _kinds(
        "apb_gpio_0001", _APB_GPIO_PROMPT, _APB_GPIO_RTL)


def test_cross_clause_internal_net_not_a_port():
    """'the pointer (`r_ptr`) decrements, and the data is output' — 'output'
    belongs to the separate clause 'the data is output', not to r_ptr."""
    assert _dir(_ASYNC_FILO_PROMPT, "r_ptr") is None
    assert "MISSING-PORT" not in _kinds(
        "async_filo_0001", _ASYNC_FILO_PROMPT, _ASYNC_FILO_RTL)


def test_attributive_variants_all_suppressed():
    # MULTI-WORD attributive noun-phrases (direction word + modifier + head
    # noun + paren) — these are the #762 internal-net form, suppressed.
    assert _dir("loaded from the input control register (`reg_in`)",
                "reg_in") is None
    assert _dir("the output status flag (`stat_reg`)", "stat_reg") is None
    assert _dir("the input data buffer (`buf_int`)", "buf_int") is None


def test_noleak_bare_appositive_role_label_kept():
    """§4.05 NO-LEAK (#762r2): the bare appositive role-label form
    '<dir> <noun> `name`' — where the backtick IS that noun — is a GENUINE port
    direction and must NOT be suppressed (it is structurally identical to an
    internal-net mention; only the given-code-internal-net mask, not prose
    grammar, may drop a real net). Dropping these silently waved a real port
    direction through — the leak this round closes."""
    assert _dir("output signal `done_o` asserts when ready", "done_o") == "output"
    assert _dir("input data `din` is sampled", "din") == "input"
    assert _dir("input clock `clk_i` drives the core", "clk_i") == "input"
    assert _dir("The output of the module `result_o` is valid",
                "result_o") == "output"
    assert _dir("`s_ready` (active high) is an output.", "s_ready") == "output"
    assert _dir("`done`, when asserted, is an output.", "done") == "output"


def test_noleak_bare_appositive_reversed_direction_still_fires():
    """A bare appositive role-label whose RTL declares the OPPOSITE direction
    must STILL fire PORT-DIRECTION — proving the kept direction is load-bearing,
    not inert."""
    # prose says `din` is an input; RTL declares it an output -> mismatch.
    assert "PORT-DIRECTION" in _kinds(
        None, "input data `din` is sampled",
        "module foo(output din); endmodule")


def test_cross_clause_variants_all_suppressed():
    # coordinating conjunctions and punctuation clause breaks
    assert _dir("`w_ptr` increments, while the data is output", "w_ptr") is None
    assert _dir("`tmp` holds it; then the result is input", "tmp") is None
    assert _dir("(`addr_int`) is decoded but the byte is output", "addr_int") is None


# ── (b) REGRESSION GUARD: prior correct behaviour unchanged ──────────────────
def test_single_noun_paren_role_label_preserved():
    """The LEGITIMATE single-noun role-label paren form 'input data (`x`)' /
    'output bus (`y`)' must STILL be extracted as a real port direction — the
    direction word labels the port the paren wraps (NOT a #762 attributive)."""
    assert _dir("input data (`x`)", "x") == "input"
    assert _dir("output bus (`y`)", "y") == "output"
    assert _dir("input parameters (`p`)", "p") == "input"


def test_before_role_label_still_recognised():
    assert _dir("The bus exposes input `register_addr_i`.",
                "register_addr_i") == "input"


def test_after_copular_role_label_still_recognised():
    """A genuine 'is an output' predication has NO clause break in its gap, so
    the #762 clause-break guard must NOT suppress it."""
    assert _dir("The signal `s_ready` is an output.", "s_ready") == "output"
    assert _dir("`data_valid` is an input.", "data_valid") == "input"


def test_753_guards_unchanged():
    """The #753 copular value-assignment + trailing-noun guards still hold."""
    pif = M.extract_prompt_iface(
        "When `sel` is high, the output clock should be `clk2`.")
    assert "clk2" not in pif.ports
    assert _dir("The `sync_header` is the first 2 bits of the input.",
                "sync_header") in (None, "")


# ── (c) §4.05 NEGATIVE NO-LEAK: genuine missing ports STILL fire ─────────────
def test_noleak_table_declared_port_still_missing():
    """A genuine table-declared input port absent from the RTL ports must STILL
    fire MISSING-PORT — the prose guards never weaken the table source."""
    p = "| Signal | Direction |\n|---|---|\n| `missing_port` | input |\n"
    assert "MISSING-PORT" in _kinds(None, p, "module foo(input clk); endmodule")


def test_noleak_genuine_prose_input_still_missing():
    """A genuine prose role-label 'an input `data_valid`' absent from the RTL
    must STILL fire MISSING-PORT (no clause break, no attributive noun)."""
    p = "There is an input `data_valid`."
    assert "MISSING-PORT" in _kinds(None, p, "module foo(input clk); endmodule")


def test_noleak_table_port_comentioned_in_attributive_prose_still_fires():
    """A real TABLE-declared port co-mentioned in attributive prose still fires
    if missing — the table source takes precedence over the prose attributive
    mis-attribution (the #762 invariant)."""
    p = ("| Signal | Direction |\n|---|---|\n| `control_valid` | output |\n\n"
         "The state is held by the output control_valid register (`ctrl_int`).")
    assert "MISSING-PORT" in _kinds(
        None, p, "module foo(input clk); endmodule")


# ── (d) #478 END-STATE: real program via subprocess, returncode assert ───────
def test_endstate_apb_gpio_no_phantom_strict(tmp_path):
    (tmp_path / "p.txt").write_text(_APB_GPIO_PROMPT)
    (tmp_path / "c.sv").write_text(_APB_GPIO_RTL)
    r = subprocess.run(
        [sys.executable, str(PROG), "--id", "apb_gpio_0001",
         "--prompt", str(tmp_path / "p.txt"), "--rtl", str(tmp_path / "c.sv"),
         "--strict"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "interface-conformance ok" in r.stdout


def test_endstate_async_filo_no_phantom_strict(tmp_path):
    (tmp_path / "p.txt").write_text(_ASYNC_FILO_PROMPT)
    (tmp_path / "c.sv").write_text(_ASYNC_FILO_RTL)
    r = subprocess.run(
        [sys.executable, str(PROG), "--id", "async_filo_0001",
         "--prompt", str(tmp_path / "p.txt"), "--rtl", str(tmp_path / "c.sv"),
         "--strict"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "interface-conformance ok" in r.stdout


def test_endstate_noleak_missing_port_strict_exit1(tmp_path):
    """The #478 end-state for the NO-LEAK case: a genuine missing table port
    under --strict exits 1 and names the port."""
    (tmp_path / "p.txt").write_text(
        "| Signal | Direction |\n|---|---|\n| `data_in` | input |\n")
    (tmp_path / "c.sv").write_text("module foo(input clk); endmodule")
    r = subprocess.run(
        [sys.executable, str(PROG),
         "--prompt", str(tmp_path / "p.txt"), "--rtl", str(tmp_path / "c.sv"),
         "--strict"], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "MISSING-PORT" in r.stdout and "data_in" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
