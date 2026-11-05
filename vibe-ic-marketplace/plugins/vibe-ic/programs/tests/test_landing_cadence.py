#!/usr/bin/env python3
"""test_landing_cadence.py — the version-derived test cadence, wired into the
LANDING and into the PUSH.

Every test here is written so that it can GO RED. The asymmetry under test is
one-directional and the failure that matters is silent, so each pole is
asserted with its own opposite: a milestone that CAN be let off by a subset is
the defect, and a check that only ever sees the happy tier would not notice.

Policy (gatekeeper_review.derive_cadence, 2026-06-17):
    x.y.0 -> FULL      x.y.Z -> TARGETED      no bump -> NONE
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import configparser

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_REPO = _PLUGIN.parents[2]
_LAND = _REPO / "tools" / "gatekeeper-land.sh"
_HOOK = _REPO / "tools" / "git-hooks" / "pre-push"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load("_t_landing_cadence", _PROGRAMS / "landing_cadence.py")
gr = _load("_t_gatekeeper_review", _PROGRAMS / "gatekeeper_review.py")


def _population_fixture(tmp_path, config=None):
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "pytest.ini").write_text(config or (
        "[pytest]\ntestpaths = programs/tests\n"
        "norecursedirs = programs/tests/data_cases\n"))
    _population_file(root, "programs/tests/test_primary.py")
    _population_file(root, "programs/tests/nested/test_required.py")
    _population_file(root, "programs/tests/data_cases/case_a/test_reject.py", failing=True)
    return root


def _population_file(root, rel, failing=False):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_case():\n    assert " + ("False" if failing else "True") + "\n")
    return path


def test_declared_excluded_growth_does_not_add_a_release_blocker(tmp_path):
    root = _population_fixture(tmp_path)
    expected = ["programs/tests/nested/test_required.py", "programs/tests/test_primary.py"]
    before = lc.tree_test_files(root)
    _population_file(root, "programs/tests/data_cases/case_b/test_reject.py", failing=True)
    after = lc.tree_test_files(root)
    assert before == expected
    assert after == expected


def test_eligible_nested_growth_is_preserved(tmp_path):
    root = _population_fixture(tmp_path)
    before = set(lc.tree_test_files(root))
    added = "programs/tests/deeper/nested/test_required_new.py"
    _population_file(root, added, failing=True)
    after = set(lc.tree_test_files(root))
    assert after - before == {added}
    assert before - after == set()


def test_fixed_tree_excluded_data_never_enters_full_selection():
    from _hostpaths import require_repo
    ini = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "pytest.ini")
    config = configparser.ConfigParser(interpolation=None)
    config.read(ini)
    excluded = set()
    for pattern in config["pytest"]["norecursedirs"].split():
        scope = ini.parent / pattern
        if scope.is_dir():
            excluded.update(p.relative_to(ini.parent).as_posix() for p in scope.rglob("test_*.py"))
    assert excluded, "the declared excluded scope must contain a real witness"
    assert sorted(set(lc.tree_test_files(ini.parent)) & excluded) == []


@pytest.mark.parametrize("config", [None, "[pytest\nbroken", "[pytest]\n",
                                      "[pytest]\ntestpaths = missing\n"])
def test_unknown_population_cannot_emit_full_selection(tmp_path, capsys, config):
    root = _population_fixture(tmp_path)
    ini = root / "pytest.ini"
    if config is None:
        ini.unlink()
    else:
        ini.write_text(config)
    rc = lc.main(["--plugin-root", str(root), "--emit-full-selection"])
    output = capsys.readouterr()
    assert rc == 2
    assert output.out == ""
    assert "NOT_DETERMINED" in output.err


def test_declared_paths_and_python_patterns_define_the_population(tmp_path):
    root = _population_fixture(tmp_path, "[pytest]\ntestpaths = checks\npython_files = check_*.py *_spec.py\n")
    _population_file(root, "checks/check_alpha.py")
    _population_file(root, "checks/nested/beta_spec.py")
    _population_file(root, "checks/test_not_selected.py")
    assert lc.tree_test_files(root) == ["checks/check_alpha.py", "checks/nested/beta_spec.py"]


@pytest.mark.parametrize("ignored", ["programs/tests/data_cases", "data_cases", "*/data_*"])
def test_population_agrees_with_isolated_pytest_collection(tmp_path, ignored):
    root = _population_fixture(tmp_path, "[pytest]\ntestpaths = programs/tests\n"
                               f"norecursedirs = {ignored}\n")
    _population_file(root, "programs/tests/nested/additional_test.py")
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                             "-p", "no:cacheprovider"], cwd=root,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    actual = sorted({line.split("::")[0] for line in result.stdout.splitlines() if "::test_case" in line})
    assert actual == ["programs/tests/nested/additional_test.py",
                      "programs/tests/nested/test_required.py", "programs/tests/test_primary.py"]
    assert lc.tree_test_files(root) == actual


def test_nested_legitimate_failure_remains_executable(tmp_path):
    root = _population_fixture(tmp_path)
    bad = "programs/tests/deeper/test_product_failure.py"
    _population_file(root, bad, failing=True)
    selected = lc.tree_test_files(root)
    assert bad in selected
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *selected],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAILED " + bad + "::test_case" in result.stdout
    assert "1 failed, 2 passed" in result.stdout


def test_targeted_selection_shares_declared_population(tmp_path):
    root = _population_fixture(tmp_path)
    selector = lc._test_selector()
    (root / "programs" / "alpha.py").write_text("VALUE = 1\n")
    good = "programs/tests/nested/test_alpha.py"
    rejected = "programs/tests/data_cases/test_alpha.py"
    _population_file(root, good)
    _population_file(root, rejected, failing=True)
    for mode in selector.MODES:
        selected = selector.select_tests(["programs/alpha.py", rejected], root, mode=mode)
        assert good in selected
        assert rejected not in selected
        assert set(selected) <= set(lc.tree_test_files(root))


def test_discovery_never_imports_subject_collectors(tmp_path):
    root = _population_fixture(tmp_path)
    (root / "conftest.py").write_text("raise RuntimeError('candidate collector executed')\n")
    assert lc.tree_test_files(root) == ["programs/tests/nested/test_required.py", "programs/tests/test_primary.py"]


def test_explicit_testpath_file_follows_pytest_initial_file_semantics(tmp_path):
    root = _population_fixture(tmp_path, "[pytest]\ntestpaths = checks/explicit.py\npython_files = test_*.py\n")
    _population_file(root, "checks/explicit.py")
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                             "-p", "no:cacheprovider"], cwd=root,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks/explicit.py::test_case" in result.stdout
    assert lc.tree_test_files(root) == ["checks/explicit.py"]


# --------------------------------------------------------------------------
# a real git repo carrying a real version bump
# --------------------------------------------------------------------------
_PLUGIN_JSON = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"


def _repo_with_bump(tmp_path: Path, prev: str, cur: str) -> Path:
    repo = tmp_path / "r"
    (repo / Path(_PLUGIN_JSON).parent).mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def git(*a):
        subprocess.run(["git", *a], cwd=repo, env=env, check=True,
                       capture_output=True)

    def write(v):
        (repo / _PLUGIN_JSON).write_text(json.dumps({"name": "x", "version": v}))

    git("init", "-q", "-b", "main")
    write(prev)
    git("add", "-A"); git("commit", "-qm", f"base {prev}")
    write(cur)
    git("add", "-A"); git("commit", "-qm", f"head {cur}")
    return repo


# ============================ POLE A — patch ==============================

def test_a_patch_bump_is_targeted(tmp_path):
    repo = _repo_with_bump(tmp_path, "1.11.94", "1.11.95")
    cadence, why = lc.cadence_for(repo, "HEAD~1", "HEAD")
    assert cadence == "TARGETED", why


# ========================== POLE B — milestone ============================

def test_a_milestone_bump_is_full(tmp_path):
    repo = _repo_with_bump(tmp_path, "1.11.95", "1.12.0")
    cadence, why = lc.cadence_for(repo, "HEAD~1", "HEAD")
    assert cadence == "FULL", why


def test_a_major_milestone_is_full_too(tmp_path):
    repo = _repo_with_bump(tmp_path, "1.12.7", "2.0.0")
    assert lc.cadence_for(repo, "HEAD~1", "HEAD")[0] == "FULL"


# ================== the direction of every failure ========================

@pytest.mark.parametrize("head", [
    "4b825dc642cb6eb9a060e54bf8d69288fbee4904",   # the empty tree: no manifest
    "refs/heads/does-not-exist",
])
def test_a_head_it_cannot_read_is_full_never_none(tmp_path, head):
    """'I could not read the version' must never arrive as 'the cheap tier is
    fine'. NONE here would be exactly that, because NONE takes the same branch
    as TARGETED everywhere downstream."""
    repo = _repo_with_bump(tmp_path, "1.11.94", "1.11.95")
    cadence, why = lc.cadence_for(repo, "HEAD~1", head)
    assert cadence == "FULL", why
    assert cadence != "NONE"


def test_the_caller_cannot_supply_the_answer():
    """A caller-supplied cadence is a caller-supplied answer. The one thing this
    program exists to stop is a milestone declaring itself a patch, so there is
    no flag that lets it."""
    with pytest.raises(SystemExit):
        lc.main(["--cadence", "TARGETED"])
    src = (_PROGRAMS / "landing_cadence.py").read_text()
    assert '"--cadence"' not in src and "'--cadence'" not in src


# ============ describe(): the claim is earned from the selection ==========


def test_emit_full_selection_is_the_same_list_describe_judges(capsys):
    """The list that is RUN and the list completeness is judged against must be
    one list, or the landing could run one and certify the other."""
    assert lc.main(["--emit-full-selection", "--plugin-root", str(_PLUGIN)]) == 0
    emitted = capsys.readouterr().out.split()
    assert emitted == lc.tree_test_files(_PLUGIN)
    assert len(emitted) > 100


# ==================== the landing script is actually wired ================

def _code_only(text: str) -> str:
    """Shell text with comment lines removed. Asserting a token is 'not in' a
    file that EXPLAINS why the token is forbidden matches the explanation and
    reports the prose as the defect."""
    return "\n".join(l for l in text.splitlines()
                      if not l.lstrip().startswith("#"))


def test_the_landing_derives_the_cadence_and_does_not_accept_one():
    t = _LAND.read_text()
    assert "landing_cadence.py" in t, "the landing never asks what tier it owes"
    assert re.search(r'LANDING_CADENCE="?\$\(python3 "\$PROGRAMS/landing_cadence\.py"', t)
    assert '[ -n "$LANDING_CADENCE" ] || LANDING_CADENCE=FULL' in t, \
        "an unanswerable cadence must fall back to the STRICTER tier"
    assert "--cadence" not in _code_only(t), \
        "the landing must not be able to assert its own tier"


def test_the_landing_runs_the_whole_tree_on_a_milestone():
    t = _LAND.read_text()
    assert 'if [ "$LANDING_CADENCE" = "FULL" ]; then' in t
    assert "--emit-full-selection" in t
    assert "ci_targeted_test_select.py" in t, "the patch tier must be unchanged"


def test_the_stamp_records_the_cadence_it_was_earned_at():
    t = _LAND.read_text()
    assert "printf 'cadence=%s\\n' \"$LANDING_CADENCE\"" in t
    # line 1 must still be the commit and only the commit: two existing readers
    # depend on it (`head -1` here, and an older whole-file hook that fails closed)
    i = t.index("printf 'cadence=%s")
    assert "git rev-parse HEAD" in t[i - 200:i]


# ======================= the hook enforces the asymmetry ==================
# Driven by EXECUTING the shipped block, not by reading it: a text assertion
# cannot tell a guard from a guard with an inverted comparison.

_HOOK_BLOCK_START = "    STAMP_CADENCE=\"$(sed -n 's/^cadence=//p' \"$STAMP\" | tail -1)\""
_HOOK_BLOCK_END = "    STAMP_BASE="


def _hook_block() -> str:
    t = _HOOK.read_text()
    i = t.index(_HOOK_BLOCK_START)
    j = t.index(_HOOK_BLOCK_END, i)
    return t[i:j]


def _run_hook_block(tmp_path: Path, stamp_lines, milestone: str):
    """Execute the shipped refusal block with a stub landing_cadence.py that
    answers the hook's question with `milestone` (yes|no|unknown|<silence>).
    Returns (FAILED, stderr)."""
    stamp = tmp_path / "stamp"
    stamp.write_text("".join(l + "\n" for l in stamp_lines))
    progs = tmp_path / "programs"
    progs.mkdir(exist_ok=True)
    if milestone != "MISSING":
        body = "" if milestone == "SILENT" else \
            f"print('LANDING_MILESTONE={milestone}')\n"
        (progs / "landing_cadence.py").write_text(body)
    else:
        (progs / "landing_cadence.py").unlink(missing_ok=True)
    script = (
        # THE REAL HOOK'S FLAGS, not a convenient subset. pre-push runs under
        # `set -euo pipefail`; a harness using only `set -u` cannot see the
        # class of bug where a non-zero command ABORTS the hook, which is
        # exactly what a missing landing_cadence.py did.
        "set -euo pipefail\n"
        f'STAMP="{stamp}"\nPROGRAMS="{progs}"\nREPO_ROOT="{tmp_path}"\n'
        'HEAD_SHA=deadbeef\nPUSH_BASE=origin/main\nFAILED=0\n'
        + _hook_block() +
        '\necho "FAILED=$FAILED"\n'
    )
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    m = re.search(r"FAILED=(\d+)", p.stdout)
    assert m, p.stdout + p.stderr
    return int(m.group(1)), p.stderr


def test_hook_refuses_a_patch_stamp_for_a_milestone(tmp_path):
    """THE FORGERY. A TARGETED stamp presented for an x.y.0 tree."""
    failed, err = _run_hook_block(tmp_path, ["deadbeef", "cadence=TARGETED"], "yes")
    assert failed == 1, "a milestone was let off by a subset run"
    assert "MILESTONE" in err


def test_hook_reads_an_absent_cadence_line_as_the_weaker_tier(tmp_path):
    """A stamp written before this line existed cannot know what it ran. The
    safe reading of an absent claim is the one that cannot let a milestone
    through -- so a LEGACY one-line stamp does not satisfy a milestone."""
    failed, _ = _run_hook_block(tmp_path, ["deadbeef"], "yes")
    assert failed == 1


def test_hook_allows_a_milestone_stamped_at_full(tmp_path):
    failed, _ = _run_hook_block(tmp_path, ["deadbeef", "cadence=FULL"], "yes")
    assert failed == 0


def test_hook_does_not_punish_running_more_than_the_tier_demands(tmp_path):
    """A patch stamped at FULL is allowed. A ratchet that went red when someone
    was MORE thorough would push people toward the cheaper tier."""
    failed, _ = _run_hook_block(tmp_path, ["deadbeef", "cadence=FULL"], "no")
    assert failed == 0


def test_hook_allows_the_ordinary_patch(tmp_path):
    failed, _ = _run_hook_block(tmp_path, ["deadbeef", "cadence=TARGETED"], "no")
    assert failed == 0


@pytest.mark.parametrize("answer", ["unknown", "SILENT", "MISSING"])
def test_hook_does_not_refuse_what_it_could_not_identify(tmp_path, answer):
    """DELIBERATE, AND NAMED SO IT IS NOT MISTAKEN FOR AN OVERSIGHT.

    Only a POSITIVELY identified milestone refuses here. The strict
    'assume FULL when in doubt' default lives on the LANDING side, where it
    costs time and nothing else; here it would refuse every push from any
    checkout where the program cannot run, and a hook that refuses everything
    is a hook that gets bypassed -- a cost this repo has already paid.

    The milestone hole stays closed because the LANDING mints the stamp:
    cadence_for() returns FULL for an unreadable tree, so an x.y.0 commit
    cannot acquire a TARGETED stamp unless the program RAN and said TARGETED
    for it -- which is the case above."""
    failed, _ = _run_hook_block(tmp_path, ["deadbeef", "cadence=TARGETED"], answer)
    assert failed == 0


def test_a_checkout_without_the_program_does_not_abort_the_hook(tmp_path):
    """`python3 <missing file>` exits 2; under the hook's `set -euo pipefail`
    that aborted the WHOLE hook, refusing the push while asserting nothing
    about the commit. Every tree older than this change is such a checkout."""
    failed, err = _run_hook_block(tmp_path, ["deadbeef", "cadence=TARGETED"], "MISSING")
    assert failed == 0
    assert "ABORTED" not in err


# ------- milestone_check(): the hook's narrower question, three answers ------

def test_milestone_check_says_yes_only_for_a_milestone(tmp_path):
    repo = _repo_with_bump(tmp_path, "1.11.95", "1.12.0")
    assert lc.milestone_check(repo, "HEAD~1", "HEAD") == "yes"


def test_milestone_check_says_no_for_a_patch(tmp_path):
    repo = _repo_with_bump(tmp_path, "1.11.94", "1.11.95")
    assert lc.milestone_check(repo, "HEAD~1", "HEAD") == "no"


def test_milestone_check_says_unknown_rather_than_guessing(tmp_path):
    """The two questions have OPPOSITE defaults and that is the design:
    cadence_for -> FULL (run more), milestone_check -> unknown (accuse nobody)."""
    repo = _repo_with_bump(tmp_path, "1.11.94", "1.11.95")
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    assert lc.milestone_check(repo, "HEAD~1", empty_tree) == "unknown"
    assert lc.cadence_for(repo, "HEAD~1", empty_tree)[0] == "FULL"


def test_the_refusal_can_be_removed_and_the_tests_notice(tmp_path):
    """THE CONTROL. Delete the comparison from the block and the milestone pole
    goes green — which is what proves the passing tests above are measuring the
    guard and not the harness."""
    block = _hook_block().replace(
        '[ "$IS_MILESTONE" = "yes" ] && [ "$STAMP_CADENCE" != "FULL" ]',
        'false')
    assert "false; then" in block, "the control did not actually disarm the guard"
    stamp = tmp_path / "s"; stamp.write_text("deadbeef\ncadence=TARGETED\n")
    progs = tmp_path / "p"; progs.mkdir()
    (progs / "landing_cadence.py").write_text("print('LANDING_MILESTONE=yes')\n")
    script = ("set -u\n"
              f'STAMP="{stamp}"\nPROGRAMS="{progs}"\nREPO_ROOT="{tmp_path}"\n'
              'HEAD_SHA=d\nPUSH_BASE=origin/main\nFAILED=0\n'
              + block + '\necho "FAILED=$FAILED"\n')
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert "FAILED=0" in p.stdout, p.stdout + p.stderr
