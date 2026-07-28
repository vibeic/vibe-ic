#!/usr/bin/env python3
"""A PASS with no denominator cannot be told apart from a PASS that scanned
NOTHING.

Found by a routine sweep, not by a report: every gate wired into
`tools/ci/repo_hygiene_gates.sh` was run against an EMPTY git repository to see
which of them answer PASS. `source_chip_agnostic_check` did — and its output
was **byte-identical** to the output of a real scan over 1239 files:

    PASS: no forbidden chip / vendor / SKU tokens in plugin source (programs/ skills/ commands/)

Neither a reader nor CI could tell "clean" from "looked at nothing". That
matters here more than most places: this is the gate that keeps chip / vendor /
SKU literals out of plugin source, and "looked at nothing" is exactly what a
WRONG ROOT produces.

THE REPO HAS NOW HIT THIS DEFECT IN FOUR SEPARATE PROGRAMS, which is why the
fix is a denominator rather than a one-off:
  * `nda_tracked_tree_scan` PASSed on 21 of 20143 blobs (a cwd prefix shift)
  * `l4_systemrdl_export` audit-corpus found 0 of 201 documents and reported
    PASS (a skip-set matched against the absolute path)
  * `cross_layer_reference_check` walked 46 cells in a checkout and 23 in a
    worktree, making a COUNT-based baseline host-dependent
  * this one

So: the PASS line carries the number of files actually READ, and a scan that
read ZERO is not a PASS at all — it exits 2 and names the per-directory counts
so the cause (wrong root / missing subtree) is visible without a second run.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import source_chip_agnostic_check as C  # noqa: E402

_PLUGIN_ROOT = _PROGRAMS.parent


def _run(root: Path):
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "source_chip_agnostic_check.py"),
         str(root)],
        capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout + r.stderr)


def test_a_real_scan_reports_how_many_files_it_read():
    """THE LOAD-BEARING HALF: the verdict must carry its denominator."""
    rc, out = _run(_PLUGIN_ROOT)
    assert rc == 0, out
    assert "PASS" in out
    assert "file(s) scanned" in out, out
    # and the number must be a real one, not a placeholder
    import re
    m = re.search(r"PASS \((\d+) file\(s\) scanned\)", out)
    assert m and int(m.group(1)) > 100, out


def test_scanning_zero_files_is_NOT_a_pass(tmp_path):
    """An empty tree used to produce the same sentence as a 1239-file scan."""
    (tmp_path / "programs").mkdir()
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOTHING_SCANNED" in out, out
    assert "PASS" not in out.split("NOTHING_SCANNED")[0], out


def test_the_zero_scan_message_names_the_per_directory_counts(tmp_path):
    """So the CAUSE is visible without a second run: a missing subtree reads
    -1, an empty one reads 0, and those are different mistakes."""
    (tmp_path / "programs").mkdir()
    rc, out = _run(tmp_path)
    assert "dir_programs=0" in out, out
    assert "dir_skills=-1" in out, out


def test_a_real_and_an_empty_scan_are_no_longer_byte_identical(tmp_path):
    """The defect, stated as a property. This is what the sweep actually
    measured, and it is the thing that must never come back."""
    (tmp_path / "programs").mkdir()
    _, empty_out = _run(tmp_path)
    _, real_out = _run(_PLUGIN_ROOT)
    assert empty_out.strip() != real_out.strip()


def test_the_census_is_populated_by_audit_itself():
    """The count comes from the walk, not from a second traversal that could
    disagree with it."""
    verdict, findings = C.audit(_PLUGIN_ROOT)
    assert C.SCAN_CENSUS.get("files_read", 0) > 100, C.SCAN_CENSUS
    assert C.SCAN_CENSUS["files_read"] <= C.SCAN_CENSUS["files_found"]


def test_the_census_is_reset_between_calls(tmp_path):
    """A stale census from a previous call would let an empty scan inherit a
    healthy denominator — the exact false certificate this closes."""
    C.audit(_PLUGIN_ROOT)
    (tmp_path / "programs").mkdir()
    C.audit(tmp_path)
    assert C.SCAN_CENSUS.get("files_read", 0) == 0, C.SCAN_CENSUS


def test_a_genuine_violation_is_still_reported(tmp_path):
    """The paired half that keeps this from being a way to disable the gate:
    a forbidden token in a scanned file must still FAIL."""
    d = tmp_path / "programs"
    d.mkdir()
    tok = sorted(C._FORBIDDEN_TOKENS)[0]
    (d / "leaky.py").write_text(f'PDK = "{tok}"\n')
    rc, out = _run(tmp_path)
    assert rc == 1, out
