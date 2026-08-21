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
