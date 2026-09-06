"""Turn a required-pattern regex into a string that the regex matches (#2057).

WHY THIS EXISTS. Every skill ships a generated
`skills/<skill>/tests/test_compliance.py` whose
`test_good_output_passes_all_required` builds a synthetic document out of the
skill's own required patterns and asserts the compliance driver returns PASS.
The satisfier that built it was a hand-written chain of `re.sub` rewrites over
the pattern TEXT. #2050 measured what that cost: on 53 of the 69 skills that
ship the generated test the synthetic document did not satisfy its own
patterns, and the test skipped before its assert — so 53 skills reported a
green run while asserting nothing. cz2050 turned the blanket skip into a NAMED
list of the 53 and recorded the four ways the text-rewriting satisfier failed:

  NONCAPTURING  `(?:A|B)` kept its `?:`, so `## (?:Output)` was emitted.
  METACHAR      a literal `.?` / `.*` survived into the output text.
  ESCAPE        a final `re.sub(r'\\\\', '', s)` turned `\\b` into the letter
                `b` and left an inline `(?i)` as visible text.
  REPETITION    `{7,40}` was copied through instead of expanded.

All four are the same mistake: rewriting the SURFACE of a regex instead of
reading its STRUCTURE. This module walks the parse tree the `re` module itself
produces and emits a string for each node, so there is no construct-by-
construct rewrite list to keep complete — a construct this walker does not
know raises, loudly, instead of emitting text that looks plausible and does
not match.

THE DEFINITION OF A SATISFIER, and the only thing worth asserting about one:

    re.fullmatch(pattern, pattern_to_satisfier(pattern), FLAGS)

is not None, with FLAGS the flags the compliance driver actually audits under
(`skill_compliance_check` uses MULTILINE | IGNORECASE | DOTALL). That is
asserted for every required pattern of every skill in
`programs/tests/test_pattern_satisfier_2057.py`, so this module cannot drift
away from the patterns it serves.

The output is MINIMAL by construction — a repeat emits its lower bound, an
alternation its first satisfiable branch, an optional group nothing — because
the shortest satisfier is the one least likely to trip a *forbidden*-pattern
cross-check somewhere else in the same document.
"""
from __future__ import annotations

import re
import string
from typing import Any, Dict, List

try:                                    # Python 3.11+
    from re import _parser as _sre_parse       # type: ignore[attr-defined]
    from re import _constants as _sre_const    # type: ignore[attr-defined]
except ImportError:                     # Python <= 3.10
    import sre_parse as _sre_parse             # type: ignore[no-redef]
    import sre_constants as _sre_const         # type: ignore[no-redef]

#: The flags `_shared/skill_compliance_check.py` audits a required pattern
#: under. Imported by the test rather than re-typed there.
AUDIT_FLAGS = re.MULTILINE | re.IGNORECASE | re.DOTALL

#: Preference order when a character class leaves us a choice. Letters first so
#: a satisfier reads as text; `_` and the digits next; punctuation last.
_PREFERRED = string.ascii_lowercase + string.digits + "_" + " -.:/"

_CATEGORY_SAMPLE = {
    "CATEGORY_DIGIT": "0",
    "CATEGORY_NOT_DIGIT": "x",
    "CATEGORY_SPACE": " ",
    "CATEGORY_NOT_SPACE": "x",
    "CATEGORY_WORD": "x",
    "CATEGORY_NOT_WORD": "-",
    "CATEGORY_LINEBREAK": "\n",
    "CATEGORY_NOT_LINEBREAK": "x",
}


class UnsupportedPattern(ValueError):
    """A regex construct this walker cannot emit a satisfier for.

    Raised rather than guessed. A wrong guess is what produced `## (?:Output)`
    and 53 silently-skipping tests; a raise is a red the reader can act on.
    """


def _name(op: Any) -> str:
    return getattr(op, "name", str(op))


