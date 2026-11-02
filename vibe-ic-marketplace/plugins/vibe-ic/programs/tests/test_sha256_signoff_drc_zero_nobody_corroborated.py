"""A sign-off DRC zero that NOTHING corroborated is NOT_MEASURED, not clean.

MEASURED on the sha256 sign-off tree (lane rbsha5 / czlecmem — one run, proven
by an identical GDS sha256 — 2026-09-08, plugin v1.19.29, sky130A, image
0.3.49). `reports/phase3/drc_signoff.json` shipped:

    passed true · real_violation_total 0 · has_count FALSE
    tool_corroborated_files 0 · tool_uncorroborated_files 1
    empty_report_files 0 · determined_files 1
    finding: WARNING DRC_VIOLATION_COUNT — No violation count pattern found

The 22 385-byte KLayout RDB it read carries the deck's whole rule list and
ZERO `<item>` and ZERO `<values>` elements. So the design's sign-off DRC was
certified clean from a report that stated no count, that nothing corroborated,
and that is not empty. That is a zero produced by not looking.

DRIVEN ON THE REAL ARTEFACT, both directions, same invocation
(`drc_report_check --mode drc --under reports/phase3/drc_signoff.rpt`):

    clean main   passed True   rc 0
    with the fix passed False  rc 1   DRC_ZERO_NOT_MEASURED

THE EMPTY RULING IS THE CONTROL AND IT MUST NOT MOVE. The 2026-08-30 decision
is that a PRESENT and EMPTY report is a legitimate zero — OpenROAD's
`detailed_route -output_drc` writes a zero-byte file exactly when it found no
residual violation, and collapsing that into "no determinable count" once made
a CLEAN route FAIL. The guard requires `not empty`, so that case is out of its
reach; the third test below is what proves it, and it is the one a careless
widening breaks.
"""
import json
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eda_report_audit as A  # noqa: E402

#: The shape the sha256 sign-off report has: a KLayout RDB carrying the deck's
#: rule list and NO items. Copied from the real artefact's structure.
_RDB_NO_ITEMS = """<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>SKY130 DRC runset</description>
 <generator>drc: script='/foss/pdks/sky130A/libs.tech/klayout/drc/sky130A.lydrc'</generator>
 <top-cell>sha256</top-cell>
 <categories>
  <category><name>li.1</name><description>li.1: min width</description></category>
  <category><name>via.4a</name><description>via.4a: min spacing</description></category>
  <category><name>via4.2</name><description>via4.2: enclosure</description></category>
 </categories>
 <items>
 </items>
</report-database>
"""


