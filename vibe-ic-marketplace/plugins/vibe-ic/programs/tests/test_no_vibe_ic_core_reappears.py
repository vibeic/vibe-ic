"""Regression guard: the phased-out term `vibe-ic-core` must not
reappear in the live plugin surface (skills / programs / agents /
hooks / README / AGENT_USAGE_GUIDE).

Allowed exceptions (historical record only):
  - MIGRATION_LOG.md (audit trail of the rename)
  - plugins/.gitignore (text context comment)

Per user 2026-05-29: 'vibe-ic-core is a phase-out keyword'.
"""
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]      # plugins/vibe-ic
MARKETPLACE_ROOT = PLUGIN_ROOT.parents[1]               # vibe-ic-marketplace
PHASED_OUT = "vibe-ic-core"

# Files / paths to exempt from the scan. Anything under these survives
# the rename for documented reasons.
ALLOWED_PATHS = {
    PLUGIN_ROOT / "MIGRATION_LOG.md",       # historical audit
    MARKETPLACE_ROOT / "plugins" / ".gitignore",  # gitignore comment text
    Path(__file__).resolve(),               # this test names the phased-out
                                             # term as a string literal
}

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

    def test_migration_log_exists(self):
        # historical audit; if removed, doctrine is to also remove the
        # exemption AND retest the scan as empty
        assert (PLUGIN_ROOT / "MIGRATION_LOG.md").exists()

    def test_gitignore_exists(self):
        assert (MARKETPLACE_ROOT / "plugins" / ".gitignore").exists()