def _pick_from_set(items, negate: bool) -> str:
    """Choose one character satisfying a character class."""
    allowed = set()
    banned = set()
    open_ended = False
    for op, av in items:
        n = _name(op)
        if n == "LITERAL":
            (banned if negate else allowed).add(chr(av))
        elif n == "RANGE":
            lo, hi = av
            span = [chr(c) for c in range(lo, min(hi, lo + 512) + 1)]
            if negate:
                banned.update(span)
            else:
                allowed.update(span)
        elif n == "CATEGORY":
            sample = _CATEGORY_SAMPLE.get(_name(av))
            if sample is None:
                raise UnsupportedPattern(f"character category {_name(av)}")
            if negate:
                # A negated category bans a whole class; fall back to scanning
                # the preference list against the compiled class instead.
                open_ended = True
            else:
                allowed.add(sample)
        elif n == "NEGATE":
            continue
        else:
            raise UnsupportedPattern(f"character-set item {n}")
    if negate or open_ended:
        allowed = set(_PREFERRED) - banned
    for ch in _PREFERRED:
        if ch in allowed:
            return ch
    if allowed:
        return sorted(allowed)[0]
    raise UnsupportedPattern("character class with no satisfiable member")


def _emit(parsed, groups: Dict[int, str]) -> str:
    out: List[str] = []
    for op, av in parsed:
        n = _name(op)
        if n == "LITERAL":
            out.append(chr(av))
        elif n == "NOT_LITERAL":
            out.append("x" if chr(av) != "x" else "y")
        elif n == "ANY":
            out.append("x")
        elif n == "IN":
            negate = bool(av) and _name(av[0][0]) == "NEGATE"
            out.append(_pick_from_set(av[1:] if negate else av, negate))
        elif n in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            lo, _hi, sub = av
            body = _emit(sub, groups)
            out.append(body * lo)
        elif n == "SUBPATTERN":
            gid, _add, _del, sub = av
            body = _emit(sub, groups)
            if gid:
                groups[gid] = body
            out.append(body)
        elif n == "ATOMIC_GROUP":
            out.append(_emit(av, groups))
        elif n == "BRANCH":
            _, branches = av
            for branch in branches:
                try:
                    out.append(_emit(branch, groups))
                    break
                except UnsupportedPattern:
                    continue
            else:
                raise UnsupportedPattern("no satisfiable branch")
        elif n == "AT":
            # Zero-width: ^ $ \b \B \A \Z. Emitting nothing is correct; the
            # surrounding literals are what make the assertion hold, and the
            # fullmatch check in the test is what proves it did.
            continue
        elif n == "GROUPREF":
            out.append(groups.get(av, ""))
        elif n == "GROUPREF_EXISTS":
            _ref, yes, no = av
            out.append(_emit(no if no is not None else yes, groups))
        elif n == "ASSERT":
            direction, sub = av
            if direction == 1:
                # LOOKAHEAD IS ZERO-WIDTH. Emit nothing, exactly like `AT`:
                # the pattern that FOLLOWS produces the text the assertion is
                # about, and emitting the assertion's own content as well
                # doubles it. Measured at #2057 while auditing this module's
                # unreached branches: the previous version turned
                # `(?=abc)abc` into 'abcabc', which the fullmatch guard below
                # caught and refused — safe, but a branch that claims to
                # handle a construct and does not is worse than no branch.
                continue
            # LOOKBEHIND HAS NO FULLMATCH SATISFIER, in general. `fullmatch`
            # anchors at position 0, so the bytes a leading `(?<=…)` demands
            # can be neither inside the match nor before it. Raising names the
            # construct; guessing would emit a string that does not match.
            raise UnsupportedPattern(
                "lookbehind assertion: no string can satisfy it under "
                "re.fullmatch, which is the definition this module verifies "
                "against")
        elif n == "ASSERT_NOT":
            # A negative lookaround is satisfied by emitting nothing here and
            # letting the fullmatch guard confirm it; if the rest of the
            # pattern happens to produce the forbidden text, the guard refuses
            # rather than this branch pretending otherwise.
            continue
        else:
            raise UnsupportedPattern(f"regex opcode {n}")
    return "".join(out)


def pattern_to_satisfier(pattern: str) -> str:
    """Return a string that `pattern` matches, built from the regex's own
    parse tree.

    Raises `UnsupportedPattern` for a construct with no emittable satisfier,
    and `re.error` for a pattern that does not compile. It never returns a
    string it has not itself checked: the return is verified with
    `re.fullmatch` under the driver's audit flags before it leaves.
    """
    parsed = _sre_parse.parse(pattern)
    text = _emit(parsed, {})
    if re.fullmatch(pattern, text, AUDIT_FLAGS) is None:
        raise UnsupportedPattern(
            f"generated {text!r} does not fullmatch {pattern!r}")
    return text
