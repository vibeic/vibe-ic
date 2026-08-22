"""`emitter_population_pin_check` must refuse a population that is stated twice
and disagrees with itself.

HOW MUCH OF THIS SUITE ACTUALLY COVERS THE FIX
==============================================
"Every fix ships with a test that goes RED without the fix" is easy to satisfy
one commit at a time and easy to stop satisfying. Measured by swapping in
3c3c51aee's 326-line program and running this file against it:

    77 of 94 RED, 17 green.

Ten of the seventeen are the author's originals, which test behaviour that
already worked. The other seven are: two that read files other than the
program (the CI wiring, the polarity baseline), four that pin PRE-EXISTING
behaviour against regression, and one structural invariant that held before as
well. None is vacuous.

(Re-measured at this branch's tip. The figure read 67 of 83 for several
commits after the suite had grown past 83 -- a count of the tests that exist
goes stale the moment one is added, which is the same fault this file records
against the program's own docstring. Re-derive it, never re-read it: swap
3c3c51aee's program in and run this file.)

IF THIS AREA GOES RED FOR A REVIEWER OR A RE-MEASURE, READ THIS FIRST
====================================================================
`test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships`
bounds its subprocess at `timeout=55` -- WALL CLOCK, at three call sites -- and
its subject is `prose_polarity_consulted_check.py` over the whole corpus.

That subject is not a fixed cost, and the spread is not a smooth function of
load. Measured on this machine: 10.8s to 13.0s across most runs, one run of
19.4s at a load average near 20 with three runs of 10.9-11.3s at the SAME load
minutes later, and it has been OBSERVED failing at 58.25s under a load average
of 71 and passing on the next run with nothing changed. So a red there can mean
the census is broken, or it can mean the machine was busy at that moment, and
the two are not distinguishable from the failure alone. Do not read a single
timing as the cost; the 19.4s figure was an outlier and is quoted as one.

To tell them apart, run the gate DIRECTLY:

    python3 programs/prose_polarity_consulted_check.py ; echo $?

rc 0 means the census is intact and the test hit its wall clock. rc 1 means a
real polarity-blind extractor and the number it names is the finding.

This note lives HERE because the bound lives in a file this branch may not
loosen, and a warning nobody can find is not a warning. It is not this file's
growth: the program is 0.18% of the corpus by bytes, and the gate measures the
same with it swapped back to the author's 326-line revision.

MUTATION, TWO SWEEPS  --  MEASURED 2026-08-22, PINNED, NOT RE-DERIVED
=====================================================================
Every figure in this section is a RECORD OF A SWEEP THAT WAS RUN, not a claim
about the tree as it stands. The guard sweep was recorded in 88d63d0131
against `emitter_population_pin_check.py` blob c6612e5ec; the statement-parent
figures in 725283fc19 against blob 452cde7bd. Both 2026-08-22, both under
#712. The program has changed since (blob 566b30e2e today), so these numbers
are pinned to the trees named above and nothing here maintains them. That is
the distinction `derived_corpus_figure_check` exists to draw: re-deriving them
would destroy the record of what the sweep actually found, and leaving them
bare would read as a claim about today.

Guards: every `if ...: continue` in the program deleted in turn -- 20 sites, 8
survived, 4 of which were real gaps and are now covered (see "guards a mutation
sweep found nothing was holding"). Three of the remaining four are fast paths,
not guards: deleting them leaves the shipped tree's --json byte identical. The
fourth, `if isinstance(up, ast.stmt)`, is EQUIVALENT, and now says so with a
proof rather than a shrug: every form that walk tests for is an `ast.expr`,
and an expression is never the parent of a statement -- 602,938
statement-parent edges over 3,965 files of this tree, zero with an expression
parent. The premise that argument needs is pinned by
`test_the_statement_stop_rests_on_a_true_premise`.

Boundaries (same sweep, same pin: 2026-08-22, 88d63d0131, blob c6612e5ec):
every comparison operator flipped to its neighbour -- `>=`<->`>`,
`<`<->`<=`, `==`<->`!=`. 12 sites, ZERO survivors, including the two that carry
the semantics: `value < MIN_POPULATION` (the population floor) and
`sites > value` (the lower-bound rule, where an equality false-PASS was fixed
earlier on this branch). Reproduce by rewriting the file through `ast.unparse`
with one op flipped; the un-mutated round trip passes, so the harness itself is
not what fails.

Constants: every integer constant outside an f-string incremented by one -- 37
sites, 32 caught, 5 survivors, and each survivor is EQUIVALENT rather than
uncovered:

    rfind("\n", 0, at) + 1   both the 0 and the +1: `lstrip()` absorbs the
                             one-character shift, and searching from 1 differs
                             only if a newline sits at index 0
    calls.get(host, 0) > 1   with a default of 1 the test is still False
    max(out.get(k, 0), ...)  `calls[host]` is >= 2 on that path, so the max
                             does not move
    json.dumps(indent=2)     whitespace of the `--json -` document; pinning it
                             would be specifying the formatting, not the report

Argued AND measured: each leaves the shipped tree's --json byte identical.

The first attempt at this arm was discarded, not reported: it matched sites by
`lineno`/`col_offset`, and constants inside f-strings carry bogus positions on
this interpreter, so it edited sites other than the ones it named -- its
"survivors" pointed at docstring prose, which is how the instrument was caught.
Mutating by INDEX during one walk uses no positions and has none of that.

THE SWAP RUN THE OTHER WAY, because "my tests pass" is not the same claim as
"the author's contract still holds": 3c3c51aee's ORIGINAL test file, unmodified,
against this program -- 10 passed. Exactly one of the author's test bodies
differs here at all, `test_the_shipped_corpus_is_clean`, and only in taking the
shared `real_run` fixture instead of spawning its own subprocess; its single
assertion is AST-identical, compared node by node. A fixture can narrow where a
literal command cannot, so
`test_the_shared_run_really_sweeps_the_whole_shipped_tree` checks the sweep
against the tree on disk -- measured: point the fixture at a subdirectory and
the author's test still passes while that one fails.

Three did have to be fixed to reach that number. They asserted only that a
marker was ABSENT -- which a program with no such tier passes trivially, so they
would have survived the feature being deleted. They now assert the tier RAN and
reported zero. Re-run the swap to reproduce; a test drifting onto the green list
is a test that stopped covering the thing it names.

MEASURED 2026-08-21: a lane added a THIRD repair to a post-route block, moved the
emitter's own printed denominator from two to three, and left the test asserting
the old ratio. The population moved and the pin did not, so the test failed for
the right reason with the wrong message.

The fixtures below are synthetic on purpose. Driving this against the live
`phase3_one_shot_runner` would pin THIS program's verdict to that program's
current repair count, which is the very defect under test one level up.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/<this file>

GREPPING THIS FILE FOR `^def test_` OVERCOUNTS. Several fixtures are synthetic
test files written to disk, and they contain `def test_...` at column 0 inside a
string. Measured: 47 real top-level test functions, 50 text matches, and pytest
collects 47 -- nothing is shadowed or dropped, the three extras are fixture
contents. Use the AST, or `--collect-only`, when the count matters.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
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


#: ONE run of this guard over the real tree, for the whole module.
#:
#: It costs ~9.7s -- it parses every program and every test in the tree -- and
#: TWO tests need it. Paying twice made this module 22.6s where 39 of its other
#: tests cost 2.6s between them, so a single duplicated corpus sweep was 79% of
#: the runtime. The neighbouring `test_issue712_prose_polarity` solved the same
#: problem the same way and wrote down why; this follows it.
#:
#: Deterministic and read-only, so sharing is safe: the guard writes only the
#: JSON it is asked for.
@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("realrun") / "r.json"
    r = subprocess.run(
        [sys.executable, str(PROG), "--programs", str(PROGRAMS_DIR),
         "--tests", str(TESTS_DIR), "--json", str(out)],
        capture_output=True, text=True, timeout=900)
    return r, json.loads(out.read_text())


def test_no_counter_with_a_threshold_is_silently_missed():
    """The verdict reads `3 ... COMPARED out of 1238 program(s) SCANNED`, and a
    reader is entitled to ask whether the extractor is simply blind.

    Pinned as a RELATIONSHIP, not as a total: every program whose emitted script
    increments a counter either yields a comparable population, or states no
    numeric threshold on that counter for there to be anything to compare. A
    program that states BOTH and yields nothing is the extractor going quietly
    narrow, which is the failure this file exists to refuse."""
    import ast as _ast
    import re as _re
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E

    missed, considered = [], []
    for prog in sorted(PROGRAMS_DIR.glob("*.py")):
        try:
            tree = _ast.parse(prog.read_text(errors="replace"))
        except SyntaxError:
            continue
        script = E.emitted_script_of(tree)
        for name in set(E.INCR.findall(script)):
            # A POPULATION, on this program's own terms. One `incr` is an
            # accumulator, not a population stated twice, and `$_ci < 5` is a
            # loop bound, not a denominator -- the first version of this probe
            # ignored both and reported three false misses in
            # phase3_one_shot_runner. The instrument was wrong, not the code.
            sites = len(_re.findall(r"\bincr\s+" + _re.escape(name) + r"\b",
                                    script))
            if sites < E.MIN_POPULATION:
                continue
            if not _re.search(r"\$" + _re.escape(name) + r"\s*(>=|==)\s*\d+",
                              script):
                continue
            considered.append((prog.name, name))
            rows, _refused = E.counters_of(tree)
            if not any(r[0] == name and r[2] for r in rows):
                missed.append((prog.name, name))

    # A PROBE THAT EXAMINED NOTHING PROVES NOTHING. If `emitted_script_of` ever
    # returns empty, `missed` is empty too and this test passes while checking
    # no tree at all.
    assert considered, (
        "this probe found no emitted counter to check anywhere in the corpus, "
        "so its silence is not evidence")
    assert not missed, (
        "these emitted counters state a membership at MIN_POPULATION sites or "
        "more AND a literal threshold, and this guard compared neither: "
        + repr(missed))


def test_the_shared_run_really_sweeps_the_whole_shipped_tree(real_run):
    """`test_the_shipped_corpus_is_clean` is the author's, and the ONE change
    this branch made to it was replacing its own subprocess with this fixture --
    its assertion is AST-identical, checked. But a fixture can narrow where a
    literal command could not: point it at a subdirectory and the author's test
    still passes, over less.

    So the sweep is checked against the tree itself, using the corpus disclosure
    the verdict now carries."""
    _r, doc = real_run
    on_disk_programs = len(list(PROGRAMS_DIR.glob("*.py")))
    on_disk_tests = len(list(TESTS_DIR.rglob("test_*.py")))
    assert doc["corpus"] == {"programs": on_disk_programs,
                             "tests": on_disk_tests}, (
        "the shared run did not cover the shipped tree -- the author's corpus "
        f"test is passing over less than it did: {doc['corpus']} vs "
        f"{{'programs': {on_disk_programs}, 'tests': {on_disk_tests}}}")
    assert on_disk_programs > 100 and on_disk_tests > 100, (
        "the tree this ran against holds almost nothing, so agreement with it "
        "is not evidence")


def test_the_shipped_corpus_is_clean(real_run):
    """The corpus sweep, pinned: this guard must be green on the tree it ships
    in. It is also the file that records the reach — small, and stated."""
    r, _ = real_run
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
    the script contains neither. `phrases_of` already excluded docstrings on this
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
    literals are joined by `emitted_script_of` into a blank line, which is already
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

    # BOTH DIRECTIONS, because `sentence_scope` clamps forward and backward in
    # ONE loop and the fixture above only places the denial BEFORE the sites. A
    # broken FORWARD clamp leaves that arm green while a later line's denial
    # silently retracts earlier members -- the quiet direction, again.
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402
    deny = '  puts "no repair could be applied"'
    site = '  if {[catch {%s}]} { incr _n }'
    den = '  if {$_n >= 2} { puts ALL }'
    for where, lines in (
            ("before", [deny, site % "a", site % "b", den]),
            ("after", [site % "a", site % "b", deny, den]),
            ("between", [site % "a", deny, site % "b", den])):
        rows, refused = E.counters(
            'def s():\n    return """\n' + "\n".join(lines) + '\n"""\n')
        assert refused == [], f"{where}: the reach crossed a record boundary"
        assert rows and rows[0][1] == 2, f"{where}: sites {rows}"
        assert sorted({v for _, _, d in rows for _, v in d}) == [2], where


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

    `phrases_of` answers "what values does this emitter state?" and a value missing
    from that set makes a CORRECT pin look stale. This emitter prints
    `no repair applied, 0 of 3 repairs refused` -- it DOES state
    `of 3 repairs refused`. Ask it for polarity and the tail leaves the emitted
    set entirely, `tail not in em` skips the comparison, and the guard silently
    checks NOTHING while still printing PASS. The return code cannot see that,
    so the REACH is what is asserted.

    NEGATIVE CONTROL, MEASURED, because this test's value is entirely in
    catching a change nobody has made yet and its red against the pre-fix
    program (3c3c51aee)
    program was only a `KeyError` on an absent JSON key -- a weak red, and said
    so when it landed. Adding the symmetry itself to `phrases_of`

        if is_denied(node.value):        # skip a message that also denies
            continue

    takes it red on the assertion that matters, "the pin was not compared at all
    -- CHECK B is disarmed", and takes `test_polarity_cannot_empty_the_reach_
    into_a_PASS` with it. So the tidy-up this test exists to stop is caught by
    the property, not by an accident of the fixture."""
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


# ── what the polarity gate does and does not see ────────────────────────────────
#
def test_the_gate_clears_phrases_on_SPELLING_not_on_the_argument():
    """`phrases_of`' docstring claims the polarity gate clears it for a MECHANICAL
    reason rather than for the argument written above that claim. A claim a
    reader has to take on faith is the shape vibe-ic#712 exists to remove, so it
    is checked here.

    IF THIS GOES RED because the gate's predicate was widened, the fix is to
    update that paragraph in `phrases_of` -- the clearance has stopped being
    mechanical and the function now needs adjudicating on its merits. Do NOT
    relax this test; its whole job is to make that moment visible."""
    import ast
    import sys
    sys.path.insert(0, str(PROGRAMS_DIR))
    import prose_polarity_consulted_check as G

    fn = {n.name: n for n in ast.walk(ast.parse(PROG.read_text(encoding="utf-8")))
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}["phrases_of"]

    assert G._searches_prose(fn), "phrases_of no longer reads prose at all"
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
#: and a denominator of 3. `emitted_script_of` reads string LITERALS where the
#: pre-polarity revision (3c3c51aee) read the raw file, so each of these is a
#: way the
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


