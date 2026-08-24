#!/usr/bin/env python3
"""Every nature's entry must name a REAL step in the canonical flow.

A routing table that returns "debug_loop" cannot be executed and cannot be
checked: nothing downstream can look "debug_loop" up in
flow/phase1_phase2_phase3.yaml, so a wrong entry stays wrong silently. These
tests pin the ids to the flow itself, so the table cannot drift away from it.

THE FIRST DRAFT OF THIS TABLE WAS WRONG IN FOUR OF FIVE ROWS, and the flow said
so. Each pin below records what the YAML actually declares:

  * P0 declares `blocks_on: [1]` and reads `from: 1` — it comes AFTER step 1.
    "P0 then 1" inverted both the declared edge and the execution order. P0 is
    an admission gate, never an entry.
  * Step 1 declares `from: D1, outputs: all` — 19 files. Entering at 1 without
    D1 is refused on all of them, and step 1's own required_output IS the RTL
    glob the user supplied, so it targets the file being completed.
  * Step 13 is "Equivalence check (RTL ≡ post-DFT netlist)". It proves synthesis
    did NOT change semantics; a functional modification deliberately DOES. That
    is a category error, not a missing input.
  * Step 4 reads two D1 artefacts (L10_TEST_CASES, L12_BEHAVIORAL_SEQUENCES) for
    its stimulus, so debug entry at 4 carries `entry_requires` naming them.
"""
import os
import re
import sys

_PROGRAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _PROGRAMS)

import task_nature_route as T  # noqa: E402


def test_the_table_validates_against_the_flow():
    problems = T.validate_entries()
    assert not problems, "entry table does not match the flow:\n" + "\n".join(problems)


def test_the_flow_was_actually_read():
    """A validator that silently sees an empty flow would pass everything."""
    ids = T.flow_step_ids()
    assert len(ids) > 40, f"only {len(ids)} step ids parsed — the flow was not read"
    for must in ("D1", "1", "2", "4", "5", "9", "13", "P0"):
        assert must in ids, f"flow parse lost step {must!r}"


def test_no_entry_is_a_loop_label():
    """The Change-4 regression: labels are not executable."""
    for nature, e in T.NATURE_ENTRY.items():
        for key in ("entry_step", "fallback_entry_step"):
            v = str(e.get(key) or "")
            assert not v.endswith("_loop"), f"{nature}.{key} is a label: {v!r}"


def test_p0_is_an_admission_gate_never_an_entry():
    """P0 blocks_on [1]; entering 'at P0' would precede the step it follows."""
    for nature, e in T.NATURE_ENTRY.items():
        assert e.get("entry_step") != "P0", (
            f"{nature} enters at P0, which the flow orders AFTER step 1")


def test_functional_modification_does_not_verify_via_step_13():
    """13 proves synthesis did NOT change semantics; a modification does."""
    e = T.NATURE_ENTRY["functional_modification"]
    assert "13" not in (e.get("verify_steps") or []), (
        "step 13 cannot verify a deliberate semantic change")
    assert "13" not in (e.get("then") or [])


def test_debug_enters_at_simulation_and_says_what_it_needs():
    e = T.NATURE_ENTRY["debug"]
    assert e["entry_step"] == "4", "debug must not be pushed through Phase 1"
    req = e.get("entry_requires") or []
    joined = " ".join(req)
    assert "L10_TEST_CASES" in joined and "L12_BEHAVIORAL_SEQUENCES" in joined, (
        "step 4 reads its stimulus from D1's L10/L12 — say so up front")
    assert e.get("fallback_entry_step") == "D1"
    assert len(str(e.get("fallback_reason") or "")) > 30, (
        "a fallback without a stated reason is a silent redirect")


def test_optimization_enters_at_the_only_rtl_only_step():
    """Step 2 declares exactly one input, `from: 1` — the supplied RTL."""
    e = T.NATURE_ENTRY["optimization"]
    assert e["entry_step"] == "2"
    assert "9" in (e.get("then") or []), "area is only measurable after synthesis"


def test_every_nature_is_routed_and_carries_an_entry():
    for nature, e in T.NATURE_ENTRY.items():
        assert e.get("entry_step"), f"{nature} has no entry_step"
        assert e.get("route") in ("phase1_entry", "plugin_loop")
        assert e.get("plugin_entry", {}).get("name"), f"{nature} has no loop name"


def test_classify_carries_the_entry_step_through():
    """The routing verdict must carry the step, not only the label."""
    v = T.classify_task_nature("this counter is buggy", True, "debug")
    assert v["nature"] == "debug"
    assert T.NATURE_ENTRY[v["nature"]]["entry_step"] == "4"


if __name__ == "__main__":
    for k, val in sorted(globals().items()):
        if k.startswith("test_"):
            val()
            print("PASS", k)
