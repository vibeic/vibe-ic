"""The audit could READ a KLayout report database and could not FIND one.

MEASURED, gf180mcuD chip-path campaign 2026-08-21. `spm` passed the shuttle
operator's own container 16/16 with `DRC RESULT: SUCCESS (0 violations)`. OUR
precheck arm refused the same GDS with:

    Checker.KLayoutDRC   FAIL   drc_report_check refused:
                                "No DRC report found (searched *drc*.rpt/log/txt)"

with `drc.klayout.lyrdb` sitting in the project the whole time.

`eda_report_audit._drc_real_violation_count` lists "klayout RDB/.lyrdb XML" as
its FIRST accepted dialect and `_count_rdb_items_streaming` parses it. The
discovery glob accepted `.rpt`, `.log` and `.txt` — not `.lyrdb`, which is the
extension KLayout actually writes. So the documented format was unreachable
through the program's own file discovery, and the only way one ever got audited
was if a caller renamed it first.

WHY THIS MATTERS MORE THAN A MISSING GLOB. Since v1.11.18 step 37.5ic runs TWO
arms over the same layout, and `tapeout_precheck` treats OPPOSITE CONCLUSIVE
verdicts from the two arms as a DISAGREEMENT that FAILS the step — "one of the
two checks is wrong" being the most valuable thing it can tell you. A discovery
gap on our side manufactures exactly that signal out of nothing: their ladder
passes, ours reports "no report found", and the step refuses a clean chip while
pointing at the layout instead of at the glob.

Selection of the parser is by CONTENT, not extension, so widening the glob
cannot mis-parse anything: a file that is not a report database still returns
None and is reported unreadable.
"""
import sys
import textwrap
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import eda_report_audit as A  # noqa: E402


#: A real KLayout DRC report database, reduced to its structure. Built from the
#: shape the gf180mcuD run actually emitted (`<generator>` naming the deck,
#: `<top-cell>`, and an `<items>` list) rather than invented — my first draft
#: hand-wrote the indentation and the DIRTY variant silently came out identical
#: to the CLEAN one, so the "still refuses" test was passing on a clean file.
_CLEAN_RDB = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<report-database>\n'
    ' <description>Report for V1.2a</description>\n'
    " <generator>drc: script='/pdk/libs.tech/klayout/tech/drc/some.drc'</generator>\n"
    ' <top-cell>chip_top</top-cell>\n'
    ' <categories>\n'
    '  <category><name>V1.2a</name><description>min. via1 spacing</description></category>\n'
    ' </categories>\n'
    ' <items>\n </items>\n'
    '</report-database>\n'
)

_DIRTY_RDB = _CLEAN_RDB.replace(
    ' <items>\n </items>\n',
    ' <items>\n'
    '  <item><category>V1.2a</category><cell>chip_top</cell></item>\n'
    '  <item><category>V1.2a</category><cell>chip_top</cell></item>\n'
    ' </items>\n', 1)
assert _DIRTY_RDB != _CLEAN_RDB, "the dirty fixture must actually differ"


def _project(tmp_path, name, body):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)
    return tmp_path


def test_the_parser_could_always_read_a_report_database():
    """CONTROL: the reading half was never the problem, so a failure below is
    about discovery and nothing else."""
    assert A._drc_real_violation_count(_CLEAN_RDB) == (0, 0)
    got = A._drc_real_violation_count(_DIRTY_RDB)
    assert got is not None and got[0] == 2, got


def test_a_klayout_report_database_is_DISCOVERED(tmp_path):
    """THE DEFECT: `.lyrdb` is what KLayout writes, and the glob excluded it."""
    proj = _project(tmp_path, "drc.klayout.lyrdb", _CLEAN_RDB)
    res = A._check_drc(proj)
    found = res.summary.get("files_found") if hasattr(res, "summary") else None
    assert found == 1, (
        "a KLayout report database in the project was not discovered, so a "
        "clean DRC reads as 'No DRC report found' — measured on a real chip "
        f"that the shuttle operator's own container passed 16/16 (files_found={found})"
    )


def test_a_discovered_clean_database_reports_zero_violations(tmp_path):
    proj = _project(tmp_path, "drc.klayout.lyrdb", _CLEAN_RDB)
    res = A._check_drc(proj)
    assert res.summary.get("determined_files") == 1, res.summary
    assert res.summary.get("real_violation_total") == 0, res.summary


def test_a_discovered_DIRTY_database_still_refuses(tmp_path):
    """NEGATIVE NO-LEAK (§4.05). Widening a glob is a relaxation of what the
    gate will look at, so the load-bearing proof is that a report with REAL
    violations, discovered by the SAME widened glob, is still caught."""
    proj = _project(tmp_path, "drc.klayout.lyrdb", _DIRTY_RDB)
    res = A._check_drc(proj)
    assert res.summary.get("files_found") == 1
    assert res.summary.get("real_violation_total") == 2, res.summary
    assert res.passed is False, "a dirty report database was waved through"


def test_an_unparseable_lyrdb_is_reported_unreadable_not_clean(tmp_path):
    """NEGATIVE NO-LEAK, second direction: a file the parser cannot read must
    not become a zero. UNMEASURED IS NOT ZERO."""
    proj = _project(tmp_path, "drc.klayout.lyrdb", "this is not a report database")
    res = A._check_drc(proj)
    assert res.passed is False
    assert res.summary.get("real_violation_total") != 0 or \
        res.summary.get("unreadable_files", 0) >= 1, res.summary


def test_antenna_discovery_takes_lyrdb_too(tmp_path):
    """KLayout's antenna check writes `antenna.klayout.lyrdb` beside its .json,
    and the .lyrdb is the one carrying the per-rule item list."""
    proj = _project(tmp_path, "antenna.klayout.lyrdb", _CLEAN_RDB)
    res = A._check_antenna(proj)
    assert res.summary.get("files_found", 0) >= 1, res.summary


def test_the_old_extensions_still_work(tmp_path):
    """CONTROL: widening must not narrow. A .rpt is still found."""
    proj = _project(tmp_path, "drc_signoff.rpt", "total violations: 0\n")
    res = A._check_drc(proj)
    assert res.summary.get("files_found", 0) >= 1