# ── the narrowing: the emitted script, not the file that prints it ──────────────
#
def test_the_narrowing_loses_no_site_in_any_emitter_spelling():
    """`emitted_script_of`'s docstring claims "nothing that was matchable stops
    being matchable" when the subject moved from the raw file to the string
    literals. That is a claim about a corpus this tree barely exercises -- it
    holds exactly ONE counter -- so it is measured against constructed spellings
    instead of taken on the one real sample.

    MEASURED against the pre-polarity revision of this file -- 3c3c51aee,
    NAMED because `origin/land/batch68-assembled` has since advanced onto the
    first four commits of this work and re-running the comparison against the
    batch head now compares this code with ITSELF: all five agree, site for
    site and denominator for denominator. Re-verified against 3c3c51aee after
    the batch moved; 0 diverging spellings.

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
    # Found by testing the ENUMERATION rather than trusting the word
    # "enumerable": these two read as PINS until `is not` and `assertFalse`
    # were added, which put the false refusal back for those spellings.
    ('assert "of 3 repairs refused" is not script()', False),
    ('self.assertFalse("of 3 repairs refused" in script())', False),
    ('self.assertIsNot(script(), "of 3 repairs refused")', False),
    # The AFFIRMING forms, which must stay pins. `assertTrue`/`assertEqual` are
    # deliberately not in the denial set; treating them as denials would drop
    # real pins, which is the silent direction.
    ('self.assertIn("of 3 repairs refused", script())', True),
    ('self.assertTrue("of 3 repairs refused" in script())', True),
    ('self.assertEqual(script(), "of 3 repairs refused")', True),
    # A comparison only denies a literal it is a SIDE of. These AFFIRM the
    # phrase; reading their `!=` as a denial drops a real pin, and a dropped
    # pin is the silent direction -- CHECK B compares one fewer thing and
    # still prints PASS.
    ('assert script().count("of 3 repairs refused") != 0', True),
    ('assert script().count("of 3 repairs refused") > 0', True),
    # and a denial of something ELSE in the same statement must not reach it
    ('assert "of 3 repairs refused" in script() and "zz" not in script()', True),
]


# ── the PIN reader's negation grammar, spelling by spelling ─────────────────────
#
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

    head = "from thing_emit import script\n\n\ndef test_p(self):\n"
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


# ── polarity may not manufacture a PASS ─────────────────────────────────────────
#
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


# ── what could not be read is REPORTED, never dropped ───────────────────────────
#
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
    # Padded so the break is DEEP in the file: a hardcoded or off-by-one line
    # number would still look plausible at the top and cannot hide here. The
    # expected line is computed from the fixture, never written down twice.
    pad = "".join(f"# filler {i}\n" for i in range(1, 21))
    broken = pad + src + "\n\ndef newer(x)  :::\n    pass\n"
    (progs / "thing_emit.py").write_text(broken, encoding="utf-8")
    break_line = next(i for i, ln in enumerate(broken.splitlines(), 1)
                      if ":::" in ln)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    out = r.stdout + r.stderr
    # THE VERDICT, not only the report. thing_emit.py is the ONLY program here
    # and it no longer parses, so nothing is compared -- that is VACUOUS, and a
    # test that checked the [UNPARSED] line alone would have gone green on a
    # PASS, which is precisely the manufactured pass this file refuses.
    assert r.returncode == RC_VACUOUS, (
        "the only program could not be read, so nothing was compared and this "
        "must not read as a pass:\n" + out)
    assert "[UNPARSED]" in r.stdout, (
        "a source this guard could not read left the reach in silence:\n" + out)
    assert "thing_emit.py" in r.stdout and "could NOT read it" in r.stdout, out
    doc = json.loads((tmp_path / "r.json").read_text())
    assert len(doc["unparsed"]) == 1, doc
    assert doc["unparsed"][0].startswith(f"thing_emit.py:{break_line}:"), (
        "the report does not send the reader to the line that would not parse "
        f"(expected {break_line}): {doc['unparsed']}")
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


# ── cost: no parsed tree outlives the answer taken from it ──────────────────────
#
def test_no_parsed_tree_outlives_the_answer_taken_from_it():
    """MEASURED REGRESSION, PINNED STRUCTURALLY.

    An earlier revision of this guard cached `ast.parse` results per program so
    both checks could share one parse. It shared the parse and kept ~820 ASTs
    live, two of them over 2 MB of source: peak RSS went 221 MB -> 596 MB, and
    the allocator and GC pressure that buys made EVERY parse in the run about
    twice as slow -- including parses of files the cache never touched, which is
    why the cost did not look like it came from the cache. On this fleet memory
    is a named constraint, so the rule is: derive the small answer, drop the
    tree.

    Asserted on the SOURCE because a memory ceiling in a unit test would be a
    bound that is legal and unreliable: no module-level or closure name may hold
    an `ast.parse` result across iterations. The `*_of` functions take a tree as
    an ARGUMENT and return a dict, a string or a list -- never the tree -- and
    every call site parses into a temporary.

    If this goes red because a cache was reintroduced, measure peak RSS before
    deciding it is fine: the last one looked obviously correct too."""
    import ast
    src = PROG.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    main_fn = fns["main"]

    # THE FAILURE SHAPE IS STORING THE TREE ITSELF: `cache[key] = ast.parse(...)`
    # or `t = ast.parse(...)` followed by `cache[key] = t`. Passing a parse
    # THROUGH a deriving call -- `cache[key] = phrases_of(ast.parse(...))` -- is
    # the CORRECT shape and must stay legal: the tree is a temporary and is
    # unreachable the moment the call returns. Matching "an ast.parse appears
    # anywhere inside the stored value" would forbid the fix along with the bug.
    def _is_parse(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "parse")

    tree_names = {t.id for n in ast.walk(main_fn)
                  if isinstance(n, ast.Assign) and _is_parse(n.value)
                  for t in n.targets if isinstance(t, ast.Name)}
    for n in ast.walk(main_fn):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript)
                                             for t in n.targets):
            held = (_is_parse(n.value)
                    or (isinstance(n.value, ast.Name) and n.value.id in tree_names))
            assert not held, (
                "a parsed tree is being stored in a container; that is the "
                "596 MB shape -- store what you derived from it instead")

    # ... and the tree-taking cores return a derived value, never their input.
    for name in ("phrases_of", "pins_of", "counters_of", "emitted_script_of"):
        assert name in fns, f"{name} is gone; the parse-once design changed"
        returns = [n for n in ast.walk(fns[name])
                   if isinstance(n, ast.Return) and n.value is not None]
        assert returns, name
        for r in returns:
            assert not (isinstance(r.value, ast.Name)
                        and r.value.id == "tree"), (
                f"{name} returns its input tree, which lets a caller cache it")


_BLIND_EXTRACTOR = '''
import re
RE = re.compile(r"targets (\\w+)")
def extract(text, rec):
    m = RE.search(text)
    if m:
        rec["pdk_target"] = m.group(1)
    return rec
'''


# ── the polarity gate is sealed against its own sharpening ──────────────────────
#
def test_the_polarity_baseline_refuses_to_grow(tmp_path):
    """`phrases_of`' docstring cites this to explain why the polarity gate cannot
    simply be sharpened: a wider predicate makes pre-existing extractors visible
    all at once, and the debt register MAY ONLY SHRINK, so it cannot take them.

    Cited behaviour gets checked, not trusted -- that is the whole shape of
    #712. Built here on a synthetic tree so it costs a few milliseconds instead
    of a scan of the real one, and so it tests the RULE rather than today's
    census number.

    This is not an argument for relaxing that rule. The rule is what stops the
    register becoming a waiver list. It is recorded so the next person reads
    "sealed by design, and here is the proof" instead of rediscovering it."""
    import sys
    sys.path.insert(0, str(PROGRAMS_DIR))
    import prose_polarity_consulted_check as G  # noqa: E402

    root = tmp_path / "t"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "one.py").write_text(_BLIND_EXTRACTOR)
    prog = str(PROGRAMS_DIR / "prose_polarity_consulted_check.py")

    def run(*extra):
        return subprocess.run([sys.executable, prog, "--root", str(root), *extra],
                              capture_output=True, text=True, timeout=120)

    assert run("--write-baseline").returncode == 0
    assert G.scan(root) == ["one::extract"]

    # a SECOND pre-existing blind extractor becomes visible
    (root / "programs" / "two.py").write_text(_BLIND_EXTRACTOR)
    assert run().returncode == 1, "a grown set passed"
    r = run("--write-baseline")
    assert r.returncode == 1, (
        "the baseline absorbed growth; it has become a waiver list:\n"
        + r.stdout + r.stderr)
    assert "GREW" in (r.stdout + r.stderr), r.stdout + r.stderr
    # and the file on disk still holds the SMALLER set
    import json as _json
    kept = _json.loads(
        (root / "programs" / "prose_polarity_baseline.json").read_text())["known"]
    assert kept == ["one::extract"], kept


# ── ... and the test side reads through a different branch ──────────────────────
#
def test_a_TEST_that_will_not_parse_is_reported_too(tmp_path):
    """THE OTHER HALF OF THE UNPARSED REACH, and it had no test until it was
    looked for: `test_a_source_that_will_not_parse_is_REPORTED_not_silently_
    skipped` breaks a PROGRAM, and CHECK B reads test files through a different
    branch entirely.

    It matters as much. A test file that will not parse is a PIN this guard did
    not check, and the pre-`pins` code could not even tell that case apart from
    "this test names no program" -- both came back as `None` from
    `named_program`, which is why that function now takes a tree the caller has
    already parsed.

    Found by asking which lines of this program no test drives, rather than by
    remembering. The instrument for that was poor -- the suite runs the guard as
    a SUBPROCESS, `trace` cannot follow it and `coverage` is not installed here
    -- so it was used as a HINT and this branch was then checked by hand and
    pinned. An unmeasured coverage number would have been worse than none."""
    progs, tests = _tree(tmp_path)
    good = (tests / "test_thing_emit.py").read_text()
    broken = good + "\n\ndef newer(x)  :::\n    pass\n"
    (tests / "test_thing_emit.py").write_text(broken, encoding="utf-8")
    break_line = next(i for i, ln in enumerate(broken.splitlines(), 1)
                      if ":::" in ln)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    out = r.stdout + r.stderr
    # THE VERDICT. Here the EMITTER still parses and its own two denominators
    # agree with its three sites, so something IS compared and the run is a real
    # PASS carrying the [UNPARSED] line -- the opposite of the companion test
    # above, and the reason both verdicts are now asserted rather than assumed
    # to be the same.
    assert r.returncode == RC_PASS, (
        "a broken TEST took the emitter's own self-check down with it:\n" + out)
    assert "[UNPARSED]" in r.stdout, (
        "an unreadable TEST left the reach in silence:\n" + out)
    assert "test_thing_emit.py" in r.stdout, out
    doc = json.loads((tmp_path / "r.json").read_text())
    assert len(doc["unparsed"]) == 1, doc
    assert doc["unparsed"][0].endswith(f":{break_line}: invalid syntax"), (
        "the report does not send the reader to the line that would not parse "
        f"(expected {break_line}): {doc['unparsed']}")
    assert "test_thing_emit.py" in doc["unparsed"][0], doc
    # the pin is gone from the reach, and says so ...
    assert doc["pins_examined"] == 0, doc
    # ... while the PROGRAM side is untouched: a broken test must not take the
    # emitter's own self-check down with it.
    assert doc["counters_examined"] > 0, doc
    assert doc["findings"] == [], doc


#: The denial is WRAPPED: the words that deny sit on the line above the `incr`
#: they govern. This is the cost `_RECORD_BREAKS` knowingly accepts.
# The wrapped denial moved from COMMENT lines to PRINTED ones. Not to make a
# test pass: `_in_an_emitted_comment` now drops a commented `incr` whatever its
# polarity, so the comment-borne version counts 2 -- the RIGHT answer -- and the
# under-reach it demonstrated is simply gone there. The cost itself is not gone;
# measured, a denial wrapped across two PRINTED lines still yields 3 sites
# against a denominator of 2. The assertions below are unchanged; only the
# vehicle moved to where the phenomenon still lives.
EMITTER_WRAPPED_DENIAL = (
    'def script() -> str:\n'
    '    return """\n'
    '  puts "the third repair is deliberately absent: there is no"\n'
    '  puts "incr _n in the fallback branch"\n'
    '  if {[catch {a}]} { incr _n }\n'
    '  if {[catch {b}]} { incr _n }\n'
    '  puts "PARTIAL: $_n of 2 repairs refused"\n'
    '  if {$_n >= 2} { puts ALL }\n'
    '"""\n')


# ── the cost `_RECORD_BREAKS` accepts, and that it is LOUD ──────────────────────
#
def test_the_accepted_under_reach_fails_LOUDLY(tmp_path):
    """THE COST OF `_RECORD_BREAKS`, DEMONSTRATED RATHER THAN ASSERTED.

    That declaration says a script is line-structured, and it is chosen on an
    argument about WHICH failure is silent: without it the reach runs 240
    characters through unrelated commands and one `puts "no repair applied"`
    quietly retracts every denominator near it; with it, a denial WRAPPED across
    two emitted lines is missed and a phantom member is counted.

    The whole justification is that the second failure is LOUD -- "a REFUSAL a
    reader sees, and answers". A cost accepted on that ground has to be shown to
    actually be loud, or the ground is just a sentence. MEASURED here: rc=1,
    and BOTH numbers are printed --

        counter $_n is incremented at 3 site(s) but its comparison denominator
        says 2

    -- so a reader has the mismatch and the counter name, and finds the wrapped
    comment. Compare the silent direction, which would print PASS.

    THIS IS NOT A TEST THAT THE BEHAVIOUR IS RIGHT. The count of 3 is WRONG;
    there are two repairs. It pins that being wrong here is ANNOUNCED, which is
    the property the design was chosen for. Its companion is
    `test_a_denial_is_bounded_by_the_line_it_is_written_on`, which pins the same
    declaration from the other side."""
    # (The same wrapping inside COMMENT lines no longer miscounts at all --
    # see `test_a_wrapped_denial_in_a_comment_no_longer_miscounts` -- so this
    # fixture states the denial in `puts` lines, where the cost is still real.)
    progs, tests = _tree(tmp_path, EMITTER_WRAPPED_DENIAL, PIN_2)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_FAIL, (
        "the miscount was not announced -- the accepted cost has become the "
        "silent one, and `_RECORD_BREAKS` no longer has its argument:\n"
        + r.stdout + r.stderr)
    assert "incremented at 3 site(s)" in r.stdout, r.stdout
    assert "says 2" in r.stdout, r.stdout
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["denied_by_polarity"] == [], (
        "the wrapped denial was seen after all; if the reach now crosses a "
        f"record boundary, both this and its companion need re-deciding: {doc}")


#: One emitted Tcl line per denominator kind `_DEN_TEMPLATES` recognises. Each
#: states a population of 4 for an emitter with two `incr` sites.
_DENOMINATOR_KINDS = {
    "comparison": '  if {$_n >= 4} { puts ALL }',
    "ratio": '  puts "($_n/4) refused"',
    "prose": '  puts "PARTIAL: $_n of 4 repairs refused"',
}


def _emitter_with(tcl_lines):
    """A two-site emitter whose script is `tcl_lines`, correctly escaped."""
    body = 'def s():\n    return (\n'
    body += '        "  if {[catch {a}]} { incr _n }\\n"\n'
    body += '        "  if {[catch {b}]} { incr _n }\\n"\n'
    for t in tcl_lines:
        body += '        %r\n' % (t + "\n")
    return body + '    )\n'


