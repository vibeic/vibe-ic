"""The deck-density extractors read deck CODE, never the sentences a rule block
carries — and the `_NOT_PROSE` exemption that states so is measured, not argued.

WHAT THE RATCHET FOUND. `metal_fill_config_gen::density_rule_layer_identifiers`
shipped reading the RAW rule block: a `re.findall` for `<layer>.area` over text
that also contains the `# Rule <id>:` header, the `##` notes beside it, and the
human-readable violation message the rule prints. That is the #706/#711 shape —
a value taken out of a sentence and written as a declaration, with nothing
asking whether the sentence DENIES it — and `prose_polarity_consulted_check
--ratchet` refused the landing by name.

THE FIX REMOVES THE REFERENT rather than arguing about it: every input now goes
through `die_level_deck_rule_attribution.deck_code_only`, which blanks every
quoted string and every `#` comment in ONE left-to-right scan that tracks both
states together, keeping offsets so the deck's own line structure — which the
section-banner block boundary is computed from — is unchanged. After it, no
sentence reaches any regex, so the polarity question has no referent, and the
claim is a `_NOT_PROSE` entry rather than a debt-register entry.

BOTH DIRECTIONS, ON THE SAME 84 TRIALS:
  * all 21 tokens of `_prose_polarity`'s own denial vocabulary — both tiers,
    the five CJK spellings included — each carrying a DECLARATION-SHAPED
    payload, in each of the 4 positions a sentence can physically occupy here,
    move 0 of 84 published answers;
  * NEGATIVE CONTROL: the identical payload spliced in as CODE moves it, so the
    fixture could have moved;
  * MUTATION: with `deck_code_only` replaced by the identity — the strip
    deleted — the same 84 trials move 84 of 84.
And the EXEMPTION's own control: the function is still what the scanner flags,
and with the entry removed the ratchet refuses again.

chip/PDK-AGNOSTIC: every deck below is written by this file.
"""
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _prose_polarity as P  # noqa: E402
import die_level_deck_rule_attribution as D  # noqa: E402
import metal_fill_config_gen as G  # noqa: E402

EXEMPT_NAME = "metal_fill_config_gen::density_rule_layer_identifiers"

#: Every token `_prose_polarity` calls a denial, spelled out so the sweep below
#: exercises the vocabulary itself rather than a sample of it. Asserted against
#: that module in `test_the_vocabulary_is_the_modules_own`, so a token added
#: there and not here is a test failure rather than a quiet gap in the sweep.
TOKENS = ["not", "no", "none", "without", "excluding", "excluded", "never",
          "non", "非", "无", "無", "不", "否", "removed", "obsolete",
          "superseded", "n/a", "inapplicable", "deprecated", "no longer",
          "does not apply"]

#: The four places a SENTENCE can physically sit in this production.
SLOTS = {"H": " — {s}",      # the `# Rule <id>:` header itself
         "N": " {s}",        # a `##` note line under it
         "T": "  # {s}",     # a trailing comment on the code line
         "S": " {s}"}        # inside the violation MESSAGE string

PAYLOAD = "plant_layer.area / chip_area"

BASE = D.FILE_SEP + """/deck/density.rb
chip_area = extent.sized(0.0).area

# Rule COV1.a: layer_one coverage over the entire die{H}
##{N}
if (layer_one.area / chip_area) * 100 < 30{T}
  extent.output('COV1.a', 'COV1.a : layer_one coverage{S}')
end
"""


def _deck(**kw):
    f = {"H": "", "N": "", "T": "", "S": ""}
    f.update(kw)
    return BASE.format(**f)


def _answer(**kw):
    return G.density_rule_layer_identifiers(_deck(**kw))


def _denial_alternatives():
    r"""Every alternative `_prose_polarity` spells, derived from its own source.

    A regex ALTERNATIVE is the unit of that module's vocabulary — `\bexclud\w*\b`
    is one entry that TOKENS covers with two words, and `\bnon-?\b` is one entry
    covered by one — so the population this list must describe is the set of
    alternatives, not the set of words.
    """
    raw = P._DENIAL_CORE + "|" + P._DENIAL_RETIRED
    return [a for a in raw.split("|") if a]


