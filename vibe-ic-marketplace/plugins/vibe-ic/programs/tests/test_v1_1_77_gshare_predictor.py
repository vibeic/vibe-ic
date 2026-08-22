#!/usr/bin/env python3
"""Tests for programs/gshare_predictor_synth.py — the gshare branch-predictor
datapath deterministic SOLVER.

DECOMPOSITION + FLOOR (Prob153_gshare):
  The gshare datapath decomposes into (a) a global-history shift register of width
  H, (b) a PHT of 2**H K-bit saturating counters, (c) index = pc XOR history, (d)
  predict_taken = counter MSB, (e) saturating-clamp train + history shift + mispred
  recovery, (f) reset + train>predict precedence + predict-sees-pre-train-PHT
  bypass. EVERY one of (a)-(f-timing) is unambiguously stated by Prob153 EXCEPT the
  two host-OBSERVABLE reset VALUES (the K-bit PHT counter reset value and the H-bit
  history reset value). The prompt's only reset sentence is line 58: "Reset is
  asynchronous active-high." — it pins polarity/sync, NOT the values.

  This is a genuine §4.1 FLOOR, PROVEN two ways below:
    * host-observability: resetting the PHT to 2'b00 (SNT) or 2'b10 (LT) instead of
      2'b01 (LNT) yields 403 / 596 mismatches vs the golden ref (NOT zero), and
      resetting history to 7'h7f yields 47 — so the unstated values are load-bearing,
      not don't-cares. (recorded as constants here; reproduced live in the §4.05
      observability note in the solver docstring.)
    * narrowness: the SAME prompt with ONE sentence added stating the two reset
      values FIRES and the emitted datapath host-scores 0/1083 against the golden
      reference + golden testbench (test_floor_is_exactly_reset_values_*).

  So the solver SKIPs Prob153-as-written (honest AI-floor) and would FIRE+PASS the
  instant the reset values are disclosed. It NEVER hard-codes the 2'b01 / 0
  convention from the problem name — that would be the §4.05 leak.

§4.05 NO-LEAK negatives: >=5 boundary prompts, each one stated structural fact
removed from a complete (reset-value-disclosed) firing prompt, MUST return None.
A wrong branch predictor silently passes lint/synth — only the TB catches it.
"""
import os
import subprocess
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.normpath(os.path.join(_HERE, ".."))   # programs/ (solver dir)
sys.path.insert(0, _PROGRAMS)

import gshare_predictor_synth as G   # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

# Authoritative dataset (host-score gate). Tests that need it SKIP cleanly when the
# external benchmark tree or iverilog is absent (keeps CI green off the lab host).
_DS = str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl"))
_PROMPT = os.path.join(_DS, "Prob153_gshare_prompt.txt")
_REF = os.path.join(_DS, "Prob153_gshare_ref.sv")
_TB = os.path.join(_DS, "Prob153_gshare_test.sv")


def _have_dataset():
    return all(os.path.exists(p) for p in (_PROMPT, _REF, _TB))


def _have_iverilog():
    from shutil import which
    return which("iverilog") is not None and which("vvp") is not None


def _host_score(dut_sv: str):
    """Compile dut + golden ref + golden TB; return the integer mismatch count."""
    with tempfile.TemporaryDirectory() as td:
        dut = os.path.join(td, "dut.sv")
        with open(dut, "w") as f:
            f.write(dut_sv)
        vvp = os.path.join(td, "a.vvp")
        c = subprocess.run(["iverilog", "-g2012", "-o", vvp, dut, _REF, _TB],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"iverilog failed: {c.stderr}\n{dut_sv}"
        r = subprocess.run(["vvp", vvp], capture_output=True, text=True, timeout=60)
        out = r.stdout
        import re
        m = re.search(r"Total mismatched samples is (\d+)", out)
        assert m, f"no mismatch line in:\n{out}"
        return int(m.group(1))


# --------------------------------------------------------------------------- #
# A COMPLETE firing prompt = Prob153 structure + the two reset values disclosed.
# (Used to prove the FLOOR is exactly the reset values, and as the base from which
# each §4.05 negative removes ONE stated fact.)
# --------------------------------------------------------------------------- #
_RESET_SENTENCE = ("On reset, the PHT saturating counters reset to 2'b01 "
                   "(weakly not taken) and the global history register resets "
                   "to 0.")


def _complete_prompt():
    assert _have_dataset()
    base = open(_PROMPT, errors="replace").read().rstrip()
    return base + "\n\n" + _RESET_SENTENCE + "\n"


# --------------------------------------------------------------------------- #
# (1) The PROBLEM IS SOLVABLE — golden ref through the golden TB scores 0.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (_have_dataset() and _have_iverilog()),
                    reason="benchmark dataset / iverilog not present")
def test_golden_ref_is_solvable_through_tb():
    import re
    ref = open(_REF, errors="replace").read()
    dut = re.sub(r"\bmodule\s+RefModule\b", "module TopModule", ref)
    assert _host_score(dut) == 0


