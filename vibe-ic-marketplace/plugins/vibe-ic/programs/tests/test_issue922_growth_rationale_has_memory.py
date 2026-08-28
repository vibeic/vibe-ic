#!/usr/bin/env python3
"""vibe-ic#922 — a `growth_rationale` may not be a permanent blanket.

Before this fix `growth_rationale` was one document-level string tested only by
``len(strip()) >= 30``. Thirty characters of anything authorised ANY net growth
of ANY size, forever. The reproduction below is the literal one from the issue:
thirty ``x`` characters, fifty new waivers, exit 0.

Both arms are required and both are here. The FAILURE arm proves the blanket is
gone; the PAIRED arm proves growth the rationale legitimately covers still
passes. A gate that refuses everything would satisfy the first arm alone, which
is how the one-sided check being replaced was written in the first place.

The program is driven as a subprocess — the shipped entry point, argv and exit
code included — rather than by importing its predicate. A test that re-states
the rule in Python proves the re-statement, not the gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "waiver_growth_check.py"

def _run(project: Path):
    """``(returncode, report)`` from one real invocation of the gate."""
    proc = _pr.run(
        [sys.executable, str(PROG), str(project), "--json"],
        capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def _project(tmp_path: Path, current: dict, baseline: dict | None = None) -> Path:
    proj = tmp_path / "proj"
    (proj / ".vibe-ic-state").mkdir(parents=True, exist_ok=True)
    (proj / "waivers.json").write_text(json.dumps(current, indent=2))
    if baseline is not None:
        (proj / ".vibe-ic-state" / "waivers_baseline.json").write_text(
            json.dumps(baseline, indent=2))
    return proj


def _steps(*names) -> dict:
    return {"waived_steps": [{"id": n} for n in names]}


#: A rationale long enough to clear the substantive-prose bar, so every test
#: below turns on the MEMORY rather than on the length.
_REASON = ("Device-level extraction is scheduled for the next release; "
           "deferral accepted by sign-off.")


def _categories(report) -> set:
    return {f["category"] for f in report["findings"]}


# ---------------------------------------------------------------- failure arm

def test_thirty_characters_no_longer_authorise_fifty_waivers(tmp_path):
    """The issue's reproduction, verbatim: 30 literal ``x`` beside 50 new
    waivers. This is the arm that FAILS against the unfixed program, where it
    printed ``[PASS]`` and exited 0."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", *[f"new_{i:02d}" for i in range(50)]),
                     growth_rationale="x" * 30),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == 50
    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_WITHOUT_MEMORY" in _categories(report)
    assert rc == 1


def test_a_rationale_may_not_reserve_headroom_above_the_current_count(tmp_path):
    """The recorded count is compared for EQUALITY, not ``>=``.

    If a larger recorded count were accepted, one edit could pre-authorise
    every waiver up to the ceiling it names — the same permanent blanket with a
    number in front of it. Here the author records 51 beside a file holding
    two, which is a claim about waivers that do not exist yet."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON, growth_rationale_covers=51),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_covers"] == 51
    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_STALE" in _categories(report)
    assert rc == 1


def test_growth_past_the_recorded_count_needs_a_renewed_rationale(tmp_path):
    """The memory itself: a rationale written against two waivers does not
    cover the third. This is the property the issue calls non-expiring."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta", "gamma"),
                     growth_rationale=_REASON, growth_rationale_covers=2),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["current_root_waivers"] == 3
    assert report["summary"]["growth_rationale_covers"] == 2
    assert "GROWTH_RATIONALE_STALE" in _categories(report)
    assert rc == 1


def test_a_boolean_is_not_a_recorded_count(tmp_path):
    """``bool`` is an ``int`` subclass, so an unguarded comparison would read
    ``growth_rationale_covers: true`` as "written against exactly one waiver".
    A memory the gate invented for the author is not a memory."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha"),
                     growth_rationale=_REASON, growth_rationale_covers=True),
        baseline={},
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_covers"] is None
    assert "GROWTH_RATIONALE_WITHOUT_MEMORY" in _categories(report)
    assert rc == 1


# ----------------------------------------------------------------- paired arm

def test_growth_the_rationale_covers_still_passes(tmp_path):
    """THE PAIRED ARM. The operator escape hatch has to keep working: a
    substantive reason, recorded against the population it was written beside,
    passes. Without this a version of the gate that refused every growth would
    look correct."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta", "gamma"),
                     growth_rationale=_REASON, growth_rationale_covers=3),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == 2
    assert report["summary"]["growth_justified"] is True
    assert not _categories(report) & {"UNJUSTIFIED_WAIVER_GROWTH",
                                      "GROWTH_RATIONALE_WITHOUT_MEMORY",
                                      "GROWTH_RATIONALE_STALE"}
    assert rc == 0


def test_the_other_dialect_gets_the_same_escape_hatch(tmp_path):
    """The attestation dialect is counted for growth (vibe-ic#525), so it must
    be justifiable the same documented way — the memory is a property of the
    document, not of one dialect."""
    entry = {"step": "lvs", "phase": "phase3", "ticket": "T-1"}
    proj = _project(
        tmp_path,
        current={"waivers": [entry],
                 "growth_rationale": _REASON, "growth_rationale_covers": 1},
        baseline={},
    )
    rc, report = _run(proj)

    assert report["summary"]["current_root_waivers"] == 1
    assert report["summary"]["growth_justified"] is True
    assert rc == 0


def test_shrinking_is_never_blocked_by_a_stale_memory(tmp_path):
    """The rationale is consulted only when the count GROWS past tolerance.

    A project that closes waivers must not be made to renew prose about the
    ones it just removed — a gate that penalises shrinking teaches operators
    not to shrink."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha"),
                     growth_rationale=_REASON, growth_rationale_covers=9),
        baseline=_steps("alpha", "beta", "gamma"),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == -2
    assert not _categories(report) & {"UNJUSTIFIED_WAIVER_GROWTH",
                                      "GROWTH_RATIONALE_WITHOUT_MEMORY",
                                      "GROWTH_RATIONALE_STALE"}
    assert rc == 0


# ------------------------------------------------------- unchanged behaviour

def test_growth_with_no_rationale_keeps_its_original_category(tmp_path):
    """A document with no usable rationale must fail exactly as it always did.

    The new requirement is additive: it splits the JUSTIFIED arm, and must not
    re-label the arm that was already failing. Callers matching on
    ``UNJUSTIFIED_WAIVER_GROWTH`` keep matching."""
    proj = _project(tmp_path, current=_steps("alpha", "beta"),
                    baseline=_steps("alpha"))
    rc, report = _run(proj)

    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(report)
    assert rc == 1


def test_too_short_a_rationale_is_still_just_a_short_rationale(tmp_path):
    """A recorded count does not substitute for the reason. Both halves are
    required, and prose below the bar fails on the prose, not on the memory."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale="too short", growth_rationale_covers=2),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(report)
    assert rc == 1
