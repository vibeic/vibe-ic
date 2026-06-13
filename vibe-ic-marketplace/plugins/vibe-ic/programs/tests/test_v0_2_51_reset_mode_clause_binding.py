"""v0.2.51 reset-mode clause-binding regressions.

Pins the #421 fix (ORGANIC-20260606-reset-mode-dual-keyword-false-positive):
a spec sentence of the form "asynchronous positive edge triggered <reset>,
synchronous active high signals <load>, and <enable>" declares an ASYNC reset
plus SYNC non-reset controls in ONE sentence. Two compounding root causes:

  1. the legacy splitter treated EVERY newline as a sentence boundary
     (`(?<=[.\\n])`) — a hard line-wrap falling between "asynchronous" and its
     reset token left the reset-bearing line carrying only the OTHER signals'
     "synchronous";
  2. detection was sentence-scoped keyword presence, not proximity-bound to
     the reset token, so the other signals' qualifier could win.

Fix in `_specrtl_common._detect_reset`: soft-unwrap hard line-wraps, then bind
the mode/polarity keyword to the CLAUSE (comma/semicolon segment) containing
the reset token; token-bound async phrases ("edge triggered <rst>", "rising
edge of <rst>", POR) out-rank floating sentence-scope keywords; the legacy
sentence-scope logic stays as the final fallback.

Corpus arbitration (acceptance evidence): old-vs-new diff over ALL 455
prompts of the three local datasets produced 19 diffs, every one moving
TOWARD the golden reference RTL's real reset structure (18 confirmed by the
golden ref, 1 with no ref reset structure but consistent with the prompt);
ZERO regressions (2026-06-06).

chip-AGNOSTIC: fixtures use generic TopModule/clk/areset/load/ena shapes only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _specrtl_common import _detect_reset, extract_spec_contract, parse_rtl_ports, strip_comments  # noqa: E402
import spec_conformance_check as scc  # noqa: E402


# the filed failure shape, with the hard line-wrap EXACTLY where the audited
# campaign's prompt wrapped it (between "positive" and "edge"): the legacy
# newline-split divorced "asynchronous" from the reset-bearing line.
_DUAL_WRAPPED = ("Build a 4-bit shift register (right shift), with asynchronous positive\n"
                 "edge triggered areset, synchronous active high signals load, and enable.\n")
_DUAL_UNWRAPPED = ("The module has asynchronous positive edge triggered areset, "
                   "synchronous active high signals load, and enable.")
# the sibling wrap (qualifier and token on the SAME line) that already worked
_DUAL_WRAP_V2 = ("The module should implement a 4-bit shift register (right shift), with\n"
                 "asynchronous positive edge triggered areset, synchronous active high\n"
                 "signals load, and enable.\n")


def test_dual_mode_sentence_hard_wrapped_resolves_async():
    mode, pol, sig = _detect_reset(_DUAL_WRAPPED)
    assert mode == "asynchronous"
    assert sig == "areset"


def test_dual_mode_sentence_unwrapped_resolves_async():
    assert _detect_reset(_DUAL_UNWRAPPED)[0] == "asynchronous"


def test_dual_mode_sentence_same_line_wrap_still_async():
    assert _detect_reset(_DUAL_WRAP_V2)[0] == "asynchronous"


def test_edge_triggered_phrase_outranks_floating_sync_keyword():
    # NO explicit "asynchronous" word — the reset's own qualifier is the
    # token-bound "positive edge triggered" phrase; "synchronous" belongs to
    # load/enable and must not win.
    s = ("Build a counter with positive edge triggered areset, synchronous "
         "active high signals load, and enable.")
    assert _detect_reset(s)[0] == "asynchronous"


def test_polarity_clause_binding():
    # active-low shares the reset clause; "active high" qualifies load/ena
    s = "Use an active-low reset rst_n, active high load and ena."
    assert _detect_reset(s)[1] == "active-low"


# ── legacy single-qualifier shapes must resolve exactly as before ──────────

def test_single_mode_sync_unchanged():
    mode, pol, _ = _detect_reset("The FSM has a synchronous active-high reset named r.")
    assert (mode, pol) == ("synchronous", "active-high")


def test_single_mode_async_unchanged():
    mode, pol, _ = _detect_reset("Use an asynchronous active-low reset rst_n.")
    assert (mode, pol) == ("asynchronous", "active-low")


def test_comma_separated_qualifier_list_still_resolves():
    # qualifier in its own clause, no other signal competes — fallback rescues
    mode, pol, _ = _detect_reset("Asynchronous, active-high reset clears the counter.")
    assert (mode, pol) == ("asynchronous", "active-high")


def test_registered_to_clock_phrase_unchanged():
    assert _detect_reset("The reset is registered to the clock.")[0] == "synchronous"


def test_no_reset_prose_unchanged():
    assert _detect_reset("A purely combinational adder.") == (None, None, None)


def test_areset_now_detected_as_signal_name():
    assert _detect_reset("Resets to zero via areset.")[2] == "areset"


# ── end-to-end: the false ERROR is gone; the true positive stays ──────────

_ASYNC_RTL = ("module TopModule(input clk, input areset, input load, input ena,\n"
              "                 input [3:0] data, output reg [3:0] q);\n"
              "  always @(posedge clk or posedge areset)\n"
              "    if (areset) q <= 4'b0;\n"
              "    else if (load) q <= data;\n"
              "    else if (ena) q <= {1'b0, q[3:1]};\n"
              "endmodule\n")
_SYNC_RTL = _ASYNC_RTL.replace("posedge clk or posedge areset", "posedge clk")

_SPEC = ("Build a 4-bit shift register (right shift), with asynchronous positive\n"
         "edge triggered areset, synchronous active high signals load, and enable.\n\n"
         " - input  clk\n - input  areset\n - input  load\n - input  ena\n"
         " - input  data (4 bits)\n - output q (4 bits)\n")


def _mismatch_findings(rtl: str):
    spec = extract_spec_contract(_SPEC, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=_SPEC)
    return [f for f in fs if f.rule == "reset-mode-spec-mismatch"]


def test_spec_faithful_async_rtl_no_false_mismatch():
    assert _mismatch_findings(_ASYNC_RTL) == []


def test_sync_rtl_against_async_spec_still_flagged():
    fs = _mismatch_findings(_SYNC_RTL)
    assert [f.severity for f in fs] == ["ERROR"]
    assert "spec says asynchronous" in fs[0].message
