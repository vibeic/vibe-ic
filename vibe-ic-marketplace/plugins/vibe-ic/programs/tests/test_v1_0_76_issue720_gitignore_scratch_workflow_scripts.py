"""ORGANIC #720 — repo hygiene: gitignore root-level scratch Workflow scripts.

Session scratch Workflow/orchestration scripts are created at the REPO ROOT as
`_*.js` (e.g. `_review_backlog_*.js`, `_sweep_workflow.js`, …). They were NOT
gitignored, so a stray `git add` could sweep template/scratch code to github.
Fix: a ROOT-ANCHORED `/_*.js` rule in the repo-root `.gitignore`.

Acceptance (verbatim from the issue):
  - `.gitignore` carries the `/_*.js` rule.
  - `git check-ignore <root>/_anything.js` → ignored.
  - `git check-ignore <subdir>/_registry.js` → NOT ignored (root-anchored).
  - No existing tracked file is newly removed from tracking.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "gitignore_scratch_guard.py"


def _repo_root() -> Path:
    cp = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent))
    if cp.returncode != 0:
        pytest.skip("not in a git repo")
    return Path(cp.stdout.strip())


def _check_ignored(root: Path, rel: str) -> bool:
    """True iff `rel` (relative to repo root) is git-ignored."""
    return subprocess.run(
        ["git", "check-ignore", rel],
        cwd=str(root), capture_output=True, text=True).returncode == 0


def test_gitignore_carries_root_anchored_scratch_rule():
    root = _repo_root()
    gi = root / ".gitignore"
    assert gi.is_file()
    assert "/_*.js" in gi.read_text().splitlines()


def test_end_state_root_scratch_js_is_ignored():
    """END-STATE: a root-level `_*.js` scratch script is ignored."""
    root = _repo_root()
    assert _check_ignored(root, "_review_backlog_600_newest.js")
    assert _check_ignored(root, "_sweep_workflow.js")
    assert _check_ignored(root, "_anything.js")


def test_noleak_subdir_underscore_js_not_ignored():
    """§ root-anchor no-leak: a tracked `_*.js` in a SUBDIR (e.g. the mcp-eda
    devices `_registry.js`) must NOT be matched by the root-anchored rule."""
    root = _repo_root()
    subdir_reg = ("vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices/"
                  "_registry.js")
    if (root / subdir_reg).is_file():
        assert not _check_ignored(root, subdir_reg)
    # a nested scratch-looking name is also not matched by the root anchor
    assert not _check_ignored(root, "some/sub/_helper.js")


def test_noleak_no_tracked_file_removed_by_rule():
    """§ the rule must not newly UN-track any committed file (a tracked file is
    not affected by .gitignore — guard that none of our `_*.js` are tracked at
    root, and the subdir `_registry.js` stays tracked)."""
    root = _repo_root()
    tracked = subprocess.run(["git", "ls-files"], cwd=str(root),
                             capture_output=True, text=True).stdout.splitlines()
    # no tracked file lives at repo root matching _*.js
    assert not [f for f in tracked
                if "/" not in f and f.startswith("_") and f.endswith(".js")]
    # the legitimate subdir _registry.js remains tracked
    assert any(f.endswith("mcp-eda/src/devices/_registry.js") for f in tracked)


def test_end_state_guard_program_passes_on_real_repo(tmp_path):
    """END-STATE via the real program: gitignore_scratch_guard exits 0 and its
    evidence shows the rule present + correctly root-anchored on this repo."""
    out = tmp_path / "ev.json"
    cp = subprocess.run(
        [sys.executable, str(_GUARD), "--json", str(out)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent))
    assert cp.returncode == 0, cp.stderr
    ev = json.loads(out.read_text())
    assert ev["ok"] is True
    assert ev["rule_present"] and ev["root_scratch_ignored"]
    assert ev["subdir_registry_ignored"] is False


def test_end_state_guard_fails_when_rule_absent(tmp_path):
    """END-STATE (defect-artifact fixture): a git repo WITHOUT the /_*.js rule
    makes the guard FAIL (exit 1) — proving the guard really enforces the rule,
    not a trivially-true check."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".gitignore").write_text("*.log\n")          # rule ABSENT
    (repo / "keep.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    cp = subprocess.run([sys.executable, str(_GUARD), "--root", str(repo)],
                        capture_output=True, text=True)
    assert cp.returncode == 1
    assert '"rule_present": false' in cp.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_scratch_path_in_the_tree_fails_even_when_the_rule_is_present():
    """Probing a rule proves the rule; listing the tree proves the outcome.

    #720 fixed the extension it happened to meet (`/_*.js`) and this guard
    probed that one rule with one synthetic filename. It reported rc 0 while
    four scratch paths sat untracked-and-unignored in the working tree for
    three to nine days: `scratchpad/`, `scratchpad_pr487_msg.txt`,
    `_gds_closure/`, and `vibe-ic-marketplace/scratch_geom_signoff_tests/`.

    Untracked-but-not-ignored is the state one `git add -A` turns into a
    commit, which is why this repo forbids `-A`. Verified on the real
    repository: removing the new rules gives rc 1 with `rule_present: true` —
    the rule is there and the outcome is still wrong, which is the whole point
    of checking the second thing.
    """
    import subprocess
    import tempfile
    from pathlib import Path
    import gitignore_scratch_guard as G

    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        (r / ".gitignore").write_text("/_*.js\n")
        (r / "scratchpad").mkdir()
        (r / "scratchpad" / "note.txt").write_text("x")
        ev = G.audit(r)
        assert ev["unignored_scratch_in_tree"], \
            "a scratch directory sitting in the tree was not noticed"
        assert ev["ok"] is False

        (r / ".gitignore").write_text("/_*.js\n/scratchpad\n")
        ev = G.audit(r)
        assert not ev["unignored_scratch_in_tree"]
