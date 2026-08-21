#!/usr/bin/env python3
"""`_aggregate_verdict` must not turn an unenumerated status into a silent PASS.

WHAT WENT WRONG
===============
``design_one_shot_runner._aggregate_verdict`` classified four FAIL statuses and
``WAIVED``, and returned ``PASS`` for everything else. Its own comment names the
hazard::

    everything this function does not enumerate falls through to the catch-all
    `return "PASS"` below

``BLOCKED`` was added by hand after that bit once. It bit again, on the status
the runner emits MORE than any other: ``SKIP`` appears at 53 call sites (against
34 ``FAIL`` and 22 ``PASS``) and was never enumerated, so it reached the same
silent ``PASS``.

The consequence is cross-phase and was found by the 63x8 round-2 review: phase 3
reads ``SKIP`` as ``PASS_WITH_WAIVERS``, phase 2 reads the identical word as
clean. Because the phase-2 verdict is ``PASS`` rather than ``PASS_WITH_WAIVERS``,
no ``waivers.json`` entry is required or auto-generated, so a disclosed skip
never reaches the must-close list. The same word, two opposite meanings, in two
runners over the same 63-step matrix.

WHAT THIS FILE LOCKS, AND WHAT IT DELIBERATELY DOES NOT
=======================================================
Locked: the classification is TOTAL. An unknown status is reported rather than
absorbed, and a ``PASS`` carrying skips says so.

NOT locked: the verdict itself. Promoting ``SKIP`` to ``PASS_WITH_WAIVERS``
would restate every published phase-2 result, which is a decision for whoever
owns the benchmark contract. The gap is disclosed here and tracked upstream; it
is not silently repaired by the reviewer who found it.
"""
from __future__ import annotations

import contextlib
import io
import re
import sys

import pytest

from _plugin_tree import plugin_path

RUNNER = plugin_path() / "programs" / "design_one_shot_runner.py"


@pytest.fixture(scope="module")
def agg():
    """The real function, lifted out of a module too heavy to import.

    Extracted by source so the assertions run against the SHIPPED text rather
    than a copy of it — a re-implementation here would pass whatever the runner
    did, which is the failure mode this whole file is about.
    """
    src = RUNNER.read_text(encoding="utf-8")
    m = re.search(r"def _aggregate_verdict.*?(?=\nif __name__)", src, re.S)
    assert m, "could not locate _aggregate_verdict in the shipped runner"
    ns: dict = {"sys": sys}
    exec(  # noqa: S102 — executing our own shipped source, by design
        "from typing import List\n"
        "class StepResult:\n"
        "    def __init__(self, name, status):\n"
        "        self.name = name; self.status = status\n" + m.group(0),
        ns,
    )
    return ns["_aggregate_verdict"], ns["StepResult"]


def _run(agg_fn, plan):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        verdict = agg_fn(plan)
    return verdict, err.getvalue()


def test_an_unknown_status_is_reported_not_absorbed(agg):
    """The catch-all. Fails on the unfixed function, which said nothing."""
    fn, SR = agg
    verdict, err = _run(fn, [SR("a", "PASS"), SR("b", "SOME_NEW_STATUS")])
    assert "UNCLASSIFIED" in err, (
        "an unenumerated status reached the verdict aggregator and produced no "
        f"diagnostic at all; stderr was {err!r}")
    assert "SOME_NEW_STATUS" in err, err


def test_an_unknown_status_does_not_become_a_failure(agg):
    """Guard the guard, in the other direction.

    Making unknown statuses FAIL would turn a rename into a red run and would
    be its own kind of lie. The requirement is visibility, not severity.
    """
    fn, SR = agg
    verdict, _ = _run(fn, [SR("a", "PASS"), SR("b", "SOME_NEW_STATUS")])
    assert verdict != "FAIL", verdict


def test_a_pass_carrying_skips_discloses_them(agg):
    """A bare PASS must not hide that steps were skipped."""
    fn, SR = agg
    verdict, err = _run(fn, [SR("synth", "PASS"), SR("lec", "SKIP")])
    assert "SKIPPED step(s)" in err, err
    assert "lec" in err, "the disclosure does not name the skipped step"
    assert "waivers" in err, (
        "the disclosure does not say why a skipped step matters — that it "
        "reaches no must-close list")


def test_the_published_verdicts_are_unchanged(agg):
    """Deliberately pinned: this change discloses, it does not reclassify.

    If a later change promotes SKIP to PASS_WITH_WAIVERS, this test must be
    retired ON PURPOSE, with the published-result restatement acknowledged —
    not quietly adjusted to match new behaviour.
    """
    fn, SR = agg
    assert _run(fn, [SR("a", "PASS")])[0] == "PASS"
    assert _run(fn, [SR("a", "PASS"), SR("b", "SKIP")])[0] == "PASS"
    assert _run(fn, [SR("a", "FAIL")])[0] == "FAIL"
    assert _run(fn, [SR("a", "WAIVED")])[0] == "PASS_WITH_WAIVERS"
    assert _run(fn, [SR("a", "ADVISORY")])[0] == "PASS"
    assert _run(fn, [SR("a", "BLOCKED")])[0] == "FAIL"


def test_every_status_the_runner_emits_is_classified(agg):
    """Totality against the runner's OWN vocabulary, discovered not typed.

    Scrapes the statuses actually constructed in the shipped source, so a new
    one added tomorrow is covered by construction rather than by remembering to
    extend a list here.
    """
    fn, SR = agg
    src = RUNNER.read_text(encoding="utf-8")
    emitted = set(re.findall(r'StepResult\([^,]+,\s*"([A-Z][A-Z_0-9-]+)"', src))
    assert emitted, "found no StepResult statuses — the scrape is broken"
    unclassified = []
    for st in sorted(emitted):
        _, err = _run(fn, [SR("s", st)])
        if "UNCLASSIFIED" in err:
            unclassified.append(st)
    assert not unclassified, (
        f"the runner emits status(es) {unclassified} that its own verdict "
        f"aggregator does not classify")
