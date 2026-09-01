#!/usr/bin/env python3
"""A KLayout DRC report that graded NO rule is not a clean block.

MEASURED. A KLayout runset OPENS its report database before it grades
anything, so a deck that raises mid-run still leaves a well-formed 474-byte
report on disk with zero categories and zero items. The producer counted only
`<item>` and wrote `violations: 0 / result: PASS`, and the A6 gate then
certified the block DRC-clean from that text report — a block whose deck never
evaluated a rule.

The deck raised for a reason worth recording: a KLayout runset resolves its
sibling tech-JSON RELATIVE TO ITSELF, and the corpus staged the deck one
directory shallower than the PDK tree it was copied from. Staged at its own
depth the same deck grades 590 rules on the same GDS.

The SVRF branch of the same runner has carried this law since the round it was
written ("a report that graded 0 rules is an unread deck, not a clean block").
This is the same law, on the branch that did not have it.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_a6_native_pv as PV  # noqa: E402


def _rdb(categories: int, items: int) -> str:
    c = "".join("<category><name>R%d</name></category>" % i
                for i in range(categories))
    it = "".join("<item><category>'R0'</category></item>"
                 for _ in range(items))
    return ("<?xml version='1.0'?><report-database><categories>%s</categories>"
            "<items>%s</items></report-database>" % (c, it))


def test_categories_are_counted_separately_from_items():
    assert PV._count_lyrdb_categories(_rdb(590, 0)) == 590
    assert PV._count_lyrdb_items(_rdb(590, 0)) == 0
    assert PV._count_lyrdb_items(_rdb(590, 4)) == 4
    assert PV._count_lyrdb_categories("") == 0


def _run(monkeypatch, tmp_path: Path, rdb_text: str, rc: int):
    monkeypatch.setattr(PV, "_tool_on_path", lambda ctn, tool: "/usr/bin/" + tool)
    report = tmp_path / "drc.report"

    def fake_exec(container, cmd, *a, **k):
        report.write_text(rdb_text)
        return rc, "", ""

    monkeypatch.setattr(PV, "_docker_exec", fake_exec)
    monkeypatch.setattr(PV, "_to_container_path", lambda ctn, p: p)
    return PV._klayout_drc_runner("/d/x.drc", "/d/x.gds", "blk", "c", report)


def test_a_deck_that_graded_nothing_is_no_evidence(monkeypatch, tmp_path):
    """The false clean this closes: 0 items out of 0 rules, rc=1."""
    violations, meta = _run(monkeypatch, tmp_path, _rdb(0, 0), 1)
    assert violations is None
    assert "graded 0 rule" in meta["reason"]


def test_a_nonzero_rc_is_no_evidence_even_with_categories(monkeypatch,
                                                          tmp_path):
    violations, meta = _run(monkeypatch, tmp_path, _rdb(590, 0), 1)
    assert violations is None
    assert "rc=1" in meta["reason"]


def test_a_real_clean_run_still_certifies_zero(monkeypatch, tmp_path):
    """The other direction, and the one that matters: a deck that graded 590
    rules and found nothing IS a clean block."""
    violations, meta = _run(monkeypatch, tmp_path, _rdb(590, 0), 0)
    assert violations == 0
    assert meta["rules_pass"] == 590


def test_a_real_violating_run_is_counted(monkeypatch, tmp_path):
    violations, meta = _run(monkeypatch, tmp_path, _rdb(590, 4), 0)
    assert violations == 4
