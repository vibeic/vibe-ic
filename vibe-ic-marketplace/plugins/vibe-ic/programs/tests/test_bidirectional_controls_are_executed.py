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

import json
import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402
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

def _run(control: Path, target: Path) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(control), str(target)],
        capture_output=True, text=True)


#: ``(control, program, perturb)`` — perturb returns the PRE-FIX source text.
def _break_atpg(src: str) -> str:
    out = src.replace("def atpg_exit_is_signal_death(", "def _removed_(", 1)
    assert out != src, "atpg_exit_is_signal_death is gone — update this control"
    return out


def _break_arith(src: str) -> str:
    out, n = re.subn(r"\[:\\-–=\]", "[:\\\\-–]", src, count=1)
    if n == 0:                       # the class is written literally in-source
        out = src.replace("[:\\-–=]", "[:\\-–]", 1)
    assert out != src, "the `=` separator class moved — update this control"
    return out


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


@pytest.mark.parametrize("control,program,perturb", CASES)
def test_the_control_passes_against_the_shipped_program(
        control, program, perturb):
    """FORWARD: the shipped program satisfies its own control."""
    proc = _run(_HERE / control, _PROGRAMS / program)
    assert proc.returncode == 0, (
        f"{control} FAILS against the shipped {program} — this is a real red "
        f"that nothing was running:\n{proc.stdout}\n{proc.stderr}")


@pytest.mark.parametrize("control,program,perturb", CASES)
def test_the_control_still_fails_against_the_pre_fix_program(
        control, program, perturb, tmp_path):
    """PAIRED GUARD: a control that cannot fail is not a control.

    Without this, wiring the file in would prove only that it runs — and a
    control that passes against everything is exactly what these two files were
    written to prevent.
    """
    stage = tmp_path / "programs"
    shutil.copytree(_PROGRAMS, stage, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    target = stage / program
    target.write_text(perturb(target.read_text(encoding="utf-8")),
                      encoding="utf-8")

    proc = _run(_HERE / control, target)
    # Both streams: the arith control reports its held negative on STDERR
    # ("NEGATIVE CONTROL HELD — …"), and an assertion that printed only stdout
    # would report an empty reason for a real failure.
    assert proc.returncode != 0, (
        f"{control} PASSED against a {program} with the fixed construct "
        f"REMOVED — the control asserts nothing:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")


def _tiers() -> List[str]:
    """The tiers the FULL SUITE runs, asked of the script that defines them.

    `run_tests.sh --list-tiers` prints its own `TEST_DIRS` array. Re-deriving
    that list here would be a second definition of "the suite", and the way
    that drift goes is a tree nothing checks — which is the defect this test
    exists to catch, one level up.
    """
    proc = _pr.run(["bash", str(_PLUGIN / "run_tests.sh"), "--list-tiers"],
                   cwd=str(_PLUGIN))
    assert proc.returncode == 0, (
        "run_tests.sh --list-tiers failed — the suite's own tier list is "
        f"unreadable, so this census has no denominator:\n"
        f"{proc.stdout}\n{proc.stderr}")
    tiers = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert tiers, "run_tests.sh --list-tiers printed nothing"
    return tiers


def _census(tiers: List[str], out: Path) -> dict:
    """Run pytest's own collector over every tier and read back what it found.

    `--continue-on-collection-errors` so ONE module that raises on import
    cannot truncate the census to the modules that happened to load — a
    shortened census is short in the safe-looking direction.
    """
    env = dict(os.environ)
    env["ZERO_COLLECT_PROBE_OUT"] = str(out)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    # An outer session's addopts (`-n auto`, an extra plugin) must not reshape
    # the census; this run answers one question and inherits no flags.
    env.pop("PYTEST_ADDOPTS", None)
    # The census walks `skills/` — the SHIPPED tree. `sys.dont_write_bytecode`
    # is per-interpreter and does not reach a child, so without this the child
    # leaves `.pyc` under `skills/` and
    # `test_issue1417_no_test_bytecompiles_the_shipped_tree` goes red. It did,
    # measured, while this census was being written.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = _pr.run(
        [sys.executable, "-m", "pytest", *tiers, "--collect-only", "-q",
         "-p", "_zero_collect_probe", "--continue-on-collection-errors",
         "-p", "no:cacheprovider"],
        cwd=str(_PLUGIN), env=env)
    assert out.is_file(), (
        "the collection probe wrote no census — pytest did not reach the end "
        f"of collection (rc={proc.returncode}):\n"
        f"--- stdout (tail) ---\n{proc.stdout[-4000:]}\n"
        f"--- stderr (tail) ---\n{proc.stderr[-2000:]}")
    census = json.loads(out.read_text(encoding="utf-8"))
    census["rc"] = proc.returncode
    census["tail"] = proc.stdout[-4000:]
    return census


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
def _excluded_tree_prefixes() -> List[str]:
    """Plugin-relative prefixes the SHIPPED exclusion roster declares.

    Raises rather than returning empty: a census that silently stopped reading
    the roster would subtract nothing and look exactly like a clean tree, which
    is the failure mode this whole module exists to refuse.
    """
    import importlib.util
    prog = _PROGRAMS / "landing_unselectable_pytest_corpus.py"
    assert prog.is_file(), (
        f"{prog} is absent — the exclusion roster this census defers to cannot "
        f"be read, and 'I could not look' is not 'nothing is excluded'.")
    spec = importlib.util.spec_from_file_location("_lupc_for_census", prog)
    mod = importlib.util.module_from_spec(spec)
    # REGISTERED BEFORE EXEC, and it is not optional: the roster's entries are
    # @dataclass, and dataclasses resolve their own module out of `sys.modules`
    # at class-creation time. Without this line the import dies in
    # `dataclasses._is_type` with AttributeError on None — measured here.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    # Its OWN derivations, not a second spelling of the layout here: the repo
    # root and the plugin's path within it are the two facts a hardcoded
    # constant would get wrong the day the tree moves.
    repo = mod.repo_root()
    assert repo is not None, (
        "no enclosing git repository — the exclusion roster's prefixes are "
        "repo-relative and cannot be resolved, which is a refusal, not an "
        "empty roster.")
    rel = mod.plugin_rel(repo)
    out = []
    for e in mod._EXCLUDED:
        pre = e.prefix
        assert pre.startswith(rel + "/"), (
            f"exclusion {pre!r} is not under this plugin ({rel!r}); this "
            f"census cannot express it and must not silently ignore it.")
        out.append(pre[len(rel) + 1:])
    return out


