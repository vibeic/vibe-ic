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
    undiscovered = sorted(on_disk - set(rows))
    assert not undiscovered, (
        f"{len(undiscovered)} file(s) match pytest's own collection patterns "
        "and sit under a tier the suite runs, yet pytest reported no collector "
        f"for them: {undiscovered[:20]}")

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
