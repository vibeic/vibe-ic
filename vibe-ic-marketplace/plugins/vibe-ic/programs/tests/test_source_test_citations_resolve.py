#!/usr/bin/env python3
"""test_source_test_citations_resolve.py — a test cited in source must EXIST.

THE DEFECT CLASS
----------------
`spef_extraction_check.py` documented a deliberate rc 1 -> 0 relaxation and
certified it with one sentence claiming a named test pinned it. That file
existed nowhere in the repository. The relaxation happened to be safe, but
nobody had established that: the sentence a reviewer relies on reads exactly the
same whether the pin exists or not, and reading it is what STOPS the reviewer
from checking. `evidence_citation_resolves_check.py` already makes this argument
for Markdown citing `.log`/`.rpt` under `benchmark-data/`. This is the same
disease one container over -- source code citing a test -- and nothing looked.

WHAT "RESOLVES" MEANS HERE, EXACTLY
-----------------------------------
A citation resolves when some file with that BASENAME exists somewhere under
the plugin root. The cited PATH is not checked and the cited file is never
opened. That is deliberate, not an oversight: `flow_compliance_check.py`
legitimately cites `tests/test_issue496_zero_denominator_gates.py` while the
only copy lives at `programs/tests/`, a survival of the plugin-root `tests/`
tree merged away at v0.2.19. Demanding the path resolve would manufacture a
finding against a citation that is substantively true. So this rule catches
"names a test that does not exist"; it does NOT catch "names the wrong
directory" or "names a real file that asserts nothing". Those remain open, and
the assertion messages below say so rather than implying a stronger check.

MEASURED over the whole plugin tree at the time of writing (3459 files: 3117
`.py`, 173 `.yaml`, 158 `.md`, 11 `.sh`):

    rule A (citation verb -> named test file)   50 citations,  2 dangling
    rule B (module self-title -> own filename)  78 titles,     2 mismatched

All four are named in the fix that lands with this file. The two dangling ones
are counted against origin/main; on this tree both are repaired, so the gate
lands green with no baseline and no waiver list.

WHAT AN ADVERSARIAL PASS BROKE, AND WHAT IT COST TO REPAIR
----------------------------------------------------------
The first cut of this rule was blind to any citation whose filename carried a
path separator: the character class before the name accepted a backtick, quote,
whitespace or `(`, and a `/` ended the match. Six real citations -- 13% of the
population, including two in the flow's own compliance gate -- were invisible
BY CONSTRUCTION while the docstring reported its count as a tree-wide
measurement. A rule that reports a partial denominator as a total is the exact
defect this file exists to catch, so it is repaired here (one character in the
separator class) rather than disclosed as a limitation. Re-measured after the
repair: 41 -> 47 in `.py` alone, no new dangling.

The same pass showed the verb alternation had no leading word boundary, so
`see` matched inside `foresee` and `unforeseen`; `\b` now precedes the group.

WHY A CITATION VERB IS REQUIRED
-------------------------------
The obvious rule -- "every `test_*.py` mentioned in a comment must exist" -- is
wrong, and measurably so. `benchmark/score_cocotb_mcp.py`, `cvdp_gate.py` and
four other modules discuss `test_runner.py`, a file that lives inside a
benchmark CONTAINER and is not a repo test at all; a verb-free rule reports
every one of those as a lie. Requiring an explicit citation verb ("pinned by",
"covered by", ...) is what separates *claiming a test backs this* from
*mentioning a filename*. Trading a false-clean for a false-alarm is not
progress, so the narrower rule is the correct one.

A DENIAL IS NOT A CLAIM (AND WHY QUOTATIONS ARE STILL JUDGED)
-------------------------------------------------------------
A comment DENYING coverage -- "this is not covered by X" -- names a test with a
citation verb and asserts the opposite of coverage. It is skipped when a
negator GOVERNS the verb: the negator must end the sentence-so-far, with at
most two words between. Both looser readings were measured wrong and are pinned
below in both directions.

A QUOTATION of a citation is the other shape that claims nothing, and it is
deliberately NOT excluded. The obvious exclusion -- "an odd number of open
quote characters earlier in the sentence" -- was built, measured, and REMOVED,
because it silently dropped 9 real citations: 8 of them are the deferral
rationales in `mcp-eda/test/test_mcp_tool_coverage_inventory.py`, which live
inside Python string literals and include the very citation this fix repaired.
Trading the rule's headline catch for immunity to a rare prose shape is a
false-clean bought with a false-alarm repair, which is worse than the thing it
fixed. So the DECLARED GAP is: a postmortem that quotes a citation verbatim
will be judged as if it made it. That costs nothing today -- every quoted
citation in the tree names a file that exists -- and when it does bite, the
remedy is to describe the defective sentence instead of reproducing it with its
verb intact. `test_a_quoted_citation_is_still_judged` pins this as intended
behaviour rather than leaving it to be rediscovered as a surprise.

ZERO-DENOMINATOR GUARD
----------------------
Both rules assert their own denominator. A regex that quietly stops matching --
a renamed convention, an escaping change, a scope that no longer resolves --
would otherwise report "0 dangling citations" forever, which is precisely the
falsely-clean verdict this file exists to prevent. A gate that cannot say how
many things it looked at has not looked.

The SPEF-side half of the same fix is covered by
``test_spef_full_scan_and_coupling_disclosure.py``, which pins the relaxation
whose false certificate started this.

chip-AGNOSTIC: pure source-text structure. No design, PDK, vendor or cell
literal appears here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]

# Verbs that turn a filename into a CLAIM about coverage. Deliberately closed:
# an open rule ("any mention") manufactures findings against prose that never
# promised anything -- see WHY A CITATION VERB IS REQUIRED above.
_VERBS = (r"pinned\s+by|pinned\s+in|covered\s+by|proven\s+by|guarded\s+by|"
          r"enforced\s+by|locked\s+by|regression[-\s]tested\s+by|"
          r"exercised\s+by|asserted\s+by|verified\s+by|tested\s+by|see")

# The verb, then at most ~80 characters of connective tissue with no sentence
# break, then the filename. Newlines are allowed inside that window because a
# wrapped docstring routinely puts the verb and the name on different lines --
# the citation this whole file exists for is wrapped exactly that way, and a
# newline-intolerant version of this regex silently missed it.
#
# The separator class INCLUDES `/`: without it every path-qualified citation
# (`covered by programs/tests/test_x.py`) was invisible, and the rule reported
# its partial count as the tree total.
#
# The leading `\b` is load-bearing: `see` is the loosest verb in the list and
# without the boundary it matched inside `foresee` / `oversee` / `unforeseen`.
_CITE_RE = re.compile(r"\b(?:" + _VERBS + r")\b[^.]{0,80}?[`'\"\s(/]"
                      r"(test_[A-Za-z0-9_]+\.py)", re.IGNORECASE)

# A module docstring that OPENS with a filename is announcing its own identity.
_TITLE_RE = re.compile(
    r'^\s*(?:#![^\n]*\n)?(?:from __future__[^\n]*\n)?\s*'
    r'(?:r|u|b)?("""|\'\'\')\s*(test_[A-Za-z0-9_]+\.py)')

