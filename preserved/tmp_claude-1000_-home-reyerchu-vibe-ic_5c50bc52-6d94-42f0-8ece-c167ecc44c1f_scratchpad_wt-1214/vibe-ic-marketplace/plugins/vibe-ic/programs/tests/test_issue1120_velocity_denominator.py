"""vibe-ic#1120 — landed-and-gated is the only legal denominator.

THE PROOF THIS EXISTS FOR (2026-08-12): authoring scaled to 23 agents, ~25 PRs
opened in hours, open count 31 -> 46, two versions landed. Growth ~10/hour
against drain ~4/hour. **A published "PRs per hour" would have looked excellent
while the system went backwards.**

WHAT THESE PIN
==============
The generator CANNOT publish the number that would have lied — there is no way
to reach un-landed work from it, and `test_the_generator_cannot_count_unlanded_
work` asserts the absence rather than trusting it.

Proxies never travel alone: every proxy figure carries its denominator in the
same sentence, the way the census prints "guards 131 of 344 = 38%".

Silicon Proof is a hard zero WITH its reason, not derived and not raisable by
activity. A dimension that reads zero is what makes the other three believable.

The page is a pure function of the gated branch, so hand-editing it is
detectable — that is the whole point of generating it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

import velocity_report_gen as V  # noqa: E402

GATE = _PROGRAMS / "velocity_report_gen.py"
_REPO = _PROGRAMS.parents[3]


def _run(*a):
    p = subprocess.run([sys.executable, str(GATE), *map(str, a)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


@pytest.fixture
def repo(tmp_path):
    """A tiny gated branch: two landed fixes, one version commit."""
    r = tmp_path / "r"
    r.mkdir()
    def git(*a):
        subprocess.run(["git", "-C", str(r), *a], capture_output=True, check=False)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    for msg in ("gate: first thing (#101)", "gate: second thing (#102)",
                "[v9.9.9] a batch"):
        (r / "f.txt").write_text(msg)
        git("add", "-A"); git("commit", "-q", "-m", msg)
    return r


# ── the denominator ─────────────────────────────────────────────────────────

def test_the_denominator_is_landed_work(repo):
    d = V.derive(repo, "main")
    assert d["denominator"]["landed_commits"] == 3, d
    assert d["engineering_velocity"]["landed_fixes"] == 2, d
    assert d["engineering_velocity"]["landed_versions"] == 1, d


def test_the_generator_cannot_count_unlanded_work():
    """The number that would have lied must be UNCOMPUTABLE, not merely unused.

    If someone adds a PR/issue counter later, this test should be deleted in the
    same commit — deliberately — rather than quietly passing.
    """
    src = Path(V.__file__).read_text(encoding="utf-8")
    for banned in ("opened_pr", "count_opened", "gh pr list", "gh issue list"):
        assert banned not in src, (
            f"{banned!r} appeared in the generator; un-landed work is now "
            f"reachable and the #1120 rule is defeated")


def test_only_the_gated_ref_is_read(repo):
    """A ref that does not exist yields nothing rather than falling back."""
    d = V.derive(repo, "no-such-ref")
    assert d["denominator"]["landed_commits"] == 0, d


# ── proxies never travel alone ──────────────────────────────────────────────

@pytest.mark.parametrize("dim", ["engineering_velocity", "autonomous_improvement"])
def test_every_proxy_declares_it_needs_its_denominator(repo, dim):
    d = V.derive(repo, "main")
    assert d[dim]["kind"] == "proxy", d[dim]
    assert d[dim]["requires_denominator_in_the_same_sentence"] is True, d[dim]


def test_the_rendered_proxy_sentence_carries_its_denominator(repo):
    d = V.derive(repo, "main")
    page = V.render(d)
    vel = [l for l in page.splitlines() if "landed fixes**" in l]
    assert vel, page
    assert " of " in vel[0] and "landed commits" in vel[0], (
        f"the velocity figure is published without its denominator in the same "
        f"sentence:\n  {vel[0]}")


# ── silicon proof is zero, and says why ─────────────────────────────────────

def test_silicon_proof_is_zero_with_a_reason(repo):
    d = V.derive(repo, "main")
    sp = d["silicon_proof"]
    assert sp["value"] == 0, sp
    assert "fabricated" in sp["reason"], sp
    assert "Silicon Proof — **0**" in V.render(d)


def test_silicon_proof_is_not_derived_from_activity(repo):
    """Adding landed work must not move it. It is raisable only by silicon."""
    before = V.derive(repo, "main")["silicon_proof"]["value"]
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty",
                    "-m", "gate: more landed work (#103)"], capture_output=True)
    after = V.derive(repo, "main")["silicon_proof"]["value"]
    assert before == after == 0, (before, after)


# ── the page cannot be talked upward ────────────────────────────────────────

def test_a_hand_edited_page_is_refused(repo):
    rc, _ = _run("--repo", repo, "--ref", "main", "--write")
    assert rc == V.RC_PASS
    rc, out = _run("--repo", repo, "--ref", "main", "--check")
    assert rc == V.RC_PASS, out
    p = repo / V.PAGE_REL
    p.write_text(p.read_text().replace("**2 landed fixes**", "**999 landed fixes**"))
    rc, out = _run("--repo", repo, "--ref", "main", "--check")
    assert rc == V.RC_FAIL, out
    assert "disagrees with the derivation" in out, out


def test_a_page_without_its_generated_banner_is_refused(repo):
    _run("--repo", repo, "--ref", "main", "--write")
    p = repo / V.PAGE_REL
    p.write_text(p.read_text().replace(V.BANNER, ""))
    rc, out = _run("--repo", repo, "--ref", "main", "--check")
    assert rc == V.RC_FAIL, out
    assert "lost its generated banner" in out, out


def test_no_landed_work_is_vacuous_not_zero_velocity(tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    subprocess.run(["git", "-C", str(r), "init", "-q"], capture_output=True)
    rc, out = _run("--repo", r, "--ref", "main", "--check")
    assert rc == V.RC_VACUOUS, out
    assert "NOT a report of zero velocity" in out, out


# ── paired guard ────────────────────────────────────────────────────────────

def test_a_check_that_always_passes_is_killed(repo):
    """A --check that cannot fail turns the page back into a hand-maintained
    status table, which is exactly what #1120 forbids."""
    _run("--repo", repo, "--ref", "main", "--write")
    p = repo / V.PAGE_REL
    p.write_text(p.read_text().replace("**2 landed fixes**", "**999 landed fixes**"))
    real, _ = _run("--repo", repo, "--ref", "main", "--check")
    assert real == V.RC_FAIL, "the tampered page passed; the check is scenery"
