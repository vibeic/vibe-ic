#!/usr/bin/env python3
"""Tests for full_suite_run_check.py — did the agent run the FULL suite?

RE-PINNED FOR THE OWNER-LEVEL RULING OF 2026-08-31. Every case below that
changed direction is marked; the ones that did not are the ones that carry the
change's weight, because a rewrite whose negative controls all moved with it
has proved nothing.

WHAT CHANGED. The acceptance used to read the ARGUMENT SHAPE: no positional
path, or a path under `pytest.ini`'s single testpath, meant FULL. It now reads
COVERAGE OF THE GIT-DERIVED POPULATION — `run_tests.sh` is FULL because the
tiers it prints cover every tracked test file, and `programs/tests` is not
because it leaves 141 of 3117 unrun. So a bare `pytest`, which resolves to that
one testpath, moved from PASS to FAIL, and so did the two `programs/tests`
cases that v1.6.0 had moved the other way. The reasoning v1.6.0 recorded was
sound for the TWO-TREE world it was made in and is preserved verbatim below;
what outran it is `tools/phase1_engine/tests` (#1391), `mcp-eda/test` (#1420),
`skills/*/tests` and `_shared` (v1.13.80).

WHAT DID NOT CHANGE, and is asserted here for that reason: a `-k` selector, a
single test file, a run with no test invocation at all, an empty log, a missing
file and a bad argument list all keep exactly the exit codes they had. Widening
the gate to recognise the runner must not have turned it into a rubber stamp.

`test_run_tests_sh_is_classified_as_the_full_suite.py` is this change's own
acceptance file and carries the runner, cheat and refusal arms.
(chip-AGNOSTIC.)"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "full_suite_run_check.py"
_spec = importlib.util.spec_from_file_location("full_suite_run_check", _PROG)
fsr = importlib.util.module_from_spec(_spec)
sys.modules["full_suite_run_check"] = fsr
_spec.loader.exec_module(fsr)


# ---- PASS cases ---------------------------------------------------------
def test_pass_the_runner_that_reaches_every_tree():
    """The one command that executes all five trees. Before the ruling this
    program held ZERO occurrences of `run_tests` and answered "the suite was
    never run" for it."""
    assert fsr.main(["--command", "./run_tests.sh"]) == 0


def test_pass_cd_then_runner_chain():
    """`cd $ROOT && ./run_tests.sh` — the canonical Step-3 command. The chain
    is split on `&&` and each segment classified, as before."""
    assert fsr.main(["--command", "cd /plugin && ./run_tests.sh"]) == 0


def test_pass_flags_after_the_runner_do_not_disturb_it():
    """`run_tests.sh` forwards extra arguments to pytest; passing some must not
    stop it being the full suite, because it still runs every tier."""
    assert fsr.main(["--command", "./run_tests.sh -q -p no:cacheprovider"]) == 0


# ---- CHANGED DIRECTION at the 2026-08-31 ruling -------------------------
def test_a_bare_pytest_is_a_subset_now():
    """CHANGED. Was `test_pass_no_path_filter` / `test_pass_bare_pytest`,
    granted FULL with the reason "pytest.ini testpaths runs both trees" —
    describing a config this repository has never had. `testpaths` names ONE
    tree (`single_testpath_guard.py` pins it), so a bare `pytest` runs one of
    five."""
    assert fsr.main(["--command", "python3 -m pytest -q"]) == 1
    assert fsr.main(["--command", "pytest"]) == 1
    assert fsr.main(["--command", "cd /plugin && python3 -m pytest -q"]) == 1
    assert fsr.main(["--command", "python3 -m pytest -q -p no:cacheprovider"]) == 1


def test_naming_a_tree_that_does_not_exist_adds_no_coverage():
    """CHANGED. Was `test_pass_both_trees_explicit`. `tests` HAS NEVER EXISTED
    in this repository — pytest does not fail on a path that is not there, it
    collects nothing — so `programs/tests tests` covers exactly what
    `programs/tests` covers, and that is one tree of five."""
    assert fsr.main(
        ["--command", "python3 -m pytest -q programs/tests tests"]) == 1


