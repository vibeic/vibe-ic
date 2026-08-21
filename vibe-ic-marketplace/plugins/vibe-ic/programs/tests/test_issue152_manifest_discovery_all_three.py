"""ORGANIC #152 — the two version tools must each touch ALL THREE version-bearing
manifests (plugin.json + the NESTED and the REPO-ROOT marketplace.json), via ONE
shared discovery, with a post-write self-check.

Historically each tool missed a DIFFERENT manifest:
  * gatekeeper_assign_version.py --write   → bumped plugin.json + NESTED, missed ROOT
  * marketplace_version_sync_check.py --fix → bumped ROOT, missed NESTED (v1.4.17)

Both marketplace.json live at ANCESTOR dirs of the plugin root, so a single
UPWARD walk from the plugin root (plugin_manifest_discovery) finds both — cwd- and
direction-independent. chip-AGNOSTIC: pure semver + JSON, synthetic tree.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import gatekeeper_assign_version as G          # noqa: E402
import plugin_manifest_discovery as PMD        # noqa: E402

_SYNC = PROGRAMS / "marketplace_version_sync_check.py"
_ASSIGN = PROGRAMS / "gatekeeper_assign_version.py"


def _make_dual_tree(tmp_path, plugin="1.4.28", nested=None, root=None):
    """A tree mirroring the real repo: a REPO-ROOT manifest AND a NESTED
    maintained manifest, both referencing the SAME plugin.json."""
    nested = plugin if nested is None else nested
    root = plugin if root is None else root
    repo = tmp_path / "repo"
    plugin_root = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": plugin,
                    "description": "x"}, indent=2) + "\n")
    nd = repo / "vibe-ic-marketplace" / ".claude-plugin"
    nd.mkdir(parents=True)
    (nd / "marketplace.json").write_text(json.dumps(
        {"name": "vibe-ic-marketplace",
         "plugins": [{"name": "vibe-ic", "version": nested,
                      "source": "./plugins/vibe-ic"}]}, indent=2) + "\n")
    rd = repo / ".claude-plugin"
    rd.mkdir(parents=True)
    (rd / "marketplace.json").write_text(json.dumps(
        {"name": "vibe-ic-marketplace",
         "plugins": [{"name": "vibe-ic", "version": root,
                      "source": "./vibe-ic-marketplace/plugins/vibe-ic"}]},
        indent=2) + "\n")
    return repo, plugin_root


def _read_all(plugin_root, repo):
    pv = json.loads((plugin_root / ".claude-plugin" / "plugin.json")
                    .read_text())["version"]

    def mv(p):
        d = json.loads(p.read_text())
        return next(e["version"] for e in d["plugins"] if e["name"] == "vibe-ic")
    nested = mv(repo / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json")
    root = mv(repo / ".claude-plugin" / "marketplace.json")
    return pv, nested, root


# ── shared discovery finds BOTH manifests ────────────────────────────────────

def test_discovery_finds_both_manifests(tmp_path):
    repo, plugin_root = _make_dual_tree(tmp_path, "1.4.28")
    _pj, mkts = PMD.find_plugin_and_manifests(plugin_root)
    assert len(mkts) == 2, [str(m) for m in mkts]
    names = {m.parent.parent.name for m in mkts}   # 'repo' (root) + 'vibe-ic-marketplace'
    assert "vibe-ic-marketplace" in names
    assert "repo" in names


# ── gatekeeper_assign_version --write bumps ALL THREE (the #152 core fix) ─────

def test_assign_write_bumps_all_three(tmp_path):
    repo, plugin_root = _make_dual_tree(tmp_path, "1.4.28")
    report, rc = G.assign(repo, None, write=True)
    assert rc == 0, report
    assert report["assigned"] == "1.4.29"
    assert len(report["wrote"]) == 3            # plugin.json + nested + root
    assert _read_all(plugin_root, repo) == ("1.4.29", "1.4.29", "1.4.29")


def test_assign_write_repairs_a_root_that_started_stale(tmp_path):
    """The exact v1.4.28 field report: plugin+nested at N, root stale at N-1 →
    the bump must land N+1 on ALL THREE (the old code left root at N-1)."""
    repo, plugin_root = _make_dual_tree(
        tmp_path, plugin="1.4.28", nested="1.4.28", root="1.4.27")
    report, rc = G.assign(repo, None, write=True)
    assert rc == 0
    assert _read_all(plugin_root, repo) == ("1.4.29", "1.4.29", "1.4.29")


def test_assign_endstate_program_writes_all_three(tmp_path):
    repo, plugin_root = _make_dual_tree(tmp_path, "1.4.28")
    r = subprocess.run(
        [sys.executable, str(_ASSIGN), "--repo", str(repo), "--write"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _read_all(plugin_root, repo) == ("1.4.29", "1.4.29", "1.4.29")


# ── sync-check --fix from the REPO ROOT repairs the NESTED (v1.4.17 blind spot) ─

def test_sync_fix_from_repo_root_repairs_nested(tmp_path):
    repo, plugin_root = _make_dual_tree(
        tmp_path, plugin="1.4.29", nested="1.4.28", root="1.4.29")
    r = subprocess.run(
        [sys.executable, str(_SYNC), "--marketplace-dir", str(repo), "--fix"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _read_all(plugin_root, repo) == ("1.4.29", "1.4.29", "1.4.29")


def test_sync_check_from_repo_root_sees_nested_drift(tmp_path):
    """Even with cwd/primary at the repo ROOT, the NESTED manifest's drift is
    now DETECTED (the union discovery), not silently blind."""
    repo, _ = _make_dual_tree(
        tmp_path, plugin="1.4.29", nested="1.4.28", root="1.4.29")
    r = subprocess.run(
        [sys.executable, str(_SYNC), "--marketplace-dir", str(repo)],
        capture_output=True, text=True)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "1.4.28" in r.stdout


# ── the post-write self-check catches residual drift ─────────────────────────

def test_verify_synced_detects_stale_manifest(tmp_path):
    repo, plugin_root = _make_dual_tree(
        tmp_path, plugin="1.4.29", nested="1.4.29", root="1.4.28")
    ok, drift = PMD.verify_synced(plugin_root)
    assert ok is False
    assert any("marketplace.json" in p and found == "1.4.28"
               for p, found, _want in drift)


def test_verify_synced_clean_when_all_match(tmp_path):
    repo, plugin_root = _make_dual_tree(tmp_path, "1.4.29")
    ok, drift = PMD.verify_synced(plugin_root)
    assert ok is True and drift == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
