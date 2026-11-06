"""v1.3.94 — unit tests for the three chip-AGNOSTIC plugin gaps a from-scratch
clean rebuild of the commercial-PDK `spm` sign-off EXPOSED (stale in-tree state
had been masking them):

  * Fix A — eda_report_audit `_is_backup_path`: an in-tree `_known_good_
            snapshot_*/` (or `*_prebuild_bak/`) copy of a design's reports must
            be EXCLUDED from the recursive report scan, else its STALE netgen
            mismatch / pre-repair antenna stub flips the live verdict.

All pure-Python / deterministic (no pya, no container, no oracle).
"""
import importlib
from pathlib import Path

audit = importlib.import_module("eda_report_audit")


# --- Fix A: backup/snapshot dir exclusion ---------------------------------
_ROOT = Path("/proj")


def test_snapshot_dir_is_backup():
    assert audit._is_backup_path(
        _ROOT / "_known_good_snapshot_v1393/reports_phase3/lvs.rpt", _ROOT)


def test_snapshots_plural_dir_is_backup():
    assert audit._is_backup_path(_ROOT / "snapshots/x.rpt", _ROOT)


def test_prebuild_bak_dir_is_backup():
    assert audit._is_backup_path(
        _ROOT / "commercial_pdk_prebuild_bak/reports/lvs.rpt", _ROOT)


def test_live_report_tree_is_not_backup():
    assert not audit._is_backup_path(_ROOT / "reports/phase3/lvs.rpt", _ROOT)


def test_legit_golden_name_is_not_backup():
    # 'golden' / 'snapshotting' substrings must NOT trip the boundary-aware
    # token (only a whole snapshot/snap/bak component does).
    assert not audit._is_backup_path(_ROOT / "golden/reports/lvs.rpt", _ROOT)






















# --- lvs_tapeout_signoff_check: prefer canonical, skip snapshot -----------
lts = importlib.import_module("lvs_tapeout_signoff_check")


def test_find_report_prefers_canonical_over_snapshot(tmp_path):
    # canonical lvs.rpt (klayout MATCH) must win over an in-tree snapshot copy
    # (stale netgen mismatch), which sorts FIRST alphabetically ('_' < 'r').
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    canon = tmp_path / "reports" / "phase3" / "lvs.rpt"
    canon.write_text("Final result: Circuits match uniquely.\n")
    snap = tmp_path / "_known_good_snapshot_v1" / "reports_phase3"
    snap.mkdir(parents=True)
    (snap / "lvs.rpt").write_text("Final result: failed pin matching.\n")
    found = lts._find_report(tmp_path)
    assert found == canon


def test_find_report_excludes_snapshot_when_no_canonical(tmp_path):
    # with no canonical report, a snapshot-only lvs.rpt is EXCLUDED (returns
    # None), never silently consumed as the sign-off report.
    snap = tmp_path / "_known_good_snapshot_v1" / "reports_phase3"
    snap.mkdir(parents=True)
    (snap / "lvs.rpt").write_text("Final result: failed pin matching.\n")
    assert lts._find_report(tmp_path) is None
