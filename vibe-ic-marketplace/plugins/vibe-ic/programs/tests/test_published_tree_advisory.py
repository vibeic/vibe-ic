#!/usr/bin/env python3
"""Regression for the caravel_user_project/v1.9.43_sky130A RESULT.md /
phase23_completion_audit.json same-day self-contradiction.

RESULT.md declared "CONVERGES ... clean PASS_WITH_WAIVERS with zero FAIL and
zero MISSING" while the SAME directory's committed
reports/audit/phase23_completion_audit.json (timestamped the same minute)
recorded verdict FAIL. Independent re-run confirmed the cell genuinely does
NOT converge (dft_atpg_coverage_check: measured stuck-at 89.59% < 95%
foundry floor, L20 un-extracted so the no-DFT waiver does not apply) — that
part is a real design gap, corrected in RESULT.md directly, not a plugin bug.

But re-running flow_compliance_check.py --strict against the COMMITTED
(published) tree also produced a second, unrelated distortion: Step 10
(pre-layout STA) and every step depending on it FAIL/MISSING because
`phase3/stage3/sta/pre_pnr_timing.rpt` does not exist in the published tree.
benchmark-data/PUBLISHING.md documents that phase3/stage3/* (PnR + extraction
working files) and *.log are deliberately excluded from what gets committed
so this is a false negative of RE-AUDITING A PUBLISHED TREE, not evidence
the run failed — measured identically on spm/v1.9.94_sky130A and
spm/v1.9.96_gf180mcuD, two independently converged reference cells whose OWN
committed phase23_completion_audit.json record PASS_WITH_WAIVERS.

This test pins `_published_tree_advisory` — a purely additive, informational
warning (changes no verdict, no count, no exit code) that fires when
project_dir structurally looks like a published benchmark-data cell
(GDS_MANIFEST present, phase3/stage3/ absent), so a future re-run's FAIL
against a published tree is never again mistaken for a live regression.

chip-AGNOSTIC: detection is two path-existence checks against generic
directory names PUBLISHING.md itself defines (phase3/stage4/gds/
GDS_MANIFEST.txt, phase3/stage3/); no IC / vendor / SKU literal appears.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402


def _make_manifest(root: Path) -> None:
    gds_dir = root / "phase3" / "stage4" / "gds"
    gds_dir.mkdir(parents=True, exist_ok=True)
    (gds_dir / "GDS_MANIFEST.txt").write_text(
        "user_project_wrapper.gds 92753582B sha256:" + "0" * 64 + "\n"
    )


def test_published_tree_with_manifest_and_no_stage3_fires(tmp_path):
    """The exact caravel/spm shape: manifest present, stage3 absent."""
    _make_manifest(tmp_path)
    note = F._published_tree_advisory(tmp_path)
    assert note is not None
    assert "PUBLISHED-TREE DETECTED" in note
    assert "PUBLISHING.md" in note
    assert "phase23_completion_audit.json" in note


def test_live_run_tree_with_stage3_present_is_silent(tmp_path):
    """A live run directory (or a published tree that DOES carry stage3, per
    PUBLISHING.md's "three hand-staged reference cells" carve-out) must NOT
    trigger the advisory — this stays silent for the common case the checker
    is actually meant to audit."""
    _make_manifest(tmp_path)
    (tmp_path / "phase3" / "stage3" / "sta").mkdir(parents=True)
    note = F._published_tree_advisory(tmp_path)
    assert note is None


def test_no_manifest_no_gds_stage_is_silent(tmp_path):
    """A fresh/incomplete run with no GDS yet must NOT be misclassified as a
    published tree just because it also lacks phase3/stage3/ (e.g. it has
    not reached PnR)."""
    note = F._published_tree_advisory(tmp_path)
    assert note is None


def test_stage3_absent_but_manifest_missing_is_silent(tmp_path):
    """phase3/stage3/ absent alone is not sufficient — GDS_MANIFEST.txt
    (the publish-time marker) must ALSO be present, or the heuristic could
    fire on a run that simply has not reached PnR yet."""
    (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
    note = F._published_tree_advisory(tmp_path)
    assert note is None


def test_advisory_is_informational_only_never_changes_exit_code(tmp_path):
    """§4.05 NO-LEAK: the advisory must be purely additive. A minimal
    published-tree-shaped project (no real flow artifacts) still exits
    non-zero exactly as it would without the manifest present — the
    advisory text changes, PASS/FAIL logic does not."""
    import subprocess

    prog = _PROGRAMS / "flow_compliance_check.py"

    r_without = subprocess.run(
        [sys.executable, str(prog), "--read-only", str(tmp_path)],
        capture_output=True, text=True,
    )

    _make_manifest(tmp_path)
    r_with = subprocess.run(
        [sys.executable, str(prog), "--read-only", str(tmp_path)],
        capture_output=True, text=True,
    )

    assert r_without.returncode == r_with.returncode
    assert "PUBLISHED-TREE DETECTED" not in r_without.stdout
    assert "PUBLISHED-TREE DETECTED" in r_with.stdout
