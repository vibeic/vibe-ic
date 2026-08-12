"""vibe-ic#1120 — the four published dimensions, and the refusals that keep
them honest.

WHY EVERY TEST BUILDS ITS OWN REPOSITORY
========================================
The figures are history-derived, and the authoring host's clone is SHALLOW (89
commits against the remote's 2007). A test that asserted against the real
repository would either encode the graft boundary as an expected number, or
skip — and a skipped test over the one property this page exists to guarantee
is the shape vibe-ic#1053 was filed about. Synthesised repositories have known,
complete history, so these cannot skip and cannot drift with `main`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_ROOT / "tools"))

import gen_engineering_evidence as ge  # noqa: E402


# --------------------------------------------------------------------------
def _run(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args],
                   check=True, capture_output=True, text=True)


def _commit(root: Path, subject: str, n: int) -> None:
    (root / f"f{n}.txt").write_text(str(n))
    _run(root, "add", "-A")
    _run(root, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", subject)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A complete-history repository with a KNOWN commit population."""
    r = tmp_path / "repo"
    (r / "docs").mkdir(parents=True)
    progs = r / ge.PROGRAMS_REL
    (progs / "tests").mkdir(parents=True)
    # 3 programs, 2 of them gate-shaped, 1 carrying a test named after it.
    (progs / "alpha_check.py").write_text("#\n")
    (progs / "beta_audit.py").write_text("#\n")
    (progs / "gamma_tool.py").write_text("#\n")
    (progs / "_helper.py").write_text("#\n")          # excluded: leading _
    (progs / "tests" / "test_alpha_check.py").write_text("#\n")
    (r / "benchmark-data" / "ic" / "cellA" / "input").mkdir(parents=True)
    (r / "benchmark-data" / "ic" / "cellA" / "input" / "spec.md").write_text("s")
    (r / "benchmark-data" / "ic" / "cellB" / "input").mkdir(parents=True)
    (r / "benchmark-data" / "ic" / "cellB" / "input" / "spec.md").write_text("s")

    _run(r, "init", "-q", "-b", "main")
    _commit(r, "chore: scaffold", 0)
    # 3 landed squash commits; 2 of them also cite a tracked item.
    _commit(r, "fix: a thing (#101)", 1)
    _commit(r, "fix: another thing (#77) (#102)", 2)
    _commit(r, "gate: a third (#88) (#103)", 3)
    _commit(r, "[v9.9.9] a version", 4)
    return r


def _gen(root: Path, *extra: str) -> int:
    return ge.main(["--root", str(root), *extra])


# --- the derivation ------------------------------------------------------
def test_landed_is_the_denominator_not_the_commit_count(repo: Path) -> None:
    """5 commits: a scaffold, three `(#N)` squashes and a version bump. Only
    the squashes are landed changes, and that gap IS the subject of #1120."""
    subs = ge.landed_subjects(repo, "HEAD")
    v = ge.velocity(subs)
    assert v["commits"] == 5, subs
    assert v["landed_changes"] == 3, subs
    assert v["versions"] == 1, subs
    # The proxy and the property must not be the same number, or this fixture
    # could not tell a tool that counts commits from one that counts landings.
    assert v["landed_changes"] != v["commits"], subs
    assert ge.autonomous(subs)["citing_a_tracked_item"] == 2, subs


def test_the_page_states_the_denominator_in_the_same_sentence(repo: Path) -> None:
    assert _gen(repo) == ge.RC_OK
    body = (repo / ge.PAGE_REL).read_text()
    # The figure and what it is out of, never a bare count.
    assert "**3 of 5 commits**" in body, body
    assert "landed on `main`" in body, body


def test_proxies_are_named_and_refused(repo: Path) -> None:
    """A page that silently omitted them would look identical to one that
    forgot. #1120 requires the refusal to be visible."""
    assert _gen(repo) == ge.RC_OK
    body = (repo / ge.PAGE_REL).read_text()
    for proxy in ("PRs opened", "commits authored", "median time-to-fix",
                  "fixes per month"):
        assert proxy in body, proxy


def test_adversarial_counts_gates_and_named_tests(repo: Path) -> None:
    a = ge.adversarial(repo)
    assert a["programs"] == 3, a          # `_helper.py` excluded
    assert a["gates"] == 2, a             # _check + _audit
    assert a["programs_with_named_test"] == 1, a


# --- Silicon Proof: the zero must be MEASURED ----------------------------
def test_silicon_proof_is_zero_and_says_so(repo: Path) -> None:
    assert _gen(repo) == ge.RC_OK
    body = (repo / ge.PAGE_REL).read_text()
    assert "**0 of 2 published cells**" in body, body
    assert "No Vibe-IC design has been fabricated" in body, body


