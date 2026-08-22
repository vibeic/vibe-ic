"""The antenna audit knew one idiom, and it was the wrong tool's.

MEASURED, gf180mcuD chip path 2026-08-22. `spm` passed the shuttle operator's
own container 16/16, its antenna stage reporting `25 rules, 0 non-zero`. OUR
precheck arm could not reach a verdict on the same layout:

    antenna_report_check <proj>
    passed: False
    {"files_found": 2, "violations": null, "clean": null, "tool_authentic": false}

`_check_antenna` knew exactly one idiom -- OpenROAD's `check_antennas`:

    found_re = r"Found\\s+(\\d+)\\s+(?:net|pin|antenna)\\s+violation"
    pair_re  = r"(\\d+)\\s+net\\s+violations?,?\\s+(\\d+)\\s+pin\\s+violations?"
    clean_re = r"antenna\\s+clean\\s*:\\s*(YES|NO|TRUE|FALSE)"

KLayout's antenna check -- which IS the antenna sign-off on gf180mcuD and on any
KLayout-deck PDK -- emits neither. It writes a per-rule tally
(`{"ANT.1": 0, "ANT.8": 0, ...}`) and a `<report-database>` whose violations are
`<item>` elements. So on those PDKs our arm returned `violations: null` while the
counterparty's arm passed, and step 37.5ic reads opposite conclusive verdicts
from its two arms as a DISAGREEMENT that FAILS the step.

The tool-signature list missed it for a second, independent reason: it carried
`gate-oxide` with a HYPHEN, and KLayout's rule descriptions say "gate oxide area"
with a SPACE.

THE DIRECTION THAT MATTERS: this helper returns None, never 0, whenever it
cannot conclude. A `{}` that became "clean" would credit a run that measured
nothing as a passing antenna sign-off.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import eda_report_audit as A  # noqa: E402

_RDB_CLEAN = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<report-database>\n'
    ' <description>Report for antenna_metaltop</description>\n'
    " <generator>drc: script='/pdk/libs.tech/klayout/tech/drc/some.drc'</generator>\n"
    ' <top-cell>chip_top</top-cell>\n'
    ' <categories>\n'
    '  <category><name>ANT.1</name><description>ANT.1: Maximum ratio of Poly2 '
    'perimeter area to related gate oxide area: 200</description></category>\n'
    ' </categories>\n'
    ' <items>\n </items>\n'
    '</report-database>\n'
)
_RDB_DIRTY = _RDB_CLEAN.replace(
    ' <items>\n </items>\n',
    ' <items>\n  <item><category>ANT.8</category></item>\n </items>\n', 1)
assert _RDB_DIRTY != _RDB_CLEAN

_TALLY_CLEAN = json.dumps({"ANT.1": 0, "ANT.8": 0, "ANT.16_i_ANT.2": 0}, indent=1)
_TALLY_DIRTY = json.dumps({"ANT.1": 0, "ANT.8": 3, "ANT.16_i_ANT.2": 0}, indent=1)


# ---------------------------------------------------------------- the dialects
def test_the_per_rule_tally_is_counted():
    assert A._antenna_klayout_count(_TALLY_CLEAN) == 0
    assert A._antenna_klayout_count(_TALLY_DIRTY) == 3


def test_the_report_database_is_counted():
    assert A._antenna_klayout_count(_RDB_CLEAN) == 0
    assert A._antenna_klayout_count(_RDB_DIRTY) == 1


def test_klayout_antenna_output_carries_a_recognised_tool_signature():
    """Second, independent cause: the list said `gate-oxide` (hyphen) and
    KLayout writes "gate oxide area" (space), so a real report read as
    hand-typed."""
    ok, matched = A._has_tool_signature(_RDB_CLEAN, "antenna")
    assert ok, "a genuine KLayout antenna report carries no recognised signature"


# ------------------------------------------------- NEGATIVE / no-leak (4.05)
def test_NEGATIVE_an_empty_tally_is_UNDETERMINED_not_clean():
    """The load-bearing one. `{}` means the run measured nothing; crediting it
    as 0 would ship a passing antenna sign-off for a run that never looked."""
    assert A._antenna_klayout_count("{}") is None


def test_NEGATIVE_a_json_that_is_not_an_antenna_tally_is_UNDETERMINED():
    assert A._antenna_klayout_count('{"foo": 0, "bar": 1}') is None


def test_NEGATIVE_a_non_numeric_value_is_UNDETERMINED_not_zero():
    assert A._antenna_klayout_count('{"ANT.1": "clean"}') is None
    assert A._antenna_klayout_count('{"ANT.1": true}') is None


def test_NEGATIVE_a_non_antenna_report_database_is_UNDETERMINED():
    """A DRC report database must not be counted as an antenna verdict."""
    drc_rdb = _RDB_CLEAN.replace("Report for antenna_metaltop", "Report for V1.2a") \
                        .replace("ANT.1: Maximum ratio of Poly2 perimeter area to "
                                 "related gate oxide area: 200",
                                 "V1.2a : min. via1 spacing") \
                        .replace("<name>ANT.1</name>", "<name>V1.2a</name>")
    assert A._antenna_klayout_count(drc_rdb) is None


def test_NEGATIVE_prose_containing_the_word_ant_does_not_fire():
    assert A._antenna_klayout_count(
        '{"important": 0, "irrelevant": 2}') is None


# ------------------------------------------------------------- end to end
def _project(tmp_path, name, body):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)
    return tmp_path


def test_a_clean_klayout_antenna_project_PASSES(tmp_path):
    proj = _project(tmp_path, "antenna.klayout.lyrdb", _RDB_CLEAN)
    res = A._check_antenna(proj)
    assert res.summary.get("violations") == 0, res.summary
    assert res.passed is True, res.summary


def test_a_DIRTY_klayout_antenna_project_still_FAILS(tmp_path):
    proj = _project(tmp_path, "antenna.klayout.lyrdb", _RDB_DIRTY)
    res = A._check_antenna(proj)
    assert res.summary.get("violations") == 1, res.summary
    assert res.passed is False, "a report with a real antenna violation passed"


def test_an_empty_tally_project_does_not_PASS(tmp_path):
    proj = _project(tmp_path, "antenna.klayout.json", "{}")
    res = A._check_antenna(proj)
    assert res.passed is False, res.summary


def test_CONTROL_the_openroad_idiom_still_works(tmp_path):
    """Widening must not narrow: the idiom that already worked must keep working,
    and must still take precedence so the two never double-count."""
    proj = _project(tmp_path, "antenna.rpt",
                    "openroad check_antennas\n"
                    "Found 0 net violations.\nFound 0 pin violations.\n"
                    + "x" * 300)
    res = A._check_antenna(proj)
    assert res.summary.get("violations") == 0, res.summary
    proj2 = _project(tmp_path / "b", "antenna.rpt",
                     "openroad check_antennas\n"
                     "Found 4 net violations.\nFound 1 pin violations.\n"
                     + "x" * 300)
    res2 = A._check_antenna(proj2)
    assert res2.summary.get("violations") == 5, res2.summary
    assert res2.passed is False
