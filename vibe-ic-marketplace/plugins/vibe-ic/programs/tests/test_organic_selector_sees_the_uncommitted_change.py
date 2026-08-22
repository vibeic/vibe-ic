#!/usr/bin/env python3
"""ORGANIC, found while gating vibe-ic#428 — and it had already cost two
landings before it was caught.

`ci_targeted_test_select` answers "which tests does this change need?" from
`git diff --name-only <base>..HEAD`, i.e. from the COMMITS. The gatekeeper's
merge queue does `git merge --squash <branch>` and then asks that question
BEFORE committing, so HEAD is still `base`, the diff is empty, and the
selector returned only its fixed smoke set.

That output is byte-indistinguishable from a real selection. Landing #235 and
#428 both printed `selected 15 test file(s)` — the same 15, for two unrelated
change-sets — and both passed. #428 adds a 32-test module that was in neither
run. The tests were run separately and are green, so nothing bad shipped; what
shipped was a GATE THAT WAS NOT LOOKING, reporting the same reassuring number
either way.

Same shape as #416, #414 and #425: the tree you are standing in is not the
change under review. Here it is the inverse — the CHANGE is in the tree and
the gate was only reading the commits.

The fix unions `<base>..HEAD` with `<base>` (base vs working tree). In CI the
tree is clean and the two agree, so CI behaviour is unchanged; the union is
what makes the local merge-queue question answerable at all.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import ci_targeted_test_select as S  # noqa: E402


def _repo(tmp_path: Path) -> tuple[Path, str]:
    r = tmp_path / "r"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    (r / "seed.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(r), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    base = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return r, base


def test_a_staged_but_uncommitted_change_is_seen(tmp_path):
    """THE LOAD-BEARING CASE — exactly the merge queue's situation."""
    r, base = _repo(tmp_path)
    (r / "prog.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(r), "add", "prog.py"], check=True)

    head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == base, "precondition: the squash is staged, not committed"

    assert S._git_changed_files(base, r) == ["prog.py"]


def test_an_unstaged_edit_is_seen_too(tmp_path):
    """A file edited after the squash staged it — the `331c434e8` shape, where
    `--cached` listed a path whose later edit was not in the commit."""
    r, base = _repo(tmp_path)
    (r / "seed.txt").write_text("x\nmore\n")
    assert S._git_changed_files(base, r) == ["seed.txt"]


def test_a_committed_change_is_still_seen(tmp_path):
    """The paired half: the CI situation must not regress."""
    r, base = _repo(tmp_path)
    (r / "prog.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(r), "add", "prog.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True)
    assert S._git_changed_files(base, r) == ["prog.py"]


def test_a_path_both_committed_and_further_edited_appears_once(tmp_path):
    """The union must not double-report, or a caller counting paths is misled."""
    r, base = _repo(tmp_path)
    (r / "prog.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(r), "add", "prog.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True)
    (r / "prog.py").write_text("x = 2\n")
    assert S._git_changed_files(base, r) == ["prog.py"]


def test_a_genuinely_clean_tree_still_reports_no_changes(tmp_path):
    """The control that keeps this honest in the other direction: unioning must
    not invent changes. If it did, every selection would look targeted and the
    smoke floor would never be recognisable as one."""
    r, base = _repo(tmp_path)
    assert S._git_changed_files(base, r) == []


def test_an_unusable_base_is_None_not_an_empty_list(tmp_path):
    """`None` (cannot look) and `[]` (looked, nothing there) must stay distinct
    — collapsing them is the same false certificate at a lower level, and the
    caller prints a different message for each."""
    r, _ = _repo(tmp_path)
    assert S._git_changed_files("no-such-ref-at-all", r) is None


def test_the_empty_case_says_so_instead_of_looking_like_a_selection(tmp_path,
                                                                   capsys):
    """The defect was not only that the diff was empty — it was that the
    OUTPUT of an empty diff reads as a real answer. The smoke floor must
    announce itself."""
    r, base = _repo(tmp_path)
    (r / "programs").mkdir()
    S.main(["--base", base, "--plugin-root", str(r)])
    err = capsys.readouterr().err
    assert "NO CHANGES" in err, err
    assert "from 0 changed path(s)" in err, err


def test_a_real_change_does_not_print_the_no_changes_banner(tmp_path, capsys):
    """Paired: the banner must not cry wolf on every run."""
    r, base = _repo(tmp_path)
    (r / "programs").mkdir()
    (r / "programs" / "prog.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(r), "add", "programs/prog.py"], check=True)
    S.main(["--base", base, "--plugin-root", str(r)])
    err = capsys.readouterr().err
    assert "NO CHANGES" not in err, err
    assert "from 1 changed path(s)" in err, err
