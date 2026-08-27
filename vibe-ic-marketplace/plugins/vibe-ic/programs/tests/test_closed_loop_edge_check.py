#!/usr/bin/env python3
"""Tests for closed_loop_edge_check.py — a declared `closed_loop` must be an
edge something can actually take.

THE POINT OF THIS FILE IS THE RED, NOT THE GREEN.

Before this check existed, NOTHING in the repository read `closed_loop`: 19
declarations in the canonical flow, zero consumers, and the 63x8 harness even
shipped an unused `flowref.closed_loop` accessor. A `fallback_to` naming a step
that does not exist would have passed every gate here. So the green over the
shipped flow proves only that the shipped flow is healthy; each RED below proves
the check would have SEEN the corresponding rot, and they are executed against a
real mutant of the real document rather than a hand-built toy.

`test_the_shipped_flow_is_green` and the mutants together are the bidirectional
control: a check that cannot fail against the pre-fix shape proves nothing.

Fixtures mutate a COPY of the shipped flow; nothing here writes the real one.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
PROG = _HERE.parent / "closed_loop_edge_check.py"
FLOW = _HERE.parent.parent / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_HERE.parent))


def _run(flow: Path, *extra):
    return subprocess.run(
        [sys.executable, str(PROG), "--flow", str(flow), *extra],
        capture_output=True, text=True)


def _doc():
    return yaml.safe_load(FLOW.read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc) -> Path:
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


def _step(doc, sid):
    for s in doc["steps"]:
        if str(s["id"]) == str(sid):
            return s
    raise AssertionError(f"step {sid} not in the flow")


#: A step that declares a closed_loop today and is therefore a live edit site.
#: Named rather than searched so that the day it stops declaring one, this file
#: fails loudly instead of quietly testing nothing.
WITNESS = "24"


# ══════════════════════════════════════════════════════════════════════
# The green half
# ══════════════════════════════════════════════════════════════════════
def test_the_shipped_flow_is_green():
    r = _run(FLOW)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_the_denominator_is_disclosed_on_every_run(tmp_path):
    """A green over an unstated denominator is how a check quietly dies."""
    r = _run(FLOW)
    assert "declared closed_loop edge(s) over" in r.stdout
    out = tmp_path / "r.json"
    _run(FLOW, "--json", str(out))
    rep = json.loads(out.read_text())
    assert rep["declarations"] == len(rep["declaring_steps"]) > 0
    assert rep["declarations"] == sum(
        1 for s in _doc()["steps"] if isinstance(s.get("closed_loop"), dict))


def test_the_witness_still_declares_a_closed_loop():
    assert isinstance(_step(_doc(), WITNESS).get("closed_loop"), dict), (
        f"step {WITNESS} no longer declares a closed_loop; the mutants below "
        f"would be editing a key that is not there and would test nothing")


# ══════════════════════════════════════════════════════════════════════
# The red half — one mutant per predicate, run against the REAL document
# ══════════════════════════════════════════════════════════════════════
def test_a_phantom_fallback_reddens(tmp_path):
    doc = _doc()
    _step(doc, WITNESS)["closed_loop"]["fallback_to"] = "zzz-no-such-step"
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CL-FALLBACK-UNRESOLVED" in r.stdout
    assert "no step with that id is declared at all" in r.stdout


def test_a_raw_type_mismatch_reddens_and_says_why(tmp_path):
    """`flow_compliance_check` keys the cascade graph on the RAW id, so a
    string '15' where the step declares the int 15 resolves to nothing THERE
    while looking fine to a reader. Dimension 5 learned this for `blocks_on`."""
    doc = _doc()
    fb = _step(doc, WITNESS)["closed_loop"]["fallback_to"]
    assert isinstance(fb, int), f"witness fallback is already {type(fb)}"
    _step(doc, WITNESS)["closed_loop"]["fallback_to"] = str(fb)
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CL-FALLBACK-UNRESOLVED" in r.stdout
    assert "keys the cascade graph on the RAW id" in r.stdout


def test_a_missing_trigger_reddens(tmp_path):
    doc = _doc()
    _step(doc, WITNESS)["closed_loop"].pop("trigger", None)
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CL-NO-TRIGGER" in r.stdout


def test_an_empty_trigger_reddens(tmp_path):
    doc = _doc()
    _step(doc, WITNESS)["closed_loop"]["trigger"] = "   "
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CL-NO-TRIGGER" in r.stdout


def test_a_missing_fallback_reddens(tmp_path):
    doc = _doc()
    _step(doc, WITNESS)["closed_loop"].pop("fallback_to", None)
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CL-NO-FALLBACK" in r.stdout


def test_an_edge_that_does_not_close_a_loop_reddens(tmp_path):
    """A `fallback_to` that neither returns to the step nor hands off to
    something waiting on it is not a loop, however plausible it reads."""
    doc = _doc()
    ids = [str(s["id"]) for s in doc["steps"]]

    def anc(sid, by):
        out, stack = set(), [sid]
        while stack:
            for p in (by.get(stack.pop(), {}).get("blocks_on") or []):
                if str(p) not in out:
                    out.add(str(p))
                    stack.append(str(p))
        return out

    by = {str(s["id"]): s for s in doc["steps"]}
    target = next(t for t in ids
                  if t != WITNESS and t not in anc(WITNESS, by)
                  and WITNESS not in anc(t, by))
    _step(doc, WITNESS)["closed_loop"]["fallback_to"] = by[target]["id"]
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, (
        f"fallback {WITNESS}->{target} closes no loop and was accepted\n"
        + r.stdout + r.stderr)
    assert "CL-NOT-A-LOOP" in r.stdout


def test_a_closed_loop_on_a_gateless_step_reddens(tmp_path):
    """Nothing can produce the verdict the trigger names, so the edge can never
    be taken."""
    doc = _doc()
    _step(doc, WITNESS).pop("gate", None)
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CL-NO-GATE" in r.stdout


def test_an_empty_gate_dict_is_also_gateless(tmp_path):
    doc = _doc()
    _step(doc, WITNESS)["gate"] = {"all_of": []}
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CL-NO-GATE" in r.stdout


# ══════════════════════════════════════════════════════════════════════
# A BARE clause is legal — the check was wrong about this once
# ══════════════════════════════════════════════════════════════════════
def test_a_bare_gate_clause_is_a_gate(tmp_path):
    """Step 13 ships `gate: {program_exit_zero: "..."}` with no `all_of`.

    The first draft of this check accepted only list-valued gate keys and
    reported step 13 as gate-less. That was the CHECK being wrong, not the flow.
    A regression here would re-manufacture a finding against a healthy step.
    """
    doc = _doc()
    thirteen = _step(doc, "13")
    assert isinstance(thirteen["gate"].get("program_exit_zero"), str), (
        "step 13 no longer carries a bare gate clause; this regression guard "
        "needs a new witness")
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 0, r.stdout + r.stderr


# ══════════════════════════════════════════════════════════════════════
# "Could not read it" must never look like "read it, it was clean"
# ══════════════════════════════════════════════════════════════════════
def test_zero_declarations_is_a_refusal_not_a_pass(tmp_path):
    doc = _doc()
    for s in doc["steps"]:
        s.pop("closed_loop", None)
    r = _run(_write(tmp_path, doc))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT_MEASURED" in r.stdout
    assert "empty denominator" in r.stdout
    assert "[PASS]" not in r.stdout


def test_an_unreadable_flow_is_a_refusal_not_a_pass(tmp_path):
    bad = tmp_path / "flow.yaml"
    bad.write_text("steps: not-a-list\n")
    r = _run(bad)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT_MEASURED" in r.stdout
    assert "[PASS]" not in r.stdout


def test_a_missing_flow_is_a_refusal_not_a_pass(tmp_path):
    r = _run(tmp_path / "does-not-exist.yaml")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT_MEASURED" in r.stdout


# ══════════════════════════════════════════════════════════════════════
# The invariant that was measured before it was asserted
# ══════════════════════════════════════════════════════════════════════
def test_the_ancestor_rule_was_rejected_for_a_reason(tmp_path):
    """Two shipped edges hand FORWARD to the timing-repair scheduler and are healthy.

    If a future author 'tightens' CL-NOT-A-LOOP to require an ancestor, this
    test tells them exactly which two cells they just reddened.
    """
    import closed_loop_edge_check as M
    doc = _doc()
    by = {str(s["id"]): s for s in doc["steps"]}
    forward = []
    for s in doc["steps"]:
        cl = s.get("closed_loop")
        if not isinstance(cl, dict):
            continue
        sid, fb = str(s["id"]), str(cl.get("fallback_to"))
        if fb != sid and fb not in M.ancestors(sid, by):
            forward.append((sid, fb))
            assert M.closes_a_loop(sid, fb, by), (
                f"{sid}->{fb} neither returns nor is waited on")
    assert forward, (
        "no forward hand-off edge remains in the flow; the ancestor rule would "
        "now be safe to assert and CL-NOT-A-LOOP could be tightened")


def test_the_program_names_no_process_or_vendor_token():
    src = PROG.read_text().lower()
    for tok in ("sky130", "gf180", "sg13g2", "tsmc", "samsung", "globalfound",
                "intel", "umc", "smic"):
        assert tok not in src, f"{PROG.name} names {tok!r}"
