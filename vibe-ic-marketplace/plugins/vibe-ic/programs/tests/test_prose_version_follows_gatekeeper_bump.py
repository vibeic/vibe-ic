#!/usr/bin/env python3
"""The version bump must carry the PROSE with it, not just the JSON.

WHY
===
`plugin_version_prose_sync_check` (#621) shipped with a working `--fix` and
nothing ever called it. The repo referenced the checker from the hygiene gate
(audit only), its own test, and INDEX.md — never from the release path. So
`gatekeeper_assign_version --write`, the ONE writer of the version, advanced
plugin.json and every marketplace.json and left the three READMEs a reader meets
first exactly where they were. Measured on the tree that prompted this fix: the
READMEs stated 1.10.2 against a shipped 1.10.29 — the gate had been reporting a
true failure for 28 consecutive releases, and no step in the release path could
ever have cleared it. Correcting the five numbers by hand resets the counter and
changes nothing; the next bump re-opens the same gap.

These tests pin the BEHAVIOUR that closes it: after a `--write` bump, the prose
states the version that was just written. They assert on returned values, exit
codes and emitted JSON — never on the text of any source file, because a test
that greps the implementation passes for a program that does nothing.

chip-AGNOSTIC: synthetic trees and pure semver strings; no design, PDK or part
number anywhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import gatekeeper_assign_version as G          # noqa: E402
import plugin_version_prose_sync_check as P    # noqa: E402

_ASSIGN = PROGRAMS / "gatekeeper_assign_version.py"


# ── fixtures ──────────────────────────────────────────────────────────────────
def _make_repo(tmp_path: Path, version: str, *, prose: bool = True) -> Path:
    """A synthetic repo mirroring the real layout: repo-root marketplace.json +
    nested marketplace.json + plugin.json, and (optionally) the three prose sites
    stating `version` in each of the forms the checker recognises."""
    plugin_root = tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": version, "description": "x"},
                   indent=2) + "\n")

    nested = tmp_path / "vibe-ic-marketplace" / ".claude-plugin"
    nested.mkdir(parents=True)
    nested.joinpath("marketplace.json").write_text(json.dumps(
        {"name": "vibe-ic-marketplace",
         "plugins": [{"name": "vibe-ic", "version": version,
                      "source": "./plugins/vibe-ic"}]}, indent=2) + "\n")

    root_mkt = tmp_path / ".claude-plugin"
    root_mkt.mkdir(parents=True)
    root_mkt.joinpath("marketplace.json").write_text(json.dumps(
        {"name": "vibe-ic-marketplace",
         "plugins": [{"name": "vibe-ic", "version": version,
                      "source": "./vibe-ic-marketplace/plugins/vibe-ic"}]},
        indent=2) + "\n")

    if prose:
        mm = ".".join(version.split(".")[:2])
        (tmp_path / "README.md").write_text(
            f"# repo\n\n"
            f"[![Plugin v{version}](https://img.shields.io/badge/"
            f"plugin-v{version}-brightgreen.svg)](x)\n"
            f"[![MCP-EDA v1.0.0](https://img.shields.io/badge/"
            f"mcp--eda-v1.0.0-brightgreen.svg)](y)\n\n"
            f"> **Status: v{mm} — mature.**\n")
        (tmp_path / "vibe-ic-marketplace" / "README.md").write_text(
            f"# marketplace\n\n"
            f"| | |\n|---|---|\n| Plugin version | **{version}** |\n\n"
            f"```\n    └── vibe-ic/   ← the single plugin (v{version})\n```\n")
        (plugin_root / "README.md").write_text(
            f"# vibe-ic — AI-Native IC Design plugin (**v{version}**)\n")
    return tmp_path


def _prose_stats(repo: Path) -> dict:
    """What the checker's own audit measured on `repo`."""
    _verdict, _findings, stats = P.audit(repo)
    return stats


