#!/usr/bin/env python3
"""The published/unpublished split in landing_is_one_commit_check.

WHY THIS FILE EXISTS
====================
`find_unsquashed` scans the last `--limit` commits of HISTORY. History is
immutable, so before this split a single past violation made the check red on
every future run until that commit scrolled out of the window. Measured on
`origin/main` at `c5c46cda1`: rc=1, two findings, both already published. The
identical rc with and without a candidate commit — the check had stopped being
about the landing under test.

`gatekeeper-land.sh` runs this program, and a red gate means no stamp, and no
stamp means `pre-push` refuses. So one immutable commit banned every direct push
to main, and the only way to land became bypassing the gate. That is the exact
progression `landing_merge_verdict.py` warns about in its own docstring, and the
reason it warns is that this repo already arrived once at a landing path with no
gate at all.

THE RULE, AND WHY IT IS NOT A WEAKENING
=======================================
    still local  -> REFUSE. `git reset --soft <base>` still works, and this is the
                    only moment #459 is preventable.
    published    -> REPORT. Squashing it now would rewrite a branch other people
                    have. Refusing does not prevent anything; it only bans.

The detector is untouched — the same pairs are found. Only the response to a
finding nobody can act on has changed, and it is still printed with both shas.

EVERY CASE HERE IS PAIRED. A file that only proved "it stops refusing" would pass
against a program that had simply been switched off.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "landing_is_one_commit_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("_lioc", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


def _git(repo: Path, *args: str) -> str:
    out = _pr.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    assert out.returncode == 0, f"git {' '.join(args)} -> {out.returncode}: {out.stderr}"
    return out.stdout


def _commit(repo: Path, name: str, body: str, subject: str) -> str:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", subject)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture()
def repo_with_one_unsquashed_landing(tmp_path: Path) -> Path:
    """A repo whose tip is the #459 shape: manifests-only on top of unversioned.

    Built with the SAME file names the detector keys on, so the fixture exercises
    the real predicate rather than a stand-in for it.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "seed.txt", "seed\n", "chore: seed [v1.0.0]")

    # the authoring commit — real content, NO version tag
    _commit(repo, "feature.py", "print('x')\n", "feat: a real change")

    # the version commit — manifests ONLY. This pair is the defect.
    mp = repo / "vibe-ic-marketplace" / ".claude-plugin"
    pl = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / ".claude-plugin"
    for d in (mp, pl):
        d.mkdir(parents=True, exist_ok=True)
    (mp / "marketplace.json").write_text('{"plugins":[{"name":"vibe-ic","version":"1.0.1"}]}\n')
    (pl / "plugin.json").write_text('{"version":"1.0.1"}\n')
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "chore(version): 1.0.1 [v1.0.1]")
    return repo


def _run(repo: Path, *extra: str):
    out = _pr.run(
        [sys.executable, str(PROG), str(repo), *extra],
        capture_output=True, text=True)
    return out.returncode, out.stderr


# ---------------------------------------------------------------------------
# 1. the detector still finds the shape — nothing below means anything without it
# ---------------------------------------------------------------------------
def test_the_detector_still_finds_the_unsquashed_pair(repo_with_one_unsquashed_landing):
    findings, examined = L.find_unsquashed(repo_with_one_unsquashed_landing, 200)
    assert examined > 0, "read no commits; the fixture or the reader is broken"
    assert len(findings) == 1, findings
    assert findings[0]["version_sha"], "the full sha must travel with the finding"


# ---------------------------------------------------------------------------
# 2. UNPUBLISHED -> REFUSE. The half that keeps the check a check.
# ---------------------------------------------------------------------------
def test_an_unpublished_unsquashed_landing_still_refuses(repo_with_one_unsquashed_landing):
    rc, err = _run(repo_with_one_unsquashed_landing)
    assert rc == 1, f"rc={rc}\n{err}"
    assert "UNSQUASHED_LANDING" in err, err
    assert "NOT YET PUBLISHED" in err, err
    assert "reset --soft" in err, "the refusal must name the fix"


