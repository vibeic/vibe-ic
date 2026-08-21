#!/usr/bin/env python3
"""The OSS-constraint deferral table must defer the steps it says it defers.

`_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS` decides which FAILing steps may be
promoted to PASS_WITH_OPEN_SOURCE_CONSTRAINTS. It is consumed as
`r.id in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`, so the KEY is load-bearing and
the label is prose.

The keys drifted. Two steps were inserted into the flow yaml and the table was
never re-keyed, so from key 21 onward every label named a step one or two later
than its key -- and the flow was quietly deferring Routing, Post-route STA,
Post-Layout Gate-Level Simulation and Post-route timing repair under labels
describing Parasitic Extraction, IR Drop, PV and Metal Fill.

That is a false PASS with the tier's own premise inverted. The tier exists for
work the open-source container CANNOT do; the container routes (TritonRoute),
runs multi-corner STA (OpenSTA), simulates gate-level with SDF (iverilog) and
repairs post-route timing (OpenROAD repair_design/repair_timing) perfectly well.

Two guards, because the drift can come back two ways.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))
import flow_compliance_check as fcc  # noqa: E402

TABLE = fcc._OPEN_SOURCE_CONTAINER_BLOCKED_STEPS


def _yaml_step_names():
    """{id: name} for every numbered step in the canonical flow."""
    doc = yaml.safe_load(FLOW.read_text())
    names = {}

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                names[o["id"]] = str(o["name"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return {k: v for k, v in names.items() if isinstance(k, int)}


# ---------------------------------------------------------------------------
# Guard 1 — the steps the container demonstrably performs may never be deferred.
#
# Named by what the step IS, resolved from the yaml, so renumbering the flow
# cannot smuggle them back in the way it smuggled them in the first time.
# ---------------------------------------------------------------------------
_CONTAINER_PERFORMS = [
    ("Routing", "TritonRoute routes global + detailed"),
    ("Post-route STA", "OpenSTA runs multi-corner multi-mode"),
    ("Post-Layout Gate-Level Simulation", "iverilog runs post-sim with SDF"),
    ("Post-route timing repair", "OpenROAD repair_design / repair_timing"),
]


@pytest.mark.parametrize("needle,why", _CONTAINER_PERFORMS)
def test_a_step_the_container_performs_is_never_deferrable(needle, why):
    names = _yaml_step_names()
    hits = [sid for sid, nm in names.items() if needle.lower() in nm.lower()]
    assert hits, f"no flow step matches {needle!r} -- fixture is stale"
    for sid in hits:
        assert sid not in TABLE, (
            f"step {sid} ({names[sid]}) is deferrable, but {why}. A FAIL there "
            f"can be promoted to PASS_WITH_OPEN_SOURCE_CONSTRAINTS, which "
            f"attests a tool limitation that does not exist.")


# ---------------------------------------------------------------------------
# Guard 2 — a key must be talking about its own step.
#
# The drift was invisible because nothing ever compared the label to the step.
# Every numbered entry has to share a content word with the name of the step it
# defers; an entry describing some other step is drift, whichever direction the
# numbering moved.
# ---------------------------------------------------------------------------
_STOP = {"the", "and", "a", "an", "of", "for", "to", "in", "on", "check",
         "checks", "signoff", "sign", "off", "only", "not", "but", "with",
         "is", "it", "no", "or", "per", "via", "pass", "step", "steps",
         "open", "source", "container", "tool", "tools", "run", "runs"}


def _words(text):
    # Two-letter tokens are kept: `EM` and `IR` are the whole content of two of
    # these step names, and dropping them made this test report drift on a
    # correctly-keyed entry.
    out = set()
    for raw in text.replace("/", " ").replace("-", " ").replace("+", " ").split():
        w = "".join(c for c in raw.lower() if c.isalnum())
        if len(w) >= 2 and w not in _STOP:
            out.add(w)
    return out


def test_every_numbered_entry_describes_the_step_it_defers():
    names = _yaml_step_names()
    drifted = []
    for sid, label in TABLE.items():
        if not isinstance(sid, int):
            continue                      # M1-M4 / A-step entries are by name
        step = names.get(sid)
        assert step, f"deferral table lists step {sid}, which the flow has not"
        # Compare only the label's leading clause -- the trailing parenthetical
        # names commercial tools, which no flow step name ever mentions.
        head = label.split("(")[0]
        if not (_words(head) & _words(step)):
            drifted.append(f"key {sid} says {head.strip()!r} "
                           f"but step {sid} is {step!r}")
    assert not drifted, (
        "the deferral table defers steps other than the ones it names:\n  "
        + "\n  ".join(drifted))


def test_the_prerequisite_steps_are_not_themselves_deferrable():
    """Promotion requires steps 6 and 36 to PASS. If either could itself be
    deferred, the tier would bootstrap its own precondition."""
    for sid in getattr(fcc, "_OS_CONSTRAINTS_PREREQ_STEPS", (6, 36)):
        assert sid not in TABLE, (
            f"step {sid} gates the promotion AND is deferrable — the tier "
            f"could satisfy its own prerequisite by deferring it")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
