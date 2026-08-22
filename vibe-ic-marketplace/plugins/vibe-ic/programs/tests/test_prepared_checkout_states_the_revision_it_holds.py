"""A prepared checkout names the commit it holds, or it has established nothing.

WHY
===
MEASURED: automation cloned a branch NAME from a local path whose branch position
was stale. The commit under test was absent from the resulting tree and the gate
run produced a complete, internally consistent verdict about the wrong revision.

THE TWO STATES THAT MUST NEVER SHARE A VERDICT
==============================================
    rc 1  REFUTED     — the tree holds a DIFFERENT commit. We looked; it is wrong.
    rc 2  NOT CHECKED — we could not establish which commit it holds.

Merging these is what let a confident verdict be published about an unidentified
tree, so each is asserted separately below, against a REAL git repository rather
than a mock — a mock of git cannot demonstrate the thing being claimed.

BIDIRECTIONAL: every red case is paired with the green form of the same tree.

chip-AGNOSTIC: git plumbing only. No design, PDK or vendor literal.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "prepared_checkout_states_the_revision_it_holds.py"

_spec = importlib.util.spec_from_file_location("pcstrih", _TOOL)
pcstrih = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pcstrih)

_ENVKEYS = {"GIT_CONFIG_GLOBAL": "gc", "GIT_CONFIG_SYSTEM": "gs"}


def _env(tmp_path):
    e = {k: str(tmp_path / v) for k, v in _ENVKEYS.items()}
    e.update({"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    return e


def _git(repo, *a, tmp_path):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True,
                          text=True, env=_env(tmp_path))


def _repo(tmp_path, name="src"):
    """A real two-commit repository."""
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q", "-b", "main", tmp_path=tmp_path)
    shas = []
    for i in (1, 2):
        (r / "f.txt").write_text(f"{i}\n")
        _git(r, "add", "f.txt", tmp_path=tmp_path)
        _git(r, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm",
             f"c{i}", tmp_path=tmp_path)
        shas.append(_git(r, "rev-parse", "HEAD", tmp_path=tmp_path).stdout.strip())
    return r, shas


def _run(*args):
    cp = subprocess.run([sys.executable, str(_TOOL), *[str(a) for a in args]],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------------- runtime arm

def test_correct_revision_is_confirmed(tmp_path):
    repo, shas = _repo(tmp_path)
    rc, out = _run("--root", repo, "--expect", shas[1])
    assert rc == 0, out
    assert "CONFIRMED" in out


def test_wrong_revision_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: reintroduce the measured defect — a tree prepared
    for one commit that actually holds another."""
    repo, shas = _repo(tmp_path)
    _git(repo, "checkout", "-q", "--detach", shas[0], tmp_path=tmp_path)
    rc, out = _run("--root", repo, "--expect", shas[1])
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "REFUTED" in out
    assert shas[0][:12] in out and shas[1][:12] in out


def test_absent_revision_without_upstream_is_not_checked(tmp_path):
    """The commit is not in the tree and nothing can say what it should be.
    That is UNDETERMINED, and it must NOT be the same code as 'wrong'."""
    repo, _ = _repo(tmp_path)
    rc, out = _run("--root", repo, "--expect", "0" * 40)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def _stale_pair(tmp_path):
    """THE MEASURED SCENARIO, built exactly.

    Clone `up` while its `main` is A; advance upstream `main` to B (the commit
    under test); leave the clone's HEAD at A. The clone does NOT contain B, and
    the clone's OWN `main` ref still resolves — to A. That resolvable stale ref
    is the whole trap.
    """
    up, shas_a = _repo(tmp_path, "up")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(up), str(clone)],
                   capture_output=True, env=_env(tmp_path))
    before = _git(clone, "rev-parse", "HEAD", tmp_path=tmp_path).stdout.strip()
    (up / "f.txt").write_text("under-test\n")
    _git(up, "add", "f.txt", tmp_path=tmp_path)
    _git(up, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm",
         "the commit under test", tmp_path=tmp_path)
    after = _git(up, "rev-parse", "HEAD", tmp_path=tmp_path).stdout.strip()
    assert before != after
    assert _git(clone, "cat-file", "-e", after,
                tmp_path=tmp_path).returncode != 0, (
        "fixture is wrong: the clone already contains the commit under test")
    assert _git(clone, "rev-parse", "main",
                tmp_path=tmp_path).stdout.strip() == before, (
        "fixture is wrong: the clone's own `main` is not stale")
    return up, clone, before, after