# Placeholders, not citations: `test_X.py` in a doc explaining a NAMING RULE
# never claimed a particular file exists.
_TEMPLATE_RE = re.compile(r"^test_(?:[A-Z]|N|x|y)\.py$")

# Words that turn the citation verb into a DENIAL of coverage. The negator
# must GOVERN the verb -- it has to end the sentence-so-far, optionally with up
# to two intervening words -- not merely appear somewhere in the sentence.
# Both looser readings were measured wrong:
#   * whole-sentence: "it doesn't matter which corner -- pinned by ``X``" is a
#     real citation with a contraction in it, and a sentence-wide test drops it.
#   * fixed character window: the real citation in `spef_extraction_check.py`
#     follows the words "did NOT go blind" one sentence earlier.
# Anchored at the end of the prefix, so it can only ever match the words
# immediately in front of the verb.
_NEGATED_RE = re.compile(
    r"(?:\bnot\b|n't\b|\bnever\b|\bno longer\b|\bnothing\b|\bneither\b|"
    r"\bnor\b|\bwithout\b)[^\S\n]+(?:[A-Za-z0-9_]+[^\S\n]+){0,2}$",
    re.IGNORECASE)

# A sentence ends at `.`/`!`/`?` followed by whitespace, or at a blank line.
# `.` alone is not enough: filenames are full of dots (`spef_check.py`), and
# splitting on those puts every citation in a sentence of its own.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s)|\n\s*\n")

# Denominators below which the rule has stopped looking rather than found
# nothing. Set well under the measured 44 / 78 so ordinary churn never trips
# them, and well above 0 so a dead regex always does.
_MIN_CITATIONS = 20
_MIN_TITLES = 20

