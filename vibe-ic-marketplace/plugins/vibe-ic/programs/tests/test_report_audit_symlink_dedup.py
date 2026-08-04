"""Regression: _discover must not count a report twice via its step symlink.

MEASURED DEFECT (sha256 x sky130A, plugin v1.9.76, round 11)
------------------------------------------------------------
The step runners publish each canonical report a SECOND time as a symlink
under ``steps/<phase>/<stage>/<step>/``.  ``_discover`` deduplicated on the
literal ``Path`` object, so the symlink and its target were two distinct keys
and BOTH survived — even though ``stat -L`` shows one inode and ``md5sum``
shows one file.  Every per-file quantity was then summed twice.

On the real run dir /home/reyerchu/_c_o_sha256_sky130A_run/g3:

    reports/phase3/drc_signoff.rpt                     inode 88639058
    steps/.../31_physical_verification.../drc_signoff.rpt -> same inode

    drc_report_check      real_violation_total = 22   <-- 11 counted twice
    tapeout_signoff_check violation count      = 11   <-- correct

i.e. two gates in the SAME run reported different counts for the same design.
The XML actually contains 11 ``<item>`` elements.

This does not flip the DRC verdict (any count > 0 is already an ERROR, and
0 * 2 == 0), so it is a REPORTING-accuracy defect, not a missed failure. It
is chip-AGNOSTIC: the symlink publication happens for every design and every
mode that eda_report_audit serves (drc/lvs/em/ir/sta/power).

Both directions are asserted below: the double-count fixture must collapse to
the true count, AND a genuinely distinct second report must still be counted
separately (so the fix cannot be "silently drop the second file").
"""
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).parent.parent
SCRIPT = PROGRAMS / 'eda_report_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(PROGRAMS))
import eda_report_audit as era  # noqa: E402


def _klayout_drc(n_items: int, top: str = "top") -> str:
    """A tool-authentic KLayout report database carrying exactly n_items."""
    items = "".join(
        """  <item>
   <category>'m5.1'</category>
   <cell>%s</cell>
   <values><value>edge-pair: (%d.0,1.0;%d.0,2.0)</value></values>
  </item>
""" % (top, i, i)
        for i in range(n_items)
    )
    return """<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>klayout DRC</description>
 <original-file>/foss/pdks/sky130A/libs.tech/klayout/drc/sky130A.lydrc</original-file>
 <top-cell>%s</top-cell>
 <categories><category><name>m5.1</name></category></categories>
 <items>
%s </items>
</report-database>
""" % (top, items)


def _audit(project: Path, out: Path):
    rc = subprocess.run(
        [sys.executable, str(PROGRAMS / 'drc_report_check.py'), str(project),
         '--mode', 'drc', '--json', str(out)],
        capture_output=True, text=True,
    )
    import json
    return rc, json.loads(out.read_text())['summary']


def test_step_symlink_is_not_counted_twice(tmp_path):
    """The canonical report + its step symlink are ONE physical file."""
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    step = tmp_path / 'steps/phase3/stage3/31_pv'
    step.mkdir(parents=True)

    rpt = tmp_path / 'reports/phase3/drc_signoff.rpt'
    rpt.write_text(_klayout_drc(3))
    (step / 'drc_signoff.rpt').symlink_to(rpt.resolve())   # what the runner publishes

    _, summary = _audit(tmp_path, tmp_path / 'out.json')

    assert summary['files_found'] == 1, (
        "the symlink and its target are one inode; discovering both double-counts "
        f"every per-file quantity (got files_found={summary['files_found']})"
    )
    assert summary['real_violation_total'] == 3, (
        "report carries 3 <item> elements; a path-keyed dedup reports 6 "
        f"(got {summary['real_violation_total']})"
    )


def test_genuinely_distinct_reports_are_still_counted_separately(tmp_path):
    """Negative control for the fix itself: two REAL files must stay two.

    Guards against 'fixing' the double-count by collapsing unrelated reports
    that merely share a basename.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    step = tmp_path / 'steps/phase3/stage3/31_pv'
    step.mkdir(parents=True)

    (tmp_path / 'reports/phase3/drc_signoff.rpt').write_text(_klayout_drc(3, "top_a"))
    (step / 'drc_signoff.rpt').write_text(_klayout_drc(4, "top_b"))  # real file, not a link

    _, summary = _audit(tmp_path, tmp_path / 'out.json')

    assert summary['files_found'] == 2, (
        f"two independent reports must both be audited (got {summary['files_found']})"
    )
    assert summary['real_violation_total'] == 7, (
        f"3 + 4 distinct violations must sum (got {summary['real_violation_total']})"
    )


def test_discover_keys_on_resolved_target(tmp_path):
    """Unit-level: _discover collapses a symlink onto its target."""
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    real = tmp_path / 'a' / 'x.rpt'
    real.write_text("klayout\n")
    (tmp_path / 'b' / 'x.rpt').symlink_to(real.resolve())

    found = era._discover(tmp_path, ['x.rpt'])
    assert len(found) == 1, f"symlink + target must collapse to one entry, got {found}"
