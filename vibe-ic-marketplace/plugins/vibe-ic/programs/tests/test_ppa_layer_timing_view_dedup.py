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
from _ppa.backends import opensta  # noqa: E402
from _ppa import timing as T       # noqa: E402

FIX = _TESTS / "fixtures" / "ppa" / "sta" / "known_answer" / "views"
# F-10 IS FIXED AND THE PIN IS GONE. Until the record lane landed, the three
# arms below were `xfail(strict=True)` with the note "goes red the moment the
# fix lands", handed over in RESULT.md per PPA_INTERFACES §6. The fix landed and
# all three xpassed, which is this file's own instruction to delete the pin: "a
# pin that survives its bug is a second bug, and it is the one that hides the
# first". The arms stay, unpinned, as the guard against a regression.
#
# WHICH MECHANISM FIXED IT CHANGED UNDER THIS FILE, AND THIS FILE WAS NOT MOVED
# WITH IT (v1.11.57, `e4c5840d6f`). These arms were written at v1.11.53 against
# `discover_reports` de-duplicating by CONTENT DIGEST: byte-identical, therefore
# one artefact, therefore one kept. A second lane then shipped
# `test_declared_mirrors_are_not_a_second_measurement.py::
#  test_two_identical_artefacts_that_are_not_declared_mirrors_both_count`,
# whose rule a content hash CANNOT satisfy -- two DIFFERENT sign-off reports
# whose bytes happen to agree are two measurements, and collapsing them by
# digest deletes evidence. Nothing in the bytes tells the two situations apart.
#
# So the contract was inverted where it had to be: byte equality now DETECTS and
# the PRODUCER'S DECLARATION decides. `discover_reports` keeps both copies and
# records the pair in `collapsed`; `collapse_declared_mirrors` drops the copy
# the run itself wrote down as a mirror in `reports/phase3/artefact_mirrors.json`
# (`phase3_one_shot_runner._publish_artefact_mirror`, three call sites), with a
# reason attached. An UNDECLARED byte-identical pair is a finding in its own
# right and BOTH count, because a double count is visible in the document and a
# deletion is not.
#
# v1.11.57's landing gate was skipped by owner directive, so nothing compared
# test IDs and these three arms landed red on main still asserting the
# superseded rule. THEY ARE CORRECTED HERE, NOT RELAXED: the property they
# protect is unchanged -- one measurement must not become two rows under one
# (metric, scope) -- and it is now asserted over the tree shape the runner
# actually produces (mirror declared), plus a new arm's worth of assertion that
# the UNDECLARED shape is loud rather than silent. The live contract is guarded
# on the other side by `test_ppa_timing.py::
# test_a_report_published_into_two_directories_is_read_ONCE`; before this
# correction the two files asserted opposite things about the same call.


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


def _declare_the_mirror(root: pathlib.Path) -> None:
    """Write the manifest the RUN ITSELF writes when it publishes a copy.

    `phase3_one_shot_runner._publish_artefact_mirror` emits this for every
    artefact it mirrors into a second directory, so a real Phase-3 tree carries
    it. Without it the pair is undeclared, and an undeclared pair is a
    different situation with a different correct answer -- asserted in
    `test_an_undeclared_duplicate_is_loud_not_silent` below.
    """
    a = root / "phase3" / "stage3" / "sta" / "sta_mcorner_ocv.rpt"
    b = root / "reports" / "phase3" / "sta" / "sta_mcorner_ocv.rpt"
    manifest = root / T._MIRROR_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(
        {"schema": "vibeic.artefact_mirrors.v1",
         "mirrors": [{"mirror": T._rel(root, b),
                      "of": T._rel(root, a),
                      "sha256": opensta.file_digest(a),
                      "reason": "published into a second directory by the runner"}]},
        indent=2) + "\n", encoding="utf-8")


