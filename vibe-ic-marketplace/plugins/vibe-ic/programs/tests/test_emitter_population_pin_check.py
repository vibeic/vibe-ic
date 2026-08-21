"""`emitter_population_pin_check` must refuse a population that is stated twice
and disagrees with itself.

MEASURED 2026-08-21: a lane added a THIRD repair to a post-route block, moved the
emitter's own printed denominator from two to three, and left the test asserting
the old ratio. The population moved and the pin did not, so the test failed for
the right reason with the wrong message.

The fixtures below are synthetic on purpose. Driving this against the live
`phase3_one_shot_runner` would pin THIS program's verdict to that program's
current repair count, which is the very defect under test one level up.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/<this file>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "emitter_population_pin_check.py")
PROGRAMS_DIR = PROG.parent
TESTS_DIR = Path(__file__).resolve().parent

RC_PASS, RC_FAIL, RC_VACUOUS, RC_USAGE = 0, 1, 2, 3

EMITTER = '''\
"""A docstring that says 1 of 2 repairs refused, which is history, not a pin."""


def script(sites: int = 3) -> str:
    return (
        "  set _n 0\\n"
        "  if {[catch {a}]} {{ incr _n }}\\n"
        "  if {[catch {b}]} {{ incr _n }}\\n"
        "  if {[catch {c}]} {{ incr _n }}\\n"
        "  puts \\"PARTIAL: $_n of 3 repairs refused\\"\\n"
        "  if {$_n >= 3} {{ puts ALL }}\\n"
    )
'''

TEST_PIN = '''\
from thing_emit import script


def test_the_partial_line_states_the_population():
    assert "of 3 repairs refused" in script()
'''


def _tree(tmp_path: Path, emitter: str = EMITTER, pin: str = TEST_PIN) -> tuple:
    progs = tmp_path / "progs"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "thing_emit.py").write_text(emitter, encoding="utf-8")
    (tests / "test_thing_emit.py").write_text(pin, encoding="utf-8")
    return progs, tests


def _run(progs: Path, tests: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), "--programs", str(progs),
         "--tests", str(tests), *[str(x) for x in extra]],
        capture_output=True, text=True, timeout=600)


# ── the honest case ──────────────────────────────────────────────────────────

def test_an_emitter_that_agrees_with_itself_and_its_pin_passes(tmp_path):
    progs, tests = _tree(tmp_path)
    r = _run(progs, tests)
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "denominator(s)" in r.stdout and "test pin(s)" in r.stdout, \
        "the reach is not stated:\n" + r.stdout


def test_the_shipped_corpus_is_clean():
    """The corpus sweep, pinned: this guard must be green on the tree it ships
    in. It is also the file that records the reach — small, and stated."""
    r = subprocess.run(
        [sys.executable, str(PROG), "--programs", str(PROGRAMS_DIR),
         "--tests", str(TESTS_DIR)],
        capture_output=True, text=True, timeout=900)
    assert r.returncode == RC_PASS, r.stdout + r.stderr


# ── check A: the emitter against itself ──────────────────────────────────────

def test_a_fourth_increment_without_moving_the_denominator_is_refused(tmp_path):
    """The lane's mistake, caught before any test runs: a member arrives and
    the printed population does not move."""
    progs, tests = _tree(tmp_path)
    ok = _run(progs, tests)
    assert ok.returncode == RC_PASS, "control arm is not green:\n" + ok.stdout

    src = (progs / "thing_emit.py").read_text()
    (progs / "thing_emit.py").write_text(
        src.replace('"  if {[catch {c}]} {{ incr _n }}\\n"',
                    '"  if {[catch {c}]} {{ incr _n }}\\n"\n'
                    '        "  if {[catch {d}]} {{ incr _n }}\\n"'),
        encoding="utf-8")
    r = _run(progs, tests)
    assert r.returncode == RC_FAIL, "the emitter's own disagreement passed:\n" + r.stdout
    assert "incremented at 4 site(s)" in r.stdout, r.stdout
    assert "says 3" in r.stdout, r.stdout


def test_a_presence_test_is_not_a_population(tmp_path):
    """`$X > 0` means "any at all". Treating it as a denominator would fire on
    every counter in the tree — measured at 8 false findings before the
    `>= MIN_POPULATION` bound existed."""
    progs, tests = _tree(
        tmp_path,
        emitter='def script():\n'
                '    return ("  set _n 0\\n"\n'
                '            "  incr _n\\n"\n'
                '            "  if {$_n > 0} { puts SOME }\\n")\n',
        pin="def test_nothing():\n    assert True\n")
    r = _run(progs, tests)
    assert r.returncode == RC_VACUOUS, r.stdout + r.stderr


# ── check B: the test pin against the emitter ────────────────────────────────

def test_a_pin_naming_a_value_the_emitter_no_longer_states_is_refused(tmp_path):
    progs, tests = _tree(tmp_path)
    src = (progs / "thing_emit.py").read_text()
    (progs / "thing_emit.py").write_text(
        src.replace('"  if {[catch {c}]} {{ incr _n }}\\n"',
                    '"  if {[catch {c}]} {{ incr _n }}\\n"\n'
                    '        "  if {[catch {d}]} {{ incr _n }}\\n"')
           .replace("of 3 repairs refused", "of 4 repairs refused")
           .replace("$_n >= 3", "$_n >= 4"),
        encoding="utf-8")

    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_FAIL, \
        "a stale pin passed after the emitter moved:\n" + r.stdout
    assert "the population moved and the pin did not" in r.stdout, r.stdout
    doc = json.loads((tmp_path / "r.json").read_text())
    stale = [f for f in doc["findings"] if f["check"] == "pin-against-emitter"]
    assert stale and stale[0]["pinned"] == "3" and stale[0]["emitted"] == ["4"], doc


def test_a_docstring_narrative_is_not_a_pin(tmp_path):
    """Both fixtures carry `1 of 2 repairs refused` in a docstring, describing
    what the number USED TO BE. Measured on the shipped tree: without this
    exclusion the guard produced 3 findings and all 3 were prose."""
    progs, tests = _tree(tmp_path)
    r = _run(progs, tests)
    assert r.returncode == RC_PASS, \
        "a docstring recounting an old number was read as a pin:\n" + r.stdout


# ── POLARITY: a statement that DENIES a member is not a member (vibe-ic#712) ─
#
# `counters` read the RAW FILE and matched `incr <name>` and `$<name> >= <D>`
# wherever they appeared, so a sentence DENYING a member counted as one. The
# gate `prose_polarity_consulted_check` named this function on the tree that
# added it (census 214 against a baseline of 213) and was right.
#
# Each fixture below is a TRUTHFUL emitter -- its own site count and its own
# printed denominator agree -- carrying one denial. A reader that cannot tell an
# assertion from a denial refuses it. Every one of these is RED without the fix.

PIN_2 = '''\
from thing_emit import script


def test_the_partial_line_states_the_population():
    assert "of 2 repairs refused" in script()
'''

#: A DENIAL inside the emitted script itself. Removing prose about the code does
#: not remove prose: a script carries comments and `puts` messages, and English
#: there denies as readily as it declares.
EMITTER_DENIED_SITE = '''\
def script() -> str:
    return (
        "  set _n 0\\n"
        "  # the retry path does not incr _n; it re-issues the command\\n"
        "  if {[catch {a}]} {{ incr _n }}\\n"
        "  if {[catch {b}]} {{ incr _n }}\\n"
        "  puts \\"PARTIAL: $_n of 2 repairs refused\\"\\n"
        "  if {$_n >= 2} {{ puts ALL }}\\n"
    )
'''

#: A RETIRED threshold. `_prose_polarity` keeps "removed" / "no longer" in a tier
#: of its own because they retire a value the document still prints in full --
#: which is exactly how a stale denominator survives in a comment.
EMITTER_RETIRED_DENOMINATOR = '''\
def script() -> str:
    return (
        "  set _n 0\\n"
        "  # $_n >= 4 is no longer the threshold, the fourth repair was removed\\n"
        "  if {[catch {a}]} {{ incr _n }}\\n"
        "  if {[catch {b}]} {{ incr _n }}\\n"
        "  if {[catch {c}]} {{ incr _n }}\\n"
        "  puts \\"PARTIAL: $_n of 3 repairs refused\\"\\n"
        "  if {$_n >= 3} {{ puts ALL }}\\n"
    )
'''

#: Prose ABOUT the code -- a docstring and a `#` comment, neither of which the
#: emitted script contains. Both deny the member they name.
EMITTER_PROSE_ABOUT_CODE = '''\
"""History: an earlier revision had a third repair with its own `incr _n`."""


# The third repair was removed, so there is no `incr _n` in the fallback branch.
def script() -> str:
    return (
        "  set _n 0\\n"
        "  if {[catch {a}]} {{ incr _n }}\\n"
        "  if {[catch {b}]} {{ incr _n }}\\n"
        "  puts \\"PARTIAL: $_n of 2 repairs refused\\"\\n"
        "  if {$_n >= 2} {{ puts ALL }}\\n"
    )
'''

#: ONE multi-line literal, so the records inside it are separated by a bare
#: newline and nothing else. This is the fixture that makes the record break
#: load-bearing -- see `test_a_denial_is_bounded_by_the_line_it_is_written_on`.
EMITTER_MULTILINE_BLOCK = (
    'def script() -> str:\n'
    '    return """\n'
    '  set _n 0\n'
    '  puts "no repair could be applied"\n'
    '  if {[catch {a}]} { incr _n }\n'
    '  if {[catch {b}]} { incr _n }\n'
    '  puts "PARTIAL: $_n of 2 repairs refused"\n'
    '  if {$_n >= 2} { puts ALL }\n'
    '"""\n')


