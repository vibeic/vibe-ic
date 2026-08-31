"""v1.14.6 — a COMPLETE KLayout report database is a stated violation count.

MEASURED CASE, spm x gf180mcuD, plugin v1.14.5, image sha256:fad41245fbff,
2026-08-31, reports/phase3/drc_signoff.rpt:

    <generator>drc: script='/foss/pdks/gf180mcuD/.../gf180mcu.drc'</generator>
    <top-cell>spm</top-cell>       763 <category> elements      <items></items>

KLayout does not print a prose violation count; it writes an item list, and an
empty one is KLayout SAYING zero. `drc_vacuous_pass_check` scanned for a textual
token, found none, and returned INCONCLUSIVE via DRC_NO_VERDICT_IN_SCOPE — so
step 31 FAILed and NINE downstream steps went PASS_VOIDED_BY_DEPENDENCY on a
design whose own `drc` step independently reported `violations=0`.

THE NEGATIVE CONTROLS ARE THE POINT. DRC_NO_VERDICT_IN_SCOPE was written for a
Magic run that died mid-check leaving a 0-byte report and `<top-cell>UNKNOWN`.
Every guard below is what separates that casualty from a database that reported,
and each control must still refuse after this change.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import drc_vacuous_pass_check as dv  # noqa: E402


def _rdb(items=0, *, top="spm", deck="/foss/pdks/gf180mcuD/x/gf180mcu.drc",
         categories=1, closed=True):
    head = ['<?xml version="1.0" encoding="utf-8"?>', "<report-database>"]
    if deck is not None:
        head.append(f"<generator>drc: script='{deck}'</generator>")
    if top is not None:
        head.append(f"<top-cell>{top}</top-cell>")
    for i in range(categories):
        head.append(f"<category><name>R{i}</name></category>")
    head.append("<items>")
    for _ in range(items):
        head.append("<item><category>R0</category></item>")
    head.append("</items>")
    if closed:
        head.append("</report-database>")
    return "\n".join(head) + "\n"


def _w(tmp_path, text, name="drc_signoff.rpt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# --- the measured case -----------------------------------------------------

def test_empty_item_list_is_a_stated_zero(tmp_path):
    assert dv.rdb_stated_violation_count(_w(tmp_path, _rdb(0))) == 0


def test_item_list_counts_violations(tmp_path):
    assert dv.rdb_stated_violation_count(_w(tmp_path, _rdb(3))) == 3


def test_the_real_shipped_shape_reads_zero(tmp_path):
    """763 categories, empty <items> — the spm sign-off report's own shape."""
    assert dv.rdb_stated_violation_count(
        _w(tmp_path, _rdb(0, categories=763))) == 0


# --- NEGATIVE CONTROLS: each must still yield NO count ---------------------

def test_truncated_database_is_not_a_verdict(tmp_path):
    """No closing tag: the writer died mid-write. This is the Magic casualty
    shape and it must stay unreadable."""
    assert dv.rdb_stated_violation_count(
        _w(tmp_path, _rdb(0, closed=False))) is None


def test_unknown_top_cell_is_not_a_verdict(tmp_path):
    """`<top-cell>UNKNOWN` is exactly what the killed Magic run wrote."""
    assert dv.rdb_stated_violation_count(_w(tmp_path, _rdb(0, top="UNKNOWN"))) is None
    assert dv.rdb_stated_violation_count(_w(tmp_path, _rdb(0, top=""))) is None


def test_no_named_deck_is_not_a_verdict(tmp_path):
    """Without a generator we cannot say WHICH rules produced the zero, and
    'which rules' is the whole content of a sign-off claim."""
    assert dv.rdb_stated_violation_count(_w(tmp_path, _rdb(0, deck=None))) is None
    assert dv.rdb_stated_violation_count(_w(tmp_path, _rdb(0, deck="  "))) is None


def test_no_categories_is_not_a_verdict(tmp_path):
    """A database with no rule categories never enumerated a deck."""
    assert dv.rdb_stated_violation_count(_w(tmp_path, _rdb(0, categories=0))) is None


def test_empty_file_is_not_a_verdict(tmp_path):
    assert dv.rdb_stated_violation_count(_w(tmp_path, "")) is None


def test_plain_text_log_is_not_a_verdict(tmp_path):
    """Not an RDB at all — the textual path owns this and is untouched."""
    assert dv.rdb_stated_violation_count(
        _w(tmp_path, "Loading DRC CIF style.\n")) is None


