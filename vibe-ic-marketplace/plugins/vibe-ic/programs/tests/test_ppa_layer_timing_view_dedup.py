#!/usr/bin/env python3
"""E2E finding F-10: every timing row is emitted twice from byte-identical files.

WHAT HAPPENS
============
`_ppa/timing.discover_reports` looks in three places:

    phase3/stage3/sta/      the stage tree, where the runner writes
    reports/phase3/sta/     the report tree, where it canonicalises a copy
    reports/phase3/

and de-duplicates with `seen.setdefault(str(f.resolve()), f)` -- by resolved
PATH. A Phase-3 tree carries the same sign-off report in the stage tree and in
the report tree; the two paths differ, so both are opened, and every row is
produced twice.

WHY NO PER-MODULE TEST SAW IT
=============================
Two reasons, and the second is the interesting one.

1. `test_ppa_timing.py` builds a tree with reports in ONE of the three
   directories. One directory cannot collide with itself.

2. The obvious de-duplication assertion does not fire. `row_digest` covers the
   whole row INCLUDING `source.path`, and the two copies have different paths,
   so the digests differ and a `len(set(digests)) == len(rows)` check passes
   with the bug present. Measured on `e36d81c0a`: 8 rows, 8 distinct digests,
   4 distinct (metric, scope) pairs.

   The duplication is only visible at the key a CONSUMER joins on, which is
   `metrics.record_key` -- and that is exactly the key nothing tested, because
   the timing lane tested digests and the metrics lane tested keys, separately.

WHY IT IS NOT COSMETIC
======================
Two identical rows under one (metric, scope) are two measurements of one thing.
Anything that counts -- coverage denominators, "how many views did we sign off",
a Pareto population -- doubles. Anything that AGGREGATES -- a worst-of, a total
negative slack sum -- is wrong by a factor that depends on how many of the
three directories happened to exist on that run, which is a property of the
runner's canonicalisation step and not of the design.

The fixtures below are byte-identical by construction and the test asserts it,
so a failure can never be blamed on two genuinely different reports.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from collections import Counter

import pytest

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

from _ppa import metrics as M      # noqa: E402
from _ppa import timing as T       # noqa: E402

FIX = _TESTS / "fixtures" / "ppa" / "sta" / "known_answer" / "views"
# F-10 IS FIXED AND THE PIN IS GONE. Until the record lane landed, the three
# arms below were `xfail(strict=True)` with the note "goes red the moment the
# fix lands", handed over in RESULT.md per PPA_INTERFACES §6. The fix landed in
# `_ppa/timing.discover_reports` (de-duplicate by CONTENT, not by resolved
# path) and all three xpassed, which is this file's own instruction to delete
# the pin: "a pin that survives its bug is a second bug, and it is the one that
# hides the first". The arms stay, unpinned, as the guard against a regression.


def _one_report() -> pathlib.Path:
    got = sorted(FIX.glob("setup_*.rpt"))
    assert got, f"no STA fixture under {FIX}; nothing below would be checked"
    return got[0]


def _tree_with_the_same_report_in_two_places(tmp_path) -> pathlib.Path:
    """The layout a real Phase-3 run leaves behind: the stage tree and the
    canonicalised report tree, holding the same bytes."""
    src = _one_report()
    a = tmp_path / "phase3" / "stage3" / "sta" / "sta_mcorner_ocv.rpt"
    b = tmp_path / "reports" / "phase3" / "sta" / "sta_mcorner_ocv.rpt"
    for d in (a, b):
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_bytes(src.read_bytes())
    # The premise, asserted rather than assumed: if these ever stopped being
    # identical the finding below would be about two different measurements.
    ha = hashlib.sha256(a.read_bytes()).hexdigest()
    hb = hashlib.sha256(b.read_bytes()).hexdigest()
    assert ha == hb, "the two fixture copies are not byte-identical"
    return tmp_path


def test_both_copies_are_discovered(tmp_path):
    """The premise of the finding, stated on its own so that a failure below
    cannot be explained away as 'discovery only found one'.

    THE PREMISE IS UNCHANGED; WHERE IT IS OBSERVED MOVED. Discovery still has
    to REACH both trees — if it only ever saw one, the two arms below would be
    green over a population of one and would prove nothing. Since the record
    lane landed F-10 it no longer RETURNS both, because the two files are
    byte-identical and one measurement recorded twice is not two measurements.
    So the premise is now read off the pair (kept, collapsed): two candidates
    were seen, one was kept, and the second was COLLAPSED ONTO THE ONE KEPT
    rather than never found. `discover_reports` takes the `collapsed` list
    precisely so this stays observable instead of becoming a silent drop.
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    collapsed = []
    found = T.discover_reports(root, collapsed)
    assert len(found) + len(collapsed) == 2, (
        f"discovery reached {len(found) + len(collapsed)} of the two trees; "
        f"kept={[str(f) for f in found]} collapsed={[str(a) for a, _ in collapsed]}")
    assert len(found) == 1 and len(collapsed) == 1, (
        f"the two copies are byte-identical, so exactly one is kept and one "
        f"collapses; kept={[str(f) for f in found]} "
        f"collapsed={[(str(a), str(b)) for a, b in collapsed]}")
    assert collapsed[0][1] == found[0], (
        "the collapse does not name the report it was collapsed onto, so a "
        "reader cannot tell a de-duplication from a dropped file")