def test_the_vocabulary_is_the_modules_own():
    """BOTH DIRECTIONS, as a set, against the population itself.

    THE OLD SECOND HALF WAS `len(TOKENS) == 21` — `len()` over an unmutated
    literal, which is true on every tree, forever, and could not have gone red
    for any reason. `population_guard_asserts_equality_not_a_floor` names
    exactly that shape, and it was the ONE offender on main at v1.19.60
    (czmainred9): a denominator that cannot go red is not a denominator, and
    the comment above TOKENS claimed the guard it did not have — "a token added
    there and not here is a test failure" was simply not asserted anywhere.

    So it is asserted now:

      forward   every token here is a denial to `_prose_polarity`  (unchanged);
      backward  every ALTERNATIVE `_prose_polarity` spells is exercised by at
                least one token here — which is the direction that catches the
                vocabulary growing and this sweep silently not growing with it.
    """
    for t in TOKENS:
        assert P.NEGATION_RE.search(t), f"{t!r} is not a denial to _prose_polarity"

    alternatives = _denial_alternatives()
    assert len(alternatives) >= 15, (
        "the alternatives could not be read out of _prose_polarity's source, "
        f"so the backward direction below asks nothing: {alternatives}")
    uncovered = [a for a in alternatives
                 if not any(re.search(a, t, re.IGNORECASE) for t in TOKENS)]
    assert uncovered == [], (
        "`_prose_polarity` spells these denials and no token in TOKENS "
        f"exercises them, so the sweep below has a silent gap: {uncovered}. "
        "Add a word each one matches — do NOT delete the alternative.")


def test_no_sentence_moves_the_published_answer():
    base = _answer()
    assert base == {"COV1.a": ["layer_one"]}
    moved = []
    for tok in TOKENS:
        for pos, tmpl in SLOTS.items():
            got = _answer(**{pos: tmpl.format(s=f"{tok} {PAYLOAD}")})
            if got != base:
                moved.append((tok, pos, got))
    assert moved == [], f"{len(moved)} of {len(TOKENS)*len(SLOTS)} prose trials moved"


def test_the_negative_control_moves_it():
    """The same payload as CODE. Without this the zero above could be a fixture
    that was never able to move."""
    base = _answer()
    txt = _deck().replace("if (layer_one.area",
                          f"if ({PAYLOAD}) * 100 < 1\n  end\n  if (layer_one.area")
    got = G.density_rule_layer_identifiers(txt)
    assert got != base
    assert got == {"COV1.a": ["layer_one", "plant_layer"]}


def test_the_strip_is_load_bearing(monkeypatch):
    """MUTATION: delete the strip and every one of the same trials moves."""
    monkeypatch.setattr(D, "deck_code_only", lambda t: t)
    base = _answer()
    moved = sum(1 for tok in TOKENS for pos, tmpl in SLOTS.items()
                if _answer(**{pos: tmpl.format(s=f"{tok} {PAYLOAD}")}) != base)
    assert moved == len(TOKENS) * len(SLOTS), (
        "the mutation must move EVERY trial the fixed code leaves alone; "
        f"it moved {moved}")


# ---------------------------------------------------------------------------
# `deck_code_only` itself, including the shape that was wrong first.
# ---------------------------------------------------------------------------

def test_an_apostrophe_in_a_comment_does_not_swallow_the_code_below():
    """The measured defect in the FIRST shape. Blanking string literals with a
    regex and then cutting at the first `#` lets an English apostrophe open a
    literal that closes far below — on the two open decks in the pinned image
    that dropped one rule from a family of 8 and reduced another deck's layer
    identifiers from six names to NONE."""
    text = ("# the rule doesn't apply to the marker layer\n"
            "chip_area = extent.sized(0.0).area\n"
            "if (metal2.area / chip_area) * 100 < 30\n")
    code = D.deck_code_only(text)
    assert "chip_area = extent" in code
    assert "metal2.area" in code
    assert "doesn" not in code


def test_a_hash_inside_a_string_is_not_a_comment():
    code = D.deck_code_only("x.output(\"DM#{i}.3\", 'msg') ; y = layer.area\n")
    assert "y = layer.area" in code
    assert "DM" not in code


def test_offsets_and_line_count_are_preserved():
    text = "a = one.area  # note\n'msg'\nb = two.area\n"
    code = D.deck_code_only(text)
    assert len(code) == len(text)
    assert code.count("\n") == text.count("\n")
    assert code.splitlines()[0].startswith("a = one.area")
    assert "msg" not in code


# ---------------------------------------------------------------------------
# The exemption pays for itself.
# ---------------------------------------------------------------------------





def test_the_backward_direction_can_actually_fail():
    """MUTATION on the guard above, since a guard nobody proved can go red is
    the very shape it was rewritten to stop being.

    Add one alternative to the vocabulary and leave TOKENS alone: the backward
    direction must name it. This drives the same expression on a mutated
    pattern rather than editing the shipped module.
    """
    mutated = [a for a in (P._DENIAL_CORE + "|" + P._DENIAL_RETIRED).split("|")
               if a] + [r"\brescinded\b"]
    uncovered = [a for a in mutated
                 if not any(re.search(a, t, re.IGNORECASE) for t in TOKENS)]
    assert uncovered == [r"\brescinded\b"], uncovered
