#!/usr/bin/env python3
"""Coverage disclosure for the Phase-3 reference-flow knob ingest (issue #198).

The sibling audit tests cover WHICH knobs are adopted and that each names its
source file. This file covers the DENOMINATOR — whether a finished run can be
audited for how much of the design's declaration it actually acted on.

Two gaps are pinned here, both reproduced against tracked corpus configs before
the fix, and both the same failure shape: NOT EXAMINED rendering exactly like
NOTHING TO EXAMINE.

  GAP-D  the audit reported an adopted-knob list with no denominator. A config
         declaring 16 assignments of which phase-3 honours 7 produced the same
         shape of report as a config declaring exactly those 7 — the names no
         phase-3 ingest reads were never counted and never listed, so a reader
         could not tell the run was configured differently from what the design
         declares.

  GAP-E  a staged config that could NOT be read reported `status="no-knobs"`,
         whose headline asserts "Nothing was silently ignored" — a clean
         verdict resting on files that were never opened. Likewise a staged
         file whose extension the scanner does not parse was neither adopted
         nor rejected nor mentioned: it simply vanished from the walk.

§4.05 fail-safe (LOAD-BEARING negative control): none of this changes a flow
parameter. A project with no staged config, and a project whose config is fully
read, must produce exactly the applied values they produce today — the ingest
DISCLOSES more, it does not decide differently.

chip-AGNOSTIC: every fixture below is synthetic. The recognised names are the
reference flow's OWN variable names, never a design/vendor/PDK-SKU literal.
"""
from __future__ import annotations

import importlib
import json

_rfb = importlib.import_module("_reference_flow_boundary")
_fc = importlib.import_module("floorplan_contract")

# A QoR-RULES artifact: metric -> expected value + comparison operator, plus a
# golden netlist hash. This is what the known-good run ACHIEVED, not how to
# configure a run — the oracle half of a mixed reference flow.
_ORACLE_RULES = json.dumps({
    "synth__netlist__hash": {"value": "0" * 40, "compare": "=="},
    "finish__timing__setup__ws": {"value": -0.5, "compare": ">="},
    "finish__design__instance__area": {"value": 177762, "compare": "<="},
    "detailedroute__route__drc_errors": {"value": 0, "compare": "<="},
})


# Three names phase-3 honours (two back-end, one synth-side) and four it
# honours nowhere — a realistic reference flow declares both kinds in one file.


# ---------------------------------------------------------------------------
# GAP-D — the denominator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GAP-E — an incomplete read must never render as a clean one
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# §4.05 NEGATIVE CONTROL — disclosure changes no flow parameter
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# §4.05 BOUNDARY — a staged reference flow is MIXED. Known oracle paths are
# excluded unopened. A neutral-named non-recipe file remains unexamined even
# when the synthetic fixture knows it contains oracle bytes.
# ---------------------------------------------------------------------------
class TestOracleBoundary:


    def test_classifier_needs_the_shape_to_dominate(self, tmp_path):
        assert _rfb.is_oracle_qor_rules(_ORACLE_RULES) is True
        assert _rfb.is_oracle_qor_rules('{"A": 1, "B": 2}') is False
        assert _rfb.is_oracle_qor_rules('not json') is False
        assert _rfb.is_oracle_qor_rules('{}') is False
        # one nested dict among many plain settings is a config, not a rules file
        assert _rfb.is_oracle_qor_rules(json.dumps({
            "A": 1, "B": 2, "C": 3,
            "D": {"value": 1, "compare": "=="}})) is False

    def test_reference_flow_is_not_in_the_shared_oracle_vocabulary(self):
        # The tree is MIXED, so its name must not be a blanket oracle marker;
        # known-oracle paths are excluded and neutral ones remain unexamined.
        assert "reference_flow" not in _rfb.ORACLE_TREE_SEGMENTS
        assert {"golden", "oracle", "ground_truth"} <= _rfb.ORACLE_TREE_SEGMENTS

    def test_contract_gate_stays_stricter_and_shares_the_vocabulary(self):
        # The sibling gate deliberately skips the whole tree (it has an
        # independent source). That is allowed, but both programs must agree on
        # what "oracle" means, so its set is built FROM the shared vocabulary.
        assert _rfb.ORACLE_TREE_SEGMENTS <= _fc._OFF_LIMITS_SEGMENTS
        assert "reference_flow" in _fc._OFF_LIMITS_SEGMENTS