# ── the regression ────────────────────────────────────────────────────────────
def test_write_bump_carries_prose_to_the_new_version(tmp_path):
    """The defect, directly: bump and the READMEs must state the NEW version."""
    repo = _make_repo(tmp_path, "1.10.2")

    # control: before the bump the prose agrees with the shipped 1.10.2
    verdict, findings, stats = P.audit(repo)
    assert verdict == "PASS", findings
    assert stats["claims_compared"] == 6, stats
    assert stats["shipped_version"] == "1.10.2"

    report, rc = G.assign(repo, None, write=True)
    assert rc == 0, report
    assert report["assigned"] == "1.10.3"

    # the prose followed the bump — checked through the gate's own audit, which
    # re-derives the shipped version from the manifest independently
    verdict, findings, stats = P.audit(repo)
    assert verdict == "PASS", findings
    assert stats["shipped_version"] == "1.10.3"
    assert stats["claims_compared"] == 6, stats
    assert stats["sites_scanned"] == 3, stats


def test_bumped_prose_files_are_reported_as_written(tmp_path):
    """`wrote` must name the prose files too — a silent rewrite is not evidence."""
    repo = _make_repo(tmp_path, "1.10.2")
    report, rc = G.assign(repo, None, write=True)
    assert rc == 0, report
    wrote = {Path(p).resolve() for p in report["wrote"]}
    for rel in ("README.md",
                "vibe-ic-marketplace/README.md",
                "vibe-ic-marketplace/plugins/vibe-ic/README.md"):
        assert (repo / rel).resolve() in wrote, (rel, report["wrote"])


def test_minor_rollover_carries_the_minor_only_claim(tmp_path):
    """`Status: vX.Y` asserts major.minor; a rollover must move it too."""
    repo = _make_repo(tmp_path, "1.10.99")
    report, rc = G.assign(repo, None, write=True)
    assert rc == 0, report
    assert report["assigned"] == "1.11.0"
    verdict, findings, stats = P.audit(repo)
    assert verdict == "PASS", findings
    assert stats["claims_compared"] == 6, stats


def test_dry_run_leaves_prose_untouched(tmp_path):
    """No --write, no rewrite — the dry-run must stay a dry-run."""
    repo = _make_repo(tmp_path, "1.10.2")
    before = (repo / "README.md").read_text()
    report, rc = G.assign(repo, None, write=False)
    assert rc == 0 and report["wrote"] == []
    assert (repo / "README.md").read_text() == before
    assert _prose_stats(repo)["shipped_version"] == "1.10.2"


def test_tree_without_prose_sites_still_bumps(tmp_path):
    """A checkout that states the version in no prose is not an error."""
    repo = _make_repo(tmp_path, "1.10.2", prose=False)
    report, rc = G.assign(repo, None, write=True)
    assert rc == 0, report
    assert report["assigned"] == "1.10.3"
    # only the JSON manifests were written
    assert all(Path(p).name in ("plugin.json", "marketplace.json")
               for p in report["wrote"]), report["wrote"]


def test_unwritable_prose_fails_the_merge_rather_than_shipping_drift(tmp_path):
    """The post-write self-check must FAIL LOUDLY, not ship a stale README."""
    repo = _make_repo(tmp_path, "1.10.2")
    victim = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "README.md"
    victim.chmod(0o444)
    try:
        report, rc = G.assign(repo, None, write=True)
    finally:
        victim.chmod(0o644)
    assert rc == 2, report
    assert "prose" in report.get("error", "").lower(), report


@pytest.mark.skipif(sys.platform == "win32", reason="posix perms")
def test_cli_end_to_end_emits_prose_files_in_json(tmp_path):
    """Exit code + emitted JSON only — the CLI is what the gatekeeper runs."""
    repo = _make_repo(tmp_path, "1.10.2")
    out = tmp_path / "assign.json"
    proc = subprocess.run(
        [sys.executable, str(_ASSIGN), "--repo", str(repo), "--write",
         "--json", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    rep = json.loads(out.read_text())
    assert rep["assigned"] == "1.10.3"
    names = {Path(p).name for p in rep["wrote"]}
    assert "README.md" in names, rep["wrote"]

    # and the gate the repo actually runs now passes on that tree
    gate = subprocess.run(
        [sys.executable,
         str(PROGRAMS / "plugin_version_prose_sync_check.py"), str(repo)],
        capture_output=True, text=True)
    assert gate.returncode == 0, gate.stderr