# Text surfaces that carry citations. `.py` is where the measured rot was, but
# a citation in a `.md` runbook or a `.yaml` gate manifest lies exactly as
# well; all currently resolve, so widening the sweep costs no findings today
# and closes the surface for tomorrow.
_SOURCE_GLOBS = ("*.py", "*.md", "*.yaml", "*.yml", "*.sh")


def _sentence_before(text: str, pos: int) -> str:
    """The text from the start of the citation's own sentence up to ``pos``."""
    last = 0
    for m in _SENTENCE_END_RE.finditer(text, 0, pos):
        last = m.end()
    return text[last:pos]


def _sources() -> List[Path]:
    out: List[Path] = []
    for pat in _SOURCE_GLOBS:
        out.extend(_PLUGIN_ROOT.rglob(pat))
    return sorted(set(out))


def _existing_test_names() -> set:
    return {p.name for p in _PLUGIN_ROOT.rglob("test_*.py")}


def scan_citations(text: str, own_name: str,
                   existing: set) -> Tuple[int, List[str]]:
    """(citations_checked, dangling_names) for one source text.

    A match is DISCOUNTED -- not counted, not judged -- when a negator governs
    its verb: that is prose denying coverage, not claiming it."""
    checked = 0
    bad: List[str] = []
    for m in _CITE_RE.finditer(text):
        name = m.group(1)
        if _TEMPLATE_RE.match(name):
            continue
        prefix = _sentence_before(text, m.start())
        if _NEGATED_RE.search(prefix):
            continue
        checked += 1
        if name not in existing and name != own_name:
            bad.append(name)
    return checked, bad


def scan_self_title(text: str, own_name: str) -> Tuple[int, str]:
    """(1, wrong_title) if the module self-titles wrongly, else (0|1, "")."""
    m = _TITLE_RE.match(text)
    if not m:
        return 0, ""
    return 1, ("" if m.group(2) == own_name else m.group(2))


def _sweep() -> Tuple[int, Dict[str, List[str]], int, Dict[str, str]]:
    existing = _existing_test_names()
    n_cit = 0
    dangling: Dict[str, List[str]] = {}
    n_title = 0
    stale: Dict[str, str] = {}
    for p in _sources():
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        c, bad = scan_citations(text, p.name, existing)
        n_cit += c
        if bad:
            dangling[str(p.relative_to(_PLUGIN_ROOT))] = bad
        if p.suffix == ".py":
            t, wrong = scan_self_title(text, p.name)
            n_title += t
            if wrong:
                stale[str(p.relative_to(_PLUGIN_ROOT))] = wrong
    return n_cit, dangling, n_title, stale


# ===========================================================================
# THE INVARIANTS
# ===========================================================================
def test_every_cited_test_file_exists():
    """A source file that says a test backs it must name a test that exists."""
    n_cit, dangling, _, _ = _sweep()
    assert n_cit >= _MIN_CITATIONS, (
        f"only {n_cit} citation(s) matched (expected >= {_MIN_CITATIONS}). "
        f"This is the zero-denominator failure, not a clean tree: the rule has "
        f"stopped recognising citations, so its 'no dangling citations' "
        f"verdict means nothing.")
    assert not dangling, (
        "source citing a test whose NAME exists nowhere under the plugin root "
        "-- a check that lies about being checked. (This rule matches on "
        "basename only; a citation naming the wrong directory, or a real file "
        "that asserts nothing, is NOT caught here.)\n" + "\n".join(
            f"  {f}: {', '.join(names)}" for f, names in sorted(
                dangling.items())))


def test_every_module_self_title_matches_its_filename():
    """A module docstring opening with a filename must open with its OWN.

    A renamed file whose docstring still announces the old name sends every
    reader and every grep to a path that is not there.
    """
    _, _, n_title, stale = _sweep()
    assert n_title >= _MIN_TITLES, (
        f"only {n_title} self-title(s) matched (expected >= {_MIN_TITLES}); "
        f"the rule has stopped looking.")
    assert not stale, (
        "module docstring announces a filename that is not its own:\n"
        + "\n".join(f"  {f} self-titles as {t}"
                    for f, t in sorted(stale.items())))


