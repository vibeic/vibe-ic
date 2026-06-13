"""tests/test_migrate_to_canonical_taxonomy.py — v1.6.30

Closes the v1.6.27 zero-coverage gap. The migration tool moves files
across the canonical Phase/Stage/Step taxonomy. Without tests it is
unsafe to run on real benchmarks. These tests cover:

  1. Empty project: vacuous behaviour (no moves, no blocks)
  2. Top-level dir migration (fpga/ → phase2/stage1/fpga/)
  3. Top-level metadata file (extraction_patterns.json → phase1/)
  4. reports/<flat>/ subfolder taxonomy migration
  5. reports/<file> auto-routing
  6. Dry-run mode does not touch the filesystem
  7. Idempotency: re-running does nothing once migrated
  8. Resume: partially migrated + extra stray entries → second pass cleans
  9. Identical-content destination collision → drop redundant src
 10. Real conflict (different content same dst) → blocked + src preserved
 11. Dir merge with conflicts: non-conflicting files move; conflicts
     remain at src/ and are reported as blocked.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from programs.migrate_to_canonical_taxonomy import (
    migrate, _safe_move_dir, _safe_move_file,
)


# ----- helpers -----

def _make_project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir()
    return p


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ----- tests -----

def test_empty_project_no_moves(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    res = migrate(p, dry_run=False)
    assert res.moves == []
    assert res.blocked == []


def test_toplevel_dir_migration_fpga(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    _write(p / "fpga" / "output_files" / "top.sof", "binary")
    res = migrate(p, dry_run=False)
    # source gone, destination populated
    assert not (p / "fpga").exists()
    assert (p / "phase2" / "stage1" / "fpga" / "output_files" / "top.sof").is_file()
    assert any(m.src == "fpga/" for m in res.moves)


def test_toplevel_metadata_file_routes_to_phase1(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    (p / "extraction_patterns.json").write_text("{}")
    res = migrate(p, dry_run=False)
    assert not (p / "extraction_patterns.json").exists()
    assert (p / "phase1" / "extraction_patterns.json").is_file()
    assert any(m.kind == "file" and m.src == "extraction_patterns.json"
               for m in res.moves)


def test_reports_flat_subdir_to_phase_parent(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    _write(p / "reports" / "lint" / "lint.rpt", "PASS")
    res = migrate(p, dry_run=False)
    assert not (p / "reports" / "lint").exists()
    assert (p / "reports" / "phase2" / "lint" / "lint.rpt").is_file()
    assert any(m.dst.startswith("reports/phase2/lint")
               for m in res.moves)


def test_reports_unknown_subdir_defaults_to_audit(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    _write(p / "reports" / "weird_thing" / "x.txt", "y")
    res = migrate(p, dry_run=False)
    assert (p / "reports" / "audit" / "weird_thing" / "x.txt").is_file()


def test_reports_flat_file_auto_routed(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    _write(p / "reports" / "compliance_verdict.txt", "Overall: PASS")
    res = migrate(p, dry_run=False)
    assert not (p / "reports" / "compliance_verdict.txt").exists()
    # Whatever bucket _pl.report_path() picks, it must NOT be reports/ root.
    assert any(m.kind == "file" and m.src == "reports/compliance_verdict.txt"
               for m in res.moves)


def test_dry_run_does_not_modify_filesystem(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    _write(p / "fpga" / "x.sof", "z")
    _write(p / "extraction_patterns.json", "{}")
    res = migrate(p, dry_run=True)
    # Sources still exist
    assert (p / "fpga" / "x.sof").is_file()
    assert (p / "extraction_patterns.json").is_file()
    # Plans were captured
    assert len(res.moves) >= 2


def test_idempotent_after_clean_run(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    _write(p / "fpga" / "x.sof", "z")
    _write(p / "extraction_patterns.json", "{}")
    _write(p / "reports" / "lint" / "x.rpt", "PASS")
    first = migrate(p, dry_run=False)
    assert len(first.moves) >= 3
    second = migrate(p, dry_run=False)
    assert second.moves == []
    assert second.blocked == []


def test_resume_completes_partial_migration(tmp_path: Path) -> None:
    """Half the canonical layout already exists, half is still stray.
    A second migrate() run should pick up the leftover work and finish
    cleanly."""
    p = _make_project(tmp_path)
    # Already migrated
    _write(p / "phase1" / "extraction_patterns.json", "{}")
    # Still stray (added later)
    _write(p / "fpga" / "y.sof", "yy")
    _write(p / "reports" / "lint" / "lint.rpt", "PASS")
    res = migrate(p, dry_run=False)
    assert (p / "phase2" / "stage1" / "fpga" / "y.sof").is_file()
    assert (p / "reports" / "phase2" / "lint" / "lint.rpt").is_file()
    assert res.blocked == []  # nothing should block
    # Already-migrated metadata file untouched
    assert (p / "phase1" / "extraction_patterns.json").is_file()


def test_identical_content_collision_drops_redundant_src(tmp_path: Path) -> None:
    """If src and dst have identical bytes, the migration treats it as
    already-done (src removed, no block)."""
    p = _make_project(tmp_path)
    body = '{"already": "moved"}'
    _write(p / "extraction_patterns.json", body)
    _write(p / "phase1" / "extraction_patterns.json", body)
    res = migrate(p, dry_run=False)
    # src removed, dst preserved, no blocks
    assert not (p / "extraction_patterns.json").exists()
    assert (p / "phase1" / "extraction_patterns.json").read_text() == body
    assert res.blocked == []


def test_real_file_conflict_blocks_and_preserves_src(tmp_path: Path) -> None:
    """src and dst have DIFFERENT bytes — block, leave src intact for
    manual resolution."""
    p = _make_project(tmp_path)
    _write(p / "extraction_patterns.json", '{"version": 1}')
    _write(p / "phase1" / "extraction_patterns.json", '{"version": 2}')
    res = migrate(p, dry_run=False)
    # src preserved
    assert (p / "extraction_patterns.json").read_text() == '{"version": 1}'
    # dst preserved
    assert (p / "phase1" / "extraction_patterns.json").read_text() == \
        '{"version": 2}'
    assert len(res.blocked) == 1
    assert "destination exists" in res.blocked[0].note


def test_dir_merge_skips_conflicts_and_reports(tmp_path: Path) -> None:
    """When a dir merges into an existing destination dir, files whose
    targets already exist are LEFT at src and reported. Non-conflicting
    files do migrate."""
    p = _make_project(tmp_path)
    # src has two files; dst already has one of them with different content
    _write(p / "fpga" / "a.sof", "A_FROM_SRC")
    _write(p / "fpga" / "b.txt", "B_FROM_SRC")
    _write(p / "phase2" / "stage1" / "fpga" / "a.sof", "A_FROM_DST")
    res = migrate(p, dry_run=False)
    # Non-conflicting file moved
    assert (p / "phase2" / "stage1" / "fpga" / "b.txt").read_text() == \
        "B_FROM_SRC"
    # Conflicting file untouched at dst, still present at src
    assert (p / "phase2" / "stage1" / "fpga" / "a.sof").read_text() == \
        "A_FROM_DST"
    assert (p / "fpga" / "a.sof").read_text() == "A_FROM_SRC"
    # Reported as blocked, with skipped_files
    assert len(res.blocked) == 1
    assert "a.sof" in res.blocked[0].skipped_files


def test_safe_move_dir_dry_run_lists_conflicts(tmp_path: Path) -> None:
    """Dry-run on a dir merge previews the conflicts that would block."""
    p = _make_project(tmp_path)
    _write(p / "src" / "a.txt", "1")
    _write(p / "dst" / "a.txt", "2")
    err, skipped = _safe_move_dir(p / "src", p / "dst", dry_run=True)
    assert err is None
    assert skipped == ["a.txt"]
    # Filesystem unchanged
    assert (p / "src" / "a.txt").is_file()
    assert (p / "dst" / "a.txt").read_text() == "2"


def test_safe_move_file_idempotent_on_byte_identical(tmp_path: Path) -> None:
    """Helper-level test for the identical-content fast path."""
    p = _make_project(tmp_path)
    _write(p / "a.txt", "same")
    _write(p / "b.txt", "same")
    err = _safe_move_file(p / "a.txt", p / "b.txt", dry_run=False)
    assert err is None
    assert not (p / "a.txt").exists()
    assert (p / "b.txt").read_text() == "same"


def test_safe_move_file_blocks_on_real_collision(tmp_path: Path) -> None:
    p = _make_project(tmp_path)
    _write(p / "a.txt", "v1")
    _write(p / "b.txt", "v2")
    err = _safe_move_file(p / "a.txt", p / "b.txt", dry_run=False)
    assert err is not None
    assert (p / "a.txt").read_text() == "v1"
    assert (p / "b.txt").read_text() == "v2"
