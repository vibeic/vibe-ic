"""Auditing evidence must not rewrite the evidence.

`flow_compliance_check` is a producer as well as a judge: it drives each step's
gates, and those gates write their reports into the project.  That is right for
the run in progress and wrong for a PUBLISHED tree, and until now there was no
way to ask for the second.

MEASURED on `benchmark-data/ic/sha256/clean_run_v1422_20260715`, copied to
scratch and hashed before and after: one default invocation ADDS 25 files and
REWRITES 17 tracked ones.  With `--read-only`: 0 and 0, same verdict.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_FCC = _PROGRAMS / "flow_compliance_check.py"

def _manifest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _project(tmp_path: Path) -> Path:
    """A minimal run tree. Enough for the audit to reach its own emitter, which
    is the write every invocation performs regardless of what the tree holds."""
    p = tmp_path / "run"
    (p / "reports").mkdir(parents=True)
    (p / "RESULT.md").write_text("# a published run\n")
    return p


def _drive(project: Path, *flags):
    return _pr.run([sys.executable, str(_FCC), str(project), *flags],
                          cwd=str(project), capture_output=True, text=True)


def test_the_default_run_writes_into_the_project(tmp_path):
    """CONTROL, and the reproduction. Without it, the read-only assertion below
    is satisfied by an audit that never got as far as writing anything."""
    p = _project(tmp_path)
    before = _manifest(p)
    _drive(p)
    after = _manifest(p)
    assert set(after) - set(before), (
        "the default invocation wrote nothing, so this file measures nothing")


def test_read_only_leaves_the_project_byte_identical(tmp_path):
    p = _project(tmp_path)
    before = _manifest(p)
    r = _drive(p, "--read-only")
    after = _manifest(p)
    assert after == before, (
        "--read-only modified the tree it was auditing: added=%s changed=%s"
        % (sorted(set(after) - set(before)),
           sorted(k for k in set(after) & set(before)
                  if after[k] != before[k])))
    assert "Overall" in r.stdout, (
        "no verdict was produced, so the no-change assertion above proves "
        "only that nothing ran:\n" + r.stdout + r.stderr)


def test_read_only_reaches_the_same_verdict(tmp_path):
    """A read-only mode that changes the answer is a different check wearing
    the same name."""
    a = _project(tmp_path / "a")
    b = _project(tmp_path / "b")
    ra, rb = _drive(a), _drive(b, "--read-only")
    assert ra.returncode == rb.returncode, (ra.stdout, rb.stdout)
    va = [ln for ln in ra.stdout.splitlines() if ln.startswith("Overall")]
    vb = [ln for ln in rb.stdout.splitlines() if ln.startswith("Overall")]
    assert va and va == vb, (va, vb)


def test_read_only_on_a_REAL_published_tree_changes_nothing(tmp_path):
    """The measurement that motivated the flag, over real evidence.

    The corpus copy is what is audited — `benchmark-data/` is never the target,
    because proving a gate does not write by writing into the corpus would be
    the defect itself.
    """
    src = _REPO / "benchmark-data/ic/sha256/clean_run_v1422_20260715"
    if not src.is_dir():                     # a shallow or filtered checkout
        import pytest
        pytest.skip("published run tree not present in this checkout")
    dst = tmp_path / "published"
    shutil.copytree(src, dst, symlinks=True)
    before = _manifest(dst)
    r = _drive(dst, "--read-only")
    after = _manifest(dst)
    assert after == before, (
        "--read-only rewrote published evidence: %d added, %d changed"
        % (len(set(after) - set(before)),
           len([k for k in set(after) & set(before)
                if after[k] != before[k]])))
    assert "Overall" in r.stdout, r.stdout + r.stderr


def test_read_only_refuses_a_json_destination_inside_the_tree(tmp_path):
    """The one write the copy cannot absorb is the audit's OWN report, and a
    caller can aim it back into the project. A read-only flag with a write left
    in it is the class of lie this whole change is about, so the path is
    refused rather than silently moved — the caller named it."""
    p = _project(tmp_path)
    before = _manifest(p)
    r = _drive(p, "--read-only", "--json", str(p / "reports" / "audit.json"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "refuses to write its --json report inside" in r.stderr, r.stderr
    assert _manifest(p) == before

    # CONTROL: a destination OUTSIDE the tree is accepted and produced, so the
    # refusal above is about the location and not about --json at all.
    out = tmp_path / "elsewhere.json"
    r2 = _drive(p, "--read-only", "--json", str(out))
    assert out.is_file(), r2.stdout + r2.stderr
    assert _manifest(p) == before, "the accepted run still wrote into the tree"


def test_read_only_refuses_rather_than_falling_back_to_writing(tmp_path):
    """A caller that asked for read-only and got a write would be worse off
    than one that never asked: it would trust the tree afterwards.

    The copy is made to fail the ordinary way — an unreadable subdirectory in
    somebody else's run tree — which also pins the exception type: `copytree`
    collects per-file errors and raises its OWN aggregate class, not `OSError`.
    """
    import os
    import pytest
    p = _project(tmp_path)
    locked = p / "unreadable"
    locked.mkdir()
    (locked / "x.txt").write_text("x\n")
    os.chmod(locked, 0o000)
    if os.access(locked, os.R_OK):           # running as root
        os.chmod(locked, 0o755)
        pytest.skip("this user can read a 000 directory; the copy cannot fail")
    try:
        before = {k: v for k, v in _manifest(p).items()
                  if not k.startswith("unreadable")}
        r = _pr.run([sys.executable, str(_FCC), str(p), "--read-only"],
                           cwd=str(p), capture_output=True, text=True)
        assert r.returncode == 2, (
            "a failed copy did not refuse:\n" + r.stdout + r.stderr)
        assert "--read-only could not copy" in r.stderr, r.stderr
        after = {k: v for k, v in _manifest(p).items()
                 if not k.startswith("unreadable")}
        assert after == before, (
            "the failed --read-only run wrote into the project anyway")
    finally:
        os.chmod(locked, 0o755)
