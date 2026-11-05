"""The two BIDIRECTIONAL controls in this directory are executed by pytest.

THE DEFECT. `tests/test_arith_declaration_emit_equals_separator.py` and
`tests/test_atpg_exit_code_not_signal.py` are named `test_*.py` and live in the
suite directory, but each defines only a `main()` and an
`if __name__ == "__main__"` guard — no `def test_*`, no test class. Measured on
`a38902d16`, they are the ONLY 2 of 2467 `test_*.py` files that collect nothing:

    $ pytest tests/test_atpg_exit_code_not_signal.py
    no tests collected in 0.32s          (pytest exit 5)

and `grep -rl` finds no runner, workflow, or script that invokes either. So
~14 assertions sat in the tree, passing, executed by nothing — while counting
toward the file census as if they were coverage. That is the shape this repo
removes elsewhere ("a checker only its own test runs"), inverted: a test that
nothing runs at all.

WHY A WRAPPER RATHER THAN A REWRITE. Both files are deliberately parameterised
by the program PATH, because their contract is bidirectional: the same file
must FAIL against the pre-fix program and PASS against the post-fix one.
Rewriting them as plain pytest tests against the shipped module would execute
the assertions but throw the negative half away — and the negative half is the
one that catches "tighten the filter until the count is zero". Both directions
are driven here instead, so the contract each docstring states is the contract
that runs.

THE PERTURBATIONS ARE THE PRE-FIX STATE, NOT AN ARBITRARY BREAK. Each removes
exactly the construct its control was written to prove:

  * `fault_atpg_run.atpg_exit_is_signal_death` — without it, a high exit code is
    read as death-by-signal on the number alone, which is the defect.
  * `arith_declaration_emit._derive_multiplier_algorithm`'s `=` in the
    separator class `[:\\-–=]` — the pre-fix regex accepted `Algorithm:` and not
    `algorithm = <v>`.

A perturbation that broke something else would prove the control runs without
proving it discriminates.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# pytest's own default `python_files` patterns, spelled ONCE in this repo and
# reused here rather than respelled. The program that owns them says why: a
# second definition of "is a test file" drifts from the one pytest uses, and
# the direction it drifts in is a file nobody runs.
from landing_unselectable_pytest_corpus import _TEST_BASENAME  # noqa: E402

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
#: The plugin root — where `pytest.ini` and `run_tests.sh` live, and the base
#: every path in the census is relative to.
_PLUGIN = _PROGRAMS.parent
_TESTS_REL = _HERE.relative_to(_PLUGIN).as_posix()



#: ``(control, program, perturb)`` — perturb returns the PRE-FIX source text.




CASES = (
    pytest.param("test_atpg_exit_code_not_signal.py", "fault_atpg_run.py",
                 _break_atpg, id="atpg_exit_is_not_a_signal"),
    pytest.param("test_arith_declaration_emit_equals_separator.py",
                 "arith_declaration_emit.py", _break_arith,
                 id="arith_equals_separator"),
)


#: The zero-collect modules that ARE executed — plugin-relative POSIX paths,
#: derived from CASES so the exemption cannot outlive the wiring that earns it.
#: Both are CLASS (b): they import cleanly and define no `test_*` at all,
#: because each is a CLI whose contract is bidirectional and parameterised by
#: the program path. `test_no_test_file_collects_zero_tests` re-checks that
#: every entry here is still zero-collect, so a stale exemption cannot survive.
DRIVEN = frozenset(f"{_TESTS_REL}/{c.values[0]}" for c in CASES)










#: How each zero-collect class reads in the finding. The probe distinguishes
#: them; a bare count cannot, and they are three different repairs.
_CLASS = {
    "failed": "COLLECTION ERROR — the module raises while being imported, so "
              "pytest reports it in a separate ERRORS section that a `-q` "
              "summary line can swallow. Fix the import.",
    "skipped": "MODULE-LEVEL SKIP — an `importorskip` / "
               "`skip(allow_module_level=True)` fired on this host. State what "
               "is missing and where it is available, or the module is "
               "not-measured everywhere and says so nowhere.",
    "passed": "NO TEST FUNCTION — the module imports cleanly and defines "
              "nothing pytest collects: a deleted body, functions not named "
              "`test_*`, or a `def test_` nested inside something pytest does "
              "not descend into.",
}


# ── ONE SOURCE OF EXCLUSIONS, TWO READERS ───────────────────────────────────
#
# This census and `landing_unselectable_pytest_corpus.py` ask DIFFERENT
# questions over the SAME population, and until v1.13.89 they answered
# differently about one file:
#
#   programs/tests/fixtures/stage1_on_pass_review/reject_caravel/reports/
#     phase2/gates/on_pass_review/test_r1_intent_top_not_built.py
#
# It is R1's own emitted regression sitting on R1's own rejecting tree —
# published evidence, tracked since v1.12.87, FAILING by construction. v1.13.77
# stopped COLLECTING it (`pytest.ini: norecursedirs`) rather than deleting it,
# and v1.13.89 declared the tree in `_EXCLUDED` so the coverage census stopped
# counting it as a test a landing could be blocked by.
#
# This census walks the tier trees with `rglob`, which does not know about
# `norecursedirs`, so it saw a file matching pytest's own patterns that pytest
# reported no collector for — DENOMINATOR 2 — and fired. Both were right about
# their own question and they disagreed about the file.
#
# THE FIX IS ALIGNMENT, NOT WEAKENING. A second hardcoded list here would drift
# from that one exactly the way `run_tests.sh` and `pytest.ini` drifted before
# #1391. So this reads the SHIPPED declaration: a tree added to `_EXCLUDED`
# later satisfies BOTH censuses at once, and a tree in NEITHER still reddens
# both. `_EXCLUDED` prefixes are REPO-relative; this census is PLUGIN-relative,
# so they are converted rather than re-spelled.


# ── the zero-collect census ─────────────────────────────────────────────
#
# THE GUARD THAT SHIPPED HERE ASKED A GLOB-AND-REGEX QUESTION, AND IT WAS BLIND
# THREE WAYS. It read `_HERE.glob("test_*.py")` and searched each body for
# `^\s*(async\s+)?def test_|^\s*class Test`. Three canaries were planted in a
# scratch clone and the guard stayed GREEN on all three (re-run against
# `612b5a94d`; the shipped predicate was executed standalone over each):
#
#   POPULATION.  `_HERE.glob` is non-recursive and names ONE directory. 131 of
#                the plugin's 3030 tracked pytest modules live outside it —
#                mcp-eda/test 39, skills/*/tests 81, tools/phase1_engine/tests
#                8, _shared 3 — so a zero-collect module planted under
#                `skills/sta-review/tests` was never looked at.
#   SPELLING.    pytest's default `python_files` is `test_*.py *_test.py`. The
#                glob named the first only, so a `*_test.py` canary planted in
#                the guard's OWN directory was invisible to it.
#   PREDICATE.   `^\s*def test_` is anchored to the start of a LINE, not to
#                module level, so a `def test_` nested inside a `main()` — which
#                pytest does not collect — read as coverage.
#
# All three are the same defect: a claim about a population, over a population
# defined by a spelling. The answer below is a REAL COLLECTION QUESTION over a
# population derived from git.
#
# WHY NOT `pytest --collect-only` OVER THE WHOLE SUITE, WHICH IS THE OBVIOUS FIX
# ------------------------------------------------------------------------------
# Because it cannot be afforded here, and the reason is a BLOCKING gate in this
# same directory rather than a preference. MEASURED on this host:
#
#     pytest --collect-only -q <the tiers, 612b5a94d>   79.7 s   42894 nodes
#     pytest --collect-only -q <796 files by name>     176.9 s   11075 nodes
#
# `ci_harness_timeout_ceiling_check` (BLOCKING) permits any ONE bounded call at
# most `min(harness bounds) // 3` = 60 s, and it is resolved from the workflows
# rather than copied, so it cannot be argued with. The whole-suite collection is
# 1.3x over that ceiling and the by-name form — the only form that could be
# chunked to fit — is 4x SLOWER per file, so chunking makes it worse, not
# better. `test_pytest_ini_paths_exist.py` records the same refusal for the same
# gate.
#
# WHAT IS DONE INSTEAD, AND WHY IT IS NOT THE REGEX AGAIN
# -------------------------------------------------------
# Two stages, and the VERDICT comes from the collector, never from the parser:
#
#   1. a CANDIDATE filter over the whole tracked population. It is an AST walk
#      of the MODULE BODY — pytest's actual `python_functions = test*` /
#      `python_classes = Test*` rules at the level pytest applies them — plus a
#      textual `__test__` / `allow_module_level` catch, which are the two ways a
#      module that parses as collectable can still yield nothing. Its errors are
#      one-directional BY CONSTRUCTION: anything it cannot vouch for becomes a
#      candidate. A `def test_` it cannot see at module level (nested, or inside
#      an `if`) is a candidate, not a pass.
#   2. a REAL `pytest --collect-only` over the candidates. Normally that is the
#      two driven files plus two synthetic controls, so it costs ~3 s.
#
# The controls in step 2 are not decoration. A collector that returned zero for
# everything would make this guard fire on the whole tree, and a collector that
# returned a node for everything would make it inert; both are asked on every
# run, over a file whose answer is known, before the tree's answer is believed.
#
# POPULATION: TRACKED PLUS UNTRACKED-NOT-IGNORED. `git ls-files` is the same
# source `landing_unselectable_pytest_corpus.py` uses, and `--others
# --exclude-standard` adds the file a contributor has written but not yet added
# while still refusing everything `.gitignore` declares is not this repo's code
# — the scratch-directory-inside-the-checkout hazard that has manufactured false
# reds here before.

_PLUGIN = _PROGRAMS.parent

#: pytest's DEFAULT `python_files`. BOTH spellings; the shipped glob had one.
_TEST_BASENAME = re.compile(r"^(test_.*\.py|.*_test\.py)$")

#: The two ways a module the AST reads as collectable still collects nothing.
#: Either spelling sends the file to the real collector instead of being trusted.
_OPT_OUT = re.compile(r"__test__|allow_module_level")

#: The ceiling `ci_harness_timeout_ceiling_check` enforces. It CANNOT be raised.
_PYTEST_TIMEOUT_S = 60

#: A tree whose `test_*.py` are the scored harness's own corpus artefacts, not
#: this repository's tests. Declared with its reason, never implied by a
#: constant — `landing_unselectable_pytest_corpus.py` states the same exclusion.
_DECLARED_OUT = ("benchmark-data/",)


def _git(args, cwd=_PLUGIN):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True,
                          timeout=_PYTEST_TIMEOUT_S)


def population():
    """Every pytest module in this plugin tree, by git rather than by glob.

    Returns paths relative to the plugin root. A git failure RAISES: "I could
    not look" must never reach a reader as "I looked and there was nothing",
    which is the whole shape this file exists to remove.
    """
    rels = []
    for extra in ([], ["--others", "--exclude-standard"]):
        proc = _git(["ls-files", "-z", *extra])
        assert proc.returncode == 0, (
            f"git ls-files {extra} failed under {_PLUGIN} — the population of "
            f"this census is UNKNOWN, and an unknown population must not be "
            f"reported as a clean one:\n{proc.stderr}")
        rels += [r for r in proc.stdout.split("\0") if r]
    return sorted({
        r for r in rels
        if _TEST_BASENAME.match(r.rsplit("/", 1)[-1])
        and not any(r.startswith(d) for d in _DECLARED_OUT)})


def defines_a_collectable_test(src: str) -> bool:
    """pytest's default collection rules, applied where pytest applies them.

    MODULE BODY ONLY. `^\\s*def test_` matched a nested definition and that is
    canary 3; `ast.parse(...).body` cannot, because a nested definition is not
    in it. Anything unparseable returns False, i.e. becomes a candidate.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    defs = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, defs) and node.name.startswith("test"):
            return True
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            if any(isinstance(s, defs) and s.name.startswith("test")
                   for s in node.body):
                return True
    return False