def _project(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")
    return tmp_path


def _drc(project: Path):
    with A.named_subjects([p for p in (project / "reports/phase3").iterdir()
                           if p.suffix == ".rpt"]):
        return A._check_drc(project)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _measured_klayout_receipt(project: Path) -> tuple[Path, Path, Path]:
    """Create the minimum *bound* invocation shape, not a textual count.

    The unit fixture models the record emitted by the KLayout runner.  The
    consumer must require all three links (GDS input, RDB, transcript) to be
    current; each negative test below breaks one link.
    """
    report = project / "reports/phase3/drc_signoff.rpt"
    transcript = report.with_suffix(".log")
    gds = project / "phase3/stage4/gds/chip.gds"
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_bytes(b"GDS fixture bytes, not an empty layout")
    transcript.write_text("KLayout completed deck execution\n", encoding="utf-8")
    record = {
        "record": "invocation", "measured": True, "tool": "klayout",
        "exit_code": 0,
        "inputs": {gds.relative_to(project).as_posix(): _sha(gds)},
        "outputs": {
            report.relative_to(project).as_posix(): _sha(report),
            transcript.relative_to(project).as_posix(): _sha(transcript),
        },
    }
    (project / "provenance.jsonl").write_text(json.dumps(record) + "\n",
                                               encoding="utf-8")
    return report, transcript, gds


def test_a_zero_nobody_corroborated_is_refused(tmp_path):
    """THE DEFECT. No stated count, no corroboration, not empty -> NOT clean."""
    proj = _project(tmp_path, "drc_signoff.rpt", _RDB_NO_ITEMS)
    r = _drc(proj)
    s = r.summary
    assert s["has_count"] is False, s
    assert s["real_violation_total"] == 0, s
    assert s.get("tool_corroborated_files") == 0, s
    assert s.get("empty_report_files", 0) == 0, s
    assert any(f.rule == "DRC_ZERO_NOT_MEASURED" for f in r.findings), \
        [f.rule for f in r.findings]
    assert r.passed is False, "a zero nobody established must not certify"


def test_the_refusal_names_it_as_not_measured_not_as_a_violation(tmp_path):
    """It must not be relabelled into a violation it did not find either.

    NOT_MEASURED and "violations found" are different answers; reporting the
    second would be inventing a count in the other direction."""
    proj = _project(tmp_path, "drc_signoff.rpt", _RDB_NO_ITEMS)
    r = _drc(proj)
    f, = [x for x in r.findings if x.rule == "DRC_ZERO_NOT_MEASURED"]
    assert "NOT_MEASURED" in f.message
    assert not any(x.rule == "DRC_REAL_VIOLATIONS_FOUND" for x in r.findings)
    assert r.summary["real_violation_total"] == 0


def test_an_EMPTY_report_is_still_a_legitimate_zero(tmp_path):
    """THE CONTROL, and the 2026-08-30 ruling this must not disturb.

    A PRESENT and EMPTY report is the clean route's own evidence. If the guard
    ever reaches this case, a clean route starts failing again — the exact
    regression that ruling was made to end.
    """
    proj = _project(tmp_path, "drc_router.rpt", "")
    r = _drc(proj)
    s = r.summary
    assert s.get("empty_report_files", 0) >= 1, s
    assert not any(f.rule == "DRC_ZERO_NOT_MEASURED" for f in r.findings), \
        [f.rule for f in r.findings]


def test_a_report_that_STATES_a_count_is_untouched(tmp_path):
    """The other direction the guard must not reach: a real, stated zero."""
    proj = _project(tmp_path, "drc_router.rpt",
                    "DRC violations: 0\ntotal: 0 violations\n" + "x" * 3000)
    r = _drc(proj)
    assert r.summary["has_count"] is True, r.summary
    assert not any(f.rule == "DRC_ZERO_NOT_MEASURED" for f in r.findings)


def test_digest_bound_measured_klayout_receipt_corroborates_an_rdb_zero(tmp_path):
    """A real invocation binding is independent evidence, not a made-up count."""
    proj = _project(tmp_path, "drc_signoff.rpt", _RDB_NO_ITEMS)
    _measured_klayout_receipt(proj)
    r = _drc(proj)
    assert r.summary["has_count"] is False
    assert r.summary["receipt_corroborated_files"] == 1
    assert not any(f.rule == "DRC_ZERO_NOT_MEASURED" for f in r.findings)


@pytest.mark.parametrize("break_link", ["report", "transcript", "gds", "exit"])
def test_a_stale_or_nonmeasured_receipt_cannot_corroborate(tmp_path, break_link):
    proj = _project(tmp_path, "drc_signoff.rpt", _RDB_NO_ITEMS)
    report, transcript, gds = _measured_klayout_receipt(proj)
    if break_link == "report":
        report.write_text(_RDB_NO_ITEMS + "\n", encoding="utf-8")
    elif break_link == "transcript":
        transcript.unlink()
    elif break_link == "gds":
        gds.write_bytes(b"different GDS bytes")
    else:
        ledger = project_ledger = proj / "provenance.jsonl"
        row = json.loads(ledger.read_text(encoding="utf-8"))
        row["exit_code"] = 1
        project_ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    r = _drc(proj)
    assert r.summary["receipt_corroborated_files"] == 0
    assert any(f.rule == "DRC_ZERO_NOT_MEASURED" for f in r.findings)
