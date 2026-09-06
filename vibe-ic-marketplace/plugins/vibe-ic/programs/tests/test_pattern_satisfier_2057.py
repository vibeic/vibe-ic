"""#2057 item 2 — the satisfier, and the 53 named xfails it was the cause of.

THE RULER. cz2050 replaced a blanket `pytest.skip()` in every generated
`skills/<skill>/tests/test_compliance.py` with a NAMED list of the 53 skills
whose synthetic good-output did not satisfy their own required patterns, and
recorded that all 53 reduced to EIGHT requirement IDs defeated by
`_pattern_to_satisfier` in FOUR measured ways. This file is the proof that the
four are gone and that the list is empty because the cause was fixed, not
because the list was edited:

  * `_OLD_SATISFIER` below is the pre-#2057 implementation, verbatim, kept as a
    NEGATIVE CONTROL. Each construct test asserts that the old one FAILED on
    that construct and the new one succeeds. A test that cannot fail against
    the pre-fix code proves nothing, so both arms run here in one process.
  * the corpus test runs EVERY required pattern of EVERY skill through the new
    satisfier and asserts `re.fullmatch` under the flags the compliance driver
    actually audits with. That is the definition of a satisfier, and it is
    checked over the whole population, not a sample.
  * the membership tests hold `SYNTHETIC_FIXTURE_LIMITATIONS` empty and
    `REMOVED_BY_2057` at the exact 53 names cz2050 measured, so "all 53 went"
    is a set a reader can check rather than a count to be trusted.
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).resolve()
_PLUGIN = _HERE.parents[2]
_SKILLS = _PLUGIN / "skills"
sys.path.insert(0, str(_PLUGIN / "_shared"))

import pattern_satisfier as PS            # noqa: E402
import synthetic_fixture_limits as LIMITS  # noqa: E402
import skill_compliance_check as scc      # noqa: E402


# ---------------------------------------------------------------------------
# The pre-#2057 satisfier, verbatim, as the negative control.
# ---------------------------------------------------------------------------
def _OLD_SATISFIER(pat: str) -> str:
    s = pat
    s = re.sub(r'\\s\*', ' ', s)
    s = re.sub(r'\\s\+', ' ', s)
    s = re.sub(r'\\d\+', '1', s)
    s = re.sub(r'\\d', '1', s)
    s = re.sub(r'\\w\+', 'x', s)
    s = re.sub(r'\\w', 'x', s)
    s = re.sub(r'\[([^\]]+)\]\+', lambda m: m.group(1)[0], s)
    s = re.sub(r'\[([^\]]+)\]', lambda m: m.group(1)[0], s)
    s = re.sub(r'\(([^|)]+)\|[^)]+\)', lambda m: m.group(1), s)
    s = s.replace('^', '').replace('$', '')
    s = s.replace('\\.', '.').replace('\\|', '|')
    s = s.replace('\\(', '(').replace('\\)', ')')
    s = s.replace('\\[', '[').replace('\\]', ']')
    s = s.replace('\\*', '*').replace('\\+', '+')
    s = re.sub(r'\\', '', s)
    return s or 'XXX'


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, PS.AUDIT_FLAGS) is not None


#: One LIVE pattern per requirement ID cz2050 named, with the construct class
#: it defeats the old satisfier through. Taken from the skill's own
#: compliance.yaml, not invented, and re-read from the yaml below so an edited
#: pattern cannot leave this table describing something that is gone.
_LIVE_DEFECTS = {
    'R_has_output_section': ('ams-sim', 'NONCAPTURING'),
    'R_next_step': ('ams-sim', 'NONCAPTURING'),
    'R_anti_patterns': ('fpga-led-probe-allocation', 'METACHAR'),
    'R_four_modes': ('fpga-led-probe-allocation', 'METACHAR'),
    'R_blocking_declared': ('flow-change-acceptance', 'ESCAPE'),
    'R_no_literals': ('flow-change-acceptance', 'ESCAPE + NONCAPTURING'),
    'R1_handoff_line': ('core-agent-loop', 'REPETITION'),
    'R1_closing_comment_cites_a_commit': ('fork-gatekeeper-loop',
                                          'ESCAPE + REPETITION'),
}


def _pattern_of(skill: str, req_id: str) -> str:
    spec = yaml.safe_load((_SKILLS / skill / "compliance.yaml").read_text())
    for r in spec.get("requirements") or []:
        if r["id"] == req_id:
            return r["pattern"]
    raise AssertionError(f"{skill}: requirement {req_id} is gone")


@pytest.mark.parametrize("req_id", sorted(_LIVE_DEFECTS))
def test_each_named_cause_is_fixed_and_the_old_satisfier_still_fails_it(req_id):
    """BOTH DIRECTIONS, in one process: the old implementation must fail on
    this pattern and the new one must satisfy it. If the old one passed, this
    pattern was never evidence of the defect and the entry is wrong."""
    skill, construct = _LIVE_DEFECTS[req_id]
    pat = _pattern_of(skill, req_id)
    assert req_id in LIMITS.REASONS, req_id
    assert LIMITS.REASONS[req_id].startswith(construct + ':'), (
        req_id, construct, LIMITS.REASONS[req_id])

    old = _OLD_SATISFIER(pat)
    assert not _matches(pat, old), (
        f"{req_id}: the pre-#2057 satisfier already satisfied {pat!r} "
        f"(it produced {old!r}) — this row is not evidence of the defect")

    new = PS.pattern_to_satisfier(pat)
    assert re.fullmatch(pat, new, PS.AUDIT_FLAGS) is not None, (req_id, new)


def test_the_four_construct_classes_by_construction():
    """The four causes as bare regexes, so the fix is pinned even if every
    skill's pattern changes. Each asserts the exact wrong output the old
    satisfier emitted, quoted from cz2050's measurement."""
    cases = [
        # NONCAPTURING — the alternation rule kept the `?:`
        (r'##\s+(?:Output|Findings)', '## ?:Output'),
        # METACHAR — a literal `.?` survived, two chars where one may match
        (r'##\s+Anti.?patterns', '## Anti.?patterns'),
        # ESCAPE — the final backslash strip turned `\b` into `b`
        (r'(?i)\b(BLOCKING|ADVISORY)\b', '(?i)bBLOCKINGb'),
        # REPETITION — `{7,40}` copied through instead of expanded
        (r'\b[0-9a-f]{7,40}\b', 'b0{7,40}b'),
    ]
    for pat, old_output in cases:
        assert _OLD_SATISFIER(pat) == old_output, (pat, _OLD_SATISFIER(pat))
        assert not _matches(pat, old_output), pat
        new = PS.pattern_to_satisfier(pat)
        assert re.fullmatch(pat, new, PS.AUDIT_FLAGS) is not None, (pat, new)