def test_the_value_flag_parsing_still_holds():
    """UNCHANGED IN SUBSTANCE. `-p no:cacheprovider` must still not be read as
    a positional path — if it were, the reason below would name it as a covered
    directory instead of naming the trees that went unrun."""
    pop = fsr.population()
    full, reason = fsr._classify_pytest(
        ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "programs/tests"], pop)
    assert full is False
    assert "no:cacheprovider" not in reason
    assert "programs/tests" in reason


# ---- FAIL cases ---------------------------------------------------------
def test_programs_tests_alone_is_not_full_anymore():
    """CHANGED, and it is the same test twice over.

    It was written PRE-merge to pin `programs/tests` alone == subset. v1.6.0
    inverted it with a measurement (`pytest -q --collect-only` and
    `pytest programs/tests -q --collect-only` both collected 19504) and a
    stated reason: the integration tree `tests/` was empty, so one tree WAS the
    whole suite. Correct for the two-tree world it was asked in.

    The 2026-08-31 ruling inverts it back, for a different reason and against a
    different population: four more trees were recognised after v1.6.0, and
    `programs/tests` leaves 141 of 3117 tracked test files unrun. Nothing about
    the v1.6.0 measurement was wrong; it is simply no longer the question."""
    assert fsr.main(["--command", "python3 -m pytest -q programs/tests/"]) == 1


def test_fail_only_integration_tests():
    """UNCHANGED."""
    assert fsr.main(["--command", "pytest tests/"]) == 1


def test_fail_single_file():
    """UNCHANGED. A file-level path is a subset wherever it lives."""
    assert fsr.main(["--command", "pytest tests/test_compliance.py"]) == 1
    assert fsr.main(
        ["--command", "pytest programs/tests/test_landing_cadence.py"]) == 1


def test_fail_k_selector():
    """UNCHANGED. A narrowing selector cannot be rescued by any coverage set —
    including the runner's. This is the case that keeps the widening honest."""
    assert fsr.main(["--command", "python3 -m pytest -q -k version"]) == 1
    assert fsr.main(["--command", "python3 -m pytest -q -m slow"]) == 1


def test_fail_no_pytest_at_all():
    """UNCHANGED. The suite was never run -> honest FAIL, never vacuous PASS.
    A shell script that is not a test runner stays in this class: recognising
    "runs a .sh" rather than "runs every tier" would pass anything."""
    assert fsr.main(["--command", "git push origin main"]) == 1
    assert fsr.main(["--command", "./tools/ci/repo_hygiene_gates.sh"]) == 1


# ---- file scan + JSON + edge --------------------------------------------
def test_file_scan_subset_then_full(tmp_path):
    """UNCHANGED IN SHAPE, re-pinned in content: a full-suite run ANYWHERE in
    the log rescues it. The rescuing line is now the runner, because a bare
    `pytest` no longer rescues anything."""
    f = tmp_path / "log.txt"
    f.write_text(
        "python3 -m pytest -q programs/tests/\n"   # subset
        "./run_tests.sh\n"                          # full — rescues it
    )
    out = tmp_path / "r.json"
    rc = fsr.main([str(f), "--json", str(out)])
    assert rc == 0   # a full-suite run is present anywhere => PASS
    rep = json.loads(out.read_text())
    assert rep["full_suite_found"] is True
    assert rep["pytest_invocations"] == 2