def test_a_denied_increment_in_the_script_is_not_a_member(tmp_path):
    """THE DENIAL, FED TO THE EXTRACTOR. `does not incr _n` is a statement that
    there is no third member. Counting it produces a population of 3 for an
    emitter with two sites and a printed denominator of 2, so a BLOCKING gate
    refuses a correct emitter over a number nobody stated -- #706 in the
    counting direction."""
    progs, tests = _tree(tmp_path, EMITTER_DENIED_SITE, PIN_2)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, (
        "a sentence DENYING a member was counted as one:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["findings"] == [], doc
    assert [(d["what"], d["denial"]) for d in doc["denied_by_polarity"]] == [
        ("increment", "not")], doc


def test_a_retired_denominator_in_the_script_is_not_read_as_live(tmp_path):
    """The other half of the same blindness. `$_n >= 4 is no longer the
    threshold` prints the retired number in full; read as a live denominator it
    disagrees with the three sites that do exist."""
    progs, tests = _tree(tmp_path, EMITTER_RETIRED_DENOMINATOR,
                         PIN_2.replace("of 2", "of 3"))
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, (
        "a threshold a sentence RETIRED was read as live:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert [(d["what"], d["matched"]) for d in doc["denied_by_polarity"]] == [
        ("comparison denominator", "$_n >= 4")], doc


def test_prose_about_the_code_is_not_the_emitted_script(tmp_path):
    """The subject half. A docstring and a `#` comment are prose ABOUT the code;
    the script contains neither. `phrases` already excluded docstrings on this
    exact argument and `counters` did not, so one file answered one question two
    ways."""
    progs, tests = _tree(tmp_path, EMITTER_PROSE_ABOUT_CODE, PIN_2)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, (
        "a docstring and a comment contributed members to the script's "
        "population:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["findings"] == [], doc


def test_a_denial_is_bounded_by_the_line_it_is_written_on(tmp_path):
    """THE RECORD BREAK, PINNED, and it is the quiet direction that needs it.

    A script is line-structured: `puts "no repair could be applied"` is its own
    statement and does not reach the `incr` on the next line. Drop
    `extra_breaks=("\\n",)` and the reach runs 240 characters through unrelated
    commands -- every increment and every denominator in this fixture is inside
    that budget with no sentence terminator between them, so all four are
    retracted, the guard compares NOTHING, and it still prints PASS. Asserting
    on the return code alone would not see that, so the reach is asserted.

    The fixture is ONE triple-quoted block on purpose. Separate adjacent string
    literals are joined by `emitted_script` into a blank line, which is already
    a `SENTENCE_BREAK`; only inside a multi-line literal is the declared record
    break the thing doing the work."""
    progs, tests = _tree(tmp_path, EMITTER_MULTILINE_BLOCK, PIN_2)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["denied_by_polarity"] == [], (
        "a denial retracted members it does not govern -- the reach crossed a "
        "record boundary:\n" + json.dumps(doc, indent=2))
    assert doc["counters_examined"] == 2, doc


def test_polarity_did_not_switch_the_population_check_off(tmp_path):
    """THE NEGATIVE CONTROL, and the reason the four tests above are not enough:
    a `counters` that returned nothing at all would pass every one of them.

    Same fixture as the first test -- one denied member -- with a THIRD member
    that nothing denies. The denominator still says 2, so the disagreement is
    real and must still be refused, at the right number."""
    progs, tests = _tree(tmp_path, EMITTER_DENIED_SITE, PIN_2)
    assert _run(progs, tests).returncode == RC_PASS, "control arm is not green"

    src = (progs / "thing_emit.py").read_text()
    (progs / "thing_emit.py").write_text(
        src.replace('"  if {[catch {b}]} {{ incr _n }}\\n"',
                    '"  if {[catch {b}]} {{ incr _n }}\\n"\n'
                    '        "  if {[catch {c}]} {{ incr _n }}\\n"'),
        encoding="utf-8")
    r = _run(progs, tests)
    assert r.returncode == RC_FAIL, (
        "an undenied member arrived and the guard stayed green -- polarity is "
        "suppressing more than the denial:\n" + r.stdout)
    assert "incremented at 3 site(s)" in r.stdout, r.stdout
    assert "says 2" in r.stdout, r.stdout


def test_what_polarity_refused_is_printed_not_quietly_dropped(tmp_path):
    """THE REACH IS PRINTED, ALWAYS -- this guard's own rule, and it now governs
    the matches polarity removed too. A reach that shrank because a denial was
    believed is part of the reach; a guard that silently counts less than it
    read is the defect it exists to catch one level up."""
    progs, tests = _tree(tmp_path, EMITTER_DENIED_SITE, PIN_2)
    r = _run(progs, tests)
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "[POLARITY]" in r.stdout, "the suppression is invisible:\n" + r.stdout
    assert "incr _n" in r.stdout and "DENIES it" in r.stdout, r.stdout
    assert "1 match(es) not counted" in r.stdout, r.stdout


# ── POLARITY on the PIN side: `not in` is a denial, not a pin ────────────────
#
# A pin is an ASSERTION that the emitter states the value. `assert "..." not in
# script()` asserts the opposite, and it is how a test correctly records that a
# population MOVED. Read as a pin it is compared against the emitter's new
# number and refuses a correct test for "the population moved and the pin did
# not" -- while the test is asserting exactly that the population moved.

EMITTER_FOUR = '''\
def script() -> str:
    return (
        "  set _n 0\\n"
        "  if {[catch {a}]} {{ incr _n }}\\n"
        "  if {[catch {b}]} {{ incr _n }}\\n"
        "  if {[catch {c}]} {{ incr _n }}\\n"
        "  if {[catch {d}]} {{ incr _n }}\\n"
        "  puts \\"PARTIAL: $_n of 4 repairs refused\\"\\n"
        "  if {$_n >= 4} {{ puts ALL }}\\n"
    )
'''

#: A CORRECT test: it records that the emitter no longer says the OLD number.
PIN_DENIES_THE_OLD_NUMBER = '''\
from thing_emit import script


def test_the_old_three_repair_wording_is_gone():
    assert "of 3 repairs refused" not in script()
'''

#: An emitter whose own message denies something ELSE in the same breath. It
#: still states `of 3 repairs refused` -- that is one of the strings it prints.
EMITTER_DENIAL_IN_THE_MESSAGE = '''\
def script() -> str:
    return (
        "  set _n 0\\n"
        "  if {[catch {a}]} {{ incr _n }}\\n"
        "  if {[catch {b}]} {{ incr _n }}\\n"
        "  if {[catch {c}]} {{ incr _n }}\\n"
        "  puts \\"NOT_APPLIED: no repair applied, 0 of 3 repairs refused\\"\\n"
        "  if {$_n >= 3} {{ puts ALL }}\\n"
    )
'''


def test_a_test_that_DENIES_a_phrase_is_not_a_pin(tmp_path):
    """MEASURED before the fix: a self-consistent 4-site emitter and a correct
    test that asserts the 3-repair wording is GONE produced rc=1 and one
    finding, with both files correct. The denial is spelled in the CODE (`not
    in`), outside the literal, so the polarity question is asked over the source
    STATEMENT the literal begins in."""
    progs, tests = _tree(tmp_path, EMITTER_FOUR, PIN_DENIES_THE_OLD_NUMBER)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, (
        "a test DENYING a phrase was read as pinning it:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["findings"] == [], doc
    assert doc["pins_examined"] == 0, doc
    # The evidence names the CONSTRUCT, not a word out of the line: the pin
    # side is read on Python's negation grammar, so `not in` is reported rather
    # than the bare "not" a prose vocabulary would have matched.
    assert [(d["what"], d["denial"]) for d in doc["denied_by_polarity"]] == [
        ("test pin", "not in")], doc


def test_the_emitter_side_is_NOT_asked_the_same_question(tmp_path):
    """THE ASYMMETRY, PINNED, because it is the one thing about this fix that a
    later reader would most reasonably try to "tidy up" into symmetry.

    `phrases` answers "what values does this emitter state?" and a value missing
    from that set makes a CORRECT pin look stale. This emitter prints
    `no repair applied, 0 of 3 repairs refused` -- it DOES state
    `of 3 repairs refused`. Ask it for polarity and the tail leaves the emitted
    set entirely, `tail not in em` skips the comparison, and the guard silently
    checks NOTHING while still printing PASS. The return code cannot see that,
    so the REACH is what is asserted."""
    progs, tests = _tree(tmp_path, EMITTER_DENIAL_IN_THE_MESSAGE,
                         PIN_2.replace("of 2", "of 3"))
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["denied_by_polarity"] == [], (
        "the emitter side was asked for polarity and dropped a value it really "
        "does print:\n" + json.dumps(doc, indent=2))
    assert doc["pins_examined"] == 1, (
        "the pin was not compared at all -- CHECK B is disarmed:\n"
        + json.dumps(doc, indent=2))


def test_the_gate_clears_phrases_on_SPELLING_not_on_the_argument():
    """`phrases`' docstring claims the polarity gate clears it for a MECHANICAL
    reason rather than for the argument written above that claim. A claim a
    reader has to take on faith is the shape vibe-ic#712 exists to remove, so it
    is checked here.

    IF THIS GOES RED because the gate's predicate was widened, the fix is to
    update that paragraph in `phrases` -- the clearance has stopped being
    mechanical and the function now needs adjudicating on its merits. Do NOT
    relax this test; its whole job is to make that moment visible."""
    import ast
    import sys
    sys.path.insert(0, str(PROGRAMS_DIR))
    import prose_polarity_consulted_check as G

    fn = {n.name: n for n in ast.walk(ast.parse(PROG.read_text(encoding="utf-8")))
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}["phrases"]

    assert G._searches_prose(fn), "phrases no longer reads prose at all"
    assert G._match_derived_names(fn) == set(), (
        "`m` now enters `derived` -- the for-target gap named in the docstring "
        "has been closed")
    assert G._writes_a_declared_value(fn) is False, (
        "the gate now sees this write; the docstring's account of WHY it was "
        "cleared is stale and must be rewritten, not this assertion")

    # ... and it is only spelling: the record really is keyed AND filled by the
    # match, which is the #706 shape written through `setdefault(...).add(...)`.
    writes = [n for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "add"
              and isinstance(n.func.value, ast.Call)
              and isinstance(n.func.value.func, ast.Attribute)
              and n.func.value.func.attr == "setdefault"]
    assert len(writes) == 1, f"expected one setdefault(...).add(...): {writes}"
    groups = sorted({sub.args[0].value for sub in ast.walk(writes[0])
                     if isinstance(sub, ast.Call)
                     and isinstance(sub.func, ast.Attribute)
                     and sub.func.attr == "group"
                     and sub.args and isinstance(sub.args[0], ast.Constant)})
    assert groups == [1, 2], (
        "the key and the value no longer both come out of the match, so the "
        f"docstring's 'only spelling' account no longer holds: {groups}")


#: Five ways a real emitter spells the same honest script -- three `incr` sites
#: and a denominator of 3. `emitted_script` reads string LITERALS where the
#: pre-polarity revision read the raw file, so each of these is a way the
#: narrowing could have lost a site.
_SPELLINGS = {
    "adjacent literals":
        'def s():\n'
        '    return (\n'
        '        "  if {[catch {a}]} { incr _n }\\n"\n'
        '        "  if {[catch {b}]} { incr _n }\\n"\n'
        '        "  if {[catch {c}]} { incr _n }\\n"\n'
        '        "  if {$_n >= 3} { puts ALL }\\n")\n',
    "one triple-quoted block":
        'def s():\n'
        '    return """\n'
        '  if {[catch {a}]} { incr _n }\n'
        '  if {[catch {b}]} { incr _n }\n'
        '  if {[catch {c}]} { incr _n }\n'
        '  if {$_n >= 3} { puts ALL }\n'
        '"""\n',
    "f-strings":
        'def s(tag):\n'
        '    return (\n'
        '        f"  if {{[catch {{a}}]}} {{ incr _n }} ;# {tag}\\n"\n'
        '        f"  if {{[catch {{b}}]}} {{ incr _n }} ;# {tag}\\n"\n'
        '        f"  if {{[catch {{c}}]}} {{ incr _n }} ;# {tag}\\n"\n'
        '        f"  if {{$_n >= 3}} {{ puts {tag} }}\\n")\n',
    "list append and join":
        'def s():\n'
        '    parts = []\n'
        '    parts.append("  if {[catch {a}]} { incr _n }")\n'
        '    parts.append("  if {[catch {b}]} { incr _n }")\n'
        '    parts.append("  if {[catch {c}]} { incr _n }")\n'
        '    parts.append("  if {$_n >= 3} { puts ALL }")\n'
        '    return "\\n".join(parts)\n',
    "%-format and .format":
        'def s(x):\n'
        '    return ("  if {[catch {a}]} { incr _n } ;# %s" % x\n'
        '            + "\\n  if {[catch {b}]} {{ incr _n }} ;# {0}".format(x)\n'
        '            + "\\n  if {[catch {c}]} { incr _n }"\n'
        '            + "\\n  if {$_n >= 3} { puts ALL }")\n',
}


def test_the_narrowing_loses_no_site_in_any_emitter_spelling():
    """`emitted_script`'s docstring claims "nothing that was matchable stops
    being matchable" when the subject moved from the raw file to the string
    literals. That is a claim about a corpus this tree barely exercises -- it
    holds exactly ONE counter -- so it is measured against constructed spellings
    instead of taken on the one real sample.

    MEASURED against the pre-polarity revision of this file: all five agree,
    site for site and denominator for denominator.

    A SIXTH SPELLING IS DELIBERATELY NOT IN THIS SET, and is named rather than
    quietly dropped: an emitter that builds each repair through a HELPER CALL
    reads as ONE site on both revisions, because K counts `incr` written in the
    source and not times emitted. That is the known limitation recorded under
    "WHAT THIS CANNOT COUNT" in the module docstring; it is not a narrowing
    regression, and asserting today's behaviour here would cement a refusal of
    an honest emitter."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402
    for name, src in _SPELLINGS.items():
        rows, refused = E.counters(src)
        assert refused == [], f"{name}: polarity refused something: {refused}"
        assert len(rows) == 1, f"{name}: expected one counter, got {rows}"
        counter, sites, dens = rows[0]
        assert (counter, sites) == ("_n", 3), f"{name}: read {sites} site(s)"
        assert sorted({v for _, v in dens}) == [3], f"{name}: dens {dens}"


#: How a test spells a pin, and whether it is one. `True` means the line PINS
#: the value (it must be compared against the emitter); `False` means the line
#: DENIES it (comparing it refuses a correct test).
_PIN_SPELLINGS = [
    ('assert "of 3 repairs refused" in script()', True),
    ('assert "of 3 repairs refused" not in script()', False),
    ('assert "of 3 repairs refused" in script(), "no PARTIAL line"', True),
    ('assert "of 3 repairs refused" in script()  # not 2 any more', True),
    ('self.assertNotIn("of 3 repairs refused", script())', False),
    ('assert not any("of 3 repairs refused" in s for s in [script()])', False),
    ('assert script() != "of 3 repairs refused"', False),
]


def test_the_pin_reader_gets_every_negation_spelling_right():
    """THE MEASUREMENT THAT MOVED THIS READER OFF THE PROSE VOCABULARY.

    `pins` first asked `_prose_polarity` over the source statement. Over these
    spellings that got THREE wrong, in BOTH directions -- the assertion MESSAGE
    and the trailing COMMENT each carry a negation word that governs nothing,
    so a real pin was dropped and CHECK B quietly compared less than it read;
    and `assertNotIn` has no word boundary before "Not", so the denial was
    MISSED and the false refusal `pins` exists to stop came straight back.

    A test denies a containment in the ways the LANGUAGE provides, and those are
    productions of Python's grammar -- enumerable and unambiguous. `counters` on
    the other side of this file reads real English and does consult the
    vocabulary; the two readers follow their two subjects.

    The last case is the CONTROL on reach: a negation in a DIFFERENT statement
    must not deny this one."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    head = "from thing_emit import script\n\n\ndef test_p():\n"
    for line, is_a_pin in _PIN_SPELLINGS:
        kept, refused = E.pins(head + "    " + line + "\n")
        assert bool(kept) is is_a_pin, (
            f"{line!r} read as {'a pin' if kept else 'a denial'}; "
            f"refused={refused}")
        assert bool(refused) is (not is_a_pin), (line, refused)

    outer = (head + "    if not script():\n        pass\n"
             + '    assert "of 3 repairs refused" in script()\n')
    kept, refused = E.pins(outer)
    assert kept and not refused, (
        "a negation in an enclosing statement denied an assertion it does not "
        f"govern: {refused}")


#: Every denominator denied AND every pin denied -- polarity empties the reach.
EMITTER_EVERYTHING_DENIED = '''\
def script() -> str:
    return (
        "  set _n 0\\n"
        "  if {[catch {a}]} {{ incr _n }}\\n"
        "  if {[catch {b}]} {{ incr _n }}\\n"
        "  # $_n >= 2 is no longer the threshold, that gate was removed\\n"
        "  puts \\"PARTIAL: 0 of 2 repairs refused\\"\\n"
    )
'''

PIN_DENIES_EVERYTHING = '''\
from thing_emit import script


def test_the_old_wording_is_gone():
    assert "of 2 repairs refused" not in script()
'''


def test_polarity_cannot_empty_the_reach_into_a_PASS(tmp_path):
    """THE PROPERTY THE WHOLE POLARITY CHANGE TURNS ON, and the one it would be
    worst to get wrong.

    Consulting polarity can only ever REMOVE things from what this guard
    compares. That is safe exactly while an emptied reach is reported as
    VACUOUS -- "nothing was compared, this is NOT a pass" -- and catastrophic
    the moment it prints PASS instead, because then a denial anywhere in an
    emitted script becomes a way to switch a blocking gate off and be thanked
    for it with a green line.

    So the extreme is exercised rather than reasoned about: an emitter whose
    only denominator sits in a sentence retiring it, and a test whose only
    phrase it DENIES. rc must be 2, the words "NOT a pass" must be printed, and
    the `[POLARITY]` line must name what was removed -- an emptied reach that
    does not say why is the silent direction wearing a verdict."""
    progs, tests = _tree(tmp_path, EMITTER_EVERYTHING_DENIED,
                         PIN_DENIES_EVERYTHING)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    out = r.stdout + r.stderr
    assert r.returncode == RC_VACUOUS, (
        "polarity emptied the reach and the guard did not say so:\n" + out)
    assert "NOT a pass" in out, out
    assert "VACUOUS_PASS:" in out, out
    assert "[POLARITY]" in r.stdout, (
        "the reach was emptied without naming what removed it:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["counters_examined"] == 0 and doc["pins_examined"] == 0, doc
    assert len(doc["denied_by_polarity"]) == 2, doc


def test_a_source_that_will_not_parse_is_REPORTED_not_silently_skipped(tmp_path):
    """THE ONE DIRECTION THE NARROWING COULD QUIETLY LOSE.

    `counters` used to read the RAW FILE, so a program with a syntax error was
    still regex-scanned and its `incr` sites still counted. Reading the AST
    instead means an unparseable file yields nothing -- MEASURED, the same
    fixture gives 2 sites to a raw-text scan and `[]` to `counters` -- and a
    reach that shrank because a file would not parse is still a shrunken reach.

    It is not a FAILURE: a syntax error is another gate's business, and this one
    refusing would be it answering a question it was not asked. It is a stated
    NON-EXAMINATION, which is this file's own rule -- the reach is printed,
    always -- and it appears in the head line and in the JSON so a run that read
    less than the tree holds says so in both places.

    The tree ships 0 unparseable programs today; this exists for the version
    skew that makes one, where the failure would otherwise be invisible."""
    progs, tests = _tree(tmp_path)
    src = (progs / "thing_emit.py").read_text()
    (progs / "thing_emit.py").write_text(src + "\n\ndef newer(x)  :::\n    pass\n",
                                         encoding="utf-8")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    out = r.stdout + r.stderr
    assert "[UNPARSED]" in r.stdout, (
        "a source this guard could not read left the reach in silence:\n" + out)
    assert "thing_emit.py" in r.stdout and "could NOT read it" in r.stdout, out
    doc = json.loads((tmp_path / "r.json").read_text())
    assert len(doc["unparsed"]) == 1, doc
    assert doc["unparsed"][0].startswith("thing_emit.py:"), doc
    assert "source(s) NOT examined because they would not parse" in r.stdout, out
    # and nothing was invented from a file that could not be read
    assert doc["counters_examined"] == 0, doc


def test_a_parseable_tree_reports_nothing_unparsed(tmp_path):
    """The control on the sentence above: the count is a MEASUREMENT, not a
    label that is always printed as zero."""
    progs, tests = _tree(tmp_path)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "[UNPARSED]" not in r.stdout, r.stdout
    assert json.loads((tmp_path / "r.json").read_text())["unparsed"] == []


# ── the vacuous tier ─────────────────────────────────────────────────────────

def test_a_tree_stating_no_population_twice_is_vacuous_and_says_so(tmp_path):
    progs = tmp_path / "p"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "quiet.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    r = _run(progs, tests)
    assert r.returncode == RC_VACUOUS, r.stdout + r.stderr
    assert "VACUOUS_PASS:" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "NOT a pass" in r.stdout, r.stdout


# ── the bad invocation tier ──────────────────────────────────────────────────

def test_a_programs_directory_that_does_not_exist_is_rc3(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), "--programs", str(tmp_path / "nope")],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == RC_USAGE, r.stdout + r.stderr
    assert "USAGE_ERROR:" in r.stderr, r.stderr


def test_an_unknown_flag_is_rc3_not_argparse_2():
    r = subprocess.run([sys.executable, str(PROG), "--not-a-flag"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == RC_USAGE, r.stdout + r.stderr


# ── discrimination: revert the rule, the refusal disappears ──────────────────

def test_reverting_the_comparison_lets_the_disagreement_pass(tmp_path):
    """THE MUTATION ARM. Both checks reduce to one comparison each; neutering
    them makes the fixture that is refused above pass."""
    progs, tests = _tree(tmp_path)
    src = (progs / "thing_emit.py").read_text()
    (progs / "thing_emit.py").write_text(
        src.replace('"  if {[catch {c}]} {{ incr _n }}\\n"',
                    '"  if {[catch {c}]} {{ incr _n }}\\n"\n'
                    '        "  if {[catch {d}]} {{ incr _n }}\\n"'),
        encoding="utf-8")
    honest = _run(progs, tests)
    assert honest.returncode == RC_FAIL, "control arm is not red:\n" + honest.stdout

    source = PROG.read_text(encoding="utf-8")
    mutant_body = (source
                   .replace("                if value != sites:",
                            "                if False:")
                   .replace("                if value not in emitted:",
                            "                if False:"))
    assert mutant_body.count("if False:") == 2, \
        "the mutation did not apply — one of the two rules moved"
    mutant = tmp_path / "mutant.py"
    mutant.write_text(mutant_body, encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(mutant), "--programs", str(progs),
         "--tests", str(tests)],
        capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONPATH": str(PROGRAMS_DIR)})
    assert r.returncode == RC_PASS, (
        "the mutant still refused, so the refusal does not come from the "
        "comparisons this test names:\n" + r.stdout + r.stderr)