# ---------------------------------------------------------------------------
# The whole population, not a sample
# ---------------------------------------------------------------------------
def _every_required_pattern():
    out = []
    for y in sorted(_SKILLS.glob("*/compliance.yaml")):
        spec = yaml.safe_load(y.read_text()) or {}
        for r in spec.get("requirements") or []:
            out.append((y.parent.name, r["id"], r["pattern"]))
    return out


def test_every_required_pattern_of_every_skill_has_a_satisfier():
    """THE DEFINITION OF A SATISFIER, over the whole tree."""
    pats = _every_required_pattern()
    assert len(pats) >= 150, f"population collapsed to {len(pats)}"
    broken = []
    for skill, rid, pat in pats:
        try:
            sat = PS.pattern_to_satisfier(pat)
        except (PS.UnsupportedPattern, re.error) as e:
            broken.append((skill, rid, f"{e.__class__.__name__}: {e}"))
            continue
        if re.fullmatch(pat, sat, PS.AUDIT_FLAGS) is None:
            broken.append((skill, rid, f"no fullmatch: {sat!r}"))
    assert broken == [], (
        f"{len(broken)} pattern(s) have no verified satisfier: "
        + "; ".join(f"{s}:{r} {w}" for s, r, w in broken))


def test_the_satisfier_is_deterministic():
    for _skill, _rid, pat in _every_required_pattern():
        assert PS.pattern_to_satisfier(pat) == PS.pattern_to_satisfier(pat)


def test_an_unemittable_construct_raises_instead_of_guessing():
    """A guess is what produced `## (?:Output)`. Both directions: a construct
    with no satisfier raises, and the raise is not thrown for everything."""
    with pytest.raises(PS.UnsupportedPattern):
        PS.pattern_to_satisfier(r'[^\s\S]')      # a class with no member
    assert PS.pattern_to_satisfier(r'ok') == 'ok'


def test_the_return_is_verified_before_it_leaves():
    """The module checks its own answer. Break the emitter and the checked
    return must refuse rather than hand back something that does not match."""
    original = PS._emit
    try:
        PS._emit = lambda parsed, groups: "definitely-not-it"
        with pytest.raises(PS.UnsupportedPattern):
            PS.pattern_to_satisfier(r'## Output')
    finally:
        PS._emit = original
    assert PS.pattern_to_satisfier(r'## Output') == '## Output'


