from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "trusted_test_selection", HERE / "trusted_test_selection.py")
assert SPEC and SPEC.loader
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Selection Test")
    _git(repo, "config", "user.email", "selection@example.test")
    selector = (HERE.parent.parent / "vibe-ic-marketplace" / "plugins" /
                "vibe-ic" / "programs" / "ci_targeted_test_select.py")
    _write(repo, S.SELECTOR_REL, selector.read_text(encoding="utf-8"))
    _write(repo, f"{S.PLUGIN_REL}/programs/foo.py", "VALUE = 1\n")
    _write(
        repo, f"{S.PLUGIN_REL}/programs/tests/test_foo.py",
        "import foo\n\ndef test_foo():\n    assert foo.VALUE == 1\n")
    for rel in S.CONTROL_TESTS:
        _write(repo, f"{S.PLUGIN_REL}/{rel}",
               f"def test_{Path(rel).stem}():\n    assert True\n")
    base = _commit(repo, "base")
    _write(repo, f"{S.PLUGIN_REL}/programs/foo.py", "VALUE = 2\n")
    (repo / S.PLUGIN_REL / "programs/tests/test_foo.py").unlink()
    _write(repo, f"{S.PLUGIN_REL}/programs/tests/test_new.py",
           "def test_new():\n    assert True\n")
    candidate = _commit(repo, "candidate")
    return repo, base, candidate