# ---------------------------------------------------------------------------
# END-TO-END BIDIRECTIONAL CONTROL.
#
# The unit tests above exercise a function that does not exist before this
# change, so on the pre-fix tree they fail by AttributeError — which proves the
# function is new, not that the REFUSAL still holds. These drive the whole gate
# through its CLI, so they run identically on both trees. Three of the four MUST
# give the same answer on both: that is what shows this change fills a gap in
# what the gate can READ and does not loosen what it REFUSES.
#
#   truncated RDB      INCONCLUSIVE  on both   <- the Magic-casualty shape
#   UNKNOWN top-cell   INCONCLUSIVE  on both
#   RDB with items>0   never a clean on both
#   complete clean RDB INCONCLUSIVE pre-fix -> PASS post-fix   <- THE BUG
# ---------------------------------------------------------------------------
import json as _json
import subprocess as _sp


def _project(tmp_path, rdb_text, name):
    proj = tmp_path / name
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "drc_signoff.rpt").write_text(
        rdb_text, encoding="utf-8")
    return proj


def _run_gate(proj):
    out = proj / "v.json"
    _sp.run([sys.executable, str(_PROGRAMS / "drc_vacuous_pass_check.py"),
             str(proj), "--under", "reports/phase3/drc_signoff.rpt",
             "--json", str(out)], capture_output=True, text=True)
    return _json.loads(out.read_text())


def test_e2e_truncated_database_is_never_a_clean(tmp_path):
    r = _run_gate(_project(tmp_path, _rdb(0, closed=False), "trunc"))
    assert r["verdict"] != "PASS", r


def test_e2e_unknown_top_cell_is_never_a_clean(tmp_path):
    r = _run_gate(_project(tmp_path, _rdb(0, top="UNKNOWN"), "unk"))
    assert r["verdict"] != "PASS", r


def test_e2e_reported_violations_are_counted_not_called_clean(tmp_path):
    """THIS GATE JUDGES VACUOUSNESS, NOT CLEANLINESS — read its own words:
    `DRC_NONZERO_COUNT ... not a vacuous PASS (defer to the violation-count
    gate)`. So a 3-item database must come back as a REAL READING carrying the
    number 3, and must NOT come back as a clean-DRC claim. Asserting
    `verdict != PASS` here would be asserting the wrong contract: PASS from this
    program means "this reading was not vacuous", and the violation count is
    another gate's verdict.

    What this control actually protects is that the three violations are SEEN
    and NAMED. Before the change they were invisible — the database was
    unparsed, so the gate reported that nothing in scope stated a count at all.
    """
    r = _run_gate(_project(tmp_path, _rdb(3), "dirty"))
    rules = {f["rule"] for f in r["findings"]}
    assert "DRC_NONZERO_COUNT" in rules, r
    assert "DRC_CLEAN_EARNED" not in rules, r
    assert any("3 violation" in f["message"] for f in r["findings"]), r
    assert r["summary"]["per_file"][0]["nonzero_count"] == 3, r


def test_tokens_straddling_a_chunk_boundary_are_counted_once(
        tmp_path, monkeypatch):
    """REGRESSION on this change's own first draft. The reader is chunked, and
    counting `buf[:cut]` and the carry as two strings split any token across the
    boundary and counted it in NEITHER — a 228-byte database whose single
    `<category>` sat on the cut read as "no deck enumerated" and returned None.

    The chunk size is driven DOWN rather than the file up. A test that tries to
    outgrow a 1 MiB chunk with generated XML is slow, and its precondition is
    the thing most likely to rot — the first draft of THIS test asserted
    `len(big) > _RDBV_CHUNK // 8` and the generated database simply was not that
    big, so the test failed on its own precondition while the reader was
    correct. Shrinking the window makes the boundary crossings certain and
    numerous, which is the property under test.
    """
    monkeypatch.setattr(dv, "_RDBV_CHUNK", 64)
    monkeypatch.setattr(dv, "_RDBV_OVERLAP", 8)
    doc = _rdb(37, categories=41)
    assert len(doc) > 64 * 20            # many windows, by construction
    assert dv.rdb_stated_violation_count(_w(tmp_path, doc)) == 37


def test_boundary_regression_also_holds_at_the_shipped_chunk_size(tmp_path):
    """The same database at the real window, so the shipped constant is
    exercised too and the monkeypatched test above cannot be the only cover."""
    assert dv.rdb_stated_violation_count(
        _w(tmp_path, _rdb(37, categories=41))) == 37