def test_both_copies_are_discovered(tmp_path):
    """The premise of the finding, stated on its own so that a failure below
    cannot be explained away as 'discovery only found one'.

    THE PREMISE IS UNCHANGED; WHAT DISCOVERY DOES WITH IT MOVED. Discovery has
    to REACH both trees — if it only ever saw one, the arms below would be
    green over a population of one and would prove nothing. That is asserted
    directly here, on the paths, rather than inferred from a count.

    WHAT THIS ARM NO LONGER ASSERTS, AND WHY. It used to require `len(found)
    == 1`: byte-identical, therefore collapsed to one. Since v1.11.57 the bytes
    DETECT and the producer's declaration DECIDES, so an undeclared pair keeps
    BOTH and merely REPORTS the pair — see the note at the head of this file.
    The observable that survives, and the one this arm now pins, is that the
    duplicate is never silent: the pair is reported, and it names both members,
    so a reader can tell a duplicate from a dropped file. The "counted once"
    property moved to the arms below, where the mirror is declared.
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    a = root / "phase3" / "stage3" / "sta" / "sta_mcorner_ocv.rpt"
    b = root / "reports" / "phase3" / "sta" / "sta_mcorner_ocv.rpt"
    collapsed = []
    found = T.discover_reports(root, collapsed)
    assert {f.resolve() for f in found} == {a.resolve(), b.resolve()}, (
        f"discovery did not reach both trees; kept={[str(f) for f in found]} "
        f"collapsed={[str(x) for x, _ in collapsed]}")
    assert len(collapsed) == 1, (
        f"the two copies are byte-identical, so exactly one pair is REPORTED "
        f"as a byte-identical duplicate; "
        f"collapsed={[(str(x), str(y)) for x, y in collapsed]}")
    assert collapsed[0][0].resolve() != collapsed[0][1].resolve(), (
        "the reported pair names one file twice, so it is not a pair")
    assert {collapsed[0][0].resolve(), collapsed[0][1].resolve()} == \
        {a.resolve(), b.resolve()}, (
        "the report does not name the file it duplicates, so a reader cannot "
        "tell a duplicate from a dropped file: "
        f"{(str(collapsed[0][0]), str(collapsed[0][1]))}")


def test_one_measurement_is_not_counted_twice(tmp_path):
    """F-10, at the key a consumer joins on.

    `metrics.record_key` is what `MetricIndex` uses. Two rows sharing a key
    are two copies of one fact.

    OVER THE TREE THE RUNNER ACTUALLY PRODUCES. `_publish_artefact_mirror`
    writes `reports/phase3/artefact_mirrors.json` for every copy it publishes,
    so a real Phase-3 tree declares its mirror; `_declare_the_mirror` builds
    exactly that. The property asserted is the same one F-10 was filed for —
    one measurement, one row per (metric, scope). What changed is that the
    collapse is driven by the producer's declaration rather than by a content
    hash, because a hash cannot tell a copy from a second reading that agrees.
    The undeclared case is asserted separately, below.
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    _declare_the_mirror(root)
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
    hash are not two measurements; they are one measurement, recorded twice —
    and the run said so itself, in the mirror manifest `_declare_the_mirror`
    writes. That declaration is what makes this a defect rather than a
    coincidence: without it, identical bytes prove nothing (see
    `test_an_undeclared_duplicate_is_loud_not_silent`).
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    _declare_the_mirror(root)
    rows, _ = T.timing_rows(root)
    assert rows, "no rows produced; nothing would be checked"
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


def test_an_undeclared_duplicate_is_loud_not_silent(tmp_path):
    """The other half of the corrected contract, asserted so that "both are
    kept" can never quietly become "and nobody is told".

    An undeclared byte-identical pair keeps BOTH rows on purpose: deleting a
    real second measurement is worse than double-counting one, because a double
    count is visible in the document and a deletion is not. That trade is only
    defensible while the duplication is REPORTED. If this note ever stops being
    emitted, the double count becomes silent and F-10 is back in a new place —
    which is precisely the failure the arms above were written to prevent, so
    it is pinned here rather than left to the mechanism's good intentions.
    """
    root = _tree_with_the_same_report_in_two_places(tmp_path)
    rows, notes = T.timing_rows(root)
    assert rows, f"no rows produced; nothing was checked. notes={notes}"
    keys = Counter((r["metric"], json.dumps(r.get("scope"), sort_keys=True))
                   for r in rows)
    assert any(n > 1 for n in keys.values()), (
        "an UNDECLARED byte-identical pair no longer double-counts. That may "
        "be an improvement, but it is a contract change: re-read the note at "
        "the head of this file, move the 'both are kept' rule with it, and "
        "reconcile `test_ppa_timing.py::"
        "test_a_report_published_into_two_directories_is_read_ONCE` and "
        "`test_declared_mirrors_are_not_a_second_measurement.py` in the same "
        "commit -- do not delete this arm on its own.")
    assert any("undeclared byte-identical artefacts" in n for n in notes), (
        "both copies were counted and NOTHING said so. A double count that is "
        f"not reported is a silent one. notes={notes}")


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
