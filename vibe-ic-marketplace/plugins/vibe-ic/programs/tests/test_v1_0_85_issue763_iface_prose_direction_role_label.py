#!/usr/bin/env python3
"""ORGANIC #763 [P2, chip-AGNOSTIC] — iface_conformance_v2 emits spurious
PORT-DIRECTION (and MISSING-PORT) findings because the prose direction
extractors attribute an English direction WORD ("input"/"output") to the nearest
backtick signal name even when the word is NOT a port role-label.

Three grammatical mis-reads (all reproduced on shipped 1.0.84):

  (1) imperative VERB / GERUND — "Output the signal only during the `clk_pulse`"
      -> clk_pulse=output (Output is the verb, not a role-label);
      "output by XORing `serial_in`" -> serial_in=output.
  (2) ATTRIBUTIVE NOUN-MODIFIER of a following common noun —
      "Select the output encoding based on the `mode`" -> mode=output (output
      modifies 'encoding'); "if `dfmt_enable` is disabled output data will be ..."
      (AFTER rule) -> dfmt_enable=output.
  (3) PRIOR-CLAUSE LEAK across a sentence boundary —
      "Encoded output signal. The encoding applied to `serial_in`" -> the
      adjective 'output' leaks 33 chars across a period onto serial_in.

FIX (chip-AGNOSTIC, pure English-grammar structure):
  * BEFORE rule: `_before_dir_is_role_label(gap)` rejects a match whose gap
    crosses a sentence/clause boundary, leads with a modified common-noun, or
    leads with a verb/preposition — while KEEPING thin role-label gaps and the
    noun-paren "input data (`x`)" form.
  * AFTER rule: skip a direction word immediately followed by a data-noun when
    the gap is a verbal/conditional clause (`_AFTER_DATA_NOUN_RE` +
    `_AFTER_GAP_CLAUSE_RE`); the descriptive "`x`: Output signal" /
    "16-bit output signal" forms (no clause verb) are preserved.

§4.05 NO-LEAK: a GENUINE direction reversal where 'input'/'output' truly IS a
role-label ("register the `serial_in` output", "input `serial_in` is used as")
must STILL be extracted and STILL fire PORT-DIRECTION when the RTL reverses it.

chip-AGNOSTIC: pure English-grammar structure over the prose gap; no chip/
vendor/SKU literal as detection logic.
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


# the real Serial_Line_Converter spec, embedded verbatim from the acceptance cmd
_SL_SPEC = (
    "## Interface\n"
    "Output the signal only during the `clk_pulse`.\n"
    "The signal should be driven through the mode selector based on `mode`.\n"
    "Select the output encoding based on the `mode`.\n"
    "The encoding applied to `serial_in` shifts the data.\n")
_SL_RTL = (
    "module serial_line_code_converter(\n"
    "  input logic clk,\n"
    "  input logic reset_n,\n"
    "  input logic serial_in,\n"
    "  input logic [2:0] mode,\n"
    "  input logic clk_pulse,\n"
    "  output logic serial_out\n"
    ");\nendmodule\n")


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


# ── (a) NEW-PATH: the three grammatical mis-reads no longer mis-attribute ────
def test_imperative_verb_not_role_label():
    """'Output the signal only during the `clk_pulse`' — 'Output' is a verb."""
    assert _dir("Output the signal only during the `clk_pulse`.",
                "clk_pulse") is None


def test_gerund_verb_not_role_label():
    assert _dir("The result is produced output by XORing `serial_in`.",
                "serial_in") is None


def test_attributive_noun_modifier_before_not_role_label():
    """'Select the output encoding based on the `mode`' — output modifies
    'encoding', not mode."""
    assert _dir("Select the output encoding based on the `mode`.",
                "mode") is None


def test_attributive_noun_modifier_after_clause_not_role_label():
    """AFTER rule: 'if `dfmt_enable` is disabled output data will be ...' —
    output modifies 'data' in a verbal clause."""
    assert _dir("if `dfmt_enable` is disabled output data will be sent.",
                "dfmt_enable") is None


def test_prior_clause_leak_across_period_not_role_label():
    """'Encoded output signal. The encoding applied to `serial_in`' — 'output'
    leaks across the sentence boundary onto serial_in."""
    assert _dir(
        "Encoded output signal. The encoding applied to `serial_in` shifts.",
        "serial_in") is None


def test_serial_converter_no_spurious_port_direction():
    """The full spec must produce NO PORT-DIRECTION findings against the
    spec-faithful RTL (serial_in/mode/clk_pulse are all inputs)."""
    assert "PORT-DIRECTION" not in _kinds(
        "cvdp_copilot_Serial_Line_Converter_0001", _SL_SPEC, _SL_RTL)


# ── (b) REGRESSION GUARD: prior correct role-label extraction unchanged ──────
def test_before_thin_role_label_preserved():
    assert _dir("The bus exposes input `register_addr_i`.",
                "register_addr_i") == "input"
    assert _dir("output `done_o` asserts when finished.", "done_o") == "output"


def test_before_noun_paren_role_label_preserved():
    """The noun-paren role-label form 'input data (`x`)' is KEPT."""
    assert _dir("input data (`x`)", "x") == "input"
    assert _dir("output parameters (`cfg`)", "cfg") == "output"


def test_after_descriptive_role_label_preserved():
    """'`serial_out`: Encoded output signal' — descriptive AFTER form, no clause
    verb in the gap, so it is preserved (output IS the role-label)."""
    assert _dir("`serial_out`: Encoded output signal.", "serial_out") == "output"
    assert _dir("The signal `s_ready` is an output.", "s_ready") == "output"
    assert _dir("`data_valid` is an input.", "data_valid") == "input"


def test_753_guards_unchanged():
    pif = M.extract_prompt_iface(
        "When `sel` is high, the output clock should be `clk2`.")
    assert "clk2" not in pif.ports


# ── (c) §4.05 NEGATIVE NO-LEAK: genuine direction reversals STILL fire ───────
def test_noleak_after_role_label_reversal_still_extracted():
    """'register the `serial_in` output' — 'output' is NOT preceded by a
    sentence boundary, NOT a verb-object gap, and NOT followed by a clause-noun,
    so it IS accepted as a role-label and a reversed RTL still fires."""
    assert _dir("register the `serial_in` output", "serial_in") == "output"
    assert "PORT-DIRECTION" in _kinds(
        None, "register the `serial_in` output",
        "module foo(input serial_in); endmodule")


def test_noleak_before_role_label_reversal_still_fires():
    """'The input `serial_in` is used as ...' — genuine BEFORE role-label; an
    RTL declaring serial_in as output must STILL fire PORT-DIRECTION."""
    p = "The input `serial_in` is used as the data source."
    assert _dir(p, "serial_in") == "input"
    assert "PORT-DIRECTION" in _kinds(
        None, p, "module foo(output serial_in); endmodule")


def test_noleak_genuine_missing_port_still_fires():
    p = "| Signal | Direction |\n|---|---|\n| `ready_o` | output |\n"
    assert "MISSING-PORT" in _kinds(None, p, "module foo(input clk); endmodule")


# ── (d) #478 END-STATE: real program via subprocess, returncode assert ───────
def test_endstate_serial_converter_no_phantom_strict(tmp_path):
    (tmp_path / "spec.txt").write_text(_SL_SPEC)
    (tmp_path / "rtl.sv").write_text(_SL_RTL)
    r = subprocess.run(
        [sys.executable, str(PROG), "--id",
         "cvdp_copilot_Serial_Line_Converter_0001",
         "--prompt", str(tmp_path / "spec.txt"),
         "--rtl", str(tmp_path / "rtl.sv"), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "interface-conformance ok" in r.stdout


def test_endstate_prose_direction_reversal_is_advisory_770(tmp_path):
    """ORGANIC #770 RE-ANCHOR: a PROSE-ONLY direction the RTL CONTRADICTS is now
    ADVISORY (reported, but does NOT hard-block under --strict) — the author's
    compilable structural RTL declaration is stronger evidence than a free-prose
    direction-proximity scrape. The finding is still PRINTED (a reviewer sees
    it), but rc is 0. (Pre-#770 this exited 1; #770 deliberately supersedes that:
    13 of the round5-7 iface FPs were exactly this prose-vs-RTL direction
    conflict where the RTL was correct.)"""
    (tmp_path / "spec.txt").write_text(
        "The input `serial_in` is used as the data source.")
    (tmp_path / "rtl.sv").write_text("module foo(output serial_in); endmodule")
    r = subprocess.run(
        [sys.executable, str(PROG),
         "--prompt", str(tmp_path / "spec.txt"),
         "--rtl", str(tmp_path / "rtl.sv"), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PORT-DIRECTION" in r.stdout and "ADVISORY" in r.stdout


def test_endstate_noleak_table_direction_reversal_strict_exit1(tmp_path):
    """ORGANIC #770 §4.05 NO-LEAK: a STRUCTURAL (markdown signal-table) direction
    the RTL contradicts MUST STILL hard-BLOCK under --strict (rc 1). The
    provenance relaxation applies ONLY to free-prose sources; a real table /
    given-code direction is high-confidence and keeps its veto."""
    (tmp_path / "spec.txt").write_text(
        "| Signal | Direction |\n|---|---|\n| `serial_in` | input |\n")
    (tmp_path / "rtl.sv").write_text("module foo(output serial_in); endmodule")
    r = subprocess.run(
        [sys.executable, str(PROG),
         "--prompt", str(tmp_path / "spec.txt"),
         "--rtl", str(tmp_path / "rtl.sv"), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PORT-DIRECTION" in r.stdout and "serial_in" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
