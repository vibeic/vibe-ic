"""Regression guard: the phased-out term `vibe-ic-core` must not
reappear in the live plugin surface (skills / programs / agents /
hooks / README / AGENT_USAGE_GUIDE).

Allowed exceptions (historical record only):
  - plugins/.gitignore (text context comment)

Per user 2026-05-29: 'vibe-ic-core is a phase-out keyword'.
"""
from pathlib import Path

import pytest

from _plugin_tree import plugin_root, repo_root, NOT_SHIPPED_REASON

# flow #486: the plugin root is the manifest anchor (works on both the
# source monorepo and the flattened install cache). The marketplace root
# (vibe-ic-marketplace/) and its plugins/.gitignore are repo-only and NOT
# shipped in the cache, so derived lookups below degrade to NAMED skips.
PLUGIN_ROOT = plugin_root()                             # plugins/vibe-ic
_RR = repo_root()                                        # None on the cache
MARKETPLACE_ROOT = (_RR / "vibe-ic-marketplace") if _RR is not None else None
PHASED_OUT = "vibe-ic-core"

# Files / paths to exempt from the scan. Anything under these survives
# the rename for documented reasons.
ALLOWED_PATHS = {
    Path(__file__).resolve(),               # this test names the phased-out
                                             # term as a string literal
}
if MARKETPLACE_ROOT is not None:
    # gitignore comment text (source monorepo only)
    ALLOWED_PATHS.add(MARKETPLACE_ROOT / "plugins" / ".gitignore")

# Subdirs to never walk into
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}


def _walk(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


class TestVibeIcCoreScrubbed:
    def test_no_vibe_ic_core_in_plugin_tree(self):
        offenders = []
        for path in _walk(PLUGIN_ROOT):
            if path in ALLOWED_PATHS:
                continue
            try:
                if PHASED_OUT in path.read_text(encoding="utf-8",
                                                  errors="ignore"):
                    offenders.append(str(path.relative_to(PLUGIN_ROOT)))
            except Exception:
                continue
        assert not offenders, (
            f"phased-out term {PHASED_OUT!r} found in: {offenders[:10]}"
            f"{' ...' if len(offenders) > 10 else ''}")

    def test_no_vibe_ic_core_in_marketplace_root_docs(self):
        # Top-level docs: README, AGENT_USAGE_GUIDE
        if MARKETPLACE_ROOT is None:
            pytest.skip(f"vibe-ic-marketplace/ docs: {NOT_SHIPPED_REASON}")
        offenders = []
        for name in ("README.md", "AGENT_USAGE_GUIDE.md"):
            path = MARKETPLACE_ROOT / name
            if not path.exists():
                continue
            if PHASED_OUT in path.read_text(encoding="utf-8",
                                              errors="ignore"):
                offenders.append(name)
        assert not offenders, (
            f"phased-out term {PHASED_OUT!r} reappeared in: {offenders}")


class TestExemptionsStillExist:
    """The exemptions themselves must remain pointing at real files,
    otherwise the scan loses meaning."""

    def test_gitignore_exists(self):
        if MARKETPLACE_ROOT is None:
            pytest.skip(f"plugins/.gitignore: {NOT_SHIPPED_REASON}")
        assert (MARKETPLACE_ROOT / "plugins" / ".gitignore").exists()