# ── SWEPT SPACES: every kind, route, form and boundary ──────────────────────────
#
def test_polarity_reaches_every_denominator_kind(tmp_path):
    """`counters_of` asks polarity about EVERY literal denominator, and
    `_DEN_TEMPLATES` recognises three kinds. Only `comparison` was ever
    exercised, so a change that applied the consult to the first kind and not
    the rest would have gone unnoticed -- and it would fail in the confident
    direction: a retired `($_n/4)` or `of 4 repairs` read as live, refusing a
    truthful emitter over a number nobody stated.

    Swept rather than sampled, and each kind is checked in BOTH states: the
    undenied line must be found and compared, the denied one must be refused AND
    reported under its own kind name, so the evidence tells a reader which of
    the three was dropped."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    for kind, line in _DENOMINATOR_KINDS.items():
        rows, refused = E.counters(_emitter_with([line]))
        found = sorted({v for _, _, dens in rows for _, v in dens})
        assert found == [4], f"{kind}: not recognised at all, got {found}"
        assert refused == [], f"{kind}: undenied line was refused: {refused}"

        retired = "  # " + line.strip() + " is no longer the threshold"
        rows, refused = E.counters(_emitter_with([retired]))
        found = sorted({v for _, _, dens in rows for _, v in dens})
        assert found == [], (
            f"{kind}: a RETIRED denominator was read as live -- polarity does "
            f"not reach this kind: {found}")
        assert [r[0] for r in refused] == [f"{kind} denominator"], (
            f"{kind}: refused under the wrong name, so the evidence would not "
            f"say which kind was dropped: {refused}")


#: Every route by which a test in this tree names the program it exercises,
#: plus the two shapes that must resolve to None.
_NAMING_ROUTES = [
    ("from X import ...",      "from thing_emit import script\n",        "thing_emit"),
    ("import X",               "import thing_emit\n",                    "thing_emit"),
    ("import pkg.X",           "import pkg.thing_emit\n",                "thing_emit"),
    ("path literal X.py",      'P = "thing_emit.py"\n',                  "thing_emit"),
    ("path literal dir/X.py",  'P = "programs/thing_emit.py"\n',         "thing_emit"),
    ("names two programs",     "import thing_emit\nimport other_emit\n", None),
    ("names no program",       "import os\n",                            None),
]


def test_every_route_a_test_names_its_program_by(tmp_path):
    """`named_program` decides which emitter a pin belongs to, so a route it
    fails to recognise silently removes that test's pins from CHECK B -- the
    quiet direction. Only `from X import ...` was exercised, and this branch
    changed the function's SIGNATURE (it takes the caller's parsed tree now),
    which is exactly when the unexercised routes are worth checking.

    THE TWO `None` ROWS ARE THE POINT OF THAT SIGNATURE CHANGE. None must mean
    "names 0 or more than 1 program" and nothing else. It used to also mean
    "this file would not parse", which made a test the guard COULD NOT READ
    indistinguishable from one that names nothing -- the reach shrank in
    silence. Parsing is the caller's job now and an unreadable file is REPORTED;
    see `test_a_TEST_that_will_not_parse_is_reported_too`. This test pins the
    other half: None still means ambiguity, and ambiguity is still refused."""
    import ast
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    stems = {"thing_emit", "other_emit"}
    for label, src, want in _NAMING_ROUTES:
        got = E.named_program(ast.parse(src), stems)
        assert got == want, (
            f"{label}: resolved to {got!r}, expected {want!r} -- a route that "
            f"stops resolving takes that test's pins out of CHECK B without "
            f"saying so")


#: A two-site emitter, to which each prose form below is prepended.
_TWO_SITE_TAIL = ('def s():\n    return (\n'
                  '        "  if {[catch {a}]} { incr _n }\\n"\n'
                  '        "  if {[catch {b}]} { incr _n }\\n"\n'
                  '        "  if {$_n >= 2} { puts ALL }\\n")\n')

#: Every way prose about the code can mention `incr _n` without the emitted
#: script containing it. None may contribute a member.
_PROSE_FORMS = {
    "module docstring":
        '"""history: a third repair had its own incr _n."""\n\n\n' + _TWO_SITE_TAIL,
    "f-string docstring":
        'V = 3\nf"""a third repair had its own incr _n, rev {V}."""\n\n\n'
        + _TWO_SITE_TAIL,
    "function docstring":
        _TWO_SITE_TAIL.replace(
            'def s():\n', 'def s():\n    """a third repair had incr _n."""\n'),
    "class docstring":
        'class C:\n    """a third repair had its own incr _n."""\n\n\n'
        + _TWO_SITE_TAIL,
    "bare block string":
        _TWO_SITE_TAIL.replace(
            'def s():\n', 'def s():\n    "a third repair had incr _n"\n'),
    "hash comment":
        '# a third repair had its own incr _n\n' + _TWO_SITE_TAIL,
    "control: no prose at all": _TWO_SITE_TAIL,
}


def test_no_form_of_prose_about_the_code_enters_the_script():
    """`_emitted_nodes` decides what counts as emitted, and everything else in
    this file trusts that decision. Its docstring claims a string that is an
    expression STATEMENT is never emitted -- and, specifically, that an f-string
    docstring's PARTS are skipped with it, because `ast.walk` reaches each inner
    `Constant` on its own and skipping the `JoinedStr` alone would let the same
    prose back in through the other door.

    THAT SECOND CLAIM IS LOAD-BEARING AND WAS UNTESTED. MEASURED by making
    exactly the mistake it warns about -- `skip.add(id(n.value))` in place of
    the walk over its parts:

        plain docstring      sites=2      unaffected
        f-string docstring   sites=3      the prose became a member

    Every form is swept rather than sampled because they reach the skip set by
    different routes, and the failure is the confident direction: a phantom
    member makes a truthful emitter disagree with its own denominator."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    for name, src in _PROSE_FORMS.items():
        rows, refused = E.counters(src)
        sites = rows[0][1] if rows else 0
        assert sites == 2, (
            f"{name}: prose about the code entered the script and the "
            f"population became {sites}")
        assert refused == [], f"{name}: {refused}"


def _two_site_emitter_stating(line):
    """A two-`incr` emitter whose script is exactly `line`."""
    body = 'def s():\n    return (\n'
    body += '        "  if {[catch {a}]} { incr _n }\\n"\n' * 2
    return body + '        %r\n    )\n' % (line + "\n")


def test_the_population_floor_holds_at_exactly_two(tmp_path):
    """`MIN_POPULATION` separates a POPULATION from a PRESENCE TEST, and the
    boundary is where an off-by-one lives. It is unguarded and this branch
    restructured the line that enforces it -- from an inline
    `value >= MIN_POPULATION and ...` into an early `continue` -- so the
    restructure is checked rather than assumed.

    BOTH DIRECTIONS COST, and they are not symmetric. Admitting D=1 is noise:
    the file records 8 false findings over this corpus before the bound existed.
    Dropping D=2 is worse and quieter -- a genuine two-member population simply
    stops being compared, and the guard still prints PASS. So the row that
    matters most is D=2, the first real population.

    Swept over all three denominator kinds, because the bound is applied once
    for a loop that runs over `_DEN_TEMPLATES` and a kind could be excluded
    from it without any single-kind test noticing."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    assert E.MIN_POPULATION == 2, (
        "the floor moved; this test states 2 in its own name and reasoning and "
        "must be re-read, not re-pointed")
    kinds = {
        "comparison": '  if {$_n >= %d} { puts ALL }',
        "ratio": '  puts "($_n/%d) refused"',
        "prose": '  puts "PARTIAL: $_n of %d repairs refused"',
    }
    for kind, tmpl in kinds.items():
        for d in (0, 1):
            rows, _ = E.counters(_two_site_emitter_stating(tmpl % d))
            found = sorted({v for _, _, dens in rows for _, v in dens})
            assert found == [], (
                f"{kind}: `{d}` was read as a population, not a presence test "
                f"-- that is the 8-false-findings shape: {found}")
        for d in (2, 3):
            rows, _ = E.counters(_two_site_emitter_stating(tmpl % d))
            found = sorted({v for _, _, dens in rows for _, v in dens})
            assert found == [d], (
                f"{kind}: `{d}` is a real population and stopped being "
                f"compared -- silently: {found}")


#: TWO counters in one emitted script. `_a` is honest. `_b` carries a phantom
#: site inside a DENYING comment and a RETIRED threshold, so both polarity paths
#: fire on one counter while the other must be untouched.
EMITTER_TWO_COUNTERS = (
    'def s():\n    return (\n'
    '        "  if {[catch {x}]} { incr _a }\\n"\n'
    '        "  if {[catch {y}]} { incr _a }\\n"\n'
    '        "  if {$_a >= 2} { puts A }\\n"\n'
    '        "  # the retry path does not incr _b; it re-issues\\n"\n'
    '        "  if {[catch {p}]} { incr _b }\\n"\n'
    '        "  if {[catch {q}]} { incr _b }\\n"\n'
    '        "  if {[catch {r}]} { incr _b }\\n"\n'
    '        "  # $_b >= 9 is no longer the threshold\\n"\n'
    '        "  if {$_b >= 3} { puts B }\\n")\n')


def test_two_counters_in_one_script_do_not_contaminate_each_other():
    """`counters_of` keeps one `refused` list for the whole script while
    counting each name separately, and every other test here uses exactly ONE
    counter -- so a bug that attributed a denial to the wrong counter, or let
    one counter's denied site suppress another's, had nowhere to show.

    Both failure directions are covered by the one fixture: `_b`'s phantom site
    and retired threshold must be dropped from `_b` and MUST NOT touch `_a`,
    which is honest at 2 sites and a denominator of 2. If the two ever share
    state, `_a` moves -- and `_a` moving is the silent kind, because a guard
    that quietly stops comparing a correct counter still prints PASS.

    The real tree has exactly one counter, so this shape is not reachable from
    the shipped corpus and only a constructed input can reach it."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    rows, refused = E.counters(EMITTER_TWO_COUNTERS)
    sites = {name: n for name, n, _ in rows}
    dens = {name: sorted(v for _, v in d) for name, _, d in rows}

    assert sites == {"_a": 2, "_b": 3}, (
        f"a counter's site count moved; the two are sharing state: {sites}")
    assert dens == {"_a": [2], "_b": [3]}, (
        f"a denominator crossed counters or a retired one survived: {dens}")
    # both of `_b`'s denials fired, and each names `_b` in its evidence
    assert len(refused) == 2, refused
    for what, matched, word in refused:
        assert "_b" in matched, (
            f"a denial on `_b` was recorded against something else: "
            f"{what} {matched!r} ({word})")


#: Two literals that are NOT adjacent in the real script -- `_mid()` runs
#: between them -- and neither carries a newline of its own, so only the JOIN
#: keeps them apart. The second denies; the first holds a member.
EMITTER_NON_ADJACENT_LITERALS = (
    'def _mid():\n    return "  # unrelated\\n"\n\n\n'
    'def s():\n    return (\n'
    '        "  if {[catch {a}]} { incr _n }"\n'
    '        + _mid()\n'
    '        + "  puts \\"no repair could be applied\\""\n'
    '        + "\\n  if {[catch {b}]} { incr _n }"\n'
    '        + "\\n  if {$_n >= 2} { puts ALL }")\n')


def test_literals_that_are_not_adjacent_cannot_lend_each_other_a_polarity():
    """`emitted_script_of` claims that joining with a NEWLINE rather than
    concatenating stops two literals which are not adjacent in the real script
    -- anything assembled through a call between them -- from fusing into one
    statement and lending each other a polarity. That was an argument with
    nothing holding it up.

    MEASURED by making the change it argues against, `"".join` in place of
    `"\\n".join`:

        joined by a newline   sites=2   refused=[]
        concatenated          sites=1   refused=[('increment', 'no')]

    So the claim is load-bearing, and the failure it prevents is the SILENT
    one: a real member disappears because a denial from a DIFFERENT part of the
    script reached it, and the guard then compares a population of 1 against a
    denominator of 2 -- or, with one fewer site, agrees and prints PASS.

    This is the shape the helper-assembled emitter under "WHAT THIS CANNOT
    COUNT" is NOT: there the count is wrong and LOUD. Here it would be wrong and
    quiet, which is why the join is not a stylistic choice."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    rows, refused = E.counters(EMITTER_NON_ADJACENT_LITERALS)
    assert refused == [], (
        "a denial reached across the seam between two literals that are not "
        f"adjacent in the emitted script: {refused}")
    assert rows and rows[0][1] == 2, (
        f"a member was lost to a neighbouring literal's polarity: {rows}")
    assert sorted({v for _, _, d in rows for _, v in d}) == [2], rows


#: Unreadable, and reachable by BOTH checks: it contains `incr ` so CHECK A
#: opens it, and a test names it so `emitter_phrases` opens it too.
EMITTER_BROKEN_AND_NAMED = (
    'def s():\n    return "  incr _n\\n  if {$_n >= 2} {}\\n"\n\n\n'
    'def newer(x)  :::\n    pass\n')
PIN_NAMES_THE_BROKEN_ONE = (
    'from thing_emit import s\n\n\ndef test_p():\n'
    '    assert "of 2 repairs refused" in s()\n')


def test_one_unreadable_file_is_counted_once_not_once_per_check(tmp_path):
    """`record_unparsed` exists because both checks can reach the same file,
    and its docstring calls a reach report that counts one file twice "its own
    small lie". Nothing held that up.

    The reach report is this guard's honesty mechanism -- it is what lets a
    reader tell "nothing to compare" from "I could not read the tree" -- so a
    report that inflates it is worse than a merely uninformative one. MEASURED
    by removing the dedupe on a file that BOTH checks open:

        with dedupe      1 entry    "1 source(s) NOT examined"
        without          2 entries  "2 source(s) NOT examined"   for ONE file

    The fixture reaches both paths on purpose: it contains `incr ` so CHECK A
    parses it, and a test names it so `emitter_phrases` parses it too. It also
    lands on the VACUOUS tier, which is where an inflated count would be read
    most literally -- nothing was compared, so the only numbers a reader has are
    these."""
    progs, tests = _tree(tmp_path, EMITTER_BROKEN_AND_NAMED,
                         PIN_NAMES_THE_BROKEN_ONE)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    out = r.stdout + r.stderr
    assert r.returncode == RC_VACUOUS, out
    doc = json.loads((tmp_path / "r.json").read_text())
    assert len(doc["unparsed"]) == 1, (
        f"one unreadable file was counted once per check: {doc['unparsed']}")
    assert r.stdout.count("[UNPARSED]") == 1, r.stdout
    assert "1 source(s) NOT examined" in r.stdout, (
        "the head overstates how much of the tree went unread:\n" + r.stdout)


# ── EVIDENCE: a refusal must send the reader to the right place ─────────────────
#
def test_a_refused_pin_points_at_the_phrase_not_the_keyword(tmp_path):
    """A refusal is only useful if it sends the reader to the right line. This
    branch already requires the COUNTER side's evidence to name the counter it
    belongs to; the PIN side had no such check, and its `where` is the only
    thing telling a reader which of a test file's assertions was not compared.

    Two cases, and the second is the one that discriminates:

      * a denial on a known line, with padding above it, so a hardcoded or
        off-by-one line number shows;
      * a MULTI-LINE assertion, where the `assert` keyword and the phrase are on
        DIFFERENT lines. `where` must point at the PHRASE -- that is what the
        reader is searching for -- and not at the keyword.

    `pins_of` uses the literal's own `lineno` for exactly this, which is why the
    multi-line case lands on the phrase."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import emitter_population_pin_check as E  # noqa: E402

    emitter = ('def script() -> str:\n    return (\n'
               '        "  if {[catch {a}]} { incr _n }\\n"\n'
               '        "  if {[catch {b}]} { incr _n }\\n"\n'
               '        "  puts \\"PARTIAL: $_n of 2 repairs refused\\"\\n"\n'
               '        "  if {$_n >= 2} { puts ALL }\\n")\n')
    padded = ("from thing_emit import script\n\n\n"           # 1-3
              "def test_a():\n    assert True\n\n\n"           # 4-7
              "def test_gone():\n    x = 1\n"                  # 8-9
              '    assert "of 2 repairs refused" not in script()\n')   # 10
    progs, tests = _tree(tmp_path, emitter, padded)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    # THE VERDICT, not only the evidence. This test pinned where the refusal
    # points and never checked what the run concluded, so the guard could have
    # started REFUSING this fixture -- a denying assertion is not a pin, so
    # nothing here disagrees -- and it would still have gone green.
    assert r.returncode == RC_PASS, (
        "a test that DENIES a phrase was read as pinning it:\n"
        + r.stdout + r.stderr)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["findings"] == [], doc
    denied = doc["denied_by_polarity"]
    assert len(denied) == 1, denied
    assert denied[0]["where"].endswith(":10"), (
        f"the refusal points at the wrong line: {denied[0]['where']}")

    multiline = ("from thing_emit import script\n\n\n"        # 1-3
                 "def test_gone():\n"                          # 4
                 "    assert (\n"                              # 5  keyword
                 '        "of 2 repairs refused"\n'            # 6  phrase
                 "        not in script())\n")                 # 7
    kept, refused = E.pins(multiline)
    assert kept == {}, kept
    assert [ln for _, ln, _ in refused] == [6], (
        "the refusal points at the `assert` keyword rather than the phrase the "
        f"reader is looking for: {refused}")


EMITTER_HONEST_TWO_SITES = (
    'def s():\n    return (\n'
    '        "  if {[catch {a}]} { incr _h }\\n"\n'
    '        "  if {[catch {b}]} { incr _h }\\n"\n'
    '        "  if {$_h >= 2} { puts ALL }\\n")\n')

