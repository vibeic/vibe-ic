#!/usr/bin/env python3
"""Unit tests for `l_doc_evidence_util`, the shared evidence-resolution helper
behind the L24/L25/L26 semantic gates (landed with the #320-#327 series).

Written by the gatekeeper at land time: the D1 program-test-coverage gate
correctly FAILed the PR because this shared module shipped untested. Its whole
job is to decide whether a stated value is actually READABLE in the artefact it
cites — i.e. whether a verdict is derived from evidence or merely asserted. A
regression here would let asserted verdicts pass as derived ones across every
gate that delegates to it, which is the exact defect class this campaign has
been chasing (an empty result and a real result indistinguishable at the
verdict).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import l_doc_evidence_util as E  # noqa: E402


def test_no_information_recognises_absence_not_a_claim():
    for v in (None, "", [], {}, "   "):
        assert E.is_no_information(v) is True, v
    for tok in E.NO_INFORMATION_TOKENS:
        assert E.is_no_information(tok) is True
        assert E.is_no_information(tok.upper()) is True, "must be case-insensitive"


def test_populated_is_the_strict_inverse():
    for v in (0, "10 ns", ["x"], {"a": 1}, False):
        assert E.is_populated(v) is True, v
        assert E.is_no_information(v) is False, v


def test_zero_and_false_are_claims_not_absences():
    """A measured 0 is a RESULT. Treating it as 'no information' is how a real
    zero gets confused with an unmeasured one."""
    assert E.is_no_information(0) is False
    assert E.is_no_information(False) is False


def test_load_json_returns_none_on_bad_input(tmp_path):
    assert E.load_json(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert E.load_json(bad) is None, "unparseable evidence is not evidence"


def test_resolve_under_project_refuses_escape(tmp_path):
    """A cited path must stay inside the project — otherwise a doc could point
    its 'evidence' at an unrelated file on the host."""
    (tmp_path / "reports").mkdir()
    inside = tmp_path / "reports" / "sta.rpt"
    inside.write_text("worst slack 1.0")
    assert E.resolve_under_project(tmp_path, "reports/sta.rpt") == inside
    for escape in ("../../../etc/passwd", "/etc/passwd"):
        got = E.resolve_under_project(tmp_path, escape)
        assert got is None or tmp_path in got.parents or got == inside, escape


def test_value_readable_in_file_both_directions(tmp_path):
    """The load-bearing check: a value the gate CLAIMS must be findable in the
    artefact it cites. Both directions, or it proves nothing."""
    f = tmp_path / "sta.rpt"
    f.write_text("worst slack max 6.14\ntns max 0.00\n")
    assert E.value_readable_in_file(f, "6.14") is True
    assert E.value_readable_in_file(f, 6.14) is True
    assert E.value_readable_in_file(f, "99.99") is False, (
        "a value NOT in the artefact must not read as evidenced")


def test_value_readable_tolerates_numeric_formatting(tmp_path):
    f = tmp_path / "r.rpt"
    f.write_text("count = 1826 instances\n")
    assert E.value_readable_in_file(f, 1826) is True
    assert E.value_readable_in_file(f, "1826") is True


def test_value_readable_on_missing_file_is_false(tmp_path):
    assert E.value_readable_in_file(tmp_path / "nope.rpt", "1") is False


def test_find_layer_files_matches_the_full_stem(tmp_path):
    """`stem` is the FULL doc name (e.g. L24_SIGNOFF), not a prefix — pinned
    so a caller cannot quietly start passing "L24" and silently find nothing."""
    gd = tmp_path / "phase1" / "generated_docs"   # the canonical root
    gd.mkdir(parents=True)
    (gd / "L24_SIGNOFF.json").write_text("{}")
    (gd / "L25_OTHER.json").write_text("{}")
    assert [p.name for p in E.find_layer_files(tmp_path, "L24_SIGNOFF")] == ["L24_SIGNOFF.json"]
    assert E.find_layer_files(tmp_path, "L24") == [], "a bare prefix must not match"


def test_find_layer_files_covers_the_soc_per_block_layout(tmp_path):
    """SoC projects put each sub-block's docs one level deeper."""
    blk = tmp_path / "phase1" / "generated_docs" / "core_a"
    blk.mkdir(parents=True)
    (blk / "L24_SIGNOFF.json").write_text("{}")
    assert [p.name for p in E.find_layer_files(tmp_path, "L24_SIGNOFF")] == ["L24_SIGNOFF.json"]


def test_generated_docs_roots_prefers_the_canonical_location(tmp_path):
    """Canonical-first matters: a stale copy elsewhere in the tree must not
    shadow the real one, or a gate reads last run's evidence."""
    canon = tmp_path / "phase1" / "generated_docs"
    canon.mkdir(parents=True)
    other = tmp_path / "old" / "generated_docs"
    other.mkdir(parents=True)
    roots = E.generated_docs_roots(tmp_path)
    assert roots and roots[0] == canon, roots


def test_find_layer_files_empty_when_absent(tmp_path):
    assert E.find_layer_files(tmp_path, "L99") == []
