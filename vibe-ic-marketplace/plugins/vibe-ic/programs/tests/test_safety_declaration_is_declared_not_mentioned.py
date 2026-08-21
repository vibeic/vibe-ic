"""A safety mechanism is DECLARED, never MENTIONED.

`_SAFETY_DECL_RE` was one flat pattern matched against the RAW bytes of every
.v/.sv file, comments included, and two of its alternatives are ordinary
English:

    reg [5:0] round1;   // t+1, kept in lockstep for K[t+1]

"kept in lockstep" is English for "in step". That one word admitted a design
declaring no ASIL, no safety goal and no safety mechanism anywhere in L1..L9
into an ASIL-D FMEDA graded against a 99 % diagnostic-coverage floor, which it
then FAILed. `// no ECC here` — a comment stating the ABSENCE — matched too.

THE SPLIT

    STRONG   terms of art nobody writes by accident: ISO-26262, ASIL-x, FMEDA,
             functional safety, diagnostic coverage, safety mechanism, parity
             protect. Their presence IS a declaration, honoured ANYWHERE,
             comments included — that is what a real ECC block's header says.
    WEAK     real safety vocabulary with an incidental reading: `lockstep`,
             bare `ecc`. Honoured from the design's DECLARATIVE prose and from
             RTL CODE, but NOT from RTL commentary — the one place the
             incidental reading actually occurs.

WHY THIS FILE EXISTS AT ALL. The fix landed with no test. Measured by mutation
before writing this: collapsing `_SAFETY_DECL_WEAK_RE` into
`_SAFETY_DECL_STRONG_RE` — which switches the entire fix off and restores the
defect exactly — leaves all 53 tests in the three fmeda-named files GREEN. So
the fix could be reverted, or quietly undone by an unrelated rewrite, with the
suite silent. That is the same shape as the IHP captable discovery a 734-line
rewrite removed in v1.9.x: correct code, nothing holding it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "fmeda_fault_injection_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "fmeda_fault_injection_coverage_probe", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fmeda_fault_injection_coverage_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()

#: The comment that caused this. Ordinary English, in a design with no safety
#: declaration anywhere.
_INCIDENTAL_COMMENT = "reg [5:0] round1;   // t+1, kept in lockstep for K[t+1]\n"

#: A comment stating the ABSENCE of the mechanism. Matching this is worse than
#: matching a neutral mention: the text says the opposite of what it is read as.
_ABSENCE_COMMENT = "// no ECC here — the datapath is unprotected\n"


# ── the weak terms must not be a declaration in RTL commentary ───────────────
def test_lockstep_in_a_comment_is_not_a_declaration():
    assert M._SAFETY_DECL_STRONG_RE.search(_INCIDENTAL_COMMENT) is None, (
        "an ordinary-English comment reads as a term of art; that is what "
        "admitted a design with no ASIL into an ASIL-D FMEDA")


def test_a_comment_denying_ecc_is_not_a_declaration():
    assert M._SAFETY_DECL_STRONG_RE.search(_ABSENCE_COMMENT) is None, (
        "a comment saying there is NO ECC was read as declaring one")


# ── but they ARE a declaration where a declaration legitimately lives ────────
def test_the_weak_terms_still_fire_on_declarative_prose():
    """The accept case. Without it, the fix could be implemented by deleting
    the weak terms entirely, and a design that really does declare lockstep in
    its L-doc would stop being graded as a safety design."""
    for text in ("The design uses lockstep redundancy for the control path.\n",
                 "Memory is protected by ECC.\n"):
        assert M._SAFETY_DECL_WEAK_RE.search(text) is not None, text


def test_the_weak_terms_still_fire_on_rtl_code():
    """`ecc_syndrome`-style identifiers are code, not commentary."""
    assert M._SAFETY_DECL_WEAK_RE.search("wire [7:0] ecc;\n") is not None


# ── the strong terms are honoured anywhere, comments included ────────────────
@pytest.mark.parametrize("text", [
    "// ISO-26262 ASIL-D safety mechanism: SEC-DED over the register file\n",
    "// FMEDA: diagnostic coverage target 99%\n",
    "// parity protect on the address bus\n",
    "/* functional safety: this block implements the safety mechanism */\n",
])
def test_terms_of_art_are_a_declaration_even_in_a_comment(text):
    """A real ECC block declares itself in its header comment, and that must
    keep firing. This is the half a naive 'strip all comments' fix would break."""
    assert M._SAFETY_DECL_STRONG_RE.search(text) is not None, text


# ── the two patterns must stay distinct ──────────────────────────────────────
def test_the_weak_terms_are_not_in_the_strong_pattern():
    """The mutation that switches the fix off.

    Collapsing weak into strong restores the defect exactly, and every other
    test in the fmeda suite stays green through it — which is why this
    assertion is written against the patterns rather than only against
    behaviour.
    """
    for term in ("lockstep", "ecc"):
        assert term not in M._SAFETY_DECL_STRONG_RE.pattern.lower(), (
            f"'{term}' is back in the STRONG pattern, so an ordinary-English "
            f"comment declares a safety mechanism again")


def test_the_union_still_matches_everything_either_half_does():
    """`_SAFETY_DECL_RE` is kept as the historical name for outside readers and
    must remain a true union — a third caller reading it should not silently
    get a narrower answer than the two halves it is built from."""
    for text in ("kept in lockstep\n", "ASIL-D\n", "wire ecc;\n", "FMEDA\n"):
        strong = M._SAFETY_DECL_STRONG_RE.search(text)
        weak = M._SAFETY_DECL_WEAK_RE.search(text)
        union = M._SAFETY_DECL_RE.search(text)
        assert bool(union) == bool(strong or weak), text


# ── the call site is what makes the split mean anything ──────────────────────
def test_the_caller_applies_weak_only_to_the_comment_stripped_text():
    """Two patterns that are never applied to different inputs are one pattern.

    Read from the source because the discrimination is a property of the CALL,
    not of either regex: `combined` carries comments, `combined_code` does not.
    """
    src = PROG.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "_SAFETY_DECL_STRONG_RE.search(combined)" in code, (
        "the strong pattern is no longer applied to the comment-bearing text")
    assert "_SAFETY_DECL_WEAK_RE.search(combined_code)" in code, (
        "the weak pattern is not applied to the comment-stripped text — the "
        "split then decides nothing")
