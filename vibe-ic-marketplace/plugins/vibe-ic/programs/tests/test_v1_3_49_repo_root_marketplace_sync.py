#!/usr/bin/env python3
"""v1.3.49 — regression tests for marketplace_version_sync_check.py covering the
REPO-ROOT (outer) manifest, not just the nearest/maintained one.

Motivating defect (owner directive 2026-07-09, "把它 bump 對齊"): the repo carries
TWO marketplace.json manifests referencing the SAME plugin —
  * MAINTAINED : vibe-ic-marketplace/.claude-plugin/marketplace.json
                 (source ./plugins/vibe-ic)          — gate-tracked
  * REPO-ROOT  : .claude-plugin/marketplace.json
                 (source ./vibe-ic-marketplace/plugins/vibe-ic) — NOT tracked
The old gate walked up to the NEAREST marketplace.json only (the maintained one),
so the repo-root manifest silently drifted: it sat at 1.3.42 for six releases
while the maintained manifest + plugin.json advanced to 1.3.48. `/plugin update`
that reads the repo-root manifest would see no version change and no-op.

These tests build a NESTED two-manifest tree (repo-root manifest wrapping a
maintained sub-manifest, both resolving to the SAME plugin.json) and pin:
  * a repo-root manifest at a MISMATCHED version FAILs (even when the maintained
    manifest matches — the exact drift the old gate missed);
  * an ALIGNED tree PASSes;
  * --fix repairs the drifting repo-root manifest;
and a REGRESSION GUARD that only the VERSION field is enforced — divergent
owner / homepage / source between the two manifests must NOT FAIL the gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (
    Path(__file__).resolve().parents[2]
    / "programs"
    / "marketplace_version_sync_check.py"
)


def _make_nested_tree(tmp_path: Path,
                      *,
                      plugin_name: str = "vibe-ic",
                      pj_version: str,
                      maintained_version: str | None,
                      root_version: str | None,
                      root_owner: str = "VibeIC.AI",
                      root_homepage: str = "https://github.com/vibeic/vibe-ic",
                      maintained_owner: str = "Reyer",
                      maintained_homepage: str = "https://vibeic.ai") -> Path:
    """Build a nested tree mirroring the real repo layout:

        root/
          .claude-plugin/marketplace.json        (REPO-ROOT; source ->
                                                   ./sub/plugins/<name>)
          sub/
            .claude-plugin/marketplace.json      (MAINTAINED; source ->
                                                   ./plugins/<name>)
            plugins/<name>/.claude-plugin/plugin.json   (version pj_version)

    Both manifests' source paths resolve to the SAME plugin.json. Returns the
    plugin dir (pass it as --marketplace-dir so the walk finds the maintained
    manifest as PRIMARY and the repo-root manifest as the OUTER one).
    """
    root = tmp_path / "root"
    sub = root / "sub"
    plugin_dir = sub / "plugins" / plugin_name
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": plugin_name, "version": pj_version}, indent=2)
    )

    def _mkt(base: Path, source: str, version: str | None,
             owner: str, homepage: str) -> None:
        entry: dict = {"name": plugin_name, "source": source,
                       "homepage": homepage}
        if version is not None:
            entry["version"] = version
        (base / ".claude-plugin").mkdir(parents=True)
        (base / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "vibe-ic-marketplace",
                        "owner": {"name": owner},
                        "plugins": [entry]}, indent=2)
        )

    _mkt(sub, f"./plugins/{plugin_name}", maintained_version,
         maintained_owner, maintained_homepage)
    _mkt(root, f"./sub/plugins/{plugin_name}", root_version,
         root_owner, root_homepage)
    return plugin_dir


def _run(marketplace_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG),
         "--marketplace-dir", str(marketplace_dir), *extra],
        capture_output=True, text=True)


def test_root_manifest_mismatch_fails_even_when_maintained_matches(tmp_path):
    """THE motivating defect: maintained + plugin.json aligned at 1.3.48 but the
    repo-root manifest stale at 1.3.42 → the old gate PASSed (blind), the new
    gate FAILs. This is the load-bearing regression guard."""
    plugin_dir = _make_nested_tree(
        tmp_path,
        pj_version="1.3.48",
        maintained_version="1.3.48",   # maintained matches — old gate would PASS
        root_version="1.3.42",         # repo-root stale — must FAIL now
    )
    r = _run(plugin_dir)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "[FAIL]" in r.stdout
    assert "2 manifest(s)" in r.stdout
    assert "1.3.42" in r.stdout and "1.3.48" in r.stdout


def test_aligned_tree_passes(tmp_path):
    """All three (plugin.json + maintained + repo-root) at 1.3.49 → PASS."""
    plugin_dir = _make_nested_tree(
        tmp_path,
        pj_version="1.3.49",
        maintained_version="1.3.49",
        root_version="1.3.49",
    )
    r = _run(plugin_dir)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[PASS]" in r.stdout
    assert "2 manifest(s)" in r.stdout


def test_fix_repairs_drifting_root_manifest(tmp_path):
    """--fix bumps the repo-root manifest to plugin.json's version and PASSes."""
    plugin_dir = _make_nested_tree(
        tmp_path,
        pj_version="1.3.49",
        maintained_version="1.3.49",
        root_version="1.3.42",
    )
    r = _run(plugin_dir, "--fix")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[PASS_AFTER_FIX]" in r.stdout
    root_mkt = json.loads(
        (tmp_path / "root" / ".claude-plugin" / "marketplace.json").read_text()
    )
    assert root_mkt["plugins"][0]["version"] == "1.3.49"
    # a follow-up plain run is now PASS
    assert _run(plugin_dir).returncode == 0


def test_only_version_enforced_owner_homepage_source_may_diverge(tmp_path):
    """The two manifests legitimately differ in owner / homepage / source (the
    real repo-root is VibeIC.AI/github.com, the maintained is Reyer/vibeic.ai).
    The gate must enforce VERSION equality ONLY — divergent owner/homepage/source
    at the SAME version must PASS."""
    plugin_dir = _make_nested_tree(
        tmp_path,
        pj_version="1.3.49",
        maintained_version="1.3.49",
        root_version="1.3.49",
        root_owner="VibeIC.AI",
        root_homepage="https://github.com/vibeic/vibe-ic",
        maintained_owner="Reyer",
        maintained_homepage="https://vibeic.ai",
    )
    r = _run(plugin_dir)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[PASS]" in r.stdout


def test_maintained_drift_still_caught(tmp_path):
    """Regression: the ORIGINAL surface (maintained manifest drift) is still
    caught — the repo-root check is additive, not a replacement."""
    plugin_dir = _make_nested_tree(
        tmp_path,
        pj_version="1.3.49",
        maintained_version="1.3.40",   # maintained stale
        root_version="1.3.49",
    )
    r = _run(plugin_dir)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "[FAIL]" in r.stdout
    assert "1.3.40" in r.stdout


def test_single_manifest_unchanged_behavior(tmp_path):
    """Regression guard: a tree with only ONE marketplace.json (no outer) still
    checks exactly that one — the multi-manifest walk adds nothing spurious."""
    root = tmp_path / "solo"
    plugin_dir = root / "plugins" / "demo"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.2.3"}, indent=2)
    )
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "demo", "source": "./plugins/demo",
                                 "version": "1.2.3"}]}, indent=2)
    )
    r = _run(root)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[PASS]" in r.stdout
    assert "1 manifest(s)" in r.stdout