def test_no_test_file_collects_zero_tests(tmp_path):
    """No module the suite discovers may collect zero tests, undeclared.

    THE QUESTION IS ASKED OF PYTEST, NOT OF A GLOB. This test used to walk
    `_HERE.glob("test_*.py")` and grep each file for `^\\s*def test_`. Three
    canaries were planted against that version on 03ea6f5ad9 and it stayed
    GREEN on all three, so it could not say no about a known-bad subject:

      * a zero-collect module under `skills/sta-review/tests/` — the glob was
        non-recursive AND single-directory, and 128 of the 3028 modules the
        suite discovers live outside it (mcp-eda/test 39, skills/*/tests 81,
        tools/phase1_engine/tests 8);
      * a module spelled `*_test.py` in this very directory — pytest's default
        `python_files` includes that pattern and a `test_*.py` glob does not;
      * a NESTED `def test_`, which `^\\s*def test_` matches because of the
        `\\s*` while pytest collects nothing from the module.

    A fourth was found while writing the replacement: `report.result` counts a
    Module's DIRECT children, so a module holding only an empty `class Test…`
    reports one child and zero tests. The probe counts leaf items instead.

    THE DENOMINATOR IS ASSERTED BEFORE THE FINDING IS BELIEVED. A census that
    silently collected nothing yields an empty difference set and reads exactly
    like a clean tree. So: every tier must contribute rows, pytest's discovery
    must match the files on disk that its own patterns name, and this module
    must appear in its own census with tests in it.

    AND `DRIVEN` IS THIS TEST'S OWN CAN-SAY-NO CONTROL, which is the reason the
    exemption is re-checked rather than merely subtracted. The probe has no
    separate test; it does not need one, because a probe that has stopped
    discriminating cannot reach the end of this function in ANY direction:

      * reports every module as collecting something -> the two DRIVEN modules
        stop being zero-collect -> `resurrected` fires;
      * reports every module as collecting nothing    -> `silent` fires with
        3026 entries;
      * reports nothing at all                        -> the three denominator
        assertions fire.

    The two known-bad subjects are inside the guard's own subject, so the
    question "can this still say no" is answered on every run.
    """
    tiers = _tiers()
    census = _census(tiers, tmp_path / "census.json")
    rows = {r["file"]: r for r in census["rows"]}

    # ---- DENOMINATOR 1: every tier the full suite runs is in the census.
    missing_tiers = [t for t in tiers
                     if not any(f.startswith(t + "/") for f in rows)]
    assert not missing_tiers, (
        "tier(s) named by run_tests.sh contributed NO module to the census — "
        "pytest collected nothing from them and said so only by staying "
        f"quiet: {missing_tiers}\n{census['tail']}")

    # ---- DENOMINATOR 2: pytest's discovery == the files on disk that pytest's
    # own patterns name. A file on disk pytest never reports is worse than a
    # zero-collect one: it is not discovered at all.
    on_disk = {
        str(p.relative_to(_PLUGIN))
        for t in tiers
        for p in (_PLUGIN / t).rglob("*.py")
        if "__pycache__" not in p.parts and _TEST_BASENAME.match(p.name)
    }
    # A DECLARED-EXCLUDED TREE IS DATA, NOT AN UNDISCOVERED TEST. Read from the
    # shipped roster, never re-spelled here — see _excluded_tree_prefixes.
    excluded_prefixes = _excluded_tree_prefixes()
    assert excluded_prefixes, (
        "the shipped exclusion roster is EMPTY, so this census is subtracting "
        "nothing and cannot be distinguished from one that stopped reading it. "
        "If the roster is legitimately empty, that is a change to "
        "landing_unselectable_pytest_corpus._EXCLUDED and this assertion is "
        "where it must be acknowledged.")
    declared_data = sorted(f for f in on_disk
                           if any(f.startswith(x) for x in excluded_prefixes))
    assert declared_data, (
        f"no file on disk lies under any declared exclusion "
        f"{excluded_prefixes} — the subtraction below removes nothing, so this "
        f"census would pass whether or not it consulted the roster at all.")
    on_disk -= set(declared_data)
    undiscovered = sorted(on_disk - set(rows))
    assert not undiscovered, (
        f"{len(undiscovered)} file(s) match pytest's own collection patterns "
        "and sit under a tier the suite runs, yet pytest reported no collector "
        f"for them: {undiscovered[:20]}\n"
        f"(this census already subtracted {len(declared_data)} file(s) under "
        f"the exclusion roster's declared tree(s) {excluded_prefixes}. A file "
        f"here is one NOTHING declares data and NOTHING collects — declare its "
        f"tree in landing_unselectable_pytest_corpus._EXCLUDED, which both "
        f"censuses read, or make it collect.)")

    # ---- DENOMINATOR 3: a positive control that cannot come out cheap. This
    # module is in the census with tests in it, or the census did not run.
    me = f"{_TESTS_REL}/{Path(__file__).name}"
    assert rows.get(me, {}).get("nodes", 0) > 0, (
        f"the census does not report this very module ({me}) as collecting any "
        f"test — it is not measuring what it claims to. rows={len(rows)} "
        f"rc={census['rc']}")

    zero = {f: r for f, r in rows.items() if r["nodes"] == 0}

    # ---- The exemption may not outlive the wiring that justifies it.
    for d in sorted(DRIVEN):
        assert (_PLUGIN / d).is_file(), (
            f"DRIVEN names {d}, which does not exist — the exemption is stale; "
            "delete it in the commit that removed the file.")
    resurrected = sorted(set(DRIVEN) - set(zero))
    assert not resurrected, (
        f"{resurrected} now collect(s) tests of their own, so the zero-collect "
        "exemption above is stale. Delete it — a row that outlives its truth "
        "is the one the next reader believes.")

    # ---- The disclosure, kept from rotting. Each driven control names its
    # driver in its OWN text, so a reader who opens only that file learns it is
    # executed rather than dead — and a sweep that counts collection, which is
    # how these two were found, has something to read. A pointer nothing checks
    # goes stale; this is the check.
    driver = Path(__file__).name
    unlinked = sorted(
        d for d in DRIVEN
        if driver not in (_PLUGIN / d).read_text(encoding="utf-8",
                                                 errors="replace"))
    assert not unlinked, (
        f"{unlinked} collect(s) no tests and IS driven from here, but says so "
        f"nowhere in its own text. Name {driver} in its docstring, or the next "
        "reader of that file alone sees a module nothing runs.")

    # ---- The finding.
    silent = sorted(set(zero) - set(DRIVEN))
    assert not silent, (
        f"{len(silent)} module(s) collect ZERO tests and nothing declares them "
        f"driven (census: {len(rows)} modules, "
        f"{sum(r['nodes'] for r in rows.values())} tests, {len(tiers)} tiers):\n"
        + "\n".join(
            f"  * {f}\n      {_CLASS.get(zero[f]['outcome'], zero[f]['outcome'])}"
            for f in silent)
        + "\n\nA module collecting zero tests is indistinguishable from a green "
          "one in a summary line. Make it run, or drive it from a test and add "
          "it to DRIVEN with the reason — do not delete it to tidy the count.")
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