def _worktrees(repo: Path, base: str, candidate: str, tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    base_tree = tmp_path / "base"
    candidate_tree = tmp_path / "candidate"
    _git(repo, "worktree", "add", "-q", "--detach", str(base_tree), base)
    _git(repo, "worktree", "add", "-q", "--detach", str(candidate_tree),
         candidate)
    return base_tree, candidate_tree


def test_union_keeps_deleted_base_test_and_new_candidate_test(tmp_path):
    repo, base, candidate = _repo(tmp_path)
    base_tree, candidate_tree = _worktrees(
        repo, base, candidate, tmp_path / "trees")
    record = S.build(
        object_repo=repo, base=base, candidate=candidate,
        selector_commit=base,
        selector_path=base_tree / S.SELECTOR_REL,
        base_snapshot=base_tree,
        candidate_snapshot=candidate_tree,
    )
    payload = record["payload"]
    by_path = {row["path"]: row for row in payload["tests"]}
    deleted = by_path["programs/tests/test_foo.py"]
    added = by_path["programs/tests/test_new.py"]
    assert deleted["base"]["present"] is True
    assert deleted["candidate"] == {"present": False}
    assert added["base"] == {"present": False}
    assert added["candidate"]["present"] is True
    assert "programs/tests/test_foo.py" in payload["base_selection"]
    assert "programs/tests/test_foo.py" not in payload["candidate_selection"]
    assert "programs/tests/test_new.py" in payload["candidate_selection"]
    assert record["payload_sha256"] == S.hashlib.sha256(
        S.transition.canonical_bytes(payload)).hexdigest()


def test_candidate_selector_rewrite_cannot_narrow_base_owned_result(tmp_path):
    repo, base, candidate = _repo(tmp_path)
    _git(repo, "checkout", "-q", candidate)
    _write(repo, S.SELECTOR_REL,
           "MODE_IMPORT_EDGE='import-edge'\n"
           "def select_tests(*args, **kwargs): return []\n")
    narrowed = _commit(repo, "candidate narrows selector")
    base_tree, candidate_tree = _worktrees(
        repo, base, narrowed, tmp_path / "trees")
    record = S.build(
        object_repo=repo, base=base, candidate=narrowed,
        selector_commit=base,
        selector_path=base_tree / S.SELECTOR_REL,
        base_snapshot=base_tree,
        candidate_snapshot=candidate_tree,
    )
    assert "programs/tests/test_foo.py" in record["payload"]["base_selection"]
    assert all(rel in record["payload"]["candidate_selection"]
               for rel in S.CONTROL_TESTS)


def test_selector_path_must_match_the_selected_authority_commit(tmp_path):
    repo, base, candidate = _repo(tmp_path)
    base_tree, candidate_tree = _worktrees(
        repo, base, candidate, tmp_path / "trees")
    selector = base_tree / S.SELECTOR_REL
    selector.write_text("def select_tests(*a, **k): return []\n",
                        encoding="utf-8")
    with pytest.raises(S.Refusal, match="do not match"):
        S.build(
            object_repo=repo, base=base, candidate=candidate,
            selector_commit=base, selector_path=selector,
            base_snapshot=base_tree,
            candidate_snapshot=candidate_tree,
        )


def test_missing_mandatory_control_refuses_instead_of_shrinking(tmp_path):
    repo, base, candidate = _repo(tmp_path)
    _git(repo, "checkout", "-q", candidate)
    (repo / S.PLUGIN_REL / S.CONTROL_TESTS[0]).unlink()
    missing = _commit(repo, "delete control")
    base_tree, candidate_tree = _worktrees(
        repo, base, missing, tmp_path / "trees")
    with pytest.raises(S.Refusal, match="mandatory negative control is absent"):
        S.build(
            object_repo=repo, base=base, candidate=missing,
            selector_commit=base,
            selector_path=base_tree / S.SELECTOR_REL,
            base_snapshot=base_tree,
            candidate_snapshot=candidate_tree,
        )


def test_distinct_commit_cannot_be_laundered_through_the_same_snapshot(tmp_path):
    repo, base, candidate = _repo(tmp_path)
    base_tree, _candidate_tree = _worktrees(
        repo, base, candidate, tmp_path / "trees")
    with pytest.raises(S.Refusal, match="selection snapshot is not object-exact"):
        S.build(
            object_repo=repo, base=base, candidate=candidate,
            selector_commit=base,
            selector_path=base_tree / S.SELECTOR_REL,
            base_snapshot=base_tree,
            candidate_snapshot=base_tree,
        )


def test_progress_plan_exactly_binds_ordered_selection():
    assert S.progress_plan(
        ["programs/tests/test_a.py", "programs/tests/test_b.py"],
        scope="pytest:B1", stall_grace_seconds=300) == {
            "schema": 1,
            "scope": "pytest:B1",
            "stall_grace_seconds": 300,
            "units": [
                "pytest:collection-complete",
                "pytest:programs/tests/test_a.py",
                "pytest:programs/tests/test_b.py",
                "pytest:record-published",
            ],
        }
    with pytest.raises(S.Refusal, match="sorted/unique"):
        S.progress_plan(
            ["programs/tests/test_b.py", "programs/tests/test_a.py"],
            scope="pytest:B1", stall_grace_seconds=300)


def test_progress_plan_interleaves_only_parent_owned_matrix_module_units():
    plan = S.progress_plan(
        [S.HERMETIC_MATRIX_FILE], scope="pytest:B1",
        stall_grace_seconds=300)
    expected = []
    spec = S.HERMETIC_TEST_PROGRESS[S.HERMETIC_MATRIX_FILE]
    by_ordinal = {}
    for ordinal, nodeid, scope, total in spec["domains"]:
        by_ordinal.setdefault(ordinal, []).append((nodeid, scope, total))
    for ordinal in range(1, spec["items"] + 1):
        for nodeid, scope, total in by_ordinal.get(ordinal, ()):
            expected.extend(
                S.domain_progress_unit(
                    S.HERMETIC_MATRIX_FILE, nodeid, scope, completed, total)
                for completed in range(1, total + 1))
        expected.append(S.test_progress_unit(
            S.HERMETIC_MATRIX_FILE, ordinal, spec["items"]))
    assert plan["units"] == [
        "pytest:collection-complete",
        *expected,
        f"pytest:{S.HERMETIC_MATRIX_FILE}",
        "pytest:record-published",
    ]
    assert sum(row[3] for row in spec["domains"]) == 29
    assert len(expected) == 61
    assert len(expected) == len(set(expected))


def test_nested_progress_schedule_matches_live_pytest_collection():
    plugin_root = HERE.parent.parent / S.PLUGIN_REL
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", *S.HERMETIC_TEST_PROGRESS],
        cwd=plugin_root, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    collected = [
        line.strip() for line in proc.stdout.splitlines()
        if any(line.startswith(test_file + "::")
               for test_file in S.HERMETIC_TEST_PROGRESS)
    ]
    for test_file, spec in S.HERMETIC_TEST_PROGRESS.items():
        nodes = [nodeid for nodeid in collected
                 if nodeid.startswith(test_file + "::")]
        assert len(nodes) == spec["items"], (
            test_file, spec["items"], len(nodes))
        for ordinal, nodeid, _scope, _total in spec["domains"]:
            assert nodes[ordinal - 1] == nodeid


def test_every_nested_progress_producer_has_one_exact_base_owned_schedule():
    plugin_root = HERE.parent.parent / S.PLUGIN_REL
    all_tests = sorted(
        path.relative_to(plugin_root).as_posix()
        for path in (plugin_root / "programs/tests").glob("test_*.py"))
    discovered = S.nested_progress_producers(
        all_tests, plugin_root=plugin_root)
    assert set(discovered) == set(S.HERMETIC_TEST_PROGRESS)
    assert all(
        discovered[test_file]
        in S.HERMETIC_TEST_PROGRESS[test_file]["producer_profiles"]
        for test_file in discovered)
    S.validate_nested_progress_inventory(all_tests, plugin_root=plugin_root)


def test_a_new_or_unscheduled_nested_producer_refuses(tmp_path):
    plugin_root = tmp_path / "plugin"
    owner = "programs/tests/test_new_nested.py"
    path = plugin_root / owner
    path.parent.mkdir(parents=True)
    path.write_text("def test_x():\n    replay_many([])\n", encoding="utf-8")
    with pytest.raises(S.Refusal, match="inventory differs"):
        S.validate_nested_progress_inventory(
            [owner], plugin_root=plugin_root)


def test_domain_progress_unit_refuses_ambiguous_or_unbounded_labels():
    with pytest.raises(S.Refusal, match="nodeid"):
        S.domain_progress_unit("programs/tests/test_a.py", "other.py::test_x",
                               "scope", 1, 1)
    with pytest.raises(S.Refusal, match="scope"):
        S.domain_progress_unit("programs/tests/test_a.py",
                               "programs/tests/test_a.py::test_x",
                               "scope|forged", 1, 1)
    with pytest.raises(S.Refusal, match="denominator"):
        S.domain_progress_unit("programs/tests/test_a.py",
                               "programs/tests/test_a.py::test_x",
                               "scope", 1, 10_001)
    with pytest.raises(S.Refusal, match="test-progress denominator"):
        S.test_progress_unit("programs/tests/test_a.py", 2, 1)