def test_the_silicon_zero_is_measured_not_hardcoded(repo: Path) -> None:
    """THE CONTROL FOR THE ZERO. A hardcoded 0 and a measured 0 render
    identically; only planting evidence tells them apart."""
    before = ge.silicon_proof(repo, "HEAD")
    assert before["fabricated"] == 0, before
    fab = repo / "benchmark-data" / "ic" / "cellA" / "tapeout_receipt.json"
    fab.write_text("{}")
    _run(repo, "add", "-A")
    _run(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "plant fabrication evidence")
    after = ge.silicon_proof(repo, "HEAD")
    assert after["fabricated"] == 1, after
    assert _gen(repo) == ge.RC_OK
    body = (repo / ge.PAGE_REL).read_text()
    assert "**1 of 2 published cells**" in body, body
    assert "No Vibe-IC design has been fabricated" not in body, body


# --- the freshness gate: a hand-edited figure must not survive -----------
def test_a_freshly_generated_page_passes(repo: Path) -> None:
    """THE POSITIVE ARM. Without it, a check that refuses everything would
    satisfy every other test in this file."""
    assert _gen(repo) == ge.RC_OK
    assert _gen(repo, "--check") == ge.RC_OK


def test_a_hand_edited_figure_is_caught(repo: Path) -> None:
    assert _gen(repo) == ge.RC_OK
    page = repo / ge.PAGE_REL
    page.write_text(page.read_text().replace("**3 of 5 commits**",
                                             "**3000 of 5 commits**"))
    assert _gen(repo, "--check") == ge.RC_STALE


def test_a_page_with_no_anchor_refuses_rather_than_passing(repo: Path) -> None:
    assert _gen(repo) == ge.RC_OK
    page = repo / ge.PAGE_REL
    page.write_text("\n".join(ln for ln in page.read_text().splitlines()
                              if not ln.startswith("ANCHOR:")) + "\n")
    assert _gen(repo, "--check") == ge.RC_REFUSED


def test_an_anchor_this_repo_cannot_see_refuses(repo: Path) -> None:
    assert _gen(repo) == ge.RC_OK
    page = repo / ge.PAGE_REL
    page.write_text(page.read_text().replace(
        "ANCHOR: ", "ANCHOR: ", 1).replace(
        ge.page_anchor(page.read_text()), "0" * 40))
    assert _gen(repo, "--check") == ge.RC_REFUSED


def test_an_absent_page_is_a_refusal_never_a_pass(repo: Path) -> None:
    assert _gen(repo, "--check") == ge.RC_REFUSED


# --- the shallow guard: the defect this tool hit on its own first run ----
def test_a_shallow_clone_REFUSES_and_never_reports_a_smaller_number(
        repo: Path, tmp_path: Path) -> None:
    """The measured instance: on a shallow clone the page read `86 of 89`
    while the remote carried 2007. A smaller plausible number is the failure
    mode; a refusal is the fix."""
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1",
                    f"file://{repo}", str(shallow)],
                   check=True, capture_output=True, text=True)
    assert ge.is_shallow(shallow) is True
    assert ge.is_shallow(repo) is False
    assert _gen(shallow) == ge.RC_REFUSED
    assert _gen(shallow, "--check") == ge.RC_REFUSED


def test_the_freshness_gate_is_WIRED_into_the_hygiene_sweep() -> None:
    """A generator nothing invokes produces no verdict.

    This repo has a gate for that class (`gate_is_wired_check`) which
    classifies by filename suffix — `*_check`/`*_lint`/`*_audit`/`*_guard` — so
    a `gen_*.py` under `tools/` is invisible to it. The wiring is therefore
    asserted HERE, by name, or nothing would notice it being removed. It is
    also the red arm for this change: `git checkout origin/main --
    tools/ci/repo_hygiene_gates.sh` fails this test and nothing else.
    """
    sweep = (_ROOT / "tools" / "ci" / "repo_hygiene_gates.sh").read_text()
    assert "gen_engineering_evidence.py" in sweep, \
        "the freshness check is not invoked by the hygiene sweep"
    assert "--check" in sweep, sweep[:200]
    # `run_tolerating_uncheckable`, not `run`: rc 2 means "this clone is
    # shallow and cannot answer", which must be loud and non-fatal. Pinned so
    # a future edit to plain `run` is a visible decision, not a silent one.
    line = next(ln for ln in sweep.splitlines()
                if "gen_engineering_evidence.py" in ln or
                ("engineering evidence fresh" in ln))
    block = sweep[sweep.index("engineering evidence fresh") - 200:
                  sweep.index("gen_engineering_evidence.py") + 60]
    assert "run_tolerating_uncheckable" in block, line


def test_the_shallow_guard_does_not_fire_on_a_complete_clone(
        repo: Path, tmp_path: Path) -> None:
    """Paired with the above: a guard that refused every clone would pass the
    test above and be useless."""
    full = tmp_path / "full"
    subprocess.run(["git", "clone", "-q", f"file://{repo}", str(full)],
                   check=True, capture_output=True, text=True)
    assert ge.is_shallow(full) is False
    assert _gen(full) == ge.RC_OK
