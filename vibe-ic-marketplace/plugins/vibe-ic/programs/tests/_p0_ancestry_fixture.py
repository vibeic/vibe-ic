"""P0's declared ancestry — the premise every "stub the umbrella, read the
verdict" test rests on, and the one #923 silently removed.

WHAT BROKE
==========
`flow_compliance_check` forces a NON-PROMOTABLE `Overall: FAIL` whenever a step
that claims to be done has a transitive `blocks_on` ancestor that is applicable
and has not really PASSed::

    if ordering_fail_lines:
        forced_fail = True
    ...
    if not ok or forced_fail:
        overall = "FAIL"

and since v1.9.x a PASS in that position is additionally rewritten to
`PASS_VOIDED_BY_DEPENDENCY`, which `_flow_verdict_tiers` classifies NON_GREEN.

`P0` had no `blocks_on` edge until vibe-ic#923 wrote down the one it always had
in fact — `blocks_on: [1]`, and step 1 `blocks_on: [D1]`. The edge is right:
P0 reads step 1's RTL, so a FAILED Phase 1 must red it. But a synthetic fixture
project — one `rtl/top.v` and no phase-1 or spec-to-RTL artefacts — leaves every
one of those ancestors MISSING. So from #923 onward every test that stubs the P0
umbrella and then reads the RUN's verdict stopped measuring its own subject and
started measuring that edge.

It shows up in both directions, which is why this module exists rather than a
per-test patch:

  * the `rc == 0` / `overall == "PASS"` assertions went RED — seven of them, on
    `origin/main`, for a reason none of them is about;
  * the `rc == 1` assertions in the same files went VACUOUS — the ordering guard
    forces FAIL whatever the records say, so they could no longer tell a
    consumer that reads records from one that reads prose.

WHAT THIS DOES
==============
Neutralises exactly that edge and nothing else: the steps `P0` itself declares
it depends on are reported PASS, so the ordering guard has nothing to say and
the verdict is decided, once again, by the P0 population under test. Every other
step is left to the real `check_step` — the fixture project still has no
artefacts, those steps are still MISSING, and the run is still judged on them.

DISCOVERED, NOT ENUMERATED. The ancestry is read out of the shipped flow
definition and walked with the producer's OWN `_ancestors`, the same function
the ordering guard walks it with. No step id is written down here, so an edge
added to P0 tomorrow is followed without editing this file — and an edge
DELETED tomorrow shrinks what is neutralised rather than leaving a stale
hard-coded exemption behind.

A WAIVED STEP IS LEFT ALONE. Waivers are applied inside `check_step`, so a
fixture that waives a step must reach the real function or the waiver path stops
being real. This module delegates whenever the project's own `waivers.json`
names the step, which keeps the step-level-waiver guards honest.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Set

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as F                      # noqa: E402
import flow_step_execution_coverage_check as _COV      # noqa: E402

#: The umbrella whose ancestry these fixtures have to satisfy.
P0 = "P0"


def p0_ancestry(flow_def: Path | None = None) -> Set[str]:
    """The transitive `blocks_on` ancestry of `P0`, as ids, from the flow def.

    Walked with `flow_step_execution_coverage_check._ancestors` — the function
    the ordering guard itself uses — so this cannot drift from the rule it is
    compensating for.
    """
    path = Path(flow_def) if flow_def else Path(F.DEFAULT_FLOW_DEF)
    flow = yaml.safe_load(path.read_text())
    graph = {str(s.get("id")): [str(e) for e in (s.get("blocks_on") or [])]
             for s in flow.get("steps", []) if s.get("id") is not None}
    assert P0 in graph, (
        f"the flow definition at {path} declares no {P0!r} step; the fixtures "
        f"that stub the {P0} umbrella have nothing to attach to")
    return set(_COV._ancestors(P0, graph))


def satisfy_p0_ancestry(monkeypatch) -> Set[str]:
    """Report `P0`'s declared ancestry PASS for the duration of one test.

    Returns the ancestry it neutralised, so a caller can assert the fixture was
    not a no-op. Asserts non-empty here too: if `P0` ever loses its edges this
    helper silently becomes decorative, and a decorative fixture is how the
    vacuity above went unnoticed in the first place.
    """
    ancestry = p0_ancestry()
    assert ancestry, (
        f"{P0} declares no `blocks_on` ancestry, so this fixture neutralises "
        f"nothing — either the edge vibe-ic#923 added was removed (and the "
        f"tests using this helper need re-deriving) or the flow failed to load")
    real_check_step = F.check_step

    def _stub(project, step: Dict[str, Any], waivers: Dict, **kw):
        raw_id = step.get("id")
        try:
            sid = int(raw_id)
        except (ValueError, TypeError):
            sid = raw_id
        if str(raw_id) in ancestry and sid not in waivers and raw_id not in waivers:
            return F.StepResult(
                id=raw_id, name=step.get("name", ""),
                stage=step.get("stage", ""), status="PASS",
                reasons=[f"(test fixture) declared ancestor of {P0}, reported "
                         f"PASS so the ordering guard is not the thing under "
                         f"test"],
                evidence=[])
        return real_check_step(project, step, waivers, **kw)

    monkeypatch.setattr(F, "check_step", _stub)
    return ancestry
