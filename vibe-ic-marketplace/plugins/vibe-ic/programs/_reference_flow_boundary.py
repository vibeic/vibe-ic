#!/usr/bin/env python3
"""The §4.05 boundary inside a design's staged reference flow — ONE definition,
shared by every program that walks that tree, so two programs can never hold
contradictory positions about what is oracle.

WHY THIS MODULE EXISTS
----------------------
Two shipped programs disagreed. `floorplan_contract` skipped the whole
``reference_flow`` tree as "golden / oracle / expected-solution", while
`phase3_one_shot_runner` ingested flow knobs out of that same tree at three
live apply sites. Both cannot be right about the same directory.

Resolved by reading what those directories actually contain, across every
design in the tracked corpus that has one:

  RECIPE (design INPUT — says HOW to run).  Flow config and constraint files:
  utilization / placement-density / CTS-clustering targets, clock period, IO
  timing budgets, module parameters, tool invocation. Upstream flow scripts
  carried verbatim. They state the design's intended configuration and contain
  no result the run is supposed to produce.

  ORACLE (OFF-LIMITS — says WHAT the known-good run ACHIEVED).  A QoR-rules
  artifact: metric name -> expected value plus a comparison operator, and
  hashes of the golden netlist. Reading it would hand a run the target timing,
  area and wirelength it is supposed to independently achieve, plus a
  fingerprint of the correct answer.

So the directory NAME is not the discriminator; the CONTENT SHAPE is. A
reference flow is MIXED, and the boundary runs between files inside it.

CONSEQUENCE FOR REPORTING: declining to read the oracle artifact is COMPLIANCE,
not a coverage gap. It must never be reported as an unexamined file, because
that invites the next reader to "close the gap" by parsing the golden metrics.

chip-AGNOSTIC: pure directory-name vocabulary and pure structural shape. No
design, vendor, or PDK-SKU literal appears here or is needed.
"""
from __future__ import annotations

import json
from typing import FrozenSet, Tuple

# Directory-name vocabulary for trees that are oracle END TO END — a known-good
# solution or expected output. NOTHING reads inside these, ever. `reference_flow`
# is deliberately NOT here: it is mixed, and its oracle subset is identified by
# `is_oracle_qor_rules` on content instead.
ORACLE_TREE_SEGMENTS: FrozenSet[str] = frozenset({
    "golden", "oracle", "expected", "expected_output",
    "solution", "solutions", "answer", "answers", "ground_truth",
})

# Directory-name vocabulary for the STAGED REFERENCE FLOW tree itself. This is
# NOT a claim that the tree is oracle end to end — measured over the tracked
# corpus it is MIXED (recipe config + one QoR-rules oracle artifact), which is
# exactly why `is_oracle_qor_rules` exists. It is the vocabulary a program uses
# when it wants the STRICTER rule: skip the whole tree because it has an
# independent source for what it needs, so reading in there buys nothing and
# costs a §4.05 exposure.
REFERENCE_FLOW_TREE_SEGMENTS: FrozenSet[str] = frozenset({
    "reference_flow", "ref_flow", "reference",
})

# The strict union: every directory-name segment a program must not read from,
# NAME in a diagnostic, or point a design author at. Defined ONCE here so a
# third copy of this vocabulary can never drift from the first two.
#
# NAMING matters as much as reading: a diagnostic that cites
# `.../reference_flow/pre_syn/golden.sdc` as "the file you should have used"
# hands the author the oracle's location just as effectively as parsing it
# would. A program that walks a project tree to build a message therefore
# prunes on this set, and reports the pruned directories only by COUNT.
OFF_LIMITS_TREE_SEGMENTS: FrozenSet[str] = frozenset(
    ORACLE_TREE_SEGMENTS | REFERENCE_FLOW_TREE_SEGMENTS)

# File extensions that carry RECIPE (flow configuration) and are therefore
# legitimate to parse for declared knobs.
RECIPE_SUFFIXES: Tuple[str, ...] = (".mk", ".tcl")


def is_oracle_qor_rules(text: str) -> bool:
    """True when ``text`` is a QoR-RULES artifact: a JSON object mapping metric
    names to an EXPECTED VALUE plus a COMPARISON OPERATOR (and, in practice,
    golden netlist hashes alongside). That combination is the signature of a
    recorded known-good result, not of a configuration — a config states a
    setting, never a threshold the run must be measured against.

    Used to LABEL a staged file as off-limits. The caller must discard the
    parsed content immediately: this is a classifier, never an extractor, and
    no value read here may reach the flow.

    Structural and chip-AGNOSTIC — keys are never inspected for meaning, only
    the value shape is.
    """
    stripped = (text or "").lstrip()
    if not stripped.startswith("{"):
        return False
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return False
    if not isinstance(obj, dict) or not obj:
        return False
    graded = sum(
        1 for v in obj.values()
        if isinstance(v, dict) and "compare" in v and "value" in v)
    # Every graded entry pairs an expectation with an operator. Requiring the
    # shape to DOMINATE keeps a config that merely happens to nest a dict from
    # being misread as an oracle.
    return graded > 0 and graded * 2 >= len(obj)