# ===========================================================================
# FIXTURES
#
# Every fixture filename is ASSEMBLED at runtime, never written as a literal.
# A literal `test_<something>.py` inside this module would be scanned by the
# module's OWN sweep and reported as a dangling citation -- and the tempting
# repair, exempting this file from its own rule, is a self-issued waiver by a
# gate whose entire subject is unearned certificates. Assembling the strings
# keeps this module subject to the rule it enforces; the sweep above finds
# nothing here because there is nothing here to find.
# ===========================================================================
def _fname(stem: str) -> str:
    return "test_" + stem + ".py"


def test_this_module_is_clean_under_its_own_rule():
    """No exemptions: the enforcer is judged by the rule it enforces."""
    text = Path(__file__).read_text(errors="replace")
    checked, bad = scan_citations(text, Path(__file__).name,
                                  _existing_test_names())
    assert bad == [], bad
    _, wrong = scan_self_title(text, Path(__file__).name)
    assert wrong == "", wrong
    assert checked >= 1, (
        "this module's own docstring no longer contains a recognisable "
        "citation, so this self-check proves nothing")


# ===========================================================================
# FALSIFIABILITY — the rules must FIRE on the defect
# ===========================================================================
def test_a_citation_of_a_missing_test_is_flagged():
    """The exact shape of the defect this file was written for, wrapped across
    a line the way the real one was."""
    missing = _fname("a_file_that_does_not_exist_anywhere")
    text = ('"""A guard.\n\n'
            'A genuinely headerless input still FAILs (pinned by\n'
            f'``{missing}``). Constructed.\n'
            '"""\n')
    checked, bad = scan_citations(text, "prog.py", {_fname("real")})
    assert checked == 1, checked
    assert bad == [missing]


def test_a_path_qualified_citation_of_a_missing_test_is_flagged():
    """THE BLIND SPOT AN ADVERSARIAL PASS FOUND. One character of path prefix
    used to flip the verdict from flagged to silent, on the same verb and the
    same missing file."""
    missing = _fname("a_file_that_does_not_exist_anywhere")
    bare = "pinned by ``" + missing + "``."
    pathy = "pinned by ``programs/tests/" + missing + "``."
    assert scan_citations(bare, "prog.py", set()) == (1, [missing])
    assert scan_citations(pathy, "prog.py", set()) == (1, [missing]), (
        "a citation with a directory in front of it is still a citation")


def test_the_sweep_sees_path_qualified_citations_in_the_real_tree():
    """The denominator repair, measured rather than asserted: the tree's real
    citations include path-qualified ones, so a rule blind to them reports a
    partial count as a total."""
    pathy = re.compile(r"\b(?:" + _VERBS + r")\b[^.]{0,80}?/"
                       r"test_[A-Za-z0-9_]+\.py", re.IGNORECASE)
    hits = sum(len(pathy.findall(p.read_text(errors="replace")))
               for p in _sources())
    assert hits >= 3, (
        f"expected the tree to still contain path-qualified citations "
        f"(found {hits}); if this is genuinely 0 the regression it guards "
        f"cannot be demonstrated and the separator class needs re-measuring")


def test_a_stale_self_title_is_flagged():
    text = ('#!/usr/bin/env python3\n"""' + _fname("old_name")
            + ' — pins something."""\n')
    n, wrong = scan_self_title(text, _fname("new_name"))
    assert n == 1
    assert wrong == _fname("old_name")


# ===========================================================================
# THE OTHER SIDE — the rules must NOT fire on a legitimate state
# ===========================================================================
def test_a_citation_that_resolves_is_not_flagged():
    text = '"""Covered by ``' + _fname("real") + '``."""\n'
    checked, bad = scan_citations(text, "prog.py", {_fname("real")})
    assert checked == 1
    assert bad == []


def test_a_module_citing_itself_is_not_flagged():
    """A test file naming itself in its own docstring is self-evidently
    present; requiring it in the discovered set would flag a new file before
    the walk that finds it has run."""
    text = '"""Pinned by ``' + _fname("me") + '`` itself."""\n'
    checked, bad = scan_citations(text, _fname("me"), set())
    assert checked == 1
    assert bad == []


def test_a_bare_mention_without_a_citation_verb_is_not_a_citation():
    """The load-bearing anti-false-alarm case, taken from real source.

    Six modules discuss `test_runner.py`, which lives inside a benchmark
    container and is not a repo test. A verb-free rule calls every one of them
    a lie. Nothing here claims a test backs anything, so nothing is judged.
    """
    text = ("# The harness runs `pytest /src/test_runner.py` inside the\n"
            "# container; test_runner.py is the pytest entry point.\n")
    checked, bad = scan_citations(text, "prog.py", set())
    assert checked == 0, (
        "a bare mention was counted as a citation -- this rule would "
        "manufacture findings against prose that promised nothing")
    assert bad == []


