#!/usr/bin/env python3
"""Tests for the Phase-3 REFERENCE-FLOW QoR-KNOB INGEST — FLOORPLAN / PLACE /
CTS / TIMING side (issue #198 Branch 1) in phase3_one_shot_runner.py.

The synth-side knobs (SWAP_ARITH_OPERATORS / ADDER_MAP_FILE / REMOVE_ABC_BUFFERS
/ FASTROUTE_LAYER_ADJUST) are covered by test_reference_flow_qor_knobs.py. This
file covers the NUMERIC back-end knobs a design's staged ORFS reference flow
declares to close timing — the floorplan core-util, the global-placement
density, the CTS sink-clustering, and the repair_timing TNS budget — which
phase-3 previously ignored (ibex: our generic recipe −45.05 ns vs the ORFS
reference recipe −0.5 ns on identical RTL).

`_reference_flow_pnr_knobs(project)` ingests ONLY the ORFS knob NAMES the design
literally declares (chip-AGNOSTIC), `_reference_flow_pnr_mapping(knobs)` maps
each to the concrete OpenROAD parameter, and `_build_pnr_tcl_text` emits the
directive ONLY when the knob is present.

§4.05 NO-LEAK gates covered here (LOAD-BEARING):
  * No reference_flow staged → {} → the generated pnr.tcl is BYTE-IDENTICAL to
    the legacy flow and the placement `util` is unchanged.
  * A knob is applied ONLY when the design literally declares a VALID numeric
    value; a non-numeric / out-of-range declaration is dropped, never fabricated.
  * Only the ORFS knob NAMES are recognized — an arbitrary design var never
    leaks in.

Docker-free: the emit tests build the tcl string and (when tclsh is present)
parse it with all OpenROAD commands stubbed. No container is spawned.
"""
from __future__ import annotations

import importlib

import pytest


mod = importlib.import_module("phase3_one_shot_runner")



# The exact knobs ibex ships in input/reference_flow/orfs_config.mk.


# ---------------------------------------------------------------------------
# Ingest: _reference_flow_pnr_knobs
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Map: _reference_flow_pnr_mapping
# ---------------------------------------------------------------------------
class TestPnrKnobMapping:


    def test_withheld_class_is_derived_from_the_knob_vocabulary(self,
                                                                tmp_path):
        """The class is a property of the flow PARAMETER a knob feeds, read off
        the one vocabulary table — not a second hand-maintained knob list that
        could drift away from it.

        The parameter names are checked against the ones the PRODUCER actually
        emits, not against a literal restated here: a rename in the producer
        would otherwise leave `_RF_ROUTING_SUPPLY_PARAMS` matching nothing, and
        the whole class would silently empty out — a withhold that stops
        withholding while every other assertion in this file still passes."""
        assert mod._ORFS_WITHHELD_PNR_KNOBS == frozenset(
            k for k, params in mod._ORFS_PNR_KNOB_PARAMS.items()
            if mod._RF_ROUTING_SUPPLY_PARAMS.intersection(params))
        assert mod._ORFS_WITHHELD_PNR_KNOBS, "the class must not be empty"
        # every recognized PnR knob is in the vocabulary …
        # … and every parameter named in it is one the audit really reports.
        for knob, params in mod._ORFS_PNR_KNOB_PARAMS.items():
            assert params, knob


# ---------------------------------------------------------------------------
# Auto-die precedence: reference_flow feeds the die-util target (below L9)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Emission: _build_pnr_tcl_text — None byte-identical / knobs injected
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
