#!/usr/bin/env python3
"""`waiver_growth_check` must be able to say "this closed waiver came back".

Its header has always listed "a previously-closed waiver re-appeared" as a
CI-failing condition, and no branch emitted it: there was no `WAIVER_REOPENED`
category and neither document's closure state was ever read.

The verdict could not arrive by the growth route either, which is the part
worth pinning. Growth is a set difference over waiver IDENTITIES. A reopened
waiver's identity is in BOTH documents — closed in the baseline, open again now
— so it is neither new nor removed and moves `net_growth` by exactly 0. Every
fixture below therefore holds the waiver COUNT flat: `net_growth == 0` in all
of them, so the only thing that can separate a PASS from a FAIL is whether the
gate reads closure state at all.

Both directions are pinned. The failing direction proves the missing verdict is
now reachable; the passing direction proves closure awareness did not turn
every document with a closure record red.

Everything here is synthetic: a step id, a role name, a ticket string.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "waiver_growth_check.py"

_LONG_ENOUGH = ("The earlier closure rested on an assumption that a later "
                "revision has since withdrawn.")


def _project(tmp_path: Path, current: dict, baseline: dict) -> Path:
    (tmp_path / "waivers.json").write_text(json.dumps(current))
    state = tmp_path / ".vibe-ic-state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "waivers_baseline.json").write_text(json.dumps(baseline))
    return tmp_path


def _run(project: Path):
    """`(returncode, parsed_json)` — the gate's own emitted verdict."""
    r = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json"],
        capture_output=True, text=True)
    assert r.returncode in (0, 1), f"unexpected rc={r.returncode}\n{r.stderr}"
    return r.returncode, json.loads(r.stdout)


def _steps(closed: bool, **extra) -> dict:
    """One `waived_steps`-dialect document holding a single entry."""
    entry = {"id": 31, "reason": "deferred to the signoff deck",
             "approver": "block-owner", "ticket": "TRACKER-1"}
    if closed:
        entry["status"] = "closed"
    else:
        entry["review_required"] = True
    entry.update(extra)
    return {"waived_steps": [entry]}


def _attestation(closed: bool, **extra) -> dict:
    """The other dialect: no `id`, identified by (step, phase, ticket)."""
    entry = {"step": "lvs", "phase": "phase3", "ticket": "TRACKER-2",
             "rationale": "deferred to the signoff deck"}
    if closed:
        entry["closure_proof"] = "reports/rerun.log"
    entry.update(extra)
    return {"waivers": [entry]}


# ---------------------------------------------------------------------------
# Direction 1 — the verdict that could not be emitted
# ---------------------------------------------------------------------------
def test_a_waiver_closed_in_the_baseline_and_open_again_now_fails(tmp_path):
    """Count is flat, so the unfixed gate printed `net growth: 0` and exit 0."""
    rc, out = _run(_project(tmp_path, _steps(closed=False), _steps(closed=True)))

    assert out["summary"]["net_growth"] == 0, (
        "fixture no longer isolates the reopen from the growth route")
    assert out["summary"]["new_waivers"] == []
    assert out["summary"]["removed_waivers"] == []

    assert out["summary"]["reopened_waivers"], (
        "the reopened waiver was not reported at all")
    assert [f for f in out["findings"] if f["category"] == "WAIVER_REOPENED"]
    assert out["summary"]["pass"] is False
    assert rc == 1


def test_the_attestation_dialect_reopen_is_caught_too(tmp_path):
    """The second dialect keys on (step, phase, ticket) and closes with
    `closure_proof`. A gate that only saw one dialect's closure would leave
    half the corpus with the same unreachable verdict."""
    rc, out = _run(_project(tmp_path,
                            _attestation(closed=False),
                            _attestation(closed=True)))

    assert out["summary"]["net_growth"] == 0
    assert len(out["summary"]["reopened_waivers"]) == 1
    assert [f for f in out["findings"] if f["category"] == "WAIVER_REOPENED"]
    assert rc == 1


# ---------------------------------------------------------------------------
# Direction 2 — PASS is still reachable
# ---------------------------------------------------------------------------
def test_a_closed_waiver_that_stays_closed_still_passes(tmp_path):
    """Closure records in BOTH documents, unchanged. Reading closure state
    must not turn "this waiver is still closed" into a finding — a gate that
    can only say FAIL is the same defect wearing the other sign."""
    rc, out = _run(_project(tmp_path, _steps(closed=True), _steps(closed=True)))

    assert out["summary"]["reopened_waivers"] == []
    assert [f for f in out["findings"] if f["category"].startswith(
        "WAIVER_REOPENED")] == []
    assert out["summary"]["pass"] is True
    assert rc == 0


def test_closing_a_waiver_since_the_baseline_is_not_a_reopen(tmp_path):
    """The opposite transition — open in the baseline, closed now — is work
    being finished. It must stay a PASS, in both dialects."""
    for current, baseline in ((_steps(True), _steps(False)),
                              (_attestation(True), _attestation(False))):
        project = tmp_path / f"p{len(list(tmp_path.iterdir()))}"
        project.mkdir()
        rc, out = _run(_project(project, current, baseline))
        assert out["summary"]["reopened_waivers"] == []
        assert rc == 0


def test_a_disclosed_reopen_is_reported_without_failing(tmp_path):
    """The escape hatch is operator-written and lives in the waiver document.
    It downgrades to a WARN — reported, not refused — and the run stays green,
    so a legitimate reopen does not force anyone to delete the baseline's
    closure record to get a PASS."""
    rc, out = _run(_project(tmp_path,
                            _steps(closed=False, reopen_rationale=_LONG_ENOUGH),
                            _steps(closed=True)))

    assert out["summary"]["reopened_waivers"] == out["summary"][
        "reopened_waivers_disclosed"] != []
    warns = [f for f in out["findings"]
             if f["category"] == "WAIVER_REOPENED_DISCLOSED"]
    assert warns and warns[0]["severity"] == "WARN"
    assert out["summary"]["pass"] is True
    assert rc == 0


def test_a_token_reopen_rationale_does_not_buy_a_pass(tmp_path):
    """The hatch carries the same substance bar as `growth_rationale`. A
    one-word field is not a justification, and a hatch that opens for one is
    the rubber stamp the waiver gates exist to refuse."""
    rc, out = _run(_project(tmp_path,
                            _steps(closed=False, reopen_rationale="needed"),
                            _steps(closed=True)))

    assert out["summary"]["reopened_waivers_disclosed"] == []
    assert [f for f in out["findings"] if f["category"] == "WAIVER_REOPENED"]
    assert rc == 1


# ---------------------------------------------------------------------------
# Blast radius — the growth number itself did not move
# ---------------------------------------------------------------------------
def test_closure_awareness_did_not_re_score_the_growth_population(tmp_path):
    """Closed entries are still counted as roots on both sides. Redefining the
    population to "open obligations only" would silently re-score every
    project carrying closure records, so it was deliberately not done: this
    pins the counts a document with a closure record produces."""
    rc, out = _run(_project(tmp_path, _steps(closed=True), _steps(closed=True)))

    assert out["summary"]["current_root_waivers"] == 1
    assert out["summary"]["baseline_root_waivers"] == 1
    assert out["summary"]["current_waivers_by_key"] == {"waived_steps": 1}
    assert out["summary"]["net_growth"] == 0
    assert rc == 0
