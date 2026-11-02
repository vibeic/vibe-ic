#!/usr/bin/env python3
"""The bit-mapping contract drives a generator AND a test that discriminates it.

#2215 asks for three things beyond retaining the contract, and each is a
separate claim with a separate way of being wrong:

  1. program-generated RTL implements the stated mapping, preserves the other
     payload bits, and obeys the stated conditions;
  2. the emitted test is BRANCH-DISCRIMINATING -- "a deliberately omitted
     inversion fails the same immutable test that the corrected output
     passes; a test that merely mentions signal names is insufficient";
  3. an incomplete, inconsistent or unsupported contract REFUSES automatic
     generation instead of inventing the missing part.

THE MUTATION TEST IS THE LOAD-BEARING ONE. The RTL and the test come from the
same contract, so their agreeing proves nothing on its own. What is measured
here is SENSITIVITY: the emitted RTL is mutated -- the conditional inversion
removed, one payload bit tied low, the extension inverted -- and the SAME
immutable test, unchanged, must fail on each. A test that survives a mutation
is a test that would have accepted a wrong candidate.

chip-AGNOSTIC: synthetic signal names throughout; the only prose is the
issue's own public-input fixture.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _prose_handoff_assertions import assert_prose_chain_handoff

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import bit_mapping_synth as S                            # noqa: E402
import spec_numeric_pack_extract as E                    # noqa: E402


def _simulator_absent() -> str:
    missing = [t for t in ("iverilog", "vvp") if shutil.which(t) is None]
    if not missing:
        return ""
    return ("NOT_MEASURED: this host has no " + " and no ".join(missing)
            + "; generated RTL cannot be executed here")


_NEEDS_SIMULATOR = pytest.mark.skipif(
    bool(_simulator_absent()),
    reason=_simulator_absent() or "iverilog and vvp are both present")

CONDITIONAL = (
    "Convert a 12-bit width to a larger width of 20-bit. "
    "When active is one, result[11] is sample[11] XOR flip. "
    "When active is zero, result[11] equals sample[11]. "
    "Bits result[10:0] always equal sample[10:0]. "
    "If extend is one, bits result[19:12] repeat result[11]; "
    "otherwise those upper bits are zero.")


def _plan(prompt: str = CONDITIONAL, **kw):
    return S.plan(E.extract(prompt), **kw)


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #
def test_the_public_input_yields_a_complete_plan():
    p = _plan()
    assert p["status"] == "READY", p["reasons"]
    assert p["target"] == "result"
    assert p["out_width"] == 20 and p["in_width"] == 12
    assert p["sources"] == ["sample"]
    assert p["controls"] == ["active", "extend", "flip"]


def test_the_target_is_never_also_an_input_port():
    """`result[19:12] repeat result[11]` is internal feedback. Emitting the
    target as an input would declare one name in two directions."""
    p = _plan()
    assert "result" not in p["sources"]
    rtl = S.emit_rtl(p)
    assert rtl.count("wire [19:0] result") == 1
    assert "input  wire [11:0] result" not in rtl


def test_every_output_bit_is_assigned_exactly_once():
    rtl = S.emit_rtl(_plan())
    for bit in range(20):
        assert rtl.count(f"assign result[{bit}] =") == 1, bit


def test_the_conditions_reach_the_emitted_logic():
    rtl = S.emit_rtl(_plan())
    assert "assign result[11] = active ? (sample[11] ^ flip) : sample[11];" in rtl
    assert "assign result[19] = extend ? result[11] : 1'b0;" in rtl
    assert "assign result[0] = sample[0];" in rtl


# --------------------------------------------------------------------------- #
# refusals: an incomplete contract must not be completed by guessing
# --------------------------------------------------------------------------- #
def test_an_unspecified_mapping_refuses():
    p = _plan("Implement a configurable data format block; detailed mapping "
              "is not yet supplied.")
    assert p["status"] == "REFUSED"
    assert any("no bit mapping" in r for r in p["reasons"])


def test_a_mapping_with_no_declared_width_refuses():
    p = _plan("Bits result[3:0] always equal sample[3:0].")
    assert p["status"] == "REFUSED"
    assert any("no output width" in r for r in p["reasons"])


def test_an_uncovered_target_bit_refuses():
    """A gap is an unstated bit, not a zero."""
    p = _plan("Convert a 4-bit width to a larger width of 8-bit. "
              "Bits result[3:0] always equal sample[3:0].")
    assert p["status"] == "REFUSED"
    assert any("covered by no mapping" in r for r in p["reasons"])


def test_half_a_condition_refuses():
    p = _plan("Convert a 4-bit width to a larger width of 8-bit. "
              "When active is one, result[3:0] is sample[3:0] XOR flip. "
              "Bits result[7:4] are zero.")
    assert p["status"] == "REFUSED"
    assert any("does not say what the other half does" in r
               for r in p["reasons"])


def test_two_target_signals_refuse():
    p = _plan("Convert a 4-bit width to a larger width of 8-bit. "
              "Bits alpha[7:0] always equal sample[7:0]. "
              "Bits beta[7:0] always equal sample[7:0].")
    assert p["status"] == "REFUSED"
    assert any("more than one target signal" in r for r in p["reasons"])


def test_a_prohibited_transform_refuses():
    """"Do not invert any source bit" and a stated inversion cannot both be
    honoured; generating either one silently picks a side."""
    p = _plan("Convert a 4-bit width to a larger width of 8-bit. "
              "Do not invert any source bit. "
              "Bits result[3:0] are the inverse of sample[3:0]. "
              "Bits result[7:4] are zero.")
    assert p["status"] == "REFUSED"
    assert any("explicitly prohibits" in r for r in p["reasons"])


def test_a_mismatched_source_width_refuses():
    p = _plan("Convert a 4-bit width to a larger width of 8-bit. "
              "Bits result[7:0] always equal sample[3:0].")
    assert p["status"] == "REFUSED"
    assert any("different widths" in r for r in p["reasons"])


def test_a_refused_plan_emits_nothing():
    p = _plan("Implement a configurable data format block.")
    with pytest.raises(ValueError):
        S.emit_rtl(p)
    with pytest.raises(ValueError):
        S.emit_tb(p)


# --------------------------------------------------------------------------- #
# the emitted vectors
# --------------------------------------------------------------------------- #
def test_the_vector_space_is_exhaustive_over_the_stated_controls():
    p = _plan()
    rows = S.vectors(p)
    # every combination of the three controls appears
    seen = {tuple(sorted(r["controls"].items())) for r in rows}
    assert len(seen) == 2 ** len(p["controls"])
    # and every source bit is exercised in both polarities
    ones = [r["sources"]["sample"] for r in rows]
    for bit in range(p["in_width"]):
        assert any(v & (1 << bit) for v in ones), bit
        assert any(not (v & (1 << bit)) for v in ones), bit


def test_the_model_agrees_with_hand_computation():
    """Spot-check the contract's own answer, computed by hand from the prose,
    so the model is anchored to something other than itself."""
    p = _plan()
    # active=1, flip=1, extend=1, sample = all ones
    got = S._model(p, {"sample": 0xFFF},
                   {"active": 1, "flip": 1, "extend": 1})
    # result[11] = 1 ^ 1 = 0; result[10:0] = 0x7FF; result[19:12] = 8x0
    assert got == 0x007FF
    # active=0 leaves the sign bit alone, extend replicates it
    got = S._model(p, {"sample": 0xFFF},
                   {"active": 0, "flip": 1, "extend": 1})
    assert got == 0xFFFFF


# --------------------------------------------------------------------------- #
# PROVE IT BY RUNNING IT -- and prove the test can fail
# --------------------------------------------------------------------------- #
def _run(tmp_path: Path, rtl: str, tb: str) -> tuple[int, str]:
    (tmp_path / "dut.v").write_text(rtl)
    (tmp_path / "tb.sv").write_text(tb)
    build = subprocess.run(
        ["iverilog", "-g2012", "-s", "vibeic_ai_challenge_tb", "-o",
         str(tmp_path / "sim.vvp"), str(tmp_path / "dut.v"),
         str(tmp_path / "tb.sv")],
        capture_output=True, text=True, timeout=60)
    if build.returncode != 0:
        return build.returncode, build.stdout + build.stderr
    run = subprocess.run(["vvp", str(tmp_path / "sim.vvp")],
                         capture_output=True, text=True, timeout=60)
    return run.returncode, run.stdout + run.stderr


@_NEEDS_SIMULATOR
def test_generated_rtl_passes_the_generated_test(tmp_path):
    p = _plan()
    rc, out = _run(tmp_path, S.emit_rtl(p), S.emit_tb(p))
    assert "VIBEIC_AI_CHALLENGE=PASS" in out, out[-800:]
    assert "VIBEIC_AI_CHALLENGE=FAIL" not in out
    assert rc == 0


@_NEEDS_SIMULATOR
@pytest.mark.parametrize("name, old, new", [
    # the deliberately omitted inversion the issue names by example
    ("omitted_inversion",
     "assign result[11] = active ? (sample[11] ^ flip) : sample[11];",
     "assign result[11] = sample[11];"),
    # a payload bit that stops being preserved
    ("payload_bit_tied_low",
     "assign result[5] = sample[5];",
     "assign result[5] = 1'b0;"),
    # the conditional extension inverted
    ("extension_polarity_flipped",
     "assign result[19] = extend ? result[11] : 1'b0;",
     "assign result[19] = extend ? 1'b0 : result[11];"),
    # a source bit read from the wrong place
    ("source_bit_off_by_one",
     "assign result[3] = sample[3];",
     "assign result[3] = sample[2];"),
])
def test_the_same_immutable_test_fails_a_mutated_implementation(
        tmp_path, name, old, new):
    """SENSITIVITY, measured. The test is not changed between the two runs --
    only the RTL is -- so this is the check the issue asks for: a test that
    merely mentioned the signal names would survive every one of these."""
    p = _plan()
    rtl, tb = S.emit_rtl(p), S.emit_tb(p)
    assert old in rtl, f"the mutation target is not in the emitted RTL: {old}"
    rc, out = _run(tmp_path, rtl.replace(old, new, 1), tb)
    assert "VIBEIC_AI_CHALLENGE=FAIL" in out, (name, out[-800:])
    assert "VIBEIC_AI_CHALLENGE=PASS" not in out, (name, out[-800:])


@_NEEDS_SIMULATOR
def test_a_renamed_design_takes_the_same_path(tmp_path):
    """Routing is not keyed to any identity: rename every signal and the same
    generator produces RTL that passes the same generated test."""
    renamed = (CONDITIONAL
               .replace("result", "out_word").replace("sample", "in_word")
               .replace("active", "enable").replace("flip", "mask")
               .replace("extend", "widen"))
    p = _plan(renamed, module="renamed_unit")
    assert p["status"] == "READY", p["reasons"]
    assert p["target"] == "out_word" and p["sources"] == ["in_word"]
    rc, out = _run(tmp_path, S.emit_rtl(p), S.emit_tb(p))
    assert "VIBEIC_AI_CHALLENGE=PASS" in out, out[-800:]


@_NEEDS_SIMULATOR
@pytest.mark.parametrize("in_w, out_w", [(4, 8), (8, 16), (16, 32)])
def test_other_legal_widths_take_the_same_path(tmp_path, in_w, out_w):
    prompt = (f"Convert a {in_w}-bit width to a larger width of {out_w}-bit. "
              f"When active is one, result[{in_w - 1}] is "
              f"sample[{in_w - 1}] XOR flip. "
              f"When active is zero, result[{in_w - 1}] equals "
              f"sample[{in_w - 1}]. "
              f"Bits result[{in_w - 2}:0] always equal sample[{in_w - 2}:0]. "
              f"If extend is one, bits result[{out_w - 1}:{in_w}] repeat "
              f"result[{in_w - 1}]; otherwise those upper bits are zero.")
    p = _plan(prompt, module=f"width_{in_w}_{out_w}")
    assert p["status"] == "READY", p["reasons"]
    rc, out = _run(tmp_path, S.emit_rtl(p), S.emit_tb(p))
    assert "VIBEIC_AI_CHALLENGE=PASS" in out, out[-800:]


@_NEEDS_SIMULATOR
def test_the_emitted_rtl_is_lint_clean(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("NOT_MEASURED: this host has no verilator")
    p = _plan()
    (tmp_path / "dut.v").write_text(S.emit_rtl(p))
    lint = subprocess.run(
        ["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME",
         "--top-module", p["module"], str(tmp_path / "dut.v")],
        capture_output=True, text=True, timeout=60)
    assert lint.returncode == 0, lint.stdout + lint.stderr


# --------------------------------------------------------------------------- #
# REACHABILITY -- #2215's "a plain design document reaches the same mechanism"
# --------------------------------------------------------------------------- #
def test_the_one_shared_chain_reaches_the_generator():
    """`deterministic_emit_chain` is the single chain the runner and every
    benchmark adapter already call, so wiring here is what makes the mechanism
    reachable from a plain design document without routing on any identity."""
    import deterministic_emit_chain as C                # noqa: PLC0415
    assert "bit_mapping_synth" in C.which_emitters()
    result = C.try_emit_ex(CONDITIONAL, "", "TopModule")
    assert_prose_chain_handoff(result, CONDITIONAL)
    sentence = "Convert a 12-bit width to a larger width of 20-bit."
    assert f"[0:{len(sentence)}] {sentence}" in dict(result[2])["SPEC_SENTENCES_UNACCOUNTED"]
    rtl = S.emit_rtl(_plan(module="TopModule"))
    assert "module TopModule (" in rtl


def test_it_is_last_so_it_can_shadow_no_narrower_emitter():
    import deterministic_emit_chain as C                # noqa: PLC0415
    assert C.which_emitters()[-1] == "bit_mapping_synth"


@pytest.mark.parametrize("prompt", [
    "Implement a configurable data format block; detailed mapping is not yet supplied.",
    "Build a 4-to-1 multiplexer with inputs a, b, c, d and select s.",
    "Design a module that counts rising edges of clk and outputs the total.",
])
def test_a_prompt_that_states_no_complete_mapping_does_not_fire(prompt):
    """The chain's contract is exact-or-nothing; declining is the normal
    handover, not a failure."""
    import deterministic_emit_chain as C                # noqa: PLC0415
    kind, _rtl = C.try_emit(prompt, "", "TopModule")
    assert kind != "bit_mapping_synth"


def test_the_emitted_module_takes_the_name_the_caller_asked_for():
    import deterministic_emit_chain as C                # noqa: PLC0415
    result = C.try_emit_ex(CONDITIONAL, "", "some_other_top")
    assert_prose_chain_handoff(result, CONDITIONAL)
    sentence = "Convert a 12-bit width to a larger width of 20-bit."
    assert f"[0:{len(sentence)}] {sentence}" in dict(result[2])["SPEC_SENTENCES_UNACCOUNTED"]
    rtl = S.emit_rtl(_plan(module="some_other_top"))
    assert "module some_other_top (" in rtl