def candidates(pop=None):
    """The subset the parser cannot vouch for. Errs toward asking the collector."""
    out = []
    for rel in (population() if pop is None else pop):
        src = (_PLUGIN / rel).read_text(encoding="utf-8", errors="replace")
        if _OPT_OUT.search(src) or not defines_a_collectable_test(src):
            out.append(rel)
    return out


def collected_counts(paths, cwd):
    """`pytest --collect-only` per path — the REAL question, and the verdict.

    Returns `(counts, stdout)`. `--collect-only` exits 5 when the whole run
    collects nothing, which is an ANSWER (zero) and not a failure; any other
    non-zero exit is the collector failing to answer, and is raised rather than
    counted as zero.

    `counts` covers only paths UNDER `cwd`. `-q` prints a nodeid relative to
    rootdir, and for a file outside it that prefix comes back EMPTY — measured,
    after the one-node control below reported 0 and said so. The controls are
    therefore checked by node NAME against `stdout`, which is why it is
    returned rather than discarded.
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", "-p", "no:randomly", "--no-header",
         *[str(p) for p in paths]],
        cwd=str(cwd), capture_output=True, text=True,
        timeout=_PYTEST_TIMEOUT_S, env=env)
    assert proc.returncode in (0, 5), (
        f"the collector could not answer (exit {proc.returncode}); this census "
        f"has NOT measured zero, it has failed to look:\n"
        f"{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}")

    root = Path(cwd).resolve()
    counts = {Path(p).resolve(): 0 for p in paths
              if Path(p).resolve().is_relative_to(root)}
    for line in proc.stdout.splitlines():
        if "::" not in line:
            continue
        head = line.split("::", 1)[0].strip()
        if not head:
            continue
        mod = (root / head).resolve()
        if mod in counts:
            counts[mod] += 1
    return counts, proc.stdout


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
def test_every_test_file_in_the_tree_reaches_the_collector(tmp_path):
    """The census that made the two findable, asked of the whole tree.

    A file named `test_*.py` (or `*_test.py`) from which pytest collects nothing
    is invisible to the suite and counted by every file census — so it reads as
    coverage while asserting nothing. The two known ones are exempt BY NAME
    because they are driven above; a third would be a new one.
    """
    driven = {f"programs/tests/{c.values[0]}" for c in CASES}

    pop = population()
    assert len(pop) > 2000, (
        f"the population collapsed to {len(pop)} modules — a census over a tree "
        f"that is not there passes for the same reason an empty one does")
    for d in sorted(driven):
        assert d in pop, (
            f"{d} is exempted by name and is no longer in the tree; an exemption "
            f"for a file that does not exist hides the next file that does")

    ctl_paths = []
    for name, (body, _, _) in _CONTROLS.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
        ctl_paths.append(tmp_path / name)

    cand = candidates(pop)
    counts, out = collected_counts(
        [_PLUGIN / r for r in sorted(set(cand) | driven)] + ctl_paths, _PLUGIN)

    # ── the instrument, on files whose answer is known, every run ──
    for name, (_, node, expected) in _CONTROLS.items():
        seen = sum(1 for line in out.splitlines()
                   if line.strip().endswith("::" + node))
        assert seen == expected, (
            f"the collector reported {seen} node(s) named {node!r} for the "
            f"control {name}, not {expected}. This census has not measured the "
            f"tree — it has measured an instrument that cannot tell a "
            f"zero-collect module from a covered one.\n{out[-3000:]}")

    silent = sorted(
        r for r in cand
        if r not in driven and counts[(_PLUGIN / r).resolve()] == 0)
    assert not silent, (
        "pytest module(s) from which the collector reports ZERO nodes — pytest "
        f"collects nothing from them and no runner invokes them: {silent}")

    # The exemption stays honest in the other direction too: the two are exempt
    # because they are DRIVEN as controls, which is only true while they remain
    # the zero-collect shape the wrapper above executes by path.
    unexpected = sorted(d for d in driven
                        if counts[(_PLUGIN / d).resolve()] != 0)
    assert not unexpected, (
        f"{unexpected} now collect nodes of their own, so pytest runs them and "
        f"the by-name exemption is a second, silent execution path — remove the "
        f"exemption rather than keeping both")


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