def test_one_measurement_is_not_counted_twice(tmp_path):
    """F-10, at the key a consumer joins on.

    `metrics.record_key` is what `MetricIndex` uses. Two rows sharing a key
    are two copies of one fact.
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    rows, notes = T.timing_rows(root)
    assert rows, f"no rows produced; nothing was checked. notes={notes}"
    keys = Counter((r["metric"], json.dumps(r.get("scope"), sort_keys=True))
                   for r in rows)
    dupes = {k: n for k, n in keys.items() if n > 1}
    assert not dupes, (
        f"F-10: {len(rows)} rows carry only {len(keys)} distinct "
        f"(metric, scope) pairs -- {len(dupes)} of them appear more than once, "
        f"from byte-identical files. Duplicated: "
        f"{sorted(m for m, _ in dupes)}")


def test_the_duplicate_rows_come_from_the_same_bytes(tmp_path):
    """States WHY the duplication is a defect rather than two views.

    Both copies carry the same `source.sha256`. Two rows over one artefact
    hash are not two measurements; they are one measurement, recorded twice.
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    rows, _ = T.timing_rows(root)
    by_key = {}
    for r in rows:
        by_key.setdefault(
            (r["metric"], json.dumps(r.get("scope"), sort_keys=True)),
            []).append(r)
    same_bytes = [k for k, rs in by_key.items()
                  if len(rs) > 1 and len({x["source"]["sha256"] for x in rs}) == 1]
    assert not same_bytes, (
        f"F-10: {len(same_bytes)} (metric, scope) pair(s) are recorded more "
        f"than once over the SAME artefact sha256, i.e. one measurement "
        f"counted twice: {sorted(m for m, _ in same_bytes)}")


def test_row_digest_alone_cannot_see_this(tmp_path):
    """The reason nobody caught it -- asserted, so the next author does not
    reach for the check that already fails to work.

    This test PASSES with the bug present and must keep passing after it is
    fixed: it is documenting that `row_digest` is the wrong instrument here,
    not asserting that the bug exists.
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    rows, _ = T.timing_rows(root)
    if not rows:
        pytest.skip("no rows; the arms above report this")
    digests = [T.row_digest(r) for r in rows]
    assert len(set(digests)) == len(digests), (
        "row_digest now collides, which means `source.path` left the row. "
        "That is a real change to record identity -- re-read this file: the "
        "duplication check above must move to the digest, and this test must "
        "be deleted rather than relaxed.")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