EMITTER_WITH_A_DENIED_SITE = (
    'def s():\n    return (\n'
    '        "  # the retry path does not incr _d; it re-issues\\n"\n'
    '        "  if {[catch {p}]} { incr _d }\\n"\n'
    '        "  if {[catch {q}]} { incr _d }\\n"\n'
    '        "  if {$_d >= 2} { puts ALL }\\n")\n')


def test_a_refusal_names_the_program_it_came_from(tmp_path):
    """The counter side's `where`, across TWO programs -- which every other
    fixture on this branch lacks, so it has been trivially right until now.

    This is the same property already pinned for the PIN side (a refusal points
    at the phrase's line) and for the two-counter case (a refusal names the
    counter). Checking it on one side and not the others is how a standard ends
    up half-applied, which is what this test exists to stop.

    The files are named so ALPHABETICAL order puts the honest one FIRST: a
    `where` taken from the wrong variable, or captured outside the per-program
    loop, reports `aa_honest.py` and sends the reader to a file with nothing
    wrong in it. Both programs must still be examined -- the denial in one must
    not curtail the other."""
    progs = tmp_path / "p"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "aa_honest.py").write_text(EMITTER_HONEST_TWO_SITES, encoding="utf-8")
    (progs / "zz_denied.py").write_text(EMITTER_WITH_A_DENIED_SITE, encoding="utf-8")
    (tests / "test_x.py").write_text("def test_x():\n    assert True\n",
                                     encoding="utf-8")

    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["findings"] == [], doc
    assert [(d["where"], d["matched"]) for d in doc["denied_by_polarity"]] == [
        ("zz_denied.py", "incr _d")], (
        "the refusal names the wrong program -- a reader sent to a file with "
        f"nothing wrong in it: {doc['denied_by_polarity']}")
    assert doc["counters_examined"] == 2, (
        f"a denial in one program curtailed the other: {doc}")


EMITTER_REFUSED_WITH_A_DENIAL = (
    'def s():\n    return (\n'
    '        "  # the retry path does not incr _n; it re-issues\\n"\n'
    '        "  if {[catch {a}]} { incr _n }\\n"\n'
    '        "  if {[catch {b}]} { incr _n }\\n"\n'
    '        "  if {[catch {c}]} { incr _n }\\n"\n'
    '        "  if {$_n >= 2} { puts ALL }\\n")\n')


# ── the reach is printed on EVERY verdict path ──────────────────────────────────
#
def test_the_reach_survives_a_REFUSAL(tmp_path):
    """"THE REACH IS PRINTED, ALWAYS" is this guard's own rule, and this branch
    has pinned it on the PASS path and on the VACUOUS path. Not on FAIL -- which
    is where a reader needs it most, because a refusal is the one verdict that
    sends someone to change code.

    A finding says "these two numbers disagree". The reach says how much of the
    tree those numbers came from, what polarity declined to count, and what
    could not be read at all. Without it a refusal looks like a complete account
    of the tree when it may be an account of one file out of two.

    The fixture carries all three signals at once on a REFUSED run: a genuine
    disagreement (3 sites against a denominator of 2), a polarity refusal (the
    phantom fourth site written into a comment that denies it), and an
    unreadable neighbour. All three must appear beside the refusal, not be
    displaced by it."""
    progs = tmp_path / "p"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "thing_emit.py").write_text(EMITTER_REFUSED_WITH_A_DENIAL,
                                         encoding="utf-8")
    (progs / "broken.py").write_text(
        'def s():\n    return "  incr _z\\n"\n\ndef q(  :::\n', encoding="utf-8")
    (tests / "test_x.py").write_text("def test_x():\n    assert True\n",
                                     encoding="utf-8")

    r = _run(progs, tests)
    out = r.stdout
    assert r.returncode == RC_FAIL, out + r.stderr
    fail = [l for l in out.splitlines() if l.startswith("[FAIL]")]
    assert len(fail) == 1, out
    # EVERY field the head carries, derived from the head itself rather than
    # listed by hand -- a reach field added later must not be able to slip in
    # unchecked, which is exactly what happened to `NOT DECIDABLE`.
    for fragment in ("emitted counter denominator(s)", "test pin(s) COMPARED",
                     "not counted because the statement DENIES them",
                     "NOT examined because they would not parse",
                     "population(s) NOT DECIDABLE"):
        assert fragment in fail[0], (
            f"the refusal does not state its reach ({fragment!r} missing) -- it "
            f"reads as a complete account of the tree:\n{fail[0]}")
    assert "[POLARITY]" in out, (
        "what polarity declined to count vanished behind the refusal:\n" + out)
    assert "[UNPARSED]" in out, (
        "a file that could not be read vanished behind the refusal:\n" + out)

    # THE COUNT OF FIELDS, not just the ones named above. The list is a hand
    # written thing and drifts; the head's own shape does not. A PASS run of the
    # same guard states its reach in the same number of clauses, so a field
    # added to one verdict and not the other shows up here.
    clean = _run(*_tree(tmp_path / "clean"))
    passing = [l for l in clean.stdout.splitlines() if l.startswith("[PASS]")]
    assert passing, clean.stdout
    assert fail[0].count(";") == passing[0].count(";"), (
        "the refusal states fewer reach clauses than a pass does:\n"
        f"  FAIL: {fail[0]}\n  PASS: {passing[0]}")


# ── K: a COUNT, or a LOWER BOUND ─────────────────────────────────────────────
#
EMITTER_HELPER_ASSEMBLED = (
    'def _repair(name):\n'
    '    return "  if {[catch {%s}]} { incr _n }\\n" % name\n\n\n'
    'def script():\n    return ("  set _n 0\\n" + _repair("a") + _repair("b")\n'
    '            + _repair("c") + "  if {$_n >= 3} { puts ALL }\\n")\n')


