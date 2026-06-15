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
import subprocess
from pathlib import Path

import pytest


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
