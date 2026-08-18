"""Owner directive 2026-06-17 — "field dont need to have version to issue pr.
all versions are given by gatekeeper".

`gatekeeper_assign_version.py` is the gatekeeper's merge-time version assignment:
two authoring PRs in flight that each self-bumped would COLLIDE (both pick
`x.y.(z+1)`); only the SERIALIZED gatekeeper, landing PRs one at a time onto an
advancing main, can assign a strictly-monotonic version. This pins:

  - the BINDING scheme arithmetic (patch 0..99; x.y.99 -> x.(y+1).0),
  - the x.y.0 MILESTONE -> FULL cadence flag,
  - --write applies the assigned version to BOTH plugin.json AND the canonical
    vibe-ic-marketplace/.claude-plugin/marketplace.json (sync invariant),
  - the dry-run writes NOTHING,
  - the real program end-state (subprocess returncode + stdout).

chip-AGNOSTIC: pure semver arithmetic over the plugin's own version files.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import gatekeeper_assign_version as G  # noqa: E402


# ── pure next-version arithmetic (BINDING scheme) ─────────────────────────────
@pytest.mark.parametrize("cur,expected", [
    ("1.1.6", "1.1.7"),
    ("1.1.0", "1.1.1"),
    ("1.1.98", "1.1.99"),
    ("1.1.99", "1.2.0"),     # patch段 99 -> minor+1, patch 歸 0
    ("1.0.99", "1.1.0"),
    ("2.3.99", "2.4.0"),
    ("0.9.99", "0.10.0"),
])
def test_next_version_scheme(cur, expected):
    assert G.next_version(cur) == expected


@pytest.mark.parametrize("bad", ["1.1", "", "abc", "1.x.0"])
def test_next_version_unparseable_is_none(bad):
    # genuinely-unparseable inputs. NB: the shared parse_semver intentionally
    # TOLERATES a leading 'v' (v1.1.6) and extra components (1.1.6.0) — those
    # are not in this set because next_version legitimately handles them.
    assert G.next_version(bad) is None


@pytest.mark.parametrize("ver,milestone", [
    ("1.1.0", True), ("1.2.0", True), ("2.0.0", True),
    ("1.1.7", False), ("1.1.99", False), ("0.10.0", True),
])
def test_is_milestone(ver, milestone):
    assert G.is_milestone(ver) is milestone


# ── synthetic plugin tree fixture (mirrors the real layout) ───────────────────
def _make_tree(tmp_path, version="1.1.6"):
    """repo/
         vibe-ic-marketplace/
           .claude-plugin/marketplace.json      (canonical — gates read THIS)
           plugins/vibe-ic/.claude-plugin/plugin.json
    """
    plugin_root = tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": version,
                    "description": "x"}, indent=2) + "\n")
    mkt_dir = tmp_path / "vibe-ic-marketplace" / ".claude-plugin"
    mkt_dir.mkdir(parents=True)
    (mkt_dir / "marketplace.json").write_text(
        json.dumps({"name": "vibe-ic-marketplace",
                    "plugins": [{"name": "vibe-ic", "version": version,
                                 "source": "./plugins/vibe-ic"}]}, indent=2) + "\n")
    return tmp_path, plugin_root


def _read_version(plugin_root):
    pj = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text())
    mj = json.loads((plugin_root.parent.parent / ".claude-plugin"
                     / "marketplace.json").read_text())
    mv = next(e["version"] for e in mj["plugins"] if e["name"] == "vibe-ic")
    return pj["version"], mv


def test_assign_dryrun_writes_nothing(tmp_path):
    repo, plugin_root = _make_tree(tmp_path, "1.1.6")
    report, rc = G.assign(repo, None, write=False)
    assert rc == 0
    assert report["assigned"] == "1.1.7"
    assert report["cadence"] == "TARGETED"
    assert report["milestone"] is False
    assert report["wrote"] == []
    # disk untouched
    assert _read_version(plugin_root) == ("1.1.6", "1.1.6")


def test_assign_write_bumps_both_files_in_sync(tmp_path):
    repo, plugin_root = _make_tree(tmp_path, "1.1.6")
    report, rc = G.assign(repo, None, write=True)
    assert rc == 0
    assert report["assigned"] == "1.1.7"
    assert len(report["wrote"]) == 2
    assert _read_version(plugin_root) == ("1.1.7", "1.1.7")


def test_assign_write_milestone_rollover_cadence_full(tmp_path):
    repo, plugin_root = _make_tree(tmp_path, "1.1.99")
    report, rc = G.assign(repo, None, write=True)
    assert rc == 0
    assert report["assigned"] == "1.2.0"
    assert report["milestone"] is True
    assert report["cadence"] == "FULL"
    assert _read_version(plugin_root) == ("1.2.0", "1.2.0")


def test_assign_from_version_override_ignores_disk(tmp_path):
    repo, plugin_root = _make_tree(tmp_path, "1.1.6")
    report, rc = G.assign(repo, "2.4.55", write=False)
    assert rc == 0
    assert report["from"] == "2.4.55"
    assert report["assigned"] == "2.4.56"


def test_assign_unparseable_current_errors_rc2(tmp_path):
    repo, _ = _make_tree(tmp_path, "1.1.6")
    report, rc = G.assign(repo, "not-a-version", write=False)
    assert rc == 2
    assert "unparseable" in report["error"]


# ── END-STATE: the real program over subprocess on the synthetic tree ─────────
def test_endstate_program_dryrun_prints_assignment(tmp_path):
    repo, _ = _make_tree(tmp_path, "1.1.6")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "gatekeeper_assign_version.py"),
         "--repo", str(repo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "1.1.6 -> 1.1.7" in r.stdout
    assert "patch/TARGETED" in r.stdout
    # dry-run: plugin.json unchanged on disk
    pj = json.loads((repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                     / ".claude-plugin" / "plugin.json").read_text())
    assert pj["version"] == "1.1.6"


def test_endstate_program_write_applies_and_emits_json(tmp_path):
    repo, plugin_root = _make_tree(tmp_path, "1.1.6")
    out_json = tmp_path / "assign.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "gatekeeper_assign_version.py"),
         "--repo", str(repo), "--write", "--json", str(out_json)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _read_version(plugin_root) == ("1.1.7", "1.1.7")
    rep = json.loads(out_json.read_text())
    assert rep["from"] == "1.1.6" and rep["assigned"] == "1.1.7"
    assert len(rep["wrote"]) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