def test_a_helper_assembled_population_is_NOT_DECIDABLE_not_refused(tmp_path):
    """The false refusal this file recorded as a limitation, and then fixed --
    because the reason recorded for leaving it was measured to be wrong.

    The emitter is HONEST: three repairs, denominator 3. K counts `incr` written
    in the SOURCE, so it saw 1 and refused. `multiplied_counters` now decides
    per counter whether K is a count or a lower bound, and where it is a lower
    bound a shortfall is exactly what a helper called N times produces.

    It is NOT DECIDABLE, and NOT A PASS IN DISGUISE -- which this test asserted
    wrongly when it first landed. It required rc=PASS, and the guard duly printed
    "every population stated twice agrees" having compared NOTHING: the only
    counter present was declined, and `counters_examined` had already been
    incremented before the decline, keeping the run out of the VACUOUS tier.
    That is the manufactured-PASS shape this file is built to refuse, and my
    expectation encoded it. The count now happens only once a comparison is
    actually made, and the correct verdict here is VACUOUS -- "nothing was
    compared; this is NOT a pass".

    Second fixture: the SAME undecidable counter beside a decidable one. There
    something IS compared, so the verdict is a real PASS carrying the
    [NOT DECIDABLE] line -- which is what the first fixture would have looked
    like if it had had anything to compare."""
    progs, tests = _tree(tmp_path, EMITTER_HELPER_ASSEMBLED,
                         "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode != RC_FAIL, (
        "an honest helper-assembled emitter is still refused:\n" + r.stdout)
    assert r.returncode == RC_VACUOUS, (
        "the only counter present was declined, so nothing was compared and "
        "this must not read as a pass:\n" + r.stdout)
    assert "NOT a pass" in r.stdout, r.stdout
    assert "[NOT DECIDABLE]" in r.stdout, (
        "the guard stopped comparing without saying so:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["findings"] == [], doc
    assert doc["counters_examined"] == 0, (
        f"a declined comparison was counted as examined: {doc}")
    assert len(doc["not_determined"]) == 1, doc
    assert doc["not_determined"][0]["emitted_per_site"] == 3, doc

    # ... and with something decidable beside it, a real PASS that still says so
    both = EMITTER_HELPER_ASSEMBLED.replace(
        '            + _repair("c") + "  if {$_n >= 3} { puts ALL }\\n")\n',
        '            + _repair("c") + "  if {$_n >= 3} { puts ALL }\\n"\n'
        '            + "  if {[catch {y}]} { incr _m }\\n"\n'
        '            + "  if {[catch {z}]} { incr _m }\\n"\n'
        '            + "  if {$_m >= 2} { puts M }\\n")\n')
    progs2, tests2 = _tree(tmp_path / "two", both,
                           "def test_x():\n    assert True\n")
    r2 = _run(progs2, tests2, "--json", tmp_path / "r2.json")
    assert r2.returncode == RC_PASS, r2.stdout + r2.stderr
    assert "[NOT DECIDABLE]" in r2.stdout, r2.stdout
    doc2 = json.loads((tmp_path / "r2.json").read_text())
    assert doc2["counters_examined"] == 1 and len(doc2["not_determined"]) == 1, doc2


def test_a_lower_bound_that_EXCEEDS_the_denominator_is_still_refused(tmp_path):
    """THE CONTROL, and the reason this change is not a relaxation. Reading K as
    a lower bound only excuses a SHORTFALL. Four sites per helper call against a
    denominator of 3 is a disagreement no amount of multiplication explains, and
    it must still be refused -- which is also the direction the lane defect
    lives in ("add a fourth repair and `of 3` is wrong")."""
    emitter = EMITTER_HELPER_ASSEMBLED.replace(
        '    return "  if {[catch {%s}]} { incr _n }\\n" % name\n',
        '    return "  if {[catch {%s}]} { incr _n }\\n  { incr _n }\\n'
        '  { incr _n }\\n  { incr _n }\\n" % name\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    r = _run(progs, tests)
    assert r.returncode == RC_FAIL, (
        "a real disagreement was excused as undecidable:\n" + r.stdout)
    assert "incremented at 4 site(s)" in r.stdout, r.stdout


def test_the_real_tree_has_no_undecidable_population(real_run):
    """The shipped corpus must be untouched by the change. `_prr_refused` --
    the only counter that reaches a comparison -- has its `incr` literals INLINE
    in `_postroute_repair_estimate_tcl`, which is called once, so it is a count
    and stays fully compared. Ten other counters in that file DO qualify as
    lower bounds, and none of them states a denominator, so none reaches a
    verdict either way."""
    r, doc = real_run
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert doc["not_determined"] == [], (
        "the change moved a verdict on the shipped tree: "
        + json.dumps(doc["not_determined"], indent=2))
    assert doc["counters_examined"] == 3, doc


# The same shape as EMITTER_DENIED_INCR_IN_A_HELPER, with the denial on a
# PRINTED line instead of a comment line. That difference is the whole point:
# once a commented `incr` stopped being a site, the comment version was skipped
# by EITHER rule, so neither was individually necessary -- deleting the polarity
# consult in `multiplied_counters` outright left all 88 tests green. Measured.
EMITTER_DENIED_INCR_PRINTED_IN_A_HELPER = (
    'def _unused(name):\n'
    '    return "  puts \\"the fallback does not incr _n; it re-issues %s\\"\\n" % name\n\n\n'
    'def script():\n    return ("  set _n 0\\n"\n'
    '            + _unused("a") + _unused("b")\n'
    '            + "  if {[catch {x}]} { incr _n }\\n"\n'
    '            + "  if {$_n >= 2} { puts ALL }\\n")\n')


def test_a_denial_on_a_PRINTED_line_still_cannot_excuse_a_disagreement(tmp_path):
    """The polarity consult in `multiplied_counters`, made necessary again.

    Its companion states the denial in a comment, and since a commented `incr`
    stopped being a site that fixture is skipped by either rule -- so it no
    longer proves the consult does anything. Measured: with only that test,
    deleting the consult left the whole suite green, and the test went on
    passing under a name describing work it no longer forced.

    Here the denial is PRINTED. The comment rule does not apply, so the consult
    is the only thing standing between a denied `incr` and a lower-bound excuse
    for a real disagreement."""
    progs, tests = _tree(tmp_path, EMITTER_DENIED_INCR_PRINTED_IN_A_HELPER,
                         "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_FAIL, (
        "a denied `incr` on a printed line was read as evidence of a "
        "multiplier and excused a real disagreement:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["not_determined"] == [], doc
    assert len(doc["findings"]) == 1, doc
    assert any(d["what"] == "increment" for d in doc["denied_by_polarity"]), doc


EMITTER_DENIED_INCR_IN_A_HELPER = (
    'def _unused(name):\n'
    '    return "  # the fallback does not incr _n; it re-issues %s\\n" % name\n\n\n'
    'def script():\n    return ("  set _n 0\\n"\n'
    '            + _unused("a") + _unused("b")\n'
    '            + "  if {[catch {x}]} { incr _n }\\n"\n'
    '            + "  if {$_n >= 2} { puts ALL }\\n")\n')


def test_a_DENIED_incr_cannot_excuse_a_real_disagreement(tmp_path):
    """TWO READERS OF ONE SCRIPT MUST NOT DISAGREE ABOUT A DENIAL -- which is
    #711 itself, and it was live in the first revision of `multiplied_counters`
    on this branch.

    The emitter has ONE real increment and a denominator of 2: a genuine
    disagreement that must be REFUSED. Beside it sits a helper, called twice,
    whose only `incr _n` is DENIED by its own comment. `counters_of` refused
    that increment as a member -- correctly -- while `multiplied_counters`
    counted it as evidence of a multiplier, marked the counter a LOWER BOUND,
    and excused the disagreement as NOT DECIDABLE.

    MEASURED: rc went 1 -> 0. A real disagreement silently excused, by the
    second reader of the same text being polarity-blind -- the exact defect
    class this file was written to answer, introduced by the fix for the
    limitation two commits earlier.

    The honest helper emitter must still be NOT DECIDABLE, which the companion
    test asserts: the repair is polarity, not a retreat from the lower-bound
    rule."""
    progs, tests = _tree(tmp_path, EMITTER_DENIED_INCR_IN_A_HELPER,
                         "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_FAIL, (
        "a denied `incr` was read as evidence of a multiplier and excused a "
        "real disagreement:\n" + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["not_determined"] == [], doc
    assert len(doc["findings"]) == 1, doc
    # and the denial is still reported by the reader that DOES honour it
    assert any(d["what"] == "increment" for d in doc["denied_by_polarity"]), doc


def test_the_vacuous_tier_says_WHY_it_is_empty(tmp_path):
    """Two different facts had one sentence. "No emitted population is stated
    twice here" is FALSE when one WAS stated twice and this guard declined to
    decide it -- and on the vacuous path that sentence is nearly all a reader
    gets, because no finding was printed.

    The distinction is not cosmetic. "Nothing to compare" means the tree is
    silent on the question; "everything was withheld" means the tree spoke and
    the guard would not judge. The first is a fact about the design, the second
    a fact about this program's reach -- and only the second is a reason to come
    back and look.

    The machine-readable token that `_vacuous_exit` announces is distinguished
    too, so a harness can tell them apart without parsing English."""
    declined = ('def _repair(name):\n'
                '    return "  if {[catch {%s}]} { incr _n }\\n" % name\n\n\n'
                'def script():\n    return ("  set _n 0\\n" + _repair("a")\n'
                '            + _repair("b") + _repair("c")\n'
                '            + "  if {$_n >= 3} { puts ALL }\\n")\n')
    nothing = 'def script():\n    return "  puts hello\\n"\n'
    pin = "def test_x():\n    assert True\n"

    progs, tests = _tree(tmp_path / "declined", declined, pin)
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert r.returncode == RC_VACUOUS, out
    assert "WITHHELD from comparison" in r.stdout, (
        "a tree that DID state a population twice was reported as silent on "
        "it:\n" + r.stdout)
    assert "declined-every-comparison" in out, out

    progs, tests = _tree(tmp_path / "nothing", nothing, pin)
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert r.returncode == RC_VACUOUS, out
    assert "no emitted population is stated twice here" in r.stdout, r.stdout
    assert "no-population-stated-twice" in out, out
    assert "WITHHELD" not in r.stdout, (
        "a silent tree was reported as having had something withheld:\n"
        + r.stdout)


def test_a_NOT_DECIDABLE_line_names_where_and_why(tmp_path):
    """The last reader-facing line on this branch never held to the evidence
    standard the others do. Every existing assertion checks only that the
    substring `[NOT DECIDABLE]` appears -- so a line naming the wrong program,
    the wrong counter, or no numbers at all would have passed them all.

    It is the ONLY thing a reader gets about a comparison the guard declined, so
    it has to carry all four facts: WHERE (which program), WHAT (which counter),
    the numbers that make it undecidable (sites, and the multiplier that
    explains the shortfall), and the denominator it declined to compare against.

    Two programs, named so ALPHABETICAL order puts the honest one FIRST: a
    `where` captured outside the per-program loop reports `aa_honest.py` and
    sends the reader to a file with nothing undecidable in it. That failure is
    the one already pinned for polarity refusals; this is the same standard,
    applied to the line that did not have it."""
    honest = ('def script():\n    return (\n'
              '        "  if {[catch {a}]} { incr _h }\\n"\n'
              '        "  if {[catch {b}]} { incr _h }\\n"\n'
              '        "  if {$_h >= 2} { puts ALL }\\n")\n')
    declined = ('def _repair(name):\n'
                '    return "  if {[catch {%s}]} { incr _d }\\n" % name\n\n\n'
                'def script():\n    return ("  set _d 0\\n" + _repair("a")\n'
                '            + _repair("b") + _repair("c")\n'
                '            + "  if {$_d >= 3} { puts ALL }\\n")\n')
    progs = tmp_path / "p"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "aa_honest.py").write_text(honest, encoding="utf-8")
    (progs / "zz_declined.py").write_text(declined, encoding="utf-8")
    (tests / "test_x.py").write_text("def test_x():\n    assert True\n",
                                     encoding="utf-8")

    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    line = [l for l in r.stdout.splitlines() if "[NOT DECIDABLE]" in l]
    assert len(line) == 1, r.stdout
    line = line[0]

    assert "zz_declined.py" in line and "aa_honest.py" not in line, (
        "the line names the wrong program -- a reader sent to a file with "
        f"nothing undecidable in it:\n{line}")
    assert "$_d" in line and "$_h" not in line, (
        f"the line names the wrong counter:\n{line}")
    for fact in ("1 site(s)", "called 3x", "says 3"):
        assert fact in line, (
            f"the line does not carry {fact!r}, so a reader cannot see why it "
            f"is undecidable:\n{line}")

    doc = json.loads((tmp_path / "r.json").read_text())
    assert [(d["program"], d["counter"], d["increment_sites"],
             d["emitted_per_site"], d["denominator"])
            for d in doc["not_determined"]] == [("zz_declined.py", "_d", 1, 3, 3)], doc
    # the honest program beside it was still compared
    assert doc["counters_examined"] == 1, doc


def _helper_emitter(sites_inside, denominator):
    """A helper called 3x containing `sites_inside` increments, so the script
    emits `sites_inside * 3` against `denominator`."""
    body = "".join('            "  if {[catch {%%s_%d}]} { incr _n }\\n"\n' % i
                   for i in range(sites_inside))
    return ('def _repair(name):\n    return (\n' + body
            + '    ) %% tuple([name] * %d)\n\n\n' % sites_inside
            + 'def script():\n    return ("  set _n 0\\n" + _repair("a")\n'
              '            + _repair("b") + _repair("c")\n'
              '            + "  if {$_n >= %d} { puts ALL }\\n")\n' % denominator)


def test_equality_is_not_agreement_when_K_is_a_lower_bound(tmp_path):
    """A FALSE PASS the lower-bound rule shipped with, and the reason the rule
    is now stated as "only `sites > denominator` is decidable" rather than as
    three cases.

    The first version tested `value != sites` FIRST, so equality of the LITERAL
    count with the denominator fell through to the ordinary comparison and was
    read as agreement. But a lower-bound counter emits `sites x multiplier`:
    TWO literal increments in a helper called THREE times emit SIX against a
    denominator of 2, and the guard said "every population stated twice agrees".
    MEASURED: rc=0, no finding, no undecidable. A number that cannot be compared
    cannot match.

    All three relations swept, because the bug lived in the one nobody thinks to
    write a case for -- and the two undecidable rows land on the VACUOUS tier
    here, since these fixtures state exactly one counter and declining it leaves
    nothing compared at all."""
    for sites, denom, want_rc, want in ((1, 3, RC_VACUOUS, "not_determined"),
                                        (2, 2, RC_VACUOUS, "not_determined"),
                                        (4, 3, RC_FAIL, "findings")):
        progs, tests = _tree(tmp_path / f"s{sites}d{denom}",
                             _helper_emitter(sites, denom),
                             "def test_x():\n    assert True\n")
        r = _run(progs, tests, "--json", tmp_path / f"r{sites}{denom}.json")
        doc = json.loads((tmp_path / f"r{sites}{denom}.json").read_text())
        assert r.returncode == want_rc, (
            f"sites={sites} denominator={denom}: rc={r.returncode}, "
            f"expected {want_rc}\n{r.stdout}")
        assert len(doc[want]) == 1, (
            f"sites={sites} denominator={denom}: expected one {want}: {doc}")
        other = "findings" if want == "not_determined" else "not_determined"
        assert doc[other] == [], (
            f"sites={sites} denominator={denom}: {other} should be empty: {doc}")


def test_the_detectors_two_failure_modes_both_stay_visible(tmp_path):
    """`multiplied_counters` is deliberately narrow, and a narrow detector is
    only safe while BOTH ways it can be wrong stay visible. Those directions are
    pinned here, not its cleverness.

    UNDER-FIRE: a helper that is a METHOD is missed -- `calls` counts
    `ast.Call` whose func is a plain `Name`. The counter reads as a COUNT and
    the old false refusal returns: rc=FAIL, loud and answerable.

    OVER-FIRE: two lexical calls in EXCLUSIVE branches count as two though only
    one runs, so a possibly-decidable comparison is DECLINED -- reported as
    NOT DECIDABLE, never passed.

    If either direction ever flips to a quiet PASS, this goes red. That is the
    property; the counts themselves are allowed to be imperfect, because the
    corpus has no method-hosted emitter (measured: 0 of 29) and widening the
    detector to reach one would pay for it in the silent direction."""
    method = ('class C:\n'
              '    def _r(self, n):\n'
              '        return "  if {[catch {x}]} { incr _n }\\n"\n\n'
              '    def script(self):\n'
              '        return ("  set _n 0\\n" + self._r(1) + self._r(2)\n'
              '                + self._r(3) + "  if {$_n >= 3} { puts ALL }\\n")\n')
    progs, tests = _tree(tmp_path / "method", method,
                         "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "m.json")
    assert r.returncode == RC_FAIL, (
        "the method-hosted helper stopped failing LOUDLY -- if it now passes, "
        "the under-fire direction has gone quiet:\n" + r.stdout)
    doc = json.loads((tmp_path / "m.json").read_text())
    assert doc["not_determined"] == [], doc

    branches = ('def _r(n):\n    return "  if {[catch {x}]} { incr _n }\\n"\n\n\n'
                'def script(x):\n'
                '    if x:\n        return "  set _n 0\\n" + _r(1) + "  if {$_n >= 2} { puts A }\\n"\n'
                '    return "  set _n 0\\n" + _r(2) + "  if {$_n >= 2} { puts B }\\n"\n')
    progs, tests = _tree(tmp_path / "branches", branches,
                         "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "b.json")
    doc = json.loads((tmp_path / "b.json").read_text())
    assert r.returncode != RC_PASS, (
        "an over-fired decline was reported as a pass:\n" + r.stdout)
    assert len(doc["not_determined"]) == 1, (
        "the declined comparison was not reported at all:\n"
        + json.dumps(doc, indent=2))


def test_the_lower_bound_set_does_not_leak_between_programs(tmp_path):
    """`lower_bound` is computed per program, inside the loop. Hoisting it out
    -- an ordinary-looking refactor -- would let one program's helper excuse
    another program's genuine disagreement, silently.

    Both files declare the SAME counter name, which is what makes a leak
    possible at all: `aa_helper.py` is helper-assembled and undecidable,
    `zz_inline.py` is inline with a real disagreement (3 sites against a
    denominator of 2) and must still be REFUSED. Alphabetical order puts the
    undecidable one first, so a set carried forward from it reaches the other.

    This is the cross-contamination shape that WAS a defect once on this branch,
    between two counters in one script. It is structural here rather than
    accidental, and the test says so."""
    aa = ('def _repair(name):\n'
          '    return "  if {[catch {%s}]} { incr _n }\\n" % name\n\n\n'
          'def script():\n    return ("  set _n 0\\n" + _repair("a")\n'
          '            + _repair("b") + _repair("c")\n'
          '            + "  if {$_n >= 3} { puts ALL }\\n")\n')
    # ONE site against a denominator of 2 -- deliberately `sites < denominator`.
    # A leak only CHANGES a verdict in that relation: `sites > denominator`
    # stays decidable even for a lower-bound counter, so a fixture built that
    # way cannot detect the leak at all. Measured: the first version of this
    # test used 3 sites and its negative control PASSED.
    zz = ('def script():\n    return (\n'
          '        "  if {[catch {a}]} { incr _n }\\n"\n'
          '        "  if {$_n >= 2} { puts ALL }\\n")\n')
    progs = tmp_path / "p"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "aa_helper.py").write_text(aa, encoding="utf-8")
    (progs / "zz_inline.py").write_text(zz, encoding="utf-8")
    (tests / "test_x.py").write_text("def test_x():\n    assert True\n",
                                     encoding="utf-8")

    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_FAIL, (
        "one program's helper excused another program's disagreement:\n"
        + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert [(f["program"], f["increment_sites"], f["denominator"])
            for f in doc["findings"]] == [("zz_inline.py", 1, 2)], doc
    assert [(d["program"], d["counter"]) for d in doc["not_determined"]] == [
        ("aa_helper.py", "_n")], doc


def test_the_lower_bound_rule_reaches_every_denominator_kind(tmp_path):
    """The lower-bound path was only ever exercised with a COMPARISON
    denominator, and `_DEN_TEMPLATES` has three kinds. The polarity path had the
    identical gap and it was closed earlier on this branch; this is the same
    sweep for the rule added later.

    A kind that fell out of the rule would fail in the CONFIDENT direction: a
    retired `($_n/3)` or `of 3 repairs` compared against a literal site count
    that only counts what is written, refusing a truthful emitter.

    `denominator_kind` is asserted, not just the count. It is the field that
    tells a reader WHICH of the three statements was declined, and the evidence
    test for this line does not check it -- a record that says "something was
    undecidable" without saying which sends them to read all three."""
    head = ('def _repair(name):\n'
            '    return "  if {[catch {%s}]} { incr _n }\\n" % name\n\n\n'
            'def script():\n    return ("  set _n 0\\n" + _repair("a")\n'
            '            + _repair("b") + _repair("c") + ')
    kinds = {"comparison": '  if {$_n >= 3} { puts ALL }',
             "ratio": '  puts "($_n/3) refused"',
             "prose": '  puts "PARTIAL: $_n of 3 repairs refused"'}
    for kind, line in kinds.items():
        emitter = head + repr(line + "\n") + ")\n"
        progs, tests = _tree(tmp_path / kind, emitter,
                             "def test_x():\n    assert True\n")
        r = _run(progs, tests, "--json", tmp_path / f"{kind}.json")
        doc = json.loads((tmp_path / f"{kind}.json").read_text())
        assert doc["findings"] == [], (
            f"{kind}: a truthful helper-assembled emitter was refused: {doc}")
        assert [d["denominator_kind"] for d in doc["not_determined"]] == [kind], (
            f"{kind}: the lower-bound rule did not reach this kind, or recorded "
            f"it under another name: {doc['not_determined']}")
        # only this counter exists, so declining it leaves nothing compared
        assert r.returncode == RC_VACUOUS, r.stdout + r.stderr


EMITTER_LOWER_BOUND_BESIDE_INLINE = (
    'def _repair(name):\n'
    '    return "  if {[catch {%s}]} { incr _lb }\\n" % name\n\n\n'
    'def script():\n    return ("  set _lb 0\\n" + _repair("a") + _repair("b")\n'
    '            + _repair("c") + "  if {$_lb >= 3} { puts LB }\\n"\n'
    '            + "  if {[catch {z}]} { incr _in }\\n"\n'
    '            + "  if {$_in >= 2} { puts IN }\\n")\n')


def test_lower_bound_ness_does_not_spread_between_counters(tmp_path):
    """One script, two counters. `_lb` is helper-assembled and undecidable;
    `_in` is inline with a real disagreement and must still be REFUSED.

    The polarity path had exactly this defect once on this branch -- one
    counter's denial charged against another -- and the lower-bound rule added
    later has never been probed the same way. `name in lower_bound` keys it per
    counter, so it is structural rather than accidental; the test says so.

    `_in` is ONE site against a denominator of 2, deliberately in
    `sites < denominator`. That is the only relation a spread could move:
    `sites > denominator` stays decidable even for a lower-bound counter, so a
    fixture built that way would pass its own negative control and prove
    nothing -- measured, on the cross-PROGRAM version of this test."""
    progs, tests = _tree(tmp_path, EMITTER_LOWER_BOUND_BESIDE_INLINE,
                         "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_FAIL, (
        "one counter's helper excused another counter's disagreement:\n"
        + r.stdout)
    doc = json.loads((tmp_path / "r.json").read_text())
    assert [(f["counter"], f["increment_sites"], f["denominator"])
            for f in doc["findings"]] == [("_in", 1, 2)], doc
    assert [(d["counter"], d["emitted_per_site"])
            for d in doc["not_determined"]] == [("_lb", 3)], doc


# ── ACCEPTANCE: the incident this guard was built for ─────────────────────────
#
def _post_route_emitter(n_repairs, denominator):
    """The shape from THE DEFECT, MEASURED 2026-08-21, at any size."""
    body = "".join(
        '        "  if {[catch {repair_%d}]} { incr _prr_refused }\\n"\n' % i
        for i in range(n_repairs))
    return ('def block() -> str:\n    return (\n'
            '        "  set _prr_refused 0\\n"\n' + body
            + '        "  puts \\"SPEF_REPAIR_PARTIAL: $_prr_refused of %d '
              'repairs refused\\"\\n"\n'
              '        "  if {$_prr_refused >= %d} { puts NOT_APPLIED }\\n")\n'
              % (denominator, denominator))


def _post_route_test(pins):
    return ('from post_route import block\n\n\ndef test_the_partial_line():\n'
            '    assert "of %d repairs refused" in block()\n' % pins)


def test_the_incident_this_guard_was_built_for_is_still_caught(tmp_path):
    """ACCEPTANCE, reconstructed from this guard's own account of the defect.

    All 49 other tests here are unit-shaped -- they pin a rule, a spelling, a
    boundary. None replays the incident, so a refactor could keep every one of
    them green while the guard stopped doing the job it exists for. After a
    branch that rewrote both of its readers, added a lower-bound rule and four
    verdict paths, that is worth asserting directly.

    From the module docstring: a lane added a THIRD repair, correctly moved the
    emitter's printed denominator from two to three, and left the test asserting
    the OLD ratio.

        the incident      emitter says 3, test pins 2   -> REFUSED (CHECK B)
        the sibling       a 4th repair, `of 3` unmoved  -> REFUSED (CHECK A)
        done right        emitter and pin both say 3    -> PASS

    The third row is what stops this from being satisfiable by a guard that
    refuses everything."""
    for label, emitter, pin, want in (
            ("the incident", _post_route_emitter(3, 3), _post_route_test(2), RC_FAIL),
            ("a fourth repair", _post_route_emitter(4, 3), _post_route_test(3), RC_FAIL),
            ("the lane done right", _post_route_emitter(3, 3), _post_route_test(3), RC_PASS)):
        progs = tmp_path / label.replace(" ", "_")
        tests = progs / "tests"
        tests.mkdir(parents=True)
        (progs / "post_route.py").write_text(emitter, encoding="utf-8")
        (tests / "test_post_route.py").write_text(pin, encoding="utf-8")
        r = _run(progs, tests)
        assert r.returncode == want, (
            f"{label}: rc={r.returncode}, expected {want} -- the guard no longer "
            f"does the job it was built for:\n{r.stdout}{r.stderr}")


def test_the_verdict_is_byte_identical_across_runs(tmp_path):
    """A gate whose verdict is not reproducible is worth less than no gate --
    `test_issue712_prose_polarity` puts it as "a verdict nobody can reproduce
    green is the thing this repo is closing". Nothing here checked that.

    It is structural: every iteration is over a `sorted(...)` or an `ast.walk`,
    and the sets that do exist are consumed through `sorted`. Structural is not
    the same as verified -- one unsorted `set` iteration in a report list would
    make the ORDER of `denied_by_polarity`, `not_determined` or `unparsed` vary
    between runs, which is invisible on a PASS and maddening on a diff.

    The tree is SYNTHETIC on purpose. The property is about the algorithm, not
    the corpus, and pinning it against the real tree would cost two more
    full-corpus sweeps -- reintroducing the duplication this module just
    removed. It is built to populate every list that could reorder: a denial, a
    helper-assembled counter, an unreadable source, and a live pin.

    MEASURED on the real tree as well, once, by hand: json, stdout and rc all
    byte-identical over three runs."""
    progs = tmp_path / "p"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "aa_denial.py").write_text(
        'def s():\n    return (\n'
        '        "  # the retry path does not incr _a; it re-issues\\n"\n'
        '        "  if {[catch {x}]} { incr _a }\\n"\n'
        '        "  if {[catch {y}]} { incr _a }\\n"\n'
        '        "  puts \\"PARTIAL: $_a of 2 repairs refused\\"\\n"\n'
        '        "  if {$_a >= 2} { puts A }\\n")\n', encoding="utf-8")
    (progs / "mm_helper.py").write_text(
        'def _r(name):\n    return "  if {[catch {%s}]} { incr _m }\\n" % name\n\n\n'
        'def s():\n    return ("  set _m 0\\n" + _r("a") + _r("b") + _r("c")\n'
        '            + "  if {$_m >= 3} { puts M }\\n")\n', encoding="utf-8")
    # TWO unreadable sources, and two denials, and two undecidable counters --
    # every report list must hold at least TWO entries or it cannot REORDER, and
    # a control that cannot reorder proves nothing. Measured: with one entry
    # each, replacing a report list with `list(set(...))` passed this test three
    # times running.
    (progs / "zz_broken.py").write_text(
        'def s():\n    return "  incr _z\\n"\n\ndef q(  :::\n', encoding="utf-8")
    (progs / "yy_broken.py").write_text(
        'def s():\n    return "  incr _y\\n"\n\ndef w(  :::\n', encoding="utf-8")
    (progs / "xx_broken.py").write_text(
        'def s():\n    return "  incr _x\\n"\n\ndef v(  :::\n', encoding="utf-8")
    (progs / "nn_helper.py").write_text(
        'def _r(name):\n    return "  if {[catch {%s}]} { incr _n }\\n" % name\n\n\n'
        'def s():\n    return ("  set _n 0\\n" + _r("a") + _r("b") + _r("c")\n'
        '            + "  if {$_n >= 3} { puts N }\\n")\n', encoding="utf-8")
    (progs / "bb_denial.py").write_text(
        'def s():\n    return (\n'
        '        "  # the retry path does not incr _b; it re-issues\\n"\n'
        '        "  if {[catch {x}]} { incr _b }\\n"\n'
        '        "  if {[catch {y}]} { incr _b }\\n"\n'
        '        "  if {$_b >= 2} { puts B }\\n")\n', encoding="utf-8")
    # TWO undecodable sources. `substituted` is a report list like the others
    # and it was added FOUR commits after this fixture was written, so until now
    # it was the one list this test could not have caught reordering in -- the
    # rule above, unapplied to the newest list.
    (progs / "cc_bytes.py").write_bytes(
        b'def s():\n    return "  incr _c \xff\xfe\\n"\n')
    (progs / "dd_bytes.py").write_bytes(
        b'def s():\n    return "  incr _d \xff\xfe\\n"\n')
    # THREE, not two, for the reason `unparsed` carries three: measured, a
    # set-built two-entry list survived one attempt in three by luck. n entries
    # give at most n! orderings, and two of them agreeing across three runs is
    # not a rare accident.
    (progs / "ee_bytes.py").write_bytes(
        b'def s():\n    return "  incr _e \xff\xfe\\n"\n')
    (tests / "test_aa_denial.py").write_text(
        'from aa_denial import s\n\n\ndef test_p():\n'
        '    assert "of 2 repairs refused" in s()\n', encoding="utf-8")

    seen = set()
    for i in range(3):
        out = tmp_path / f"r{i}.json"
        r = _run(progs, tests, "--json", out)
        seen.add((r.returncode, out.read_text(), r.stdout))
    assert len(seen) == 1, (
        "the guard's verdict is not reproducible across runs -- a report list "
        "is being built from an unordered set:\n"
        + "\n---\n".join(sorted(s[1] for s in seen)))

    # and the run really did populate every list that could reorder
    doc = json.loads((tmp_path / "r0.json").read_text())
    for key in ("denied_by_polarity", "not_determined", "unparsed",
                "substituted"):
        floor = 3 if key in ("unparsed", "substituted") else 2
        assert len(doc[key]) >= floor, (
            f"{key} holds {len(doc[key])} entry, below the floor of {floor} "
            f"-- too few orderings for three runs to disagree reliably, so this "
            f"fixture cannot detect the defect the test exists for")
    # `unparsed` carries THREE, not two, because the control's strength depends
    # on it. n entries give at most n! orderings, so three runs agreeing by luck
    # costs (1/n!)^2 -- 1/4 at two entries. MEASURED rather than trusted, by
    # replacing a report list with `list(set(...))` and running the control
    # repeatedly:
    #
    #     two entries     fired 2 of 3
    #     three entries   fired 4 of 5
    #
    # The second is better than 1/36 would predict, which says CPython realises
    # fewer than 3! orderings for three short strings -- so the arithmetic is an
    # upper bound on the control's strength, not its value. It is a
    # PROBABILISTIC control either way, and that is written down rather than
    # rounded up to "it fires": the TEST is deterministic on correct code (every
    # iteration here is over a sorted sequence), only the mutation's detection
    # is chancy.
    assert len(doc["unparsed"]) >= 3, doc["unparsed"]


def test_rc0_does_not_promise_the_whole_tree_was_checked(tmp_path):
    """The EXIT CODES contract, which downstream automation reads before it
    reads anything else, and which this branch made inaccurate.

    It said rc=0 means "every emitted population agrees with its own site
    count". After the lower-bound rule, rc=0 can mean "every population I
    COMPARED agreed, and I declined others" -- so a harness taking rc=0 to mean
    the tree was fully checked is reading more than the code carries.

    Pinned as behaviour, not as prose: a run with one compared population AND
    one declined must exit 0 AND say so in the head. If those two ever stop
    coexisting the docstring is wrong again."""
    emitter = ('def _r(n):\n'
               '    return "  if {[catch {%s}]} { incr _m }\\n" % n\n\n\n'
               'def s():\n    return ("  set _m 0\\n" + _r("a") + _r("b") + _r("c")\n'
               '            + "  if {$_m >= 3} { puts M }\\n"\n'
               '            + "  if {[catch {y}]} { incr _k }\\n"\n'
               '            + "  if {[catch {z}]} { incr _k }\\n"\n'
               '            + "  if {$_k >= 2} { puts K }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["counters_examined"] >= 1, doc
    assert len(doc["not_determined"]) >= 1, (
        "this fixture no longer produces a declined population, so it cannot "
        f"show that rc=0 coexists with one: {doc}")
    assert doc["findings"] == [], doc
    head = [l for l in r.stdout.splitlines() if l.startswith("[PASS]")][0]
    assert "NOT DECIDABLE" in head, (
        "rc=0 was returned with a population declined, and the head did not "
        f"say so:\n{head}")


def test_the_json_report_carries_exactly_the_documented_keys(tmp_path):
    """`--json` is a machine-readable contract. This branch added THREE keys to
    it -- `denied_by_polarity`, `unparsed`, `not_determined` -- and the module
    docstring documented none of them until now.

    A key added or removed silently breaks whatever reads it, and nothing here
    would have noticed. The set is pinned against the docstring itself, so the
    two cannot drift: adding a key without documenting it goes red, and so does
    documenting one that is not emitted."""
    progs, tests = _tree(tmp_path)
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    emitted = set(json.loads((tmp_path / "r.json").read_text()))

    import ast as _ast
    import re as _re
    doc = _ast.get_docstring(_ast.parse(PROG.read_text(encoding="utf-8")))
    section = doc.split("--json, AND WHAT IT CARRIES", 1)[1]
    # A schema row is: exactly four spaces, the key, two-or-more spaces, prose.
    # Derived from the row SHAPE, never from a list of the keys expected -- a
    # checker that already knows the answer cannot detect drift. (The first
    # version required an underscore in the key and so missed `findings` and
    # `unparsed`; the instrument was wrong, not the docstring.)
    documented = set(_re.findall(r"^ {4}([a-z_]+) {2,}\S", section, _re.M))
    assert emitted == documented, (
        "the JSON report and its documented schema have drifted\n"
        f"  emitted but undocumented: {sorted(emitted - documented)}\n"
        f"  documented but not emitted: {sorted(documented - emitted)}")
    # A SECOND assertion, because the first one passes if a key is dropped
    # from the code and the docstring together -- drift detection cannot see
    # a lockstep removal. These are named, not counted: a magic total goes
    # stale the moment a key is legitimately added, which is how it read
    # `== 7` and went red on `substituted` for the wrong reason.
    required = {"tool", "counters_examined", "pins_examined", "findings",
                "denied_by_polarity", "not_determined", "unparsed",
                "substituted", "corpus", "pins_unmatched"}
    assert required <= emitted, (
        "a documented key has been removed from the report and its schema "
        f"together: {sorted(required - emitted)}")


def test_the_item_marker_is_not_the_verdict_marker(tmp_path):
    """`[CANNOT DETERMINE]` is this repo's VERDICT-level word: 34 uses across
    the corpus, every one beside rc 2, and `prose_polarity_consulted_check`
    prints it that way. `[NOT DECIDABLE]` is PER ITEM -- one population declined
    while the run carries on and exits 0.

    Swapping one for the other is a reasonable-looking "make the vocabulary
    consistent" change that would make a rc=0 run announce itself as
    inconclusive. Pinned so that change goes red instead of shipping."""
    emitter = ('def _r(n):\n'
               '    return "  if {[catch {%s}]} { incr _m }\\n" % n\n\n\n'
               'def s():\n    return ("  set _m 0\\n" + _r("a") + _r("b") + _r("c")\n'
               '            + "  if {$_m >= 3} { puts M }\\n"\n'
               '            + "  if {[catch {y}]} { incr _k }\\n"\n'
               '            + "  if {[catch {z}]} { incr _k }\\n"\n'
               '            + "  if {$_k >= 2} { puts K }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert r.returncode == RC_PASS, out
    assert "[NOT DECIDABLE]" in r.stdout, out
    assert "CANNOT DETERMINE" not in out, (
        "a rc=0 run is printing this repo's verdict-level word for a per-item "
        "note, which tells a reader the whole check was inconclusive:\n" + out)


# ── bytes that do not decode ────────────────────────────────────────────────
# `errors="replace"` never raises, which is why a guard reads that way -- one
# bad file cannot take the census down. The cost is that the text analysed is
# not the file, and a population the substitution lands in goes unmatched with
# nothing said. Silent narrowing is the failure this program exists to refuse.

def _undecodable_tree(tmp_path):
    emitter = ('def _r(n):\n'
               '    return "  if {[catch {%s}]} { incr _m }\\n" % n\n\n\n'
               'def s():\n    return ("  set _m 0\\n" + _r("a") + _r("b")\n'
               '            + "  if {$_m >= 2} { puts M }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    (progs / "bad_bytes.py").write_bytes(
        b'def s():\n    return "\xff\xfe caf\xe9 not utf8"\n')
    return progs, tests


def test_undecodable_bytes_are_reported_not_absorbed(tmp_path):
    """Before this, the run above printed `0 source(s) NOT examined` -- full
    reach over a file whose text it never read."""
    progs, tests = _undecodable_tree(tmp_path)
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert "[SUBSTITUTED]" in r.stdout, (
        "a file whose bytes had to be substituted was absorbed silently, so "
        "this run claims reach over text it did not read:\n" + out)
    assert "bad_bytes.py" in r.stdout, out
    assert "SUBSTITUTED to be read at all" in r.stdout, out


def test_substitution_is_in_the_json_reach(tmp_path):
    progs, tests = _undecodable_tree(tmp_path)
    j = tmp_path / "r.json"
    _run(progs, tests, "--json", str(j))
    rep = json.loads(j.read_text())
    assert [b["source"] for b in rep["substituted"]] == ["bad_bytes.py"], rep
    assert rep["substituted"][0]["characters"] > 0, rep


def test_a_clean_tree_invents_no_substitution(tmp_path):
    """A guard that manufactures reach caveats for clean sources trains its
    reader to ignore them."""
    emitter = ('def s():\n    return ("  set _m 0\\n"\n'
               '            + "  if {[catch {a}]} { incr _m }\\n"\n'
               '            + "  if {[catch {b}]} { incr _m }\\n"\n'
               '            + "  if {$_m >= 2} { puts M }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    r = _run(progs, tests)
    assert "[SUBSTITUTED]" not in r.stdout, r.stdout + r.stderr
    # ABSENCE IS NOT ENOUGH. Measured: this test also passes against the
    # pre-polarity program, which has no substitution tier at all -- so on its
    # own it survives the feature being deleted. The tier must be shown to have
    # RUN and reported zero.
    assert "0 source(s) whose bytes were SUBSTITUTED" in r.stdout, r.stdout


def test_a_legitimate_replacement_character_is_not_a_substitution(tmp_path):
    """This is why the probe is a STRICT decode and not a count of U+FFFD in
    the result: a source may legitimately contain that character, encoded as
    perfectly valid UTF-8. Counting occurrences cannot tell the two apart and
    would report a clean file as mangled."""
    emitter = ('def s():\n    return ("  # � is a real character here\\n"\n'
               '            + "  set _m 0\\n"\n'
               '            + "  if {[catch {a}]} { incr _m }\\n"\n'
               '            + "  if {[catch {b}]} { incr _m }\\n"\n'
               '            + "  if {$_m >= 2} { puts M }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    assert "�" in (progs / "thing_emit.py").read_text(), "fixture is wrong"
    (progs / "thing_emit.py").read_bytes().decode("utf-8")   # decodes strictly
    r = _run(progs, tests)
    assert "[SUBSTITUTED]" not in r.stdout, (
        "a clean file containing U+FFFD was reported as mangled:\n"
        + r.stdout + r.stderr)
    assert "0 source(s) whose bytes were SUBSTITUTED" in r.stdout, r.stdout


def test_the_vacuous_reason_does_not_deny_a_population_it_could_not_read(
        tmp_path):
    """`no-population-stated-twice` is a claim ABOUT THE TREE. It is false when
    the only sources were read through substitution -- the tree may state one
    twice in the bytes that did not survive."""
    progs, tests = _tree(tmp_path, "def s():\n    return \"  set _m 0\\n\"\n",
                         "def test_x():\n    assert True\n")
    (progs / "thing_emit.py").write_bytes(
        b'def s():\n    return "  set _m 0 \xff\xfe\\n"\n')
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert r.returncode == RC_VACUOUS, out
    assert "source-bytes-substituted" in out, out
    assert "no-population-stated-twice" not in out, (
        "this run denies the tree states a population twice, about a tree it "
        "read through byte substitution:\n" + out)


# ── paths rglob yields that will not OPEN ───────────────────────────────────
# `rglob("test_*.py")` and `glob("*.py")` match whatever bears the NAME. Each of
# these raised out of the read and took the census down with a traceback, out of
# a program whose refusal exit code is also 1 -- so a broken symlink in someone
# else's tree was indistinguishable from a population disagreement.

def _clean_pair():
    emitter = ('def s():\n    return ("  set _m 0\\n"\n'
               '            + "  if {[catch {a}]} { incr _m }\\n"\n'
               '            + "  if {[catch {b}]} { incr _m }\\n"\n'
               '            + "  if {$_m >= 2} { puts M }\\n")\n')
    return emitter, "def test_x():\n    assert True\n"


@pytest.mark.parametrize("kind", ["broken-symlink", "directory", "unreadable"])
def test_an_unopenable_path_is_reach_not_a_traceback(tmp_path, kind):
    emitter, pin = _clean_pair()
    progs, tests = _tree(tmp_path, emitter, pin)
    victim = tests / "test_hostile.py"
    if kind == "broken-symlink":
        victim.symlink_to(tmp_path / "nowhere" / "gone.py")
    elif kind == "directory":
        victim.mkdir()
    else:
        if os.geteuid() == 0:
            pytest.skip("root reads a mode-000 file, so this cannot be staged")
        victim.write_text("def test_y():\n    pass\n", encoding="utf-8")
        victim.chmod(0o000)

    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert "Traceback" not in out, (
        f"one {kind} took the whole census down:\n" + out)
    assert r.returncode == RC_PASS, out
    assert "[UNPARSED]" in r.stdout and "test_hostile.py" in r.stdout, (
        "the path was skipped without saying so, which is reach claimed over "
        "something never read:\n" + out)


def test_an_unopenable_PROGRAM_is_reach_too(tmp_path):
    """`glob("*.py")` on the program side has the same exposure, and that side
    reads through a cache -- a different code path from the test loop."""
    emitter, pin = _clean_pair()
    progs, tests = _tree(tmp_path, emitter, pin)
    (progs / "broken_emit.py").symlink_to(tmp_path / "nowhere" / "gone.py")
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert "Traceback" not in out, out
    assert r.returncode == RC_PASS, out
    assert "broken_emit.py" in r.stdout, out


def test_an_unopenable_path_is_named_once(tmp_path):
    """Two readers reach each program. A reach report that counts one file
    twice is its own small lie -- the rule `record_unparsed` already follows."""
    emitter, pin = _clean_pair()
    progs, tests = _tree(tmp_path, emitter, pin)
    (progs / "broken_emit.py").symlink_to(tmp_path / "nowhere" / "gone.py")
    j = tmp_path / "r.json"
    _run(progs, tests, "--json", str(j))
    rep = json.loads(j.read_text())
    hits = [u for u in rep["unparsed"] if "broken_emit" in u]
    assert len(hits) == 1, rep["unparsed"]


# ── the denominator ─────────────────────────────────────────────────────────
# vibe-ic#1200: a statistic over the corpus must carry its own denominator. "0
# compared" out of 1238 programs and out of an empty directory are the same
# number and not the same fact, and the second is what a typo'd --programs
# produces.

def test_the_verdict_says_out_of_how_many(tmp_path):
    emitter = ('def s():\n    return ("  set _m 0\\n"\n'
               '            + "  if {[catch {a}]} { incr _m }\\n"\n'
               '            + "  if {[catch {b}]} { incr _m }\\n"\n'
               '            + "  if {$_m >= 2} { puts M }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    (progs / "second_emit.py").write_text("def s():\n    return \"\"\n",
                                          encoding="utf-8")
    r = _run(progs, tests)
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "out of a corpus of 2 program(s) and 1 test(s) SCANNED" in r.stdout, r.stdout


def test_the_corpus_is_in_the_json_report(tmp_path):
    progs, tests = _tree(tmp_path)
    j = tmp_path / "r.json"
    _run(progs, tests, "--json", str(j))
    assert json.loads(j.read_text())["corpus"] == {"programs": 1, "tests": 1}


def test_an_empty_corpus_is_not_a_statement_about_a_tree(tmp_path):
    """Point this at a directory that exists but holds nothing -- a typo'd
    --programs, a lane that moved -- and the old answer was "no emitted
    population is stated twice here". True of an empty set, and it reads as
    "I checked and it is fine"."""
    progs = tmp_path / "progs"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert r.returncode == RC_VACUOUS, out
    assert "corpus-holds-no-program" in out, out
    assert "no-population-stated-twice" not in out, (
        "an empty directory is answering as though it held programs that "
        "state no population twice:\n" + out)
    assert "out of a corpus of 0 program(s)" in r.stdout, out


# ── pins the emitter states no literal for ──────────────────────────────────

# The emitter DOES state a literal phrase, so it is reached -- `gate(s) ready`
# is matchable. What it never states a literal for is `document(s) checked`,
# which is the phrase the test pins. That is the branch under test. An emitter
# with no matchable phrase at all is dropped one step EARLIER, by `if not em`,
# and is a different limit (named in the docstring, not in this count) -- the
# first version of this fixture staged that one by mistake and proved nothing.
# `PHRASE` matches the literal shape `of <digits> <words>`. The emitter DOES
# state one -- `of 3 gate(s) ready` -- so it is reached and `em` is non-empty.
# What it never states a literal for is `document(s) checked`, whose count it
# computes, and that is the phrase the test pins. THAT is the branch under test.
#
# An emitter with no matchable phrase at all is dropped one step EARLIER by
# `if not em`, which is a different limit -- named in the docstring, not in this
# count. The first two versions of this fixture staged that one by mistake and
# proved nothing about the branch they claimed to cover.
PIN_UNMATCHED_EMITTER = '''\
def script() -> str:
    n = 7
    return (
        "  puts \\"READY: $_g of 3 gate(s) ready\\"\\n"
        "  puts \\"DOCS: $_d of %d document(s) checked\\"\\n" % n
    )
'''

PIN_UNMATCHED_TEST = '''\
from document_emit import script


def test_it():
    assert "of 2 document(s) checked" in script()
'''


def _unmatched_tree(tmp_path):
    progs = tmp_path / "progs"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    (progs / "document_emit.py").write_text(PIN_UNMATCHED_EMITTER,
                                            encoding="utf-8")
    (tests / "test_document_emit.py").write_text(PIN_UNMATCHED_TEST,
                                                 encoding="utf-8")
    return progs, tests


def test_a_pin_the_emitter_states_no_literal_for_is_said_not_dropped(tmp_path):
    """The emitter computes the count, so there is no literal for the pinned
    `2` to disagree with. Declining is right. Dropping it in silence is not --
    this branch took 10 of the shipped corpus's 11 pins with nothing in the
    reach to show for it, while the verdict said `1 test pin(s) COMPARED` and
    read as though one was all there was."""
    progs, tests = _unmatched_tree(tmp_path)
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert "test pin(s) the named program does not state a literal for" in out, out
    assert "0 test pin(s) the named program does not" not in out, (
        "the pin was dropped without being counted:\n" + out)


def test_the_unmatched_pin_count_is_in_the_json_reach(tmp_path):
    progs, tests = _unmatched_tree(tmp_path)
    j = tmp_path / "r.json"
    _run(progs, tests, "--json", str(j))
    rep = json.loads(j.read_text())
    assert rep["pins_unmatched"] >= 1, rep
    assert rep["pins_examined"] == 0, rep


def test_an_unmatched_pin_is_reach_and_never_a_finding(tmp_path):
    """`pins_unmatched` must not become a way to fail a tree for stating
    something this guard cannot read."""
    progs, tests = _unmatched_tree(tmp_path)
    r = _run(progs, tests)
    assert r.returncode in (RC_PASS, RC_VACUOUS), r.stdout + r.stderr
    assert "[FAIL]" not in r.stdout, r.stdout
    # and the pin was actually COUNTED, so this is "reach, not a finding" and
    # not "no pin was ever seen". Written POSITIVELY: my first attempt at this
    # said `"0 test pin(s) ..." not in stdout`, which is another absence and is
    # trivially true of a program that prints no such clause at all -- measured,
    # it did not move this test off the pre-fix program's passing list.
    assert "1 test pin(s) the named program does not state a literal for" \
        in r.stdout, r.stdout


# ── --json - , the corpus spelling ──────────────────────────────────────────
# 34 programs here implement `if args.json == "-"`, and `_vacuous_exit` routes
# its sentinel to stderr expressly because of it: the document owns stdout. This
# program had a --json flag and none of that, so the convention wrote a junk
# file NAMED `-`.

def test_json_dash_puts_a_parseable_document_on_stdout(tmp_path):
    progs, tests = _tree(tmp_path)
    r = _run(progs, tests, "--json", "-")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    doc = json.loads(r.stdout)          # must parse ALONE, nothing mixed in
    assert doc["tool"] == "emitter_population_pin_check", doc
    assert not (tmp_path / "-").exists(), "a file named '-' was created"


def test_json_dash_does_not_lose_the_human_report(tmp_path):
    """Where this departs from those 34: they print the human lines only when
    --json is absent. The reach is printed, ALWAYS -- so it moves to stderr,
    which costs the document nothing."""
    progs, tests = _tree(tmp_path)
    r = _run(progs, tests, "--json", "-")
    assert "COMPARED out of a corpus of" in r.stderr, r.stderr
    assert "COMPARED out of a corpus of" not in r.stdout, (
        "the human report is mixed into the document stream:\n" + r.stdout)


def test_a_json_path_still_reports_on_stdout(tmp_path):
    """Only the dash moves the stream. A path argument is unchanged."""
    progs, tests = _tree(tmp_path)
    j = tmp_path / "r.json"
    r = _run(progs, tests, "--json", str(j))
    assert "COMPARED out of a corpus of" in r.stdout, r.stdout
    assert json.loads(j.read_text())["tool"] == "emitter_population_pin_check"


def test_json_at_a_directory_is_a_usage_error_before_the_work(tmp_path):
    """It used to run the whole sweep and die on IsADirectoryError: a traceback
    wearing rc 1, this program's REFUSAL code, so a mistyped argument was
    indistinguishable from a population disagreement."""
    progs, tests = _tree(tmp_path)
    d = tmp_path / "adir"
    d.mkdir()
    r = _run(progs, tests, "--json", str(d))
    out = r.stdout + r.stderr
    assert r.returncode == RC_USAGE, out
    assert "Traceback" not in out, out
    assert "is a directory" in out, out


# ── the document stream, on EVERY verdict path ──────────────────────────────
# A single print that forgets `file=out` puts a human line after the closing
# brace and the document stops parsing. That is not hypothetical: the commit
# that introduced `--json -` left exactly one behind, on the refusal path, where
# the PASS-path test could not see it.

CLEAN_EMIT = (
    'def script():\n'
    '    return ("  set _n 0\\n"\n'
    '            "  if {[catch {a}]} { incr _n }\\n"\n'
    '            "  if {[catch {b}]} { incr _n }\\n"\n'
    '            "  puts \\"PARTIAL: $_n of 2 repairs refused\\"\\n"\n'
    '            "  if {$_n >= 2} { puts ALL }\\n")\n')


def _verdict_tree(tmp_path, kind):
    progs = tmp_path / "progs"
    tests = progs / "tests"
    tests.mkdir(parents=True)
    if kind == "vacuous":
        return progs, tests
    (progs / "thing_emit.py").write_text(CLEAN_EMIT, encoding="utf-8")
    pin = "of 2 repairs refused" if kind != "refusal" else "of 3 repairs refused"
    (tests / "test_thing_emit.py").write_text(
        f'from thing_emit import script\n\n\n'
        f'def test_it():\n    assert "{pin}" in script()\n', encoding="utf-8")
    if kind == "substituted":
        (progs / "bad_emit.py").write_bytes(b'def s():\n    return "\xff\xfe x"\n')
    return progs, tests


@pytest.mark.parametrize("kind", ["pass", "refusal", "vacuous", "substituted"])
def test_json_dash_keeps_stdout_parseable_on_every_verdict(tmp_path, kind):
    progs, tests = _verdict_tree(tmp_path, kind)
    r = _run(progs, tests, "--json", "-")
    try:
        doc = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(
            f"a human line leaked into the document on the {kind} path ({e}):\n"
            + r.stdout) from None
    assert doc["tool"] == "emitter_population_pin_check"
    if kind == "refusal":
        assert r.returncode == RC_FAIL, r.stdout + r.stderr
        assert "[POPULATION]" in r.stderr, r.stderr


def test_every_print_after_the_stream_is_chosen_goes_through_it():
    """The structural twin of the test above, and the one that scales: it fails
    on a print added later without `file=out`, before anyone has to construct a
    tree that reaches that line. Read from the AST, because a regex over the
    source cannot tell which multi-line call carries the keyword -- the leak it
    is guarding against was left by exactly that mistake."""
    import ast as _ast
    tree = _ast.parse(PROG.read_text(encoding="utf-8"))
    main = next(n for n in _ast.walk(tree)
                if isinstance(n, _ast.FunctionDef) and n.name == "main")
    anchor = max(n.lineno for n in _ast.walk(main)
                 if isinstance(n, _ast.Assign)
                 and getattr(n.targets[0], "id", "") == "out")
    unrouted = sorted(n.lineno for n in _ast.walk(main)
                      if isinstance(n, _ast.Call)
                      and getattr(n.func, "id", "") == "print"
                      and "file" not in {k.arg for k in n.keywords}
                      and n.lineno > anchor)
    assert not unrouted, (
        "these print() calls run after the output stream is chosen and do not "
        f"use it, so `--json -` emits them into the document: {unrouted}")


def test_the_documented_vacuous_reasons_are_the_ones_emitted():
    """The EXIT CODES section said VACUOUS had TWO reasons for three commits
    after the third and fourth were added. Both sides are derived -- the code's
    from the `reason` assignment in `main`, the docs' from the backticked tokens
    in the section -- so neither can be the checker's own memory of the answer."""
    import ast as _ast
    import re as _re
    src = PROG.read_text(encoding="utf-8")
    tree = _ast.parse(src)
    main = next(n for n in _ast.walk(tree)
                if isinstance(n, _ast.FunctionDef) and n.name == "main")
    emitted = set()
    for node in _ast.walk(main):
        if (isinstance(node, _ast.Assign)
                and getattr(node.targets[0], "id", "") == "reason"):
            emitted |= {c.value for c in _ast.walk(node.value)
                        if isinstance(c, _ast.Constant)
                        and isinstance(c.value, str)}
    assert emitted, "no `reason` assignment found in main -- probe is broken"

    doc = _ast.get_docstring(tree)
    section = doc.split("2  VACUOUS", 1)[1].split("\n    3  ", 1)[0]
    documented = set(_re.findall(r"`([a-z][a-z-]{5,})`", section))
    assert emitted == documented, (
        "the vacuous reason tokens and their documentation have drifted\n"
        f"  emitted but undocumented: {sorted(emitted - documented)}\n"
        f"  documented but not emitted: {sorted(documented - emitted)}")


# ── the wiring the exit codes depend on ─────────────────────────────────────

def _ci_wiring_file():
    """Searched upward rather than counted: `parents[4]` is true today and is a
    fact about where the plugin sits, not about this program."""
    for parent in PROG.parents:
        cand = parent / "tools" / "ci" / "repo_hygiene_gates.sh"
        if cand.is_file():
            return cand
    return None


def test_ci_wires_this_gate_so_that_a_vacuous_run_fails():
    """rc 2 says "nothing was compared, this is NOT a pass". That sentence is
    only true if the harness treats rc 2 as a failure, and the harness has a
    wrapper that does NOT: `run_tolerating_uncheckable` exists for probes that
    need a clean tree and reads rc 2 as "could not check".

    Rewire this gate to that wrapper and every VACUOUS verdict this file works
    to produce becomes a green run, silently. The docstring claims the wiring;
    this checks it."""
    wiring = _ci_wiring_file()
    if wiring is None:
        pytest.skip("tools/ci/repo_hygiene_gates.sh is not in this checkout, so "
                    "the wiring claim cannot be checked from here")
    lines = [ln.strip() for ln in wiring.read_text(errors="replace").splitlines()
             if "emitter_population_pin_check" in ln
             and not ln.lstrip().startswith("#")]
    assert lines, (
        "no line in the CI script runs this gate: it is not wired, and a gate "
        "nothing runs cannot refuse anything")
    for ln in lines:
        # The specific consequence FIRST. Checked the other way round, every
        # rewiring reported only "not plain `run`", which names the symptom and
        # not what it costs.
        assert not ln.startswith("run_tolerating_uncheckable"), (
            "wired as tolerating-uncheckable: rc 2 stops failing the suite and "
            f"every VACUOUS verdict becomes a silent green: {ln!r}")
        assert ln.startswith("run "), (
            "this gate is wired through a wrapper that is not plain `run`, so "
            f"its exit codes may not mean what its docstring says: {ln!r}")


# ── every reach quantity reaches STDOUT, not only the document ──────────────

def _main_assignments():
    import ast as _ast
    tree = _ast.parse(PROG.read_text(encoding="utf-8"))
    main = next(n for n in _ast.walk(tree)
                if isinstance(n, _ast.FunctionDef) and n.name == "main")
    found = {}
    for n in _ast.walk(main):
        if isinstance(n, _ast.Assign) and isinstance(n.targets[0], _ast.Name):
            found[n.targets[0].id] = n.value
    return _ast, main, found


def test_every_reach_quantity_in_the_document_also_reaches_the_head_line():
    """A tier added to `--json` and forgotten in the verdict is invisible to
    everyone reading a terminal, which is most readers -- CI runs this gate with
    no --json at all. That is the silent narrowing this file exists to refuse,
    committed against its own reader.

    Both sides are derived from the code: the head's referenced names and the
    report's value expressions, compared by NAME. A hand-kept list of "tiers
    that should be in the head" would be one more thing to forget, and forgetting
    is the failure being guarded.

    WHAT IT DOES NOT CATCH, measured rather than assumed: a tier whose value is
    built ONLY from names the head already mentions -- `"phantom": len(unparsed)
    + 1` slips through, because the intersection is non-empty. Every tier in
    this file arrived with its own variable (`substituted`, `pins_unmatched`),
    which this does catch; the composed case is real and uncovered, and saying
    so is worth more than a stronger-sounding claim."""
    _ast, main, found = _main_assignments()
    head, report = found["head"], found["report"]
    head_names = {x.id for x in _ast.walk(head) if isinstance(x, _ast.Name)}

    # `tool` is the line's own prefix and `findings` has its own [POPULATION]
    # lines -- both DISCLOSED, neither a count in the bracket. Exempt, and the
    # exemption for `findings` is checked below rather than trusted.
    exempt = {"tool", "findings"}
    missing = []
    for k, v in zip(report.keys, report.values):
        if k.value in exempt:
            continue
        names = {x.id for x in _ast.walk(v) if isinstance(x, _ast.Name)}
        if not names & head_names:
            missing.append(k.value)
    assert not missing, (
        "these reach quantities are in the --json document and nowhere in the "
        f"verdict line, so a reader without --json cannot see them: {missing}")

    printed = set()
    for n in _ast.walk(main):
        if isinstance(n, _ast.Call) and getattr(n.func, "id", "") == "print":
            printed |= {x.id for x in _ast.walk(n) if isinstance(x, _ast.Name)}
    assert "findings" in printed, (
        "`findings` is exempt from the head line because it is printed "
        "separately, and it is no longer printed")


# ── the fix is the one the gate asked for ───────────────────────────────────

def test_the_extractor_still_looks_like_an_extractor_and_consults_polarity():
    """#712's census fell 214 -> 213 when this branch landed. There are two ways
    to make that happen and only one of them is the fix.

    The honest one: the extractor still SEARCHES PROSE and still WRITES A
    DECLARED VALUE -- the gate goes on counting it as the kind of function it
    audits -- and it now consults the polarity vocabulary. The other one is to
    stop looking like an extractor: restructure until `_searches_prose` returns
    False and the row leaves the census with nothing fixed. Both produce 213,
    and the brief's rule is that the second is the one thing that may not be
    done.

    Checked with the gate's OWN predicates rather than a reimplementation of
    them, because a private copy of "what counts as an extractor" would drift
    from the thing that actually decides the census."""
    import ast as _ast
    sys.path.insert(0, str(PROGRAMS_DIR))
    try:
        import prose_polarity_consulted_check as gate
        searches = gate._searches_prose
        writes = gate._writes_a_declared_value
        consults = gate._consults_polarity
        aliases_of = gate._aliases
    except (ImportError, AttributeError) as e:
        pytest.skip(f"the #712 gate's predicates are not importable here ({e}), "
                    f"so this cannot be checked from this checkout")

    tree = _ast.parse(PROG.read_text(encoding="utf-8"))
    aliases = aliases_of(tree)
    assert aliases, (
        "this program imports no polarity vocabulary at all, so nothing here "
        "can be consulting it")

    audited = [fn for fn in _ast.walk(tree)
               if isinstance(fn, _ast.FunctionDef)
               and searches(fn) and writes(fn)]
    assert audited, (
        "the #712 gate no longer counts ANY function here as an extractor. The "
        "census would read 213 either way -- this is what closing the row by "
        "hiding from it looks like, and it is the one move the brief forbids")

    blind = [fn.name for fn in audited if not consults(fn, aliases)]
    assert not blind, (
        f"these are extractors by the gate's own definition and consult no "
        f"polarity: {blind}")


# ── a phrase in an emitted COMMENT is not a phrase the emitter prints ───────

COMMENT_EMITTER = '''\
def script() -> str:
    return (
        "  # the summary no longer prints \\"of 3 repairs refused\\"\\n"
        "  set _n 0\\n"
        "  if {[catch {a}]} { incr _n }\\n"
        "  if {[catch {b}]} { incr _n }\\n"
        "  puts \\"PARTIAL: $_n of 2 repairs refused\\"\\n"
        "  if {$_n >= 2} { puts ALL }\\n"
    )
'''


def test_a_pin_on_a_value_only_a_COMMENT_states_is_refused(tmp_path):
    """The FALSE PASS this found. `phrases_of` offered both 3 and 2 as values
    the emitter states, because the retired 3 appears in an emitted comment
    saying it is no longer printed. A test still pinning 3 was found in that
    set and raised nothing -- a denial counted as a confirmation, #712's own
    shape, in a function the #712 gate does not audit."""
    progs, tests = _tree(
        tmp_path, COMMENT_EMITTER,
        'from thing_emit import script\n\n\n'
        'def test_it():\n    assert "of 3 repairs refused" in script()\n')
    r = _run(progs, tests)
    out = r.stdout + r.stderr
    assert r.returncode == RC_FAIL, (
        "a test pinning a value the emitter says it NO LONGER prints was "
        "accepted, because a comment supplied it:\n" + out)
    assert "[POPULATION]" in r.stdout, out
    assert "states 2" in r.stdout, out


def test_a_printed_line_carrying_a_hash_is_still_a_phrase(tmp_path):
    """The other direction, which the fix must not buy the first one with. Only
    the text BEFORE the match on its own line is examined, so a `puts` whose
    output happens to contain a hash is still a phrase the emitter prints --
    refusing it would be the false refusal `phrases_of` exists to avoid."""
    emitter = ('def script() -> str:\n'
               '    return (\n'
               '        "  set _n 0\\n"\n'
               '        "  if {[catch {a}]} { incr _n }\\n"\n'
               '        "  if {[catch {b}]} { incr _n }\\n"\n'
               '        "  puts \\"# $_n of 2 repairs refused\\"\\n"\n'
               '        "  if {$_n >= 2} { puts ALL }\\n"\n'
               '    )\n')
    progs, tests = _tree(
        tmp_path, emitter,
        'from thing_emit import script\n\n\n'
        'def test_it():\n    assert "of 2 repairs refused" in script()\n')
    r = _run(progs, tests)
    assert r.returncode == RC_PASS, (
        "a phrase on a PRINTED line was dropped because the line carries a "
        "hash:\n" + r.stdout + r.stderr)
    assert "1 test pin(s) COMPARED" in r.stdout, r.stdout


def test_a_wrapped_denial_in_a_comment_no_longer_miscounts(tmp_path):
    """The under-reach `test_the_accepted_under_reach_fails_LOUDLY` demonstrates
    used to be reachable through COMMENT lines too, and there it produced a
    count of 3 for a script with two repairs -- announced, but wrong.

    It is no longer reachable that way: a commented `incr` is not a site
    whatever its polarity, so the count is 2 and the emitter agrees with itself.
    Pinned because it is a real improvement to a documented cost, and an
    improvement nobody checks is one that can quietly go away."""
    emitter = ('def script() -> str:\n'
               '    return """\n'
               '  # the third repair is deliberately absent: there is no\n'
               '  # incr _n in the fallback branch\n'
               '  if {[catch {a}]} { incr _n }\n'
               '  if {[catch {b}]} { incr _n }\n'
               '  puts "PARTIAL: $_n of 2 repairs refused"\n'
               '  if {$_n >= 2} { puts ALL }\n'
               '"""\n')
    progs, tests = _tree(tmp_path, emitter, PIN_2)
    r = _run(progs, tests)
    assert r.returncode == RC_PASS, (
        "a commented `incr` is being counted as a site again:\n"
        + r.stdout + r.stderr)
    assert "3 site(s)" not in r.stdout, r.stdout


# ── guards a mutation sweep found nothing was holding ───────────────────────
# Deleting each `if ...: continue` in turn and running this file: 8 of 20
# survived. Three are behaviour-neutral on the shipped tree (measured, byte
# identical --json) and are fast paths, not guards. The rest are these.

def test_a_denominator_stated_only_in_a_COMMENT_is_not_a_denominator(tmp_path):
    """The comment rule's other half. The `incr` side had a test; this one did
    not, and deleting it left the whole suite green."""
    emitter = ('def script():\n    return ("  set _n 0\\n"\n'
               '            "  # if {$_n >= 2} { puts ALL }\\n"\n'
               '            "  if {[catch {a}]} { incr _n }\\n"\n'
               '            "  if {[catch {b}]} { incr _n }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["counters_examined"] == 0, (
        "a threshold written only in a comment was compared as though the "
        "script stated it:\n" + r.stdout)
    assert r.returncode == RC_VACUOUS, r.stdout + r.stderr


def test_a_commented_incr_in_a_HELPER_is_not_evidence_of_a_multiplier(tmp_path):
    """`multiplied_counters` reads the same text as `counters_of` and must
    reach the same answer -- two readers disagreeing about one script is #711
    itself. Its comment rule had no test either."""
    emitter = ('def _dead(name):\n'
               '    return "  # incr _n would go here for %s\\n" % name\n\n\n'
               'def script():\n    return ("  set _n 0\\n"\n'
               '            + _dead("a") + _dead("b")\n'
               '            + "  if {[catch {x}]} { incr _n }\\n"\n'
               '            + "  if {$_n >= 2} { puts ALL }\\n")\n')
    progs, tests = _tree(tmp_path, emitter, "def test_x():\n    assert True\n")
    r = _run(progs, tests, "--json", tmp_path / "r.json")
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["not_determined"] == [], (
        "commented `incr`s in a helper were read as evidence of a multiplier "
        "and excused a real disagreement:\n" + r.stdout)
    assert r.returncode == RC_FAIL, r.stdout + r.stderr


def test_a_tests_directory_that_does_not_exist_is_rc3(tmp_path):
    """`--programs` had this test and `--tests` did not, so deleting its check
    cost nothing. Both arguments, both rejected before the work."""
    progs, tests = _tree(tmp_path)
    r = _run(progs, tmp_path / "no_such_tests_dir")
    out = r.stdout + r.stderr
    assert r.returncode == RC_USAGE, out
    assert "Traceback" not in out, out
    assert "--tests" in out and "not a directory" in out, out


def test_a_pin_in_a_test_naming_a_silent_program_is_deliberately_not_reached(
        tmp_path):
    """THE DOCUMENTED LIMIT, pinned as a decision rather than left as an
    accident. `pins_unmatched` counts pins whose named program states no literal
    for that phrase; it does NOT count pins in a test whose named program emits
    nothing matchable, because `if not em` returns before `pins_of` is called.

    Measured on the shipped tree by deleting that guard: `pins_unmatched` goes
    10 -> 34, which is the 24 this file's docstring sizes. Reaching them costs
    `pins_of` over every parsed test and changes no verdict, so the guard stays
    -- and this test is what makes changing it a visible decision."""
    emitter = 'def script():\n    return "  puts \\"nothing countable here\\"\\n"\n'
    progs, tests = _tree(
        tmp_path, emitter,
        'from thing_emit import script\n\n\n'
        'def test_it():\n    assert "of 7 widgets seen" in script()\n')
    j = tmp_path / "r.json"
    _run(progs, tests, "--json", str(j))
    doc = json.loads(j.read_text())
    assert doc["pins_unmatched"] == 0, (
        "this pin was reached after all -- the limit the docstring sizes has "
        "changed, and the 24 it names are now counted: " + repr(doc))


def test_the_statement_stop_rests_on_a_true_premise():
    """`denies_containment` stops walking at the first statement, and the
    mutation sweep could not kill that stop. The reason is not thin coverage: an
    `ast.expr` is never the parent of an `ast.stmt` -- measured 2026-08-22 and
    recorded in 725283fc19, 602,938 statement-parent edges across 3,965 files
    of that tree, zero with an expression parent -- so no form the walk
    tests for can appear above the stop. The figures are PINNED to that
    measurement and are not re-derived here; what this test actually enforces
    is the PREMISE below, which is checked against the live tree on every run.

    That argument holds only while every form it tests for IS an expression. Add
    a check for something that can sit above a statement and the stop starts
    hiding answers instead of ending a question. This fails then, which is the
    only moment it matters."""
    import ast as _ast
    tree = _ast.parse(PROG.read_text(encoding="utf-8"))
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.FunctionDef) and n.name == "denies_containment")
    # ONLY the checks made on the walk variable itself. The first version of
    # this probe collected every `ast.X` in every isinstance call, which swept
    # in `ast.Not` and `ast.NotIn` -- operator classes, tested on `up.op` and on
    # the comparison's ops, never on `up` -- and failed on unmutated code. What
    # the stop's soundness depends on is what can be found ABOVE it, which is
    # only ever what `up` is tested against.
    walked = {"up"}
    tested = set()
    for call in _ast.walk(fn):
        if isinstance(call, _ast.Call) and getattr(call.func, "id", "") == "isinstance" \
                and getattr(call.args[0], "id", None) in walked:
            for arg in call.args[1:]:
                for node in _ast.walk(arg):
                    if isinstance(node, _ast.Attribute) and \
                            getattr(node.value, "id", "") == "ast":
                        tested.add(node.attr)
    assert tested, "no isinstance checks on the walk variable -- probe is broken"
    tested.discard("stmt")                      # the stop itself
    not_expressions = sorted(
        name for name in tested
        if not (isinstance(getattr(_ast, name, None), type)
                and issubclass(getattr(_ast, name), _ast.expr)))
    assert not not_expressions, (
        "this walk now tests for forms that are not expressions, and an "
        "expression is the only thing that cannot sit above the statement "
        f"stop -- so the stop may now be hiding an answer: {not_expressions}")


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
