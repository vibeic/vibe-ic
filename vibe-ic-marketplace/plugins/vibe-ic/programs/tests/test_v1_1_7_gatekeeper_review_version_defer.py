"""Owner directive 2026-06-17 — authoring PRs (field/core) carry NO version
bump; the gatekeeper assigns ALL versions at merge.

`gatekeeper_review.py --version-by-gatekeeper` is the AUTHORING-side review of
such a version-less PR: when cur==prev (no bump in the diff) the version-bump
gate DEFERS (rc -1 SKIP) instead of FAILing "not bumped", and the authoring
cadence floor is TARGETED. The gatekeeper's FINAL review — run WITHOUT the flag,
AFTER gatekeeper_assign_version.py writes the real version — still fully
ENFORCES the monotonic+equality bump. These tests pin both halves via the
version_bump_gate unit AND the review() orchestration (with injected versions).

§4.05 no-leak: the flag MUST NOT defer a genuinely-broken bump — a NON-monotonic
authoring bump (cur<prev) and a marketplace/plugin MISMATCH still FAIL even with
the flag set. chip-AGNOSTIC.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import gatekeeper_review as GR  # noqa: E402


# ── version_bump_gate unit: the defer condition ───────────────────────────────
def test_versionless_authoring_pr_defers_with_flag():
    # cur==prev (no bump), flag ON -> SKIP (deferred to gatekeeper at merge).
    g = GR.version_bump_gate("1.1.6", "1.1.6", "1.1.6",
                             version_by_gatekeeper=True)
    assert g.rc == -1
    assert "deferred" in g.summary
    assert g.green  # rc -1 SKIP is non-blocking


def test_versionless_authoring_pr_fails_WITHOUT_flag():
    # Same no-bump, flag OFF -> the enforced path FAILs "not bumped".
    g = GR.version_bump_gate("1.1.6", "1.1.6", "1.1.6",
                             version_by_gatekeeper=False)
    assert g.rc == 1
    assert not g.green


def test_real_bump_passes_under_flag_enforced_rerun():
    # The gatekeeper's post-assignment re-run: a real monotonic bump
    # 1.1.6 -> 1.1.7 with marketplace in sync PASSes (flag OFF = enforced).
    g = GR.version_bump_gate("1.1.7", "1.1.6", "1.1.7",
                             version_by_gatekeeper=False)
    assert g.rc == 0, g.summary
    assert g.green


# ── §4.05: the flag must NOT defer a genuinely-broken bump ────────────────────
def test_flag_does_not_defer_nonmonotonic_authoring_bump():
    # An author who (wrongly) bumped DOWNWARD: cur<prev, flag ON. cur!=prev so
    # the defer condition does NOT apply -> still evaluated -> FAIL.
    g = GR.version_bump_gate("1.1.5", "1.1.6", "1.1.5",
                             version_by_gatekeeper=True)
    assert g.rc == 1, g.summary
    assert not g.green


def test_flag_does_not_defer_marketplace_mismatch():
    # cur==prev would defer, but here the author DID bump plugin.json to 1.1.7
    # while marketplace stayed 1.1.6 -> cur!=prev so evaluated -> equality FAIL.
    g = GR.version_bump_gate("1.1.7", "1.1.6", "1.1.6",
                             version_by_gatekeeper=True)
    assert g.rc == 1, g.summary
    assert not g.green


# ── review() orchestration: cadence + verdict on a version-less authoring PR ──
def _plugin_root():
    return PROGRAMS.parent  # …/plugins/vibe-ic


def test_review_versionless_authoring_pr_cadence_targeted():
    v = GR.review(
        "BASE", "HEAD",
        repo=Path("/nonexistent"), plugin_root=_plugin_root(),
        role="core-agent",
        version_by_gatekeeper=True,
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"],
        override_cur="1.1.6", override_prev="1.1.6")
    assert v.cadence == "TARGETED"
    vb = next(g for g in v.gates if g.name == "version_bump_monotonic_check")
    assert vb.rc == -1 and "deferred" in vb.summary


def test_review_versionless_authoring_pr_version_gate_not_blocking():
    # The version gate must not appear in `blocking` for a version-less PR.
    v = GR.review(
        "BASE", "HEAD",
        repo=Path("/nonexistent"), plugin_root=_plugin_root(),
        role="core-agent",
        version_by_gatekeeper=True,
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"],
        override_cur="1.1.6", override_prev="1.1.6")
    assert not any("version_bump_monotonic_check" in b for b in v.blocking)


def test_review_without_flag_versionless_pr_blocks_on_version():
    # Same version-less PR, flag OFF -> version gate FAILs and blocks.
    v = GR.review(
        "BASE", "HEAD",
        repo=Path("/nonexistent"), plugin_root=_plugin_root(),
        role="core-agent",
        version_by_gatekeeper=False,
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"],
        override_cur="1.1.6", override_prev="1.1.6")
    assert any("version_bump_monotonic_check" in b for b in v.blocking)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── data-only change-sets: the version gate is N/A, not FAIL ─────────────────
# A benchmark-data-only PR (e.g. #278) could never pass gatekeeper_review: the
# version gate demanded a bump even though the change ships nothing via
# `/plugin update`, and main's own convention lands these as unversioned
# `docs(benchmark-data): …` commits. That pressured the maintainer into either
# bypassing the gate or inflating the version for a change no user receives.

def test_ships_to_users_classification():
    assert GR.ships_to_users(["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"])
    assert GR.ships_to_users(["mcp/server.py"])
    assert GR.ships_to_users([".claude-plugin/marketplace.json"])
    assert GR.ships_to_users(["vibe-ic-marketplace/.claude-plugin/marketplace.json"])
    assert not GR.ships_to_users(["benchmark-data/ic/spm/v1/waivers.json"])
    assert not GR.ships_to_users(["docs/INSTALL.md", "tools/ci/some_gate.sh"])


def test_data_only_changeset_skips_version_gate():
    r = GR.version_bump_gate("1.5.75", "1.5.75", "1.5.75", False,
                              ["benchmark-data/ic/spm/v1/waivers.json"])
    assert r.rc == -1, f"data-only change-set should SKIP, got rc={r.rc}"
    assert "ships nothing" in r.summary


def test_shipping_changeset_still_enforced_without_bump():
    """The exemption must NOT weaken the gate for anything users receive."""
    r = GR.version_bump_gate("1.5.75", "1.5.75", "1.5.75", False,
                              ["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"])
    assert r.rc == 1, "a shipping change with no bump must still FAIL"


def test_files_omitted_preserves_legacy_behaviour():
    """Callers that pass no file list keep the original strict semantics."""
    r = GR.version_bump_gate("1.5.75", "1.5.75", "1.5.75", False)
    assert r.rc == 1


# ── publication base: author validation and landing integration are distinct ─
def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    run = subprocess.run(["git", "-C", str(repo), *args], text=True,
                         capture_output=True, env=env, check=True)
    return run.stdout.strip()


@pytest.fixture()
def publication_history(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "gate@example.invalid")
    _git(repo, "config", "user.name", "Gate Test")
    (repo / "shared.txt").write_text("base\n")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-qm", "base", date="2026-01-01T00:00:00+00:00")
    base = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-qb", "author")
    (repo / "author.txt").write_text("fix\n")
    _git(repo, "add", "author.txt")
    _git(repo, "commit", "-qm", "fix", date="2026-01-02T00:00:00+00:00")
    head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-q", "main")
    (repo / "later.txt").write_text("later main\n")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-qm", "later", date="2026-01-04T00:00:00+00:00")
    later_main = _git(repo, "rev-parse", "HEAD")
    return repo, base, head, later_main


def _pr(body: str, head: str) -> dict:
    return {
        "body": body,
        "headRefOid": head,
        "baseRefName": "main",
        "createdAt": "2026-01-03T00:00:00Z",
    }


def test_main_advancing_after_publication_is_a_pass(publication_history):
    repo, base, head, later_main = publication_history
    body = GR.render_pr_publication_contract(base, head)
    result = GR.audit_pr_publication_contract(repo, _pr(body, head), "main")
    assert result["verdict"] == "PASS", result
    assert result["main_advanced"] is True
    assert result["current_main"] == later_main


def test_missing_publication_contract_blocks(publication_history):
    repo, _base, head, _later_main = publication_history
    result = GR.audit_pr_publication_contract(
        repo, _pr("ordinary PR body", head), "main")
    assert result["verdict"] == "FAIL"
    assert any("exactly one" in error for error in result["errors"])


def test_body_head_must_equal_the_github_pr_head(publication_history):
    repo, base, head, later_main = publication_history
    result = GR.audit_pr_publication_contract(
        repo, _pr(GR.render_pr_publication_contract(base, head), later_main),
        "main")
    assert result["verdict"] == "FAIL"
    assert any("headRefOid" in error for error in result["errors"])


def test_author_rebase_onto_later_main_is_blocked(publication_history):
    repo, base, _head, _later_main = publication_history
    _git(repo, "checkout", "-qb", "author_rebased", "main")
    (repo / "author.txt").write_text("same fix, replayed\n")
    _git(repo, "add", "author.txt")
    _git(repo, "commit", "-qm", "fix replayed",
         date="2026-01-05T00:00:00+00:00")
    rebased_head = _git(repo, "rev-parse", "HEAD")
    body = GR.render_pr_publication_contract(base, rebased_head)
    result = GR.audit_pr_publication_contract(
        repo, _pr(body, rebased_head), "main")
    assert result["verdict"] == "FAIL"
    assert any("absorbed a main commit" in error for error in result["errors"])


def test_author_can_fix_a_real_pr_defect_without_rebasing_main(
        publication_history):
    repo, base, _head, _later_main = publication_history
    _git(repo, "checkout", "-q", "author")
    (repo / "author.txt").write_text("fix corrected after review\n")
    _git(repo, "add", "author.txt")
    _git(repo, "commit", "-qm", "correct PR defect",
         date="2026-01-05T00:00:00+00:00")
    corrected_head = _git(repo, "rev-parse", "HEAD")
    body = GR.render_pr_publication_contract(base, corrected_head)
    result = GR.audit_pr_publication_contract(
        repo, _pr(body, corrected_head), "main")
    assert result["verdict"] == "PASS", result
    assert result["main_advanced"] is True


def test_author_cannot_relabel_later_main_as_publication_base(
        publication_history):
    repo, _base, _head, later_main = publication_history
    _git(repo, "checkout", "-qb", "author_after", "main")
    (repo / "after.txt").write_text("fix after\n")
    _git(repo, "add", "after.txt")
    _git(repo, "commit", "-qm", "fix after",
         date="2026-01-05T00:00:00+00:00")
    new_head = _git(repo, "rev-parse", "HEAD")
    body = GR.render_pr_publication_contract(later_main, new_head)
    result = GR.audit_pr_publication_contract(
        repo, _pr(body, new_head), "main")
    assert result["verdict"] == "FAIL"
    assert any("after PR publication" in error for error in result["errors"])


def test_duplicate_contract_cannot_hide_a_second_answer(publication_history):
    repo, base, head, _later_main = publication_history
    block = GR.render_pr_publication_contract(base, head)
    result = GR.audit_pr_publication_contract(
        repo, _pr(block + "\n" + block, head), "main")
    assert result["verdict"] == "FAIL"
    assert any("exactly one" in error for error in result["errors"])


def test_external_review_requires_the_plugin_contract():
    gate = GR.publication_base_gate(Path("/nonexistent"), "origin/main", None)
    assert gate.rc == 1
    assert "requires --pr-json" in gate.summary


def test_external_review_accepts_frozen_pair_after_main_advances(
        publication_history):
    repo, base, head, _later_main = publication_history
    metadata = _pr(GR.render_pr_publication_contract(base, head), head)
    gate = GR.publication_base_gate(repo, "main", metadata)
    assert gate.rc == 0, gate.summary
    assert "main advanced" in gate.summary


def test_stale_branch_is_gatekeeper_work_only_for_external_prs():
    stale = GR.GateResult("gatekeeper_stale_branch_check", 1, "STALE_OVERLAP")
    authoring = GR.authoring_stale_branch_policy(stale, True)
    landing = GR.authoring_stale_branch_policy(stale, False)
    assert authoring.rc == 0
    assert "Repo Gatekeeper" in authoring.summary
    assert landing is stale and landing.rc == 1


def test_publication_rule_is_in_plugin_agents_and_not_any_skill():
    plugin = PROGRAMS.parent
    benchmark_agent = (plugin / "agents" / "benchmark-agent.md").read_text()
    repo_gatekeeper = (plugin / "agents" / "repo-gatekeeper.md").read_text()
    for text in (benchmark_agent, repo_gatekeeper):
        assert "gatekeeper_review.py" in text
        assert "--check-pr-contract" in text
        assert GR.PR_PUBLICATION_POLICY in text
    skill_mentions = [
        path for path in (plugin / "skills").glob("*/SKILL.md")
        if "--check-pr-contract" in path.read_text(errors="replace")
        or GR.PR_PUBLICATION_POLICY in path.read_text(errors="replace")
    ]
    assert skill_mentions == []


def test_render_contract_cli_emits_full_pinned_shas(publication_history,
                                                    capsys):
    repo, base, head, _later_main = publication_history
    rc = GR.main(["--base", base, "--head", head, "--repo", str(repo),
                  "--render-pr-contract"])
    output = capsys.readouterr().out
    assert rc == 0
    assert GR.PR_BASE_OPEN in output
    assert base in output and head in output


def test_check_contract_cli_passes_when_main_only_advanced(
        publication_history, tmp_path, capsys):
    repo, base, head, _later_main = publication_history
    metadata = tmp_path / "pr.json"
    metadata.write_text(json.dumps(
        _pr(GR.render_pr_publication_contract(base, head), head)))
    rc = GR.main(["--base", "main", "--head", "author", "--repo", str(repo),
                  "--check-pr-contract", "--pr-json", str(metadata)])
    output = capsys.readouterr().out
    assert rc == 0
    assert "main advanced after publication" in output
