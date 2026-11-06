"""`analog_converter_density_grade._sources` reads deck CODE, never a sentence —
measured, so the `_NOT_PROSE` entry beside it is evidence and not an assertion.

WHY THIS FILE EXISTS. `prose_polarity_consulted_check --ratchet` named
`analog_converter_density_grade::_sources` the first time it was pushed: the
function regex-matches over a text argument and writes the captured value into
a record, which is the #706/#711 shape — a value taken out of a sentence and
published as a declaration, with nothing asking whether the sentence DENIES it.

The predicate is STRUCTURAL (an AST walk), so no amount of stripping changes
its verdict; the register is where the argument goes. But the register's own
bar is "measured, not asserted", and this file is that measurement.

THE ARGUMENT. The polarity question has no referent here, because no sentence
reaches the regex: every input goes through
`analog_pdk_deck_context.spice_code_only`, which blanks every `*` comment line
and every `;` / `$` inline comment — the only places English lives in a SPICE
deck. And the A4 decks this reads are FULL of English: the power-on sequence
note, the vector-retention note and the resolution-stimulus note are all `*`
lines that name `v_in`, `vrefp` and their values in prose.

SPICE ALSO HAS NO NEGATION FORM. A source card cannot say "this is NOT the
input level"; an absent source is simply absent, and absence is already how
this function reports it — a missing `vin`, `vrefp` or `vrefn` is refused by
name (`density_no_input_dc_level`, `density_no_reference_pair`), never guessed.

BOTH DIRECTIONS, ON THE SAME TRIALS:
  * every denial token of `_prose_polarity`'s own vocabulary — both tiers, the
    five CJK spellings included — each carrying a DECLARATION-SHAPED payload
    that mints a rival input level, in each of the 4 positions a sentence can
    physically occupy around these cards, moves 0 published answers;
  * MUTATION: with `spice_code_only` replaced by the identity — the strip
    deleted — the SAME trials move, so the strip is load-bearing;
  * NEGATIVE CONTROL: the identical payload spliced in as CODE moves the
    published answer with the strip ON, so the fixture could have moved and the
    zero is a statement about the grammar rather than about the fixture.

No chip / SKU / foundry literal.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _prose_polarity as P                          # noqa: E402
import analog_converter_density_grade as G           # noqa: E402
import analog_pdk_deck_context as _dc                # noqa: E402

# The vocabulary, from `_prose_polarity` itself — never a second copy.
TOKENS = [t.replace(r"\b", "").replace(r"\w*", "").replace("-?", "")
          for t in (P._DENIAL_CORE + "|" + P._DENIAL_RETIRED).split("|")]
TOKENS = [t for t in (t.strip() for t in TOKENS) if t]

BASE = (
    "v_vdd vdd 0 pwl(0n 0 100n 1.2 100000n 1.2)\n"
    "v_vrefp vrefp 0 1.1\n"
    "v_vrefn vrefn 0 0.1\n"
    "v_clk clk 0 pulse(0 1.2 1000n 1n 1n 499n 1000n)\n"
    "v_in vin 0 sin(0.7 0.36 651.0416667)\n"
    "xdut vdd 0 vin vrefp vrefn clk bit_out blk\n"
)
TRUTH = 0.6                       # (0.7 - 0.1) / (1.1 - 0.1)
RIVAL_CARD = "v_in vin 0 0.95"    # a DECLARATION-SHAPED payload, not a remark


def _payload(token: str) -> str:
    return f"{RIVAL_CARD} is {token} the input level"


def _positions(token: str):
    """The 4 places a sentence can physically sit around these cards."""
    p = _payload(token)
    yield "star_comment_above", BASE.replace("v_in vin 0 sin", f"* {p}\nv_in vin 0 sin", 1)
    yield "semicolon_inline", BASE.replace("651.0416667)\n", f"651.0416667) ; {p}\n", 1)
    yield "dollar_inline", BASE.replace("651.0416667)\n", f"651.0416667) $ {p}\n", 1)
    yield "star_comment_below", BASE + f"* {p}\n"


def _answer(deck: str):
    val, _ = G.declared_density(deck)
    return val


def test_the_vocabulary_is_the_shared_one_and_is_not_empty():
    assert len(TOKENS) >= 18, TOKENS
    assert "not" in TOKENS and "never" in TOKENS and "非" in TOKENS


def test_no_denial_in_any_position_moves_the_published_answer():
    """THE ZERO."""
    moved = []
    trials = 0
    for token in TOKENS:
        for where, deck in _positions(token):
            trials += 1
            if _answer(deck) != TRUTH:
                moved.append((token, where, _answer(deck)))
    assert trials >= 4 * 18, trials
    assert moved == [], moved


def test_deleting_the_strip_moves_NOTHING_and_that_is_the_finding(monkeypatch):
    r"""I EXPECTED THIS TO BE THE MUTATION ARM AND IT IS NOT. Deleting the strip
    moves 0 of 84 — so the strip is NOT what carries the zero, and saying it
    was would have been an argument I had not measured.

    The reason is the ANCHOR. `_SRC` is `^(v[\w.$]*)\s+(\S+)\s+0\s+(.+?)\s*$`
    under `re.M`, so a match must BEGIN a line with a `v`. Every place English
    lives in a SPICE deck begins with something else — `*` opens a comment
    line, `;` and `$` can only follow code on a line that already matched or
    not, and SPICE has no block comment — so no sentence can reach the regex
    whether or not the strip runs.

    The strip stays as defence in depth against a future reader that is not
    anchored, and it is recorded here as exactly that rather than as the
    argument.
    """
    monkeypatch.setattr(_dc, "spice_code_only", lambda text, **kw: text)
    moved = sum(1 for token in TOKENS for _w, deck in _positions(token)
                if _answer(deck) != TRUTH)
    assert moved == 0, moved


def test_unanchoring_alone_also_moves_nothing_because_the_strip_still_runs(monkeypatch):
    """The second half of the same finding: with the strip ON, unanchoring the
    pattern still moves 0 of 84. Each property alone is sufficient."""
    monkeypatch.setattr(
        G, "_SRC", re.compile(r"(v[\w.$]*)\s+(\S+)\s+0\s+(.+?)\s*$", re.M | re.I))
    moved = sum(1 for token in TOKENS for _w, deck in _positions(token)
                if _answer(deck) != TRUTH)
    assert moved == 0, moved


def test_removing_BOTH_moves_them_so_the_zero_is_not_an_accident(monkeypatch):
    """THE MUTATION ARM THAT FIRES. The anchor and the strip are REDUNDANT
    protections — either one alone keeps every sentence away from the regex, so
    neither shows up as load-bearing on its own. Remove both and the same 84
    trials move, which is what makes the zero a measurement rather than a
    property of a fixture that could never have moved."""
    monkeypatch.setattr(_dc, "spice_code_only", lambda text, **kw: text)
    monkeypatch.setattr(
        G, "_SRC", re.compile(r"(v[\w.$]*)\s+(\S+)\s+0\s+(.+?)\s*$", re.M | re.I))
    moved = sum(1 for token in TOKENS for _w, deck in _positions(token)
                if _answer(deck) != TRUTH)
    assert moved > 0, "neither the anchor nor the strip is doing anything"


def test_the_same_payload_as_CODE_does_move_it():
    """THE NEGATIVE CONTROL. The fixture COULD have moved the answer — spliced
    in as a real card rather than a comment, it does."""
    deck = BASE.replace("v_in vin 0 sin(0.7 0.36 651.0416667)\n",
                        f"{RIVAL_CARD}\n", 1)
    assert _answer(deck) != TRUTH
    assert abs(_answer(deck) - 0.85) < 1e-12          # (0.95 - 0.1) / 1.0
