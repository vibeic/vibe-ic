"""Unit tests for self_audit_doc_claim_consistency_check.py.

After v1.6.48 the gate has a single rule: UNREPRODUCIBLE_BENCHMARK_PATH.
Every fenced markdown code block that quotes a `1st_benchmark_benchmark_a/<dir>/`
path must point at a directory that exists relative to the repo root.

Each test scaffolds a synthetic repo and runs the gate against the
plugin root.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import pytest

PROG = (Path(__file__).resolve().parent.parent / "self_audit_doc_claim_consistency_check.py")


def _stage_with_benchmark(tmp: Path, *,
                          benchmarks_present: list[str] | None = None,
                          fenced_paths: list[str] | None = None,
                          ) -> Path:
    """Stage a fixture with a benchmark tree (or none) and a CHANGELOG
    fenced block that quotes specific benchmark paths."""
    repo = tmp / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (repo / "vibe-ic-marketplace" / ".claude-plugin").mkdir(parents=True)

    if benchmarks_present:
        for sub in benchmarks_present:
            (repo / "1st_benchmark_benchmark_a" / sub).mkdir(parents=True)

    cl_lines = ["# Changelog\n", "\n```\n"]
    for fp in fenced_paths or []:
        cl_lines.append(f"$ run prog 1st_benchmark_benchmark_a/{fp}\n")
    cl_lines.append("```\n")
    (plugin / "CHANGELOG.md").write_text("".join(cl_lines))

    (plugin / ".claude-plugin" / "plugin.json").write_text('{}\n')
    (repo / "vibe-ic-marketplace" / ".claude-plugin"
     / "marketplace.json").write_text('{}\n')

    return plugin


def _run(plugin_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(plugin_root)],
        capture_output=True, text=True, timeout=10,
    )


# ---------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------

def test_help_works():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert "benchmark" in r.stdout.lower()


def test_invalid_path_returns_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 2


# ---------------------------------------------------------------
# UNREPRODUCIBLE_BENCHMARK_PATH rule
# ---------------------------------------------------------------

def test_benchmark_path_pass_when_dir_exists(tmp_path):
    plugin = _stage_with_benchmark(
        tmp_path,
        benchmarks_present=["phase2+3_v10634-vendor"],
        fenced_paths=["phase2+3_v10634-vendor/"])
    r = _run(plugin)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_benchmark_path_fail_when_dir_missing(tmp_path):
    """The exact v1.6.45 escape: CHANGELOG references phase2+3_v10634
    but only phase2+3_v10634-vendor exists."""
    plugin = _stage_with_benchmark(
        tmp_path,
        benchmarks_present=["phase2+3_v10634-vendor"],
        fenced_paths=["phase2+3_v10634/"])
    r = _run(plugin)
    assert r.returncode == 1
    assert "UNREPRODUCIBLE_BENCHMARK_PATH" in (r.stdout + r.stderr)


def test_benchmark_path_vacuous_when_tree_absent(tmp_path):
    """Fresh checkout (no 1st_benchmark_benchmark_a/ on disk): rule is
    inapplicable, gate VACUOUS_PASSes."""
    plugin = _stage_with_benchmark(
        tmp_path,
        benchmarks_present=None,
        fenced_paths=["phase2+3_v10634-vendor/",
                      "phase2+3_anything_at_all/"])
    r = _run(plugin)
    assert r.returncode == 0
    assert "VACUOUS_PASS" in r.stdout


def test_benchmark_prose_mention_ignored(tmp_path):
    """A phantom path mentioned in PROSE (outside fenced block) must
    not trigger the gate — authors legitimately discuss historical
    drifts in narrative form."""
    repo = tmp_path / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (repo / "vibe-ic-marketplace" / ".claude-plugin").mkdir(parents=True)
    (repo / "1st_benchmark_benchmark_a" / "phase2+3_v10634-vendor").mkdir(
        parents=True)
    (plugin / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "v1.6.45 quoted `1st_benchmark_benchmark_a/phase2+3_v10634/` "
        "claiming the `-vendor` variant didn't exist; v1.6.46 "
        "reverted.\n"
        "\n```\n$ x 1st_benchmark_benchmark_a/phase2+3_v10634-vendor/\n```\n")
    (plugin / ".claude-plugin" / "plugin.json").write_text('{}\n')
    (repo / "vibe-ic-marketplace" / ".claude-plugin"
     / "marketplace.json").write_text('{}\n')
    r = _run(plugin)
    assert r.returncode == 0


def test_benchmark_placeholder_ignored(tmp_path):
    """Placeholder tokens like <run-id>, *.json, ?.txt are not literal
    paths and must be skipped."""
    plugin = _stage_with_benchmark(
        tmp_path,
        benchmarks_present=["phase2+3_v10634"],
        fenced_paths=["phase2+3_<run-id>/", "phase2+3_*/", "phase2+3_v10634/"])
    r = _run(plugin)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_repo_doc_scan_picks_up_readme(tmp_path):
    """v1.6.48: README.md and docs/**/*.md are also scanned, not just
    CHANGELOG.md."""
    repo = tmp_path / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (repo / "vibe-ic-marketplace" / ".claude-plugin").mkdir(parents=True)
    (repo / "1st_benchmark_benchmark_a" / "phase2+3_real").mkdir(parents=True)
    (repo / "README.md").write_text(
        "# Project\n\n```\n$ run 1st_benchmark_benchmark_a/phase2+3_phantom/\n```\n")
    (plugin / "CHANGELOG.md").write_text("# CL\n")
    (plugin / ".claude-plugin" / "plugin.json").write_text('{}\n')
    (repo / "vibe-ic-marketplace" / ".claude-plugin"
     / "marketplace.json").write_text('{}\n')
    r = _run(plugin)
    assert r.returncode == 1
    assert "phase2+3_phantom" in (r.stdout + r.stderr)
