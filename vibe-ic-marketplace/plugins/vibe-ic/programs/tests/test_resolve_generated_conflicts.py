#!/usr/bin/env python3
"""tools/resolve_generated_conflicts.sh — it must resolve GENERATED conflicts and
refuse everything else.

The whole value of this script is that it is safe to run without reading the
diff. That property is worth exactly as much as the refusal path is strict, so
every test here is paired: one that it resolves, one that it must NOT.

chip-AGNOSTIC: builds throwaway git repos in tmp_path; touches no real tree.
"""
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
SCRIPT = REPO / "tools" / "resolve_generated_conflicts.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="needs git")


def _git(cwd, *args, check=True):
    r = subprocess.run(("git",) + args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} -> {r.returncode}\n{r.stderr}")
    return r


def _sandbox(tmp_path):
    """A repo with a fake generated INDEX.md and a generator that rebuilds it
    from the *.txt entries on disk -- the same shape as the real one: a total
    line that every branch rewrites, so branches collide on the COUNTER."""
    w = tmp_path / "repo"
    (w / "tools").mkdir(parents=True)
    gen_dir = w / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    gen_dir.mkdir(parents=True)

    (w / "tools" / "gen_programs_index.py").write_text(textwrap.dedent("""
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        d = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
        out = d / "INDEX.md"
        names = sorted(p.stem for p in d.glob("*.txt"))
        body = f"total: {len(names)}\\n" + "".join(f"- {n}\\n" for n in names)
        if "--check" in sys.argv:
            sys.exit(0 if out.read_text() == body else 1)
        out.write_text(body)
        """).lstrip())

    _git(w, "init", "-q", "-b", "main")
    _git(w, "config", "user.email", "t@t")
    _git(w, "config", "user.name", "t")
    shutil.copy(SCRIPT, w / "tools" / "resolve_generated_conflicts.sh")
    (w / "tools" / "resolve_generated_conflicts.sh").chmod(0o755)

    # the script hard-codes the real generated path, so use that path here too
    (gen_dir / "base.txt").write_text("x")
    subprocess.run(["python3", "tools/gen_programs_index.py"], cwd=w, check=True)
    _git(w, "add", "-A")
    _git(w, "commit", "-qm", "base")
    return w


def _branch_adding(w, name, entry):
    gen_dir = w / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    _git(w, "checkout", "-q", "-B", name, "main")
    (gen_dir / f"{entry}.txt").write_text("x")
    subprocess.run(["python3", "tools/gen_programs_index.py"], cwd=w, check=True)
    _git(w, "add", "-A")
    _git(w, "commit", "-qm", f"add {entry}")


def _run(w, *args):
    return subprocess.run(
        ["bash", "tools/resolve_generated_conflicts.sh", *args],
        cwd=w, capture_output=True, text=True)


def test_the_counter_line_really_is_what_collides(tmp_path):
    """The premise. If two branches adding unrelated entries did NOT conflict,
    this script would be solving a problem nobody has."""
    w = _sandbox(tmp_path)
    _branch_adding(w, "a", "aaa")
    _branch_adding(w, "b", "zzz")
    _git(w, "checkout", "-q", "a")
    r = _git(w, "merge", "--no-ff", "--no-edit", "b", check=False)
    assert r.returncode != 0, "expected a conflict on the generated index"
    unmerged = _git(w, "diff", "--name-only", "--diff-filter=U").stdout.split()
    assert any("INDEX.md" in u for u in unmerged), unmerged


def test_a_generated_conflict_is_resolved_and_the_result_is_correct(tmp_path):
    w = _sandbox(tmp_path)
    _branch_adding(w, "a", "aaa")
    _branch_adding(w, "b", "zzz")
    _git(w, "checkout", "-q", "a")
    _git(w, "merge", "--no-ff", "--no-edit", "b", check=False)

    r = _run(w)
    assert r.returncode == 0, r.stderr
    assert not _git(w, "diff", "--name-only", "--diff-filter=U").stdout.strip()

    # not merely "resolved" -- resolved to the RIGHT content. Both entries must
    # survive and the counter must count them, which is the thing a
    # take-ours/take-theirs resolution would silently get wrong.
    idx = (w / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
           / "INDEX.md").read_text()
    assert "total: 3" in idx, idx
    assert "- aaa" in idx and "- zzz" in idx, idx
    chk = subprocess.run(["python3", "tools/gen_programs_index.py", "--check"], cwd=w)
    assert chk.returncode == 0


