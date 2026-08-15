"""Risk routing and verdict invariants for the bounded landing profiles."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import landing_gate_plan as P
import landing_merge_verdict as V


TREE = "a" * 40
SHA = "b" * 40


def _git(repo: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        check=True,
    )
    return cp.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    plugin = tmp_path / P.PLUGIN_PREFIX
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / "programs/tests").mkdir(parents=True)
    (plugin / "programs/module.py").write_text("VALUE = 1\n")
    (plugin / "programs/tests/test_module.py").write_text("def test_x(): pass\n")
    (plugin / ".claude-plugin/plugin.json").write_text(
        json.dumps({"version": "0.2.9"}) + "\n")
    (tmp_path / "README.md").write_text("base\n")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/gatekeeper-land.sh").write_text("base\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "gate@example.invalid")
    _git(tmp_path, "config", "user.name", "gate")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    # Routing tests should exercise the policy, not spend time building the
    # repository's real import graph in a tiny synthetic fixture.
    monkeypatch.setattr(
        P, "_selected_tests",
        lambda _r, _p: [f"programs/tests/test_{i}.py" for i in range(12)],
    )
    return tmp_path


def _commit(repo: Path, message: str = "change") -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def test_documentation_only_is_fast(repo: Path):
    (repo / "README.md").write_text("docs only\n")
    head = _commit(repo)
    got = P.plan(repo, "HEAD^", head)
    assert got.automatic_profile == "fast"
    assert got.effective_profile == "fast"
    assert got.requested_profile == "auto"
    assert got.budget_seconds == 180
    assert got.stages == [
        "merge-identity", "cheap-landing-policy", "affected-tests",
        "write-guard",
    ]


def test_localised_software_is_standard(repo: Path):
    path = repo / P.PLUGIN_PREFIX / "programs/module.py"
    path.write_text("VALUE = 2\n")
    head = _commit(repo)
    got = P.plan(repo, "HEAD^", head)
    assert got.automatic_profile == "standard"
    assert got.budget_seconds == 600
    assert "plugin-full-audit" in got.stages
    assert "repo-hygiene" not in got.stages


def test_gate_edit_is_full_and_cannot_be_downgraded(repo: Path):
    (repo / "tools/gatekeeper-land.sh").write_text("changed\n")
    head = _commit(repo)
    got = P.plan(repo, "HEAD^", head, requested="fast")
    assert got.automatic_profile == "full"
    assert got.effective_profile == "full"
    assert got.budget_seconds is None
    assert any("cannot downgrade" in reason for reason in got.reasons)


def test_milestone_version_is_full(repo: Path):
    manifest = repo / P.PLUGIN_JSON
    manifest.write_text(json.dumps({"version": "0.3.0"}) + "\n")
    head = _commit(repo)
    got = P.plan(repo, "HEAD^", head)
    assert got.effective_profile == "full"
    assert any("milestone" in reason for reason in got.reasons)


def test_deleted_test_is_full_and_recorded(repo: Path):
    rel = f"{P.PLUGIN_PREFIX}/programs/tests/test_module.py"
    (repo / rel).unlink()
    head = _commit(repo)
    got = P.plan(repo, "HEAD^", head)
    assert got.effective_profile == "full"
    assert got.deleted_tests == [rel]


def _land(*rows: tuple[str, str]) -> V.LandLog:
    text = "=== gatekeeper landing gates ===\n"
    text += "".join(f"  {word}  {label}\n" for word, label in rows)
    return V.parse_land_log(text)


def _verdict(**over) -> V.Verdict:
    kw = dict(
        rebase_status="ok", expected_tree=TREE, verified_tree=TREE,
        github_tree=TREE,
        land=_land(("PASS", "cheap policy"), ("PASS", "targeted tests (1 file(s))")),
        base_land=_land(("PASS", "cheap policy"), ("PASS", "targeted tests (1 file(s))")),
        delta=V.Delta(base_total=1, candidate_total=1, overlap=1),
        verified_sha=SHA, truncated=False, dropped_files=(), selection_size=1,
    )
    kw.update(over)
    return V.decide(**kw)


def test_a_passing_base_gate_cannot_disappear():
    base = _land(("PASS", "cheap policy"), ("PASS", "structural audit"),
                 ("PASS", "targeted tests (1 file(s))"))
    cand = _land(("PASS", "cheap policy"),
                 ("PASS", "targeted tests (1 file(s))"))
    got = _verdict(base_land=base, land=cand)
    assert not got.ok
    assert any("PASSING GATE WAS REMOVED" in reason for reason in got.reasons)


def test_a_profile_without_its_plan_is_unmeasurable():
    got = _verdict(landing_profile="fast")
    assert not got.ok
    assert got.unmeasurable
    assert any("PLAN WAS NOT SUPPLIED" in reason for reason in got.reasons)


def test_deleted_test_needs_a_recorded_reason():
    plan = {
        "automatic_profile": "full", "requested_profile": "full",
        "effective_profile": "full", "budget_seconds": None,
        "stages": ["affected-tests"], "deleted_tests": ["test_gone.py"],
        "selected_tests": ["test_kept.py"], "selected_test_files": 1,
    }
    refused = _verdict(landing_profile="full", landing_plan=plan)
    assert not refused.ok
    assert any("TEST FILE(S) WERE DELETED" in reason for reason in refused.reasons)

    allowed = _verdict(
        landing_profile="full", landing_plan=plan,
        test_removal_reason="obsolete behaviour intentionally removed",
    )
    assert allowed.ok, allowed.reasons
    assert "TEST_COVERAGE_SHRANK_AUTHORISED" in allowed.disclosures


def test_plan_reader_rejects_stale_identity(tmp_path: Path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({
        "schema_version": 1, "base": "old", "head": SHA,
        "effective_profile": "fast", "stages": ["affected-tests"],
        "deleted_tests": [], "selected_tests": ["test_x.py"],
        "selected_test_files": 1,
    }))
    doc, error = V.read_landing_plan(str(path), "fast", "new", SHA)
    assert doc is None
    assert "ANOTHER RUN" in error


def test_plan_reader_rejects_same_size_but_different_selection(tmp_path: Path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({
        "schema_version": 1, "base": "base", "head": SHA,
        "effective_profile": "fast", "stages": ["affected-tests"],
        "deleted_tests": [], "selected_tests": ["test_expected.py"],
        "selected_test_files": 1,
    }))
    doc, error = V.read_landing_plan(
        str(path), "fast", "base", SHA, ["test_substituted.py"])
    assert doc is None
    assert "DOES NOT MATCH" in error