#: Three files whose collected answer is KNOWN, re-asked on every run. Two are
#: positive: an instrument that answers zero for everything would redden the
#: whole tree, and `canary_seen_test.py` is spelled the OTHER way on purpose, so
#: the `*_test.py` half of `python_files` is proven live rather than assumed —
#: that spelling is canary 2, which the shipped glob could not see. It also
#: makes the zero canary's SILENCE mean something: its sibling, written to the
#: same directory and passed in the same argv, came back.
_CONTROLS = {
    "test_canary_one.py": (
        "def test_the_collector_reports_a_real_node():\n    assert True\n",
        "test_the_collector_reports_a_real_node", 1),
    "canary_seen_test.py": (
        "def test_the_other_spelling_is_collected():\n    assert True\n",
        "test_the_other_spelling_is_collected", 1),
    "canary_zero_test.py": (
        '''"""Named like a test; defines none. Canary 3, and canary 2's spelling."""


def main():
    def test_nested_is_not_collected():   # pytest does not collect this
        assert True
    return test_nested_is_not_collected


if __name__ == "__main__":
    main()
''',
        "test_nested_is_not_collected", 0),
}


# RENAMED at reland. Upstream this was a second `test_no_test_file_collects_zero_tests`,
# which Python silently resolves to whichever is defined last -- one of the two
# censuses would have become an invisible test, which is the defect THIS FILE exists
# to catch. The two ask different questions and both are kept: the one above asks
# whether a module the SUITE DISCOVERS collects nothing; this one asks whether a
# test-named file that EXISTS IN THE TREE was ever put in front of the collector.