def test_file_scan_of_a_programs_tests_log_is_a_subset(tmp_path):
    """CHANGED, mirroring test_programs_tests_alone_is_not_full_anymore through
    the FILE path rather than `--command`, because the two code paths reach the
    classifier differently and a fix applied to one is not applied to the other.
    The JSON report must say so too — the landing reads the file, not stdout."""
    f = tmp_path / "log.txt"
    f.write_text("python3 -m pytest -q programs/tests/\n")
    out = tmp_path / "r.json"
    assert fsr.main([str(f), "--json", str(out)]) == 1
    rep = json.loads(out.read_text())
    assert rep["full_suite_found"] is False
    assert rep["population"] > 1000
    assert "mcp-eda" in rep["invocations"][0]["reason"]
    # UNCHANGED: a genuinely narrowed run in a scanned log is still a subset.
    f2 = tmp_path / "log2.txt"
    f2.write_text("python3 -m pytest -q programs/tests/ -k foo\n")
    assert fsr.main([str(f2)]) == 1


def test_empty_input_is_honest_fail(tmp_path):
    """UNCHANGED."""
    f = tmp_path / "empty.txt"
    f.write_text("\n# nothing\n")
    rc = fsr.main([str(f)])
    # no pytest seen => the suite was NOT run => FAIL, never vacuous PASS.
    assert rc == 1


def test_missing_file_is_error(tmp_path):
    """UNCHANGED."""
    assert fsr.main([str(tmp_path / "nope.txt")]) == 2


def test_no_args_is_error():
    """UNCHANGED."""
    assert fsr.main([]) == 2


# ── THE DERIVATION ITSELF ───────────────────────────────────────────────────
# `_integration_tree_has_tests()` and the four cases that drove it are gone.
# They asked "is the legacy `tests/` tree empty?" so that `programs/tests` could
# be granted FULL while it was. The subtraction subsumes that question in both
# directions and without a probe: an EMPTY tree contributes no file to the
# population, so it cannot be missing from any coverage set; a tree that grows a
# test file joins the population and every invocation that does not run it
# becomes a subset the same day. Nobody edits the gate either way — which is
# what the removed probe was for.

def test_the_population_is_the_git_corpus_not_a_walk():
    """The population is the LANDING's corpus, imported, not a second walk.

    A second definition of "the corpus" drifts, and the direction it drifts in
    is a tree nothing checks. This asserts the two agree file-for-file."""
    lu = fsr._load_sibling("landing_unselectable_pytest_corpus")
    repo = lu.repo_root(start=Path(fsr.__file__))
    if repo is None:                                    # pragma: no cover
        import pytest
        pytest.skip("not in a repository")
    tracked = lu.tracked_test_files(repo)
    plugin_rel = Path(fsr.__file__).resolve().parents[1].relative_to(repo).as_posix()
    expect = {f[len(plugin_rel) + 1:] for f in tracked
              if f.startswith(plugin_rel + "/")
              and "/programs/tests/fixtures/" not in "/" + f}
    assert set(fsr.population()) == expect


def test_the_derived_tiers_are_the_tiers_the_runner_discovers():
    """covering_dirs(population) must equal `run_tests.sh --list-tiers`.

    Two independent derivations of "what the full suite is" — one from git, one
    from the runner's own TEST_DIRS array — and the gate is only trustworthy
    while they agree. MEASURED at e37d10e1e: 74 == 74, symmetric difference
    empty. When they diverge, one of them is wrong and this says which pair."""
    plugin = Path(fsr.__file__).resolve().parents[1]
    tiers = fsr.runner_tiers(plugin / "run_tests.sh")
    assert tiers is not None, "run_tests.sh did not answer --list-tiers"
    derived = fsr.covering_dirs(fsr.population())
    assert sorted(tiers) == derived, (
        f"only the runner lists {sorted(set(tiers) - set(derived))}; "
        f"only the population implies {sorted(set(derived) - set(tiers))}")


def test_a_subset_flag_narrows_regardless_of_the_coverage_set():
    """UNCHANGED IN MEANING (was test_subset_flags_still_narrow_regardless_of_
    tree_state). No coverage can rescue a `-k`."""
    pop = fsr.population()
    full, _ = fsr._classify_pytest(
        ["python3", "-m", "pytest", "programs/tests", "-q", "-k", "foo"], pop)
    assert full is False