# --------------------------------------------------------------------------- #
# (2) Prob153 AS-WRITTEN -> FIRE via the OWNER-DIRECTED house defaults (2026-06-23).
#     The reset values are unstated; the owner chose the genre convention (predictor
#     counter -> weakly-not-taken 2'b01, history -> 0) as the documented house default
#     (open-benchmark §4 Category-G). The solver applies it (with a provenance comment)
#     and host-scores 0. (Was the §4.1 FLOOR before the owner set the default.)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _have_dataset(), reason="benchmark dataset not present")
def test_prob153_as_written_uses_house_defaults():
    txt = open(_PROMPT, errors="replace").read()
    # the prompt is still silent on the reset values...
    low = txt.lower()
    assert "2'b01" not in low and "counters reset to" not in low
    # ...yet the solver now FIRES, applying the documented house defaults + provenance.
    rtl = G.synth(txt, "TopModule")
    assert rtl is not None
    assert "weakly-not-taken 2'b01 (house default; spec silent)" in rtl
    assert "history register reset = 0 (house default; spec silent)" in rtl
    assert "pht[i] <= 2'd1;" in rtl and "history_r <= 7'd0;" in rtl


@pytest.mark.skipif(not (_have_dataset() and _have_iverilog()),
                    reason="benchmark dataset / iverilog not present")
def test_prob153_house_default_host_scores_zero():
    rtl = G.synth(open(_PROMPT, errors="replace").read(), "TopModule")
    assert rtl is not None and _host_score(rtl) == 0   # 0/1083 with the house defaults


# --------------------------------------------------------------------------- #
# (3) FLOOR is EXACTLY the reset values: disclose them -> FIRE + host-score 0.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (_have_dataset() and _have_iverilog()),
                    reason="benchmark dataset / iverilog not present")
def test_floor_is_exactly_reset_values_fire_and_pass():
    rtl = G.synth(_complete_prompt(), "TopModule")
    assert rtl is not None, "disclosing the reset values must let the solver FIRE"
    # pin the load-bearing structural lines (a subtly-wrong one passes lint/synth).
    assert "pht [0:127]" in rtl                       # (b) 2**7 entries
    assert "history_r ^" in rtl and "train_index" in rtl   # (c) XOR index
    assert "[1] :" in rtl or "pht[predict_index][1]" in rtl  # (d) MSB predict
    assert "pht[train_index] < 2'd3" in rtl           # (e) saturating clamp up
    assert "pht[train_index] > 2'd0" in rtl           # (e) saturating clamp down
    assert "{history_r[5:0]" in rtl                   # (e) history shift on predict
    assert "history_r <= {train_history[5:0], train_taken}" in rtl  # (e) recovery
    assert "2'd1" in rtl and "7'd0" in rtl            # the DISCLOSED reset values
    assert "posedge areset" in rtl                    # (f) async active-high reset
    assert _host_score(rtl) == 0                      # AUTHORITATIVE host gate


# --------------------------------------------------------------------------- #
# (4) host-OBSERVABILITY of the reset values (so the FLOOR is real, not a
#     don't-care). The disclosed-correct datapath scores 0; a counter-reset of
#     2'b00 / 2'b10 or a history-reset of 7'h7f scores NONZERO.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (_have_dataset() and _have_iverilog()),
                    reason="benchmark dataset / iverilog not present")
@pytest.mark.parametrize("pht_lit,hist_lit", [("2'd0", "7'd0"),
                                              ("2'd2", "7'd0"),
                                              ("2'd1", "7'd127")])
def test_wrong_reset_value_is_host_observable(pht_lit, hist_lit):
    rtl = G.synth(_complete_prompt(), "TopModule")
    assert rtl is not None
    wrong = rtl.replace("pht[i] <= 2'd1;", f"pht[i] <= {pht_lit};")
    wrong = wrong.replace("history_r <= 7'd0;", f"history_r <= {hist_lit};")
    assert wrong != rtl
    assert _host_score(wrong) > 0     # a wrong reset value is NOT a don't-care


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK negatives — each removes ONE stated fact from the complete prompt.
# --------------------------------------------------------------------------- #
def _base_complete_synthetic():
    """Self-contained complete gshare prompt (no dataset dependency) so the
    negatives run even off the lab host. The prose is single-line per sentence so
    each negative's `.replace()` of a removed fact is exact (no newline-wrap)."""
    ports = (
        " - input  clk\n"
        " - input  areset\n"
        " - input  predict_valid\n"
        " - input  predict_pc (7 bits)\n"
        " - output predict_taken\n"
        " - output predict_history (7 bits)\n"
        " - input  train_valid\n"
        " - input  train_taken\n"
        " - input  train_mispredicted\n"
        " - input  train_history (7 bits)\n"
        " - input  train_pc (7 bits)\n"
    )
    prose = (
        "Implement a gshare branch predictor with 7-bit pc and 7-bit global history, hashed using xor into a 7-bit index.\n"
        "This index accesses a 128-entry table of two-bit saturating counters.\n"
        "The predictor contains a 7-bit global branch history register.\n"
        "There are two interfaces: one for predictions and one for training.\n"
        "When predict_valid=1 the predictor produces the predicted branch direction and the state of the branch history register used; the branch history register is then updated at the next positive clock edge for the predicted branch.\n"
        "When train_valid=1 update the pattern history table saturating counter toward the outcome; if the branch being trained is mispredicted, recover the branch history register.\n"
        "If training for a misprediction and a prediction occur in the same cycle, training takes precedence.\n"
        "If training and prediction of the same PHT entry happen at the same time, the prediction sees the PHT state before training because training only modifies the PHT at the next positive clock edge.\n"
        "Reset is asynchronous active-high.\n"
        "On reset the PHT counters reset to 2'b01 and the global history register resets to 0.\n"
    )
    return ports + "\n" + prose