def test_the_audit_flags_are_the_drivers_own_flags():
    """A satisfier verified under different flags than the driver audits with
    would be verified against the wrong question."""
    src = (_PLUGIN / "_shared" / "skill_compliance_check.py").read_text()
    assert "re.MULTILINE | re.IGNORECASE | re.DOTALL" in src
    assert PS.AUDIT_FLAGS == (re.MULTILINE | re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# The 53, by name
# ---------------------------------------------------------------------------
def test_the_named_limitation_list_is_empty_and_kept():
    assert LIMITS.SYNTHETIC_FIXTURE_LIMITATIONS == {}
    assert isinstance(LIMITS.SYNTHETIC_FIXTURE_LIMITATIONS, dict), (
        "the register is KEPT, empty — a new unreachable pattern lands here")


def test_the_53_removed_are_recorded_by_name_and_are_really_gone():
    """MEMBERSHIP, not a count. Every skill cz2050 named must (a) still exist,
    (b) be absent from the live register, and (c) actually have a satisfiable
    good-output now."""
    removed = LIMITS.REMOVED_BY_2057
    assert len(removed) == 53, (
        f"REMOVED_BY_2057 changed size to {len(removed)}: "
        + " ".join(sorted(removed)))
    still_declared = sorted(set(removed) & set(LIMITS.SYNTHETIC_FIXTURE_LIMITATIONS))
    assert still_declared == [], (
        "a repaired skill is back on the live register: "
        + " ".join(still_declared))
    unsatisfiable = []
    for skill in sorted(removed):
        y = _SKILLS / skill / "compliance.yaml"
        assert y.is_file(), skill
        spec = yaml.safe_load(y.read_text()) or {}
        for r in spec.get("requirements") or []:
            sat = PS.pattern_to_satisfier(r["pattern"])
            if re.fullmatch(r["pattern"], sat, PS.AUDIT_FLAGS) is None:
                unsatisfiable.append((skill, r["id"]))
    assert unsatisfiable == [], (
        f"{len(unsatisfiable)} removed entr(y/ies) are unsatisfiable again: "
        + "; ".join(f"{s}:{r}" for s, r in unsatisfiable))


def test_every_recorded_cause_still_names_a_live_requirement():
    """`REASONS` is kept as live evidence, not history: each of the eight IDs
    must still be a requirement some skill declares."""
    live = {rid for _s, rid, _p in _every_required_pattern()}
    orphans = sorted(set(LIMITS.REASONS) - live)
    assert orphans == [], (
        "REASONS names requirement IDs no skill declares: "
        + " ".join(orphans))


def test_the_generated_tests_still_assert_the_register_both_ways():
    """`ast`, not grep: the docstrings of these files QUOTE `pytest.skip()`
    while describing the defect, so a substring test would either fail on
    prose or have to stop looking for the thing it exists to find. That is the
    same exemption-by-substring shape cz2050's M4 arm caught in its own test."""
    import ast
    generated = [p for p in sorted(_SKILLS.glob("*/tests/test_compliance.py"))
                 if "Auto-generated" in p.read_text()[:200]]
    assert len(generated) == 69, len(generated)
    for p in generated:
        text = p.read_text()
        assert "SYNTHETIC_FIXTURE_LIMITATIONS" in text, p
        assert "pattern_to_satisfier" in text, p
        called = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func,
                                                         ast.Attribute):
                called.add(node.func.attr)
        assert "skip" not in called, p
        assert "xfail" not in called, p


def test_the_driver_finds_the_shared_satisfier_where_the_template_looks():
    """The generated tests import it off `DRIVER.parent`; if it is not there
    every one of the 69 collapses at import time."""
    assert (_PLUGIN / "_shared" / "pattern_satisfier.py").is_file()
    assert scc.__file__.startswith(str(_PLUGIN / "_shared"))


# ---------------------------------------------------------------------------
# The branches the LIVE CORPUS never reaches — proven, not assumed
# ---------------------------------------------------------------------------
#: MEASURED at #2057 by instrumenting `_emit` over all 175 required patterns:
#: the corpus reaches only LITERAL, IN, MAX_REPEAT, BRANCH, SUBPATTERN, ANY,
#: AT and ASSERT_NOT. Everything else this module handles was SPECULATIVE
#: code, and one of those branches was WRONG (see the lookahead test below).
#: A handler no test reaches is the same unmeasured claim #2050's dead
#: `postchecks:` key was, so each is exercised here by construction.
_UNREACHED_BY_THE_CORPUS = {
    "NOT_LITERAL": r'[^a]x',
    "MIN_REPEAT": r'ab+?c',
    "GROUPREF": r'(ab)-\1',
    "GROUPREF_EXISTS": r'(a)?(?(1)b|c)',
    "ASSERT_lookahead": r'(?=abc)abc',
    "ASSERT_NOT": r'(?!xyz)abc',
}


@pytest.mark.parametrize("label", sorted(_UNREACHED_BY_THE_CORPUS))
def test_a_branch_the_corpus_never_reaches_still_produces_a_satisfier(label):
    pat = _UNREACHED_BY_THE_CORPUS[label]
    sat = PS.pattern_to_satisfier(pat)
    assert re.fullmatch(pat, sat, PS.AUDIT_FLAGS) is not None, (pat, sat)


