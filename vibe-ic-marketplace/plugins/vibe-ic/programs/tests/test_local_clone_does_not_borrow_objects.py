"""A prepared checkout owns its objects, and "did not look" is its own verdict.

WHY
===
`landing_tier_checkout_preflight` refuses a checkout whose objects live in
another repository, and it refuses it AFTER the checkout has been built — an
hour of tier wall-clock later. This checker refuses the same shape at the site
that BUILDS it.

BIDIRECTIONAL, WHICH IS THE POINT
=================================
Every "must go red" case below is paired with the same site built the accepted
way, which must go green. A scan that refuses every clone would satisfy each
red assertion here and redden the remedy that two shipped programs print.

THE THREE VERDICTS NEVER COLLAPSE
=================================
A scan that found no clone site (rc 2) and a scan that read 12 of them and
found nothing wrong (rc 0) are different facts, and the brief this implements
requires that they never share an exit code. Asserted directly.

chip-AGNOSTIC: git plumbing and source text. No design, PDK or vendor literal.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "local_clone_does_not_borrow_objects.py"

_spec = importlib.util.spec_from_file_location("lcdnbo", _TOOL)
lcdnbo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lcdnbo)


def _run(root: Path):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# --------------------------------------------------------------------------
# GREEN — the accepted shape
# --------------------------------------------------------------------------

def test_plain_local_clone_passes(tmp_path):
    """A default local clone hardlinks immutable objects. The preflight accepts
    it and prints it as its own remedy, so this checker must not redden it."""
    (tmp_path / "prep.py").write_text(
        'import subprocess\n'
        'def prepare(src, dest):\n'
        '    subprocess.run(["git", "clone", "--quiet", str(src), str(dest)])\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "PASS" in out


def test_no_hardlinks_is_not_required(tmp_path):
    """The record this implements asked for `--no-hardlinks` to be REQUIRED.
    That would redden `prepare_gate_checkout`, which omits it deliberately and
    says why. The narrowing is asserted here so it cannot be quietly undone."""
    (tmp_path / "poller.py").write_text(
        'import subprocess\n'
        'subprocess.run(["git", "clone", "--quiet", "--no-checkout",\n'
        '                "--no-single-branch", str(root), str(dest)])\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


# --------------------------------------------------------------------------
# RED — the negative controls. These are the whole point of the file.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("option", ["--shared", "-s", "--reference",
                                    "--reference-if-able"])
def test_borrowing_clone_goes_red(tmp_path, option):
    """Reintroduce the defect: a preparation site that builds alternates."""
    (tmp_path / "prep.py").write_text(
        'import subprocess\n'
        'def prepare(src, dest):\n'
        f'    subprocess.run(["git", "clone", "--quiet", "{option}",\n'
        '                    str(src), str(dest)])\n')
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert option in out
    assert "alternates" in out


def test_a_borrowing_option_held_in_a_variable_goes_red(tmp_path):
    """MEASURED FALSE PASS, now pinned.

    This scan reported PASS on a borrowing clone written the way a real
    preparation site writes one — the options in a list one assignment away:

        OPTS = ["--quiet", "--shared"]
        subprocess.run(["git", "clone"] + OPTS + [str(src), str(dest)])

    Answering PASS because the offending token is not lexically inside the argv
    list is not conservatism, it is wrong in the passing direction.
    """
    (tmp_path / "prep.py").write_text(
        'import subprocess\n'
        'OPTS = ["--quiet", "--shared"]\n'
        'def prepare(src, dest):\n'
        '    subprocess.run(["git", "clone"] + OPTS + [str(src), str(dest)])\n')
    rc, out = _run(tmp_path)
    assert rc == 1, f"the dynamic form was not caught:\n{out}"
    assert "--shared" in out


def test_the_same_site_without_the_borrowing_option_passes(tmp_path):
    """BIDIRECTIONAL: the identical shape, with only the option removed."""
    (tmp_path / "prep.py").write_text(
        'import subprocess\n'
        'OPTS = ["--quiet", "--no-checkout"]\n'
        'def prepare(src, dest):\n'
        '    subprocess.run(["git", "clone"] + OPTS + [str(src), str(dest)])\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_borrowing_clone_in_shell_goes_red(tmp_path):
    (tmp_path / "prep.sh").write_text(
        '#!/bin/bash\n'
        'git clone --shared "$SRC" "$DEST"\n')
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"


def test_the_finding_is_real_git_behaviour(tmp_path):
    """The rule is not a style opinion: prove `--shared` really does write the
    alternates file the preflight refuses, and a plain clone really does not."""
    src = tmp_path / "src"
    src.mkdir()
    env = {"GIT_CONFIG_GLOBAL": str(tmp_path / "gc"), "GIT_CONFIG_SYSTEM":
           str(tmp_path / "gs"), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    def git(*a, cwd):
        subprocess.run(["git", *a], cwd=str(cwd), check=True,
                       capture_output=True, env=env)
    git("init", "-q", "-b", "main", cwd=src)
    (src / "f.txt").write_text("x\n")
    git("add", "f.txt", cwd=src)
    git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "c",
        cwd=src)
    shared, plain = tmp_path / "shared", tmp_path / "plain"
    git("clone", "-q", "--shared", str(src), str(shared), cwd=tmp_path)
    git("clone", "-q", str(src), str(plain), cwd=tmp_path)
    assert (shared / ".git" / "objects" / "info" / "alternates").exists()
    assert not (plain / ".git" / "objects" / "info" / "alternates").exists()


# --------------------------------------------------------------------------
# "did not look" vs "looked and found nothing" — never the same verdict
# --------------------------------------------------------------------------

def test_empty_population_is_not_checked_not_pass(tmp_path):
    (tmp_path / "unrelated.py").write_text("x = 1\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_unreadable_candidate_is_not_checked_not_pass(tmp_path):
    (tmp_path / "ok.py").write_text(
        'import subprocess\n'
        'subprocess.run(["git", "clone", str(a), str(b)])\n')
    (tmp_path / "broken.py").write_bytes(b"\xff\xfe clone \x00\x81")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_unparseable_python_is_not_checked_not_pass(tmp_path):
    (tmp_path / "bad.py").write_text('subprocess.run(["git", "clone" ,,,\n')
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_the_two_states_have_different_exit_codes(tmp_path):
    """The brief's requirement, asserted as an equation rather than prose."""
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "u.py").write_text("x = 1\n")
    looked = tmp_path / "looked"
    looked.mkdir()
    (looked / "p.py").write_text(
        'import subprocess\n'
        'subprocess.run(["git", "clone", str(a), str(b)])\n')
    rc_did_not_look, _ = _run(empty)
    rc_looked, _ = _run(looked)
    assert rc_did_not_look == 2
    assert rc_looked == 0
    assert rc_did_not_look != rc_looked


# --------------------------------------------------------------------------
# a comment, and a bad invocation
# --------------------------------------------------------------------------

def test_a_comment_is_not_a_finding(tmp_path):
    (tmp_path / "prep.sh").write_text(
        '#!/bin/bash\n'
        '# never use git clone --shared here; it builds alternates\n'
        'git clone "$SRC" "$DEST"\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out
    assert "BAD INVOCATION" in out


def test_repository_itself_is_clean():
    """Corpus sweep, run as a test so it cannot rot."""
    repo = _PROGRAMS.parents[3]
    rc, out = _run(repo)
    assert rc == 0, out
