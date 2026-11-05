#!/usr/bin/env python3
"""Step 32 may now be told what fixing timing is allowed to COST.

THE DEFECT, MEASURED ON origin/main @ 46db018669
================================================
Step 32 repaired timing with NO area ceiling whatsoever, and a design that
declared one was ignored WITHOUT A TRACE. Run against the base revision in a
second worktree, verbatim:

    _reference_flow_pnr_mapping({"PL_RESIZER_SETUP_MAX_UTIL_PCT": "55",
                                 "PL_RESIZER_HOLD_MAX_UTIL_PCT":  "45",
                                 "RESIZER_RECOVER_POWER_PCT":     "100"})
      -> keys present for the three knobs: []
      -> notes    = []
      -> rejected = []      withheld = []
    "-max_utilization" in _post_buffered_repair_tcl(...)  -> False
    "-recover_power"  in _post_buffered_repair_tcl(...)   -> False

Not adopted, not rejected, not withheld — DROPPED. That is the shape this
repository keeps re-learning: an unmeasured thing and a measured zero produce
the same artefact. The ingest already had a vocabulary, a rejection channel and
a withholding channel; these three knobs simply were not in it.

WHAT THE TOOL ACTUALLY OFFERS, measured rather than recalled
============================================================
In the pinned image (`docker run --skip`, OpenROAD 26Q3-1535-g543c33894f):

    repair_timing [-setup] [-hold] [-recover_power percent_of_paths_with_slack]
       ... [-max_utilization util] ...
    repair_design [-max_wire_length ...] [-max_utilization util] ...

There is ONE `-max_utilization` in OpenROAD. LibreLane's
`PL_RESIZER_SETUP_MAX_UTIL_PCT` / `PL_RESIZER_HOLD_MAX_UTIL_PCT` pair is its own
FLOW-level split — the same tool flag with a different value on the `-setup` and
`-hold` calls. The port therefore lands as two flow parameters reaching two
invocations, which is what the tool supports.

NO DEFAULT IS INVENTED, and that is the load-bearing half
=========================================================
Undeclared means the deck is emitted EXACTLY as before. A ceiling nobody
declared would be a ruler fitted to the answer, and the right ceiling depends on
the die the design declared — which the flow does not get to pick either.
`test_an_undeclared_ceiling_reproduces_todays_deck_byte_for_byte` is the guard.
"""
from __future__ import annotations

import sys
from pathlib import Path


_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import phase3_one_shot_runner as P  # noqa: E402

KNOBS = ("PL_RESIZER_SETUP_MAX_UTIL_PCT", "PL_RESIZER_HOLD_MAX_UTIL_PCT",
         "RESIZER_RECOVER_POWER_PCT")
PARAMS = ("resizer_setup_max_util_pct", "resizer_hold_max_util_pct",
          "recover_power_pct")


# ══════════════════════════════════════════════════════════════════════
# The ingest: READ, and either ADOPTED or REJECTED — never dropped
# ══════════════════════════════════════════════════════════════════════
def test_the_three_knobs_are_in_the_one_vocabulary():
    """`_ORFS_PNR_KNOB_PARAMS` is the ingest's single vocabulary; a knob that is
    not in it cannot be read, reported or rejected."""
    for k in KNOBS:
        assert k in P._ORFS_PNR_KNOB_PARAMS, f"{k} is not in the vocabulary"


def test_they_are_optimization_class_not_routing_resource_supply():
    """They BOUND area consumption inside the floorplan phase 3 chose; they do
    not replace a self-calibrated quantity, so they must not be withheld."""
    for k in KNOBS:
        assert k not in P._ORFS_WITHHELD_PNR_KNOBS








# ══════════════════════════════════════════════════════════════════════
# The emission: the flag appears only when the design declared it
# ══════════════════════════════════════════════════════════════════════














# ══════════════════════════════════════════════════════════════════════
# The reader never raises: a project with no declaration still gets a deck
# ══════════════════════════════════════════════════════════════════════




def test_no_process_or_vendor_token_in_the_new_code():
    src = (_HERE.parent / "phase3_one_shot_runner.py").read_text()
    for fn in ("_resizer_bound_flag", "_recover_power_tcl",
               "_postroute_timing_repair_resizer_bounds"):
        i = src.index(f"def {fn}(")
        body = src[i:src.index("\ndef ", i + 10)].lower()
        for tok in ("tsmc", "samsung", "globalfound", "umc", "smic"):
            assert tok not in body, f"{fn} names {tok!r}"
