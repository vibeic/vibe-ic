#!/usr/bin/env python3
"""#316/#306 — the enforcement audit must itself be able to stop something.

`flow_gate_enforcement_audit` measures which gates can actually block a run.
It found 4 gates declaring an intent they are not wired for — and it exited 1
about that while being wired into nothing, which is the exact defect it
names, one level up.

Fixing those 4 changes what a REAL run blocks on: a flow-owner decision, not
this audit's. So they are recorded as DEBT and the audit blocks anything NEW.
The class stops growing without the audit quietly setting enforcement policy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "flow_gate_enforcement_audit.py"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"








def test_316_the_recorded_debt_is_named_not_hidden():
    """A count alone would let the register become a shrug. Every entry names
    its gate and which contract it broke.

    #306 paydown — this used to also assert the register was NON-EMPTY, on the
    reasoning that an empty one makes the gate vacuous. That had it backwards:
    empty is the state the whole register exists to reach, and asserting
    against it made paying the last entry a test failure. Emptiness is not what
    keeps this honest — `test_316_a_new_contradiction_fails` and
    `test_316_register_may_not_grow` are, and both now prove themselves against
    debt they construct rather than debt the tree happens to owe.
    """
    known = json.loads(_BASELINE.read_text())["known"]
    for k in known:
        kind, _, gate = k.partition("::")
        assert kind in ("contradiction", "orphan"), k
        assert gate and (_PROGRAMS / f"{gate}.py").is_file(), k