# ── controls on the CANDIDATE FILTER itself ─────────────────────────────
#
# The filter may only err toward asking the collector. These pin the three
# shapes the shipped guard was blind to, at the level the filter decides them.


def test_PAIRED_GUARD_the_three_canary_shapes_are_candidates():
    """Each of the three planted canaries reaches the collector."""
    nested = _CONTROLS["canary_zero_test.py"][0]
    assert not defines_a_collectable_test(nested), (
        "a `def test_` nested inside a function was read as a module-level "
        "test — that is canary 3, and it is what `^\\s*def test_` did")
    assert not defines_a_collectable_test("x = 1\n"), "a module with nothing"
    assert not defines_a_collectable_test("def main(:\n"), (
        "an unparseable module must become a candidate, not a pass")
    assert defines_a_collectable_test(
        "class TestX:\n    def test_a(self):\n        pass\n")
    assert defines_a_collectable_test("async def test_a():\n    pass\n")
    # An opt-out the AST reads as collectable still goes to the collector.
    assert _OPT_OUT.search("def test_a():\n    pass\n__test__ = False\n")


def test_NEGATIVE_CONTROL_the_population_is_not_one_directory():
    """Canary 1's shape: the population must reach outside `programs/tests`.

    The shipped guard globbed `_HERE` only, so 128 modules — mcp-eda/test,
    tools/phase1_engine/tests, skills/*/tests, _shared — were never subjects.
    """
    pop = population()
    outside = sorted({r.split("/")[0] for r in pop
                      if not r.startswith("programs/tests/")})
    assert {"mcp-eda", "skills", "tools", "_shared"} <= set(outside), (
        f"the census no longer reaches every tree that ships tests: {outside}")
    # The SPELLING half, canary 2, pinned against the regex rather than the tree
    # (the tree carries no `*_test.py` today, and a control that depends on that
    # staying true would silently stop testing anything the day it changes).
    assert _TEST_BASENAME.match("something_test.py"), (
        "the `*_test.py` half of pytest's default `python_files` is not in the "
        "population filter — that is canary 2")
    assert not _TEST_BASENAME.match("conftest.py")