def test_a_conflict_in_an_AUTHORED_file_is_refused_and_nothing_is_staged(tmp_path):
    """The paired guard. This is the failure that would matter: a script that
    resolved authored conflicts by regenerating would destroy work silently."""
    w = _sandbox(tmp_path)
    gen_dir = w / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    for name, text in (("a", "hand written by A\n"), ("b", "hand written by B\n")):
        _git(w, "checkout", "-q", "-B", name, "main")
        (gen_dir / "authored.md").write_text(text)
        _git(w, "add", "-A")
        _git(w, "commit", "-qm", f"authored {name}")
    _git(w, "checkout", "-q", "a")
    _git(w, "merge", "--no-ff", "--no-edit", "b", check=False)

    before = _git(w, "diff", "--name-only", "--diff-filter=U").stdout
    r = _run(w)
    after = _git(w, "diff", "--name-only", "--diff-filter=U").stdout

    assert r.returncode != 0, "must refuse an authored conflict"
    assert "REFUSING" in (r.stdout + r.stderr)
    assert before == after, "the conflict must be left exactly as it was"
    assert "hand written" in (gen_dir / "authored.md").read_text()


def test_a_BROKEN_generator_refuses_instead_of_staging_a_wrong_index(tmp_path):
    """A resolver that always succeeds turns a generator outage into a silently
    committed wrong file -- strictly worse than the conflict it replaces."""
    w = _sandbox(tmp_path)
    _branch_adding(w, "a", "aaa")
    _branch_adding(w, "b", "zzz")
    _git(w, "checkout", "-q", "a")
    _git(w, "merge", "--no-ff", "--no-edit", "b", check=False)
    (w / "tools" / "gen_programs_index.py").write_text("import sys\nsys.exit(3)\n")

    r = _run(w)
    assert r.returncode != 0, "must refuse when the generator fails"
    assert _git(w, "diff", "--name-only", "--diff-filter=U").stdout.strip(), \
        "the conflict must still be there"


def test_a_generator_that_SUCCEEDS_but_lies_is_still_refused(tmp_path):
    """The previous test does not prove what its name suggests.

    A generator that exits non-zero leaves the conflict markers in place, so the
    marker check catches it even with the exit-code check removed -- verified by
    mutation: deleting BOTH the exit-code check and the --check verification
    still left all five tests green. Only a generator that fails QUIETLY -- exit
    0, no markers, wrong content -- isolates the `--check` guard, and that is the
    exact shape of a check that lies, so it needs its own test.
    """
    w = _sandbox(tmp_path)
    _branch_adding(w, "a", "aaa")
    _branch_adding(w, "b", "zzz")
    _git(w, "checkout", "-q", "a")
    _git(w, "merge", "--no-ff", "--no-edit", "b", check=False)

    # exits 0, writes a clean-looking file, and drops an entry.
    (w / "tools" / "gen_programs_index.py").write_text(textwrap.dedent("""
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        out = root / "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
        if "--check" in sys.argv:
            sys.exit(1)          # honest: what is on disk is NOT what I generate
        out.write_text("total: 1\\n- base\\n")
        sys.exit(0)
        """).lstrip())

    r = _run(w)
    assert r.returncode != 0, "a silently wrong index must not be staged"
    assert _git(w, "diff", "--name-only", "--diff-filter=U").stdout.strip(), \
        "the conflict must still be there"


def test_no_conflict_is_a_clean_no_op(tmp_path):
    w = _sandbox(tmp_path)
    r = _run(w)
    assert r.returncode == 0
    assert "nothing to resolve" in r.stdout