# ---------------------------------------------------------------------------
# 3. PUBLISHED -> REPORT. The half this change is for.
# ---------------------------------------------------------------------------
def test_a_published_unsquashed_landing_is_reported_not_refused(
        repo_with_one_unsquashed_landing):
    repo = repo_with_one_unsquashed_landing
    # make the offending commit reachable from the published ref
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    rc, err = _run(repo)
    assert rc == 0, f"a finding nobody can act on must not hold the gate shut\n{err}"
    assert "ALREADY_PUBLISHED" in err, err
    assert "REPORTED above" in err, err
    # and it is still NAMED — reporting is not swallowing
    assert "on " in err and "recorded, not refused" in err, err


# ---------------------------------------------------------------------------
# 4. a MIXTURE refuses, and says how many of each. The published half must not
#    launder the unpublished one.
# ---------------------------------------------------------------------------
def test_a_published_finding_does_not_excuse_an_unpublished_one(
        repo_with_one_unsquashed_landing):
    repo = repo_with_one_unsquashed_landing
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    # a SECOND unsquashed landing, on top, not published
    _commit(repo, "feature2.py", "print('y')\n", "feat: another real change")
    pl = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / ".claude-plugin"
    (pl / "plugin.json").write_text('{"version":"1.0.2"}\n')
    (repo / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json").write_text(
        '{"plugins":[{"name":"vibe-ic","version":"1.0.2"}]}\n')
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "chore(version): 1.0.2 [v1.0.2]")

    rc, err = _run(repo)
    assert rc == 1, f"an unpublished finding must still refuse\n{err}"
    assert "1 unpublished landing" in err, err
    assert "already on" in err, "the published ones must still be accounted for"


# ---------------------------------------------------------------------------
# 5. AN UNRESOLVABLE REF DEGRADES TOWARD STRICTER, never toward a free pass.
#    Reading "I could not find the ref" as "it must all be published" would turn
#    one missing ref into a blanket exemption.
# ---------------------------------------------------------------------------
def test_an_unresolvable_published_ref_refuses_rather_than_exempts(
        repo_with_one_unsquashed_landing):
    repo = repo_with_one_unsquashed_landing
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    rc, err = _run(repo, "--published-ref", "refs/remotes/nope/nothing")
    assert rc == 1, f"an unknown reach must not become an exemption\n{err}"
    assert "REACH_UNKNOWN" in err, err
    assert "judged as still local" in err, err


# ---------------------------------------------------------------------------
# 6. a CLEAN repo passes with the plain message — the split must not invent
#    findings where there are none.
# ---------------------------------------------------------------------------
def test_a_clean_history_still_passes_plainly(tmp_path: Path):
    repo = tmp_path / "clean"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "a.txt", "a\n", "chore: seed [v1.0.0]")
    _commit(repo, "b.txt", "b\n", "feat: one squashed landing [v1.0.1]")
    rc, err = _run(repo)
    assert rc == 0, err
    assert "every landing is a single squashed commit" in err, err
    assert "ALREADY_PUBLISHED" not in err, "invented a finding on a clean history"


# ---------------------------------------------------------------------------
# 7. the RECORD carries the split, not just a total. A reader given one number
#    cannot tell a landing that must be fixed from one that cannot be.
# ---------------------------------------------------------------------------
def test_the_json_record_separates_the_two_populations(
        repo_with_one_unsquashed_landing, tmp_path: Path):
    repo = repo_with_one_unsquashed_landing
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    out = tmp_path / "rec.json"
    _run(repo, "--json", str(out))
    rec = json.loads(out.read_text())
    assert rec["mode"] == "history"
    assert len(rec["published_findings"]) == 1, rec
    assert rec["unpublished_findings"] == [], rec
    assert rec["reach_unknown"] is None, rec
    assert rec["published_ref"], "the record must name the ref it judged against"


# ---------------------------------------------------------------------------
# 8. THE PRE-PUSH MODE IS UNTOUCHED. --base still judges the batch absolutely,
#    with no published/unpublished softening, because a batch under test is by
#    definition not yet published.
# ---------------------------------------------------------------------------
def test_the_base_mode_is_not_softened(repo_with_one_unsquashed_landing):
    repo = repo_with_one_unsquashed_landing
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    base = _git(repo, "rev-parse", "HEAD~2").strip()
    rc, err = _run(repo, "--base", base)
    assert rc == 1, f"two commits over the base must refuse even when published\n{err}"
    assert "ALREADY_PUBLISHED" not in err, "the split leaked into pre-push mode"