def test_complete_synthetic_fires():
    # sanity: the self-contained complete prompt FIRES (so each negative below
    # isolates exactly the removed fact).
    assert G.synth(_base_complete_synthetic(), "TopModule") is not None


_BASE = _base_complete_synthetic()

def _require_removed(s_before, s_after, marker):
    """Guard: each negative must actually CHANGE the prompt (a stale replace target
    that silently no-ops would make a negative pass for the wrong reason)."""
    assert s_before != s_after, f"negative '{marker}' did not change the prompt"
    return s_after


NEGATIVES = {
    # NOTE (2026-06-23, owner-directed): a MISSING reset VALUE is no longer a SKIP —
    # the solver applies the house default (PHT -> weakly-not-taken 2'b01, history ->
    # 0). Those two former negatives are now covered as a POSITIVE
    # (test_prob153_as_written_uses_house_defaults). The §4.05 negatives below remove a
    # STRUCTURAL fact (saturating-ness / XOR index / precedence / bypass / reset
    # polarity), which still SKIPs — a structural guess WOULD be a leak.
    # 3. counter saturating-ness removed (plain counter, not saturating) -> the
    #    clamp + MSB-predict convention no longer holds.
    "no_saturating":
        _require_removed(_BASE, _BASE.replace("two-bit saturating counters", "two-bit counters")
             .replace("saturating counter toward", "counter toward"), "no_saturating"),
    # 4. the XOR index removed (no longer gshare-hashed).
    "no_xor_index":
        _require_removed(_BASE, _BASE.replace(
            "hashed using xor into a 7-bit index", "used directly as a 7-bit index"), "no_xor_index"),
    # 5. train-vs-predict precedence removed (same-cycle history collision unstated).
    "no_train_precedence":
        _require_removed(_BASE, _BASE.replace(
            "training takes precedence", "the result is unspecified"), "no_train_precedence"),
    # 6. predict-sees-pre-train-PHT bypass removed.
    "no_pretrain_bypass":
        _require_removed(_BASE, _BASE.replace(
            "the prediction sees the PHT state before training because training only modifies the PHT at the next positive clock edge",
            "the ordering is unspecified"), "no_pretrain_bypass"),
    # 7. reset polarity/sync ambiguous (no "asynchronous/synchronous active-high").
    "ambiguous_reset_timing":
        _require_removed(_BASE, _BASE.replace(
            "Reset is asynchronous active-high.", "There is a reset."), "ambiguous_reset_timing"),
}


@pytest.mark.parametrize("name", sorted(NEGATIVES))
def test_no_leak_negative_skips(name):
    assert G.synth(NEGATIVES[name], "TopModule") is None, \
        f"§4.05 LEAK: {name} should SKIP (a stated fact is missing) but FIRED"


# --------------------------------------------------------------------------- #
# Non-gshare prompts must never fire (the shape gate is structure-based, not name).
# --------------------------------------------------------------------------- #
def test_non_gshare_does_not_fire():
    for p in (
        "Implement a 4-bit up counter with synchronous active-high reset.",
        " - input clk\n - output q\nA shift register with four D flops.",
        "A 2-bit saturating counter that increments on inc and clamps at 3.",  # no PHT/predict/train
    ):
        assert G.synth(p, "TopModule") is None


# --------------------------------------------------------------------------- #
# Generality: a different H (4-bit) + sync active-low reset + 16-entry PHT FIRES,
# proving the solver parses STATED structure, not the Prob153 name.
# --------------------------------------------------------------------------- #
def test_generality_different_width_and_reset_kind():
    P = _base_complete_synthetic()
    P = (P.replace("(7 bits)", "(4 bits)")
          .replace("7-bit pc", "4-bit pc").replace("7-bit global history", "4-bit global history")
          .replace("7-bit index", "4-bit index").replace("128-entry", "16-entry")
          .replace("7-bit global branch history register", "4-bit global branch history register")
          .replace("Reset is asynchronous active-high.", "Reset is synchronous active-low."))
    assert "synchronous active-low" in P and "asynchronous" not in P
    rtl = G.synth(P, "TopModule")
    assert rtl is not None
    assert "pht [0:15]" in rtl                    # 2**4 entries
    assert ", negedge areset" not in rtl and ", posedge areset" not in rtl  # synchronous
    assert "if (~areset)" in rtl                  # sync active-low condition


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