def test_a_stale_branch_name_is_refuted_not_confirmed(tmp_path):
    """THE REGRESSION THAT MATTERS.

    This program shipped ANSWERING CONFIRMED here. It resolved the ref name
    inside the checkout, where a stale `main` resolves perfectly well, so
    want == head and the upstream fallback could never fire — a false pass on
    precisely the case the program exists for. The test that was here asserted
    `rc in (0, 1, 2)`, which excludes only 3, and so pinned nothing.
    """
    up, clone, before, after = _stale_pair(tmp_path)
    rc, out = _run("--root", clone, "--expect", "main", "--upstream", up)
    assert rc == 1, f"a stale branch name was not refuted:\n{out}"
    assert "REFUTED" in out
    assert before[:12] in out and after[:12] in out
    assert "does not even contain" in out


def test_a_ref_name_without_an_upstream_cannot_be_confirmed(tmp_path):
    """A name resolved only against the tree being checked proves nothing, and
    that is NOT CHECKED rather than a pass."""
    _up, clone, _b, _a = _stale_pair(tmp_path)
    rc, out = _run("--root", clone, "--expect", "main")
    assert rc == 2, f"a name with no upstream was not undetermined:\n{out}"
    assert "REF NAME" in out
    assert "Not a pass" in out


def test_a_correct_branch_name_is_confirmed(tmp_path):
    """BIDIRECTIONAL: when the tree really does hold what the upstream names,
    the same call must go green — otherwise the rule is a ban on names."""
    up, _shas = _repo(tmp_path, "up")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(up), str(clone)],
                   capture_output=True, env=_env(tmp_path))
    rc, out = _run("--root", clone, "--expect", "main", "--upstream", up)
    assert rc == 0, out
    assert "CONFIRMED" in out


def test_an_absolute_sha_is_still_resolved_locally(tmp_path):
    """A sha means the same thing everywhere, so it needs no upstream."""
    _up, clone, before, _after = _stale_pair(tmp_path)
    rc, out = _run("--root", clone, "--expect", before)
    assert rc == 0, out
    assert "CONFIRMED" in out


def test_an_unreachable_upstream_is_not_checked(tmp_path):
    _up, clone, _b, _a = _stale_pair(tmp_path)
    rc, out = _run("--root", clone, "--expect", "main",
                   "--upstream", str(tmp_path / "no-such-remote"))
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_not_a_repository_is_not_checked(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    (d / "f.txt").write_text("x\n")
    rc, out = _run("--root", d, "--expect", "HEAD")
    assert rc == 2, out
    assert "NOT CHECKED" in out
    assert "not a pass" in out.lower()


def test_the_two_states_have_different_exit_codes(tmp_path):
    repo, shas = _repo(tmp_path)
    _git(repo, "checkout", "-q", "--detach", shas[0], tmp_path=tmp_path)
    rc_refuted, _ = _run("--root", repo, "--expect", shas[1])
    rc_unknown, _ = _run("--root", repo, "--expect", "0" * 40)
    assert rc_refuted == 1
    assert rc_unknown == 2
    assert rc_refuted != rc_unknown


def test_runtime_arm_needs_both_arguments(tmp_path):
    rc, out = _run("--root", tmp_path)
    assert rc == 3, out
    assert "BAD INVOCATION" in out


# -------------------------------------------------------------- source arm

def test_uninspected_checkout_goes_red(tmp_path):
    """THE NEGATIVE CONTROL for the source arm."""
    (tmp_path / "prep.py").write_text(
        'import subprocess\n'
        'def prepare(dest, commit):\n'
        '    subprocess.run(["git", "-C", str(dest), "checkout", commit],\n'
        '                   capture_output=True)\n')
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"


def test_inspected_checkout_passes(tmp_path):
    (tmp_path / "prep.py").write_text(
        'import subprocess\n'
        'def prepare(dest, commit):\n'
        '    cp = subprocess.run(["git", "-C", str(dest), "checkout", commit],\n'
        '                        capture_output=True)\n'
        '    if cp.returncode != 0:\n'
        '        raise SystemExit(1)\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_path_restore_is_not_in_the_population(tmp_path):
    """`git checkout -- <path>` selects no revision. Counting it would inflate
    the denominator with sites this rule has no opinion about."""
    (tmp_path / "restore.py").write_text(
        'import subprocess\n'
        'subprocess.run(["git", "-C", str(r), "checkout", "--", path],\n'
        '               capture_output=True)\n')
    rc, out = _run(tmp_path)
    assert rc == 2, out          # population empty -> NOT CHECKED, not PASS
    assert "NOT CHECKED" in out


def test_empty_population_is_not_checked(tmp_path):
    (tmp_path / "u.py").write_text("x = 1\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_absent_tree_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_PROGRAMS.parents[3])
    assert rc == 0, out