def test_a_naming_template_is_not_a_citation():
    """`test_X.py` in a doc that explains the NAMING RULE names no file."""
    text = ("# A test ``test_X.py`` (X = basename without the ``test_`` "
            "prefix) is covered by test_X.py.\n")
    checked, bad = scan_citations(text, "prog.py", set())
    assert checked == 0
    assert bad == []


def test_a_quoted_citation_is_still_judged():
    """THE DECLARED GAP, pinned as intended behaviour.

    A quotation-aware exclusion was built and removed: counting open quote
    characters dropped 9 real citations, 8 of them inside the Python string
    literals of the MCP coverage inventory -- including the one this fix
    repaired. So a postmortem that reproduces a citation verbatim is judged as
    if it made it. This test exists so that is a decision on the record, not a
    surprise; if it ever needs to change, the replacement must be measured
    against the inventory's dict-literal shape below."""
    missing = _fname("nope")
    text = ("an earlier revision said \"pinned by ``" + missing
            + "``\" and that shape is still judged.\n")
    checked, bad = scan_citations(text, "prog.py", set())
    assert checked == 1, checked
    assert bad == [missing]


def test_a_citation_inside_a_string_literal_is_still_a_citation():
    """The shape the removed exclusion destroyed. The MCP coverage inventory
    states its deferral rationales as dict VALUES; every one of them is a real
    claim that a named plugin test covers a tool, and it is the only thing
    guarding those rationales."""
    missing = _fname("nope")
    text = ('DEFERRED = {\n'
            '    "eda_thing": "wrapped Python program; covered by plugin '
            'tests ' + missing + '",\n}\n')
    checked, bad = scan_citations(text, "prog.py", set())
    assert checked == 1, checked
    assert bad == [missing]


def test_an_apostrophe_does_not_disarm_the_rule():
    """A possessive or a contraction must not disarm the rule -- that would be
    a false-clean bought with a false-alarm repair."""
    missing = _fname("nope")
    for phrase in ("the emitter's own report is covered by ``{}``.",
                   "it doesn't matter which corner -- pinned by ``{}``.",
                   'the gate\'s denominator is asserted by ``{}``.'):
        checked, bad = scan_citations(phrase.format(missing), "prog.py", set())
        assert checked == 1, (phrase, checked)
        assert bad == [missing]


def test_a_denial_of_coverage_is_not_a_citation():
    """"this is NOT covered by X" claims the opposite of coverage."""
    text = "This is NOT covered by ``" + _fname("nope") + "`` -- nothing is.\n"
    checked, bad = scan_citations(text, "prog.py", set())
    assert checked == 0
    assert bad == []


def test_a_negation_in_an_EARLIER_sentence_does_not_disarm_the_rule():
    """The exclusion is sentence-scoped for a reason: the real citation in
    `spef_extraction_check.py` is one sentence after the words "did NOT go
    blind". A window-based negation check would have swallowed it."""
    missing = _fname("nope")
    text = ("The guard did NOT go blind -- a headerless input still FAILs. "
            "Pinned by ``" + missing + "``.\n")
    checked, bad = scan_citations(text, "prog.py", set())
    assert checked == 1, "a real citation was disarmed by a previous sentence"
    assert bad == [missing]


def test_a_verb_inside_a_longer_word_is_not_a_citation_verb():
    """`see` is the loosest verb in the list; without a leading boundary it
    matched inside `foresee`, `oversee`, `unforeseen`."""
    for phrase in ("we foresee ``{}`` breaking",
                   "the runner will oversee ``{}``",
                   "an unforeseen ``{}`` interaction"):
        text = phrase.format(_fname("nope"))
        checked, bad = scan_citations(text, "prog.py", set())
        assert checked == 0, (phrase, checked)
        assert bad == []


def test_a_correct_self_title_is_not_flagged():
    text = ('#!/usr/bin/env python3\n"""' + _fname("me")
            + ' — pins something."""\n')
    n, wrong = scan_self_title(text, _fname("me"))
    assert n == 1
    assert wrong == ""


def test_a_module_with_no_self_title_is_not_judged():
    """Most modules open with prose. Demanding a filename title would be a
    style rule invented by a correctness gate."""
    n, wrong = scan_self_title('"""Verify parasitic extraction."""\n', "p.py")
    assert n == 0
    assert wrong == ""