def test_a_lookahead_is_zero_width_and_is_not_emitted_twice():
    """THE DEFECT THIS AUDIT FOUND, pinned both ways.

    The first version of the ASSERT branch emitted the assertion's own content
    AND the pattern that follows it, so `(?=abc)abc` became 'abcabc'. The
    module's fullmatch guard caught it and raised, so nothing unsafe ever
    escaped — but a branch that claims to handle a construct and does not is
    worse than no branch. A lookahead is ZERO-WIDTH; the text is produced by
    what follows.
    """
    assert PS.pattern_to_satisfier(r'(?=abc)abc') == 'abc'
    assert PS.pattern_to_satisfier(r'a(?=b)b') == 'ab'
    # and the doubled form really would not have matched
    assert re.fullmatch(r'(?=abc)abc', 'abcabc', PS.AUDIT_FLAGS) is None


def test_a_lookbehind_is_refused_by_name_rather_than_guessed():
    """`fullmatch` anchors at 0, so the bytes a leading `(?<=…)` demands can
    be neither inside the match nor before it: there is no satisfier, and the
    module says so instead of emitting a string that does not match."""
    with pytest.raises(PS.UnsupportedPattern) as e:
        PS.pattern_to_satisfier(r'(?<=ab)cd')
    assert "lookbehind" in str(e.value)


@pytest.mark.skipif(sys.version_info < (3, 11),
                    reason="possessive repeats and atomic groups are a 3.11+ "
                           "regex syntax; the pinned image is 3.12, so this "
                           "RUNS there and is skipped only on an older dev "
                           "host — an interpreter capability, never a hidden "
                           "failure")
@pytest.mark.parametrize("pat", [r'ab++c', r'(?>abc)d'])
def test_the_311_only_constructs_are_handled_on_an_interpreter_that_has_them(pat):
    sat = PS.pattern_to_satisfier(pat)
    assert re.fullmatch(pat, sat, PS.AUDIT_FLAGS) is not None, (pat, sat)


def test_every_handled_opcode_is_really_reached_by_some_pattern():
    """MEMBERSHIP on this module's own handler list, MEASURED not hand-listed.

    Instruments `_emit` and `_pick_from_set` over the live corpus PLUS every
    pattern named in this file, and asserts that every name the module
    branches on was actually reached. Derived, never a second hand-fed
    register — the same discipline item 1 applies to the layer codes.

    This is what caught the lookahead defect: `ASSERT` was handled, unreached
    by the corpus, and wrong. If a future branch is added and nothing reaches
    it, this fails and names it.
    """
    import ast
    src = Path(PS.__file__).read_text()
    handled = set()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id == "n"):
            for c in node.comparators:
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    handled.add(c.value)
                elif isinstance(c, (ast.Tuple, ast.List)):
                    handled |= {e.value for e in c.elts
                                if isinstance(e, ast.Constant)}
    assert len(handled) >= 12, (
        f"only {len(handled)} opcode branches found: "
        + " ".join(sorted(handled)))

    reached = set()
    orig_emit, orig_pick = PS._emit, PS._pick_from_set

    def traced_emit(parsed, groups):
        for op, _av in parsed:
            reached.add(PS._name(op))
        return orig_emit(parsed, groups)

    def traced_pick(items, negate):
        if negate:
            reached.add("NEGATE")
        for op, _av in items:
            reached.add(PS._name(op))
        return orig_pick(items, negate)

    pats = [p for _s, _r, p in _every_required_pattern()]
    pats += list(_UNREACHED_BY_THE_CORPUS.values())
    pats += [r'(?<=ab)cd', r'[a-z]+', r'\d\s\w', r'[^\d]']
    if sys.version_info >= (3, 11):
        pats += [r'ab++c', r'(?>abc)d']
    PS._emit, PS._pick_from_set = traced_emit, traced_pick
    try:
        for pat in pats:
            try:
                PS.pattern_to_satisfier(pat)
            except PS.UnsupportedPattern:
                pass          # a refusal still walked the tree
    finally:
        PS._emit, PS._pick_from_set = orig_emit, orig_pick

    expected = set(handled)
    if sys.version_info < (3, 11):
        # not a waiver: these two are UNPARSEABLE before 3.11, so on an older
        # dev host no pattern can reach them. The pinned image is 3.12, where
        # this assertion is complete.
        expected -= {"POSSESSIVE_REPEAT", "ATOMIC_GROUP"}
    unreached = sorted(expected - reached)
    assert unreached == [], (
        f"{unreached}: this module branches on a name that nothing — not the "
        "live corpus, not any pattern in this file — ever reaches. Exercise "
        "it or delete the branch; a handler nothing reaches is an unmeasured "
        "claim, and one of them was also WRONG (see the lookahead test).")
