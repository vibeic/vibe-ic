"""v1.1.35 — PR #31 Step-2.7 §4.05 remediation: the lone-function-word-port
rescue must drop the MULTI-LETTER conjunctions/articles (never genuine ports)
WITHOUT false-SKIPping a genuine single-char port `a`.

PR #31 narrowed the ORGANIC #770 function-word drop with `and t.strip()` so a
lone `- input a` (genuine 1-bit port) is rescued. The Step-2.7 review reproduced
a MED §4.05 FALSE-FIRE: `_NL_PORT` is line-anchored (`tail=[^\\n]*`), so a prose
sentence that WRAPS right after a function word presented an EMPTY same-line tail
and was wrongly rescued as a phantom port —

    - Input and
      output ports adhere to standard conventions.  -> phantom 'and'
    - Input a
      stream of 8-bit samples to be filtered.        -> phantom 'a'

The STRUCTURAL discriminator is `len(name) > 1`: of the function-word set, only
the single-char article `a` is a plausible 1-bit port name; the multi-letter
conjunctions/articles (and/or/nor/but/plus/with/the/an) are NEVER genuine ports
(and/or/nor are reserved keywords), so they drop whether bare (`- input or`) or
wrapped (`- Input and⏎ …`).

The single-char `a` is IRREDUCIBLE: `- Input a⏎  stream of samples` (prose) and
`- input a⏎  the primary data input` (a genuine port `a` with a wrapped
description) are STRUCTURALLY IDENTICAL — same name, empty same-line tail, bare
indented continuation. A first remediation (a `followed_by_prose` next-line
probe) dropped BOTH, which a Step-2.7 re-review proved is a §4.05 FALSE-SKIP (a
genuine lone `- input a` followed by its own description / a sibling `Outputs:`
heading vanished from the spec contract → RTL omitting port `a` would pass
unflagged). §4.05 ranks a false-SKIP (mask a real defect) STRICTLY WORSE than a
false-FIRE (a human-dismissable spurious port-missing), so the single-char `a`
ambiguity resolves toward RESCUE — `a` is kept whenever its same-line tail is
empty. This test PINS that resolution: multi-letter wraps drop; the genuine `a`
port (lone, with-description, before-heading) is never dropped.
chip-AGNOSTIC: pure English function-word grammar + identifier plausibility.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _specrtl_common as S  # noqa: E402


def _names(text):
    return [p.name for p in S._parse_nl_ports(text)]


# ── MULTI-LETTER function words drop, bare OR line-wrapped (never genuine ports)
@pytest.mark.parametrize("text", [
    "- Input an\n  address used to index the register file.",
    "- Input and\n  output ports adhere to standard synchronous conventions.",
    "- Input or\n  the result is forwarded to the next pipeline stage.",
    "- Input the\n  last value is held until the next load strobe.",
    "- input an",
    "- input or",
    "- input and",
    "- input nor",
])
def test_multiletter_function_word_drops_bare_and_wrapped(text):
    assert _names(text) == [], \
        f"multi-letter function word is grammar, not a port — must drop: {text!r}"


# ── §4.05 NO FALSE-SKIP: a GENUINE single-char port `a` is NEVER dropped ───────
# These are the exact shapes the re-review reproduced as a false-SKIP under the
# rejected `followed_by_prose` probe; here every one must KEEP `a`.
@pytest.mark.parametrize("text,kept", [
    ("- input a\n- output b", {"a", "b"}),                       # next line a bullet
    ("- input a", {"a"}),                                        # EOF
    ("- input a\n\nThe core sums the inputs.", {"a"}),           # blank-sep prose
    ("- input a\n  the primary data input", {"a"}),             # OWN wrapped description
    ("- input a\nOutputs:", {"a"}),                              # sibling heading
    ("Module ports:\n- input a\n  one of the two operands\n- input b\n- output q",
     {"a", "b", "q"}),                                           # VerilogEval-style
    ("Interface:\n - input  clock\n - input  a\n - output q\n", {"clock", "a", "q"}),
])
def test_genuine_single_char_port_a_never_false_skipped(text, kept):
    assert kept <= set(_names(text)), \
        f"genuine port(s) {kept} must survive (no §4.05 false-SKIP): {text!r} -> {_names(text)}"


def test_genuine_port_a_with_description_end_to_end_no_false_skip():
    """A genuine `- input a` carrying a wrapped description must stay in the spec
    contract so spec_conformance can still flag RTL that OMITS it."""
    spec = (
        "## Ports\n"
        "- output q\n"
        "- input a\n"
        "  the serial data input, sampled on the rising clk edge\n"
        "Behavior:\n"
        "q is a registered copy of a.\n")
    names = set(_names(spec))
    assert "a" in names, f"genuine port 'a' must not be dropped from the contract: {names}"


# ── #770/#785 single-line prose is unaffected (no-leak still holds) ────────────
@pytest.mark.parametrize("text", [
    "- Input and output signals adhere to the AXI Stream protocol.",
    "- Input or the result is forwarded to the next stage",
    "- the register holds the last computed value",
    "- Input a data stream is divided into pairs",
    "- Output latency is 1 cycle",
    "- Input ports:",
])
def test_single_line_770_785_prose_still_dropped(text):
    assert _names(text) == [], f"#770/#785 prose must stay dropped: {text!r}"


# ── width anchor still rescues even a multi-letter function-word port ──────────
def test_width_anchor_rescues_regardless_of_name():
    assert _names("- input a (8 bits)") == ["a"]
    assert _names("- input an (1 bit)") == ["an"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
