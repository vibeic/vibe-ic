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

BOTH DIRECTIONS ARE PINNED, AND THEY ARE PINNED DIFFERENTLY.

  * The FAILING direction asserts the EXIT CODE first. Against the unfixed
    program these fail with `0 != 1` — a verdict the gate could not reach, not
    a missing dictionary key.
  * Three of the PASSING-direction tests read the new summary field through
    `_reopened`, which tolerates its absence, so they are green against the
    UNFIXED program too: `..._stays_closed_still_passes`,
    `..._closing_a_waiver_..._is_not_a_reopen` and
    `..._did_not_re_score_the_growth_population`. That is deliberate. A green
    test that only passes once a new field exists says nothing about whether
    the gate still reaches PASS; these have to hold on both sides to mean
    "not always-fail".

`..._a_disclosed_reopen_is_reported_without_failing` is the one exception and
is stated as such: its VERDICT (rc 0) holds on both sides, but it also demands
the WARN finding, which only the fixed program emits.

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


def _project(root: Path, current: dict, baseline: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "waivers.json").write_text(json.dumps(current))
    state = root / ".vibe-ic-state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "waivers_baseline.json").write_text(json.dumps(baseline))
    return root


def _run(project: Path):
    """`(returncode, parsed_json)` — the gate's own emitted verdict."""
    r = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json"],
        capture_output=True, text=True)
    assert r.returncode in (0, 1), f"unexpected rc={r.returncode}\n{r.stderr}"
    return r.returncode, json.loads(r.stdout)


def _reopened(out: dict) -> list:
    """Tolerates the field's absence so the PASS-direction tests are green
    against the unfixed program as well — see the module docstring."""
    return out["summary"].get("reopened_waivers", [])


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

    assert rc == 1, "a reopened waiver did not produce a failing verdict"
    assert out["summary"]["pass"] is False

    # The growth route could not have produced that verdict.
    assert out["summary"]["net_growth"] == 0
    assert out["summary"]["new_waivers"] == []
    assert out["summary"]["removed_waivers"] == []

    assert [f for f in out["findings"] if f["category"] == "WAIVER_REOPENED"]
    assert out["summary"]["reopened_waivers"], "the reopen was not named"


def test_the_attestation_dialect_reopen_is_caught_too(tmp_path):
    """The second dialect keys on (step, phase, ticket) and closes with
    `closure_proof`. A gate that only saw one dialect's closure would leave
    half the corpus with the same unreachable verdict."""
    rc, out = _run(_project(tmp_path,
                            _attestation(closed=False),
                            _attestation(closed=True)))

    assert rc == 1
    assert out["summary"]["net_growth"] == 0
    assert len(out["summary"]["reopened_waivers"]) == 1
    assert [f for f in out["findings"] if f["category"] == "WAIVER_REOPENED"]


def test_a_token_reopen_rationale_does_not_buy_a_pass(tmp_path):
    """The hatch carries the same substance bar as `growth_rationale`. A
    one-word field is not a justification, and a hatch that opens for one is
    the rubber stamp the waiver gates exist to refuse."""
    rc, out = _run(_project(tmp_path,
                            _steps(closed=False, reopen_rationale="needed"),
                            _steps(closed=True)))

    assert rc == 1
    assert out["summary"]["reopened_waivers_disclosed"] == []
    assert [f for f in out["findings"] if f["category"] == "WAIVER_REOPENED"]


# ---------------------------------------------------------------------------
# Direction 2 — PASS is still reachable (green on BOTH sides of the fix)
# ---------------------------------------------------------------------------
def test_a_closed_waiver_that_stays_closed_still_passes(tmp_path):
    """Closure records in BOTH documents, unchanged. Reading closure state
    must not turn "this waiver is still closed" into a finding — a gate that
    can only say FAIL is the same defect wearing the other sign."""
    rc, out = _run(_project(tmp_path, _steps(closed=True), _steps(closed=True)))

    assert rc == 0
    assert out["summary"]["pass"] is True
    assert _reopened(out) == []
    assert [f for f in out["findings"]
            if f["category"].startswith("WAIVER_REOPENED")] == []


def test_closing_a_waiver_since_the_baseline_is_not_a_reopen(tmp_path):
    """The opposite transition — open in the baseline, closed now — is work
    being finished. It must stay a PASS, in both dialects."""
    for name, current, baseline in (
            ("steps", _steps(True), _steps(False)),
            ("attestation", _attestation(True), _attestation(False))):
        rc, out = _run(_project(tmp_path / name, current, baseline))
        assert rc == 0, name
        assert _reopened(out) == [], name


def test_a_disclosed_reopen_is_reported_without_failing(tmp_path):
    """The escape hatch is operator-written and lives in the waiver document.
    It downgrades to a WARN — reported, not refused — and the run stays green,
    so a legitimate reopen does not force anyone to delete the baseline's
    closure record to get a PASS."""
    rc, out = _run(_project(tmp_path,
                            _steps(closed=False, reopen_rationale=_LONG_ENOUGH),
                            _steps(closed=True)))

    assert rc == 0
    assert out["summary"]["pass"] is True
    warns = [f for f in out["findings"]
             if f["category"] == "WAIVER_REOPENED_DISCLOSED"]
    assert len(warns) == 1 and warns[0]["severity"] == "WARN"
    assert out["summary"]["reopened_waivers_disclosed"] == out["summary"][
        "reopened_waivers"] != []


# ---------------------------------------------------------------------------
# Blast radius — the growth number itself did not move
# ---------------------------------------------------------------------------
def test_closure_awareness_did_not_re_score_the_growth_population(tmp_path):
    """Closed entries are still counted as roots on both sides. Redefining the
    population to "open obligations only" would silently re-score every
    project carrying closure records, so it was deliberately not done: this
    pins the counts a document with a closure record produces, and is green
    against the unfixed program for exactly that reason."""
    rc, out = _run(_project(tmp_path, _steps(closed=True), _steps(closed=True)))

    assert rc == 0
    assert out["summary"]["current_root_waivers"] == 1
    assert out["summary"]["baseline_root_waivers"] == 1
    assert out["summary"]["current_waivers_by_key"] == {"waived_steps": 1}
    assert out["summary"]["net_growth"] == 0
