#!/usr/bin/env python3
"""--entry-step must not become a switch that turns MISSING into PASS.

A run may declare, before dispatching anything, that it entered the flow partway
through — a debug task arrives with RTL already written and already wrong, and
re-deriving documents it was never given is ceremony. Without a word for that,
the upstream steps report MISSING and the report reads exactly like a Phase 1
that ran and broke.

But the manifest is written BY THE RUN BEING JUDGED. Unconstrained, the flag is
the run grading its own scope. These tests pin the constraints that contain it.
The POSITIVE case proves the excuse can be granted at all; the NEGATIVE cases are
the load-bearing half (§ 4.05) — each is a boundary-outside fixture that must
STILL be refused, because a relaxation that leaks ships a real absence as green.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_PROGRAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _PROGRAMS)

import run_entry_manifest as R  # noqa: E402


def _project(tmp, files=()):
    p = Path(tmp)
    for f in files:
        fp = p / f
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text("{}")
    return p


def _manifest(project, entry="2"):
    m = R.build(project, entry, "design_one_shot_runner", "rtl_validate",
                ["--entry-step", entry], "2026-08-25T00:00:00Z")
    R.write(project, m)
    return m


# ── POSITIVE: the excuse CAN be granted ──────────────────────────────────────
def test_an_upstream_step_whose_consumed_outputs_are_present_is_excusable():
    with tempfile.TemporaryDirectory() as td:
        p = _project(td, ["phase1/generated_docs/L10_TEST_CASES.json"])
        m = _manifest(p)
        v = R.excusable(m, "D1",
                        ["phase1/generated_docs/L10_TEST_CASES.json",
                         "phase1/generated_docs/L3_CMD_PROTOCOL.json"],
                        ["phase1/generated_docs/L10_TEST_CASES.json"], p)
        assert v["excusable"], v["reason"]


# ── NEGATIVE no-leak: each must STILL be refused ─────────────────────────────
def test_an_absent_consumed_output_is_never_excused():
    """The anti-laundering rule: the artefacts must still BE there."""
    with tempfile.TemporaryDirectory() as td:
        p = _project(td)                       # nothing on disk
        m = _manifest(p)
        v = R.excusable(m, "D1",
                        ["phase1/generated_docs/L10_TEST_CASES.json"],
                        ["phase1/generated_docs/L10_TEST_CASES.json"], p)
        assert not v["excusable"]
        assert "ABSENT" in v["reason"].upper()


def test_a_step_that_is_not_upstream_is_never_excused():
    """A manifest may not widen its own scope to reach a downstream step."""
    with tempfile.TemporaryDirectory() as td:
        p = _project(td)
        m = _manifest(p, entry="2")            # upstream = D1, 0.5ic, 1
        v = R.excusable(m, "9", [], [], p)     # 9 is downstream of 2
        assert not v["excusable"]
        assert "not declared upstream" in v["reason"]


def test_a_hard_signoff_output_is_never_excused():
    """"We started late" is not a reason to have no DRC/LVS/STA evidence."""
    with tempfile.TemporaryDirectory() as td:
        p = _project(td)
        m = _manifest(p)
        v = R.excusable(m, "D1", ["reports/signoff/drc.rpt"], [], p)
        assert not v["excusable"]
        assert "sign-off" in v["reason"]


def test_a_phase1_constants_doc_is_not_mistaken_for_signoff():
    """`sta` is a substring of CON-STA-NTS. Unbounded, the sign-off veto matched
    L8_RTL_CONSTANTS.json and refused every excuse — the guard firing on a false
    positive is indistinguishable from the feature not working."""
    assert not R._HARD_SIGNOFF.search(
        "phase1/generated_docs/L8_RTL_CONSTANTS.json")
    assert R._HARD_SIGNOFF.search("reports/sta.rpt")
    assert R._HARD_SIGNOFF.search("phase3/lvs.rpt")
    assert not R._HARD_SIGNOFF.search("docs/installation.md")


def test_a_missing_manifest_excuses_nothing():
    with tempfile.TemporaryDirectory() as td:
        p = _project(td)
        assert not R.excusable(None, "D1", [], [], p)["excusable"]


def test_a_manifest_that_fails_validation_excuses_nothing():
    with tempfile.TemporaryDirectory() as td:
        p = _project(td)
        bad = {"schema": 99, "entry_step": "2", "runner": "x",
               "upstream_steps": []}
        assert not R.excusable(bad, "D1", [], [], p)["excusable"]


def test_a_manifest_may_not_declare_a_downstream_step_upstream():
    """Scope-widening caught at validation, before any excuse is considered."""
    with tempfile.TemporaryDirectory() as td:
        p = _project(td)
        m = R.build(p, "2", "design_one_shot_runner", "rtl_validate", [],
                    "2026-08-25T00:00:00Z")
        m["upstream_steps"].append({"id": "9", "disposition": "invented"})
        problems = R.validate(m)
        assert any("NOT upstream" in x for x in problems), problems


def test_stages_are_never_treated_as_steps():
    """The YAML declares `stages:` and `steps:`; a bare id scan returns both and
    put stage_phase1..stage5_manufacturing at the head of every upstream list."""
    ids = R.flow_step_ids()
    assert ids, "flow not read"
    assert not [i for i in ids if i.startswith("stage")], (
        "stage entities leaked into the step list")
    assert R.upstream_of("D1") == [], "D1 is the first step; nothing precedes it"


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v()
            print("PASS", k)
