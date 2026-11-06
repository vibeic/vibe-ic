"""The EM resize row must say what it DID, not only what was short.

MEASURED on spm x gf180mcuD (run11b, 2026-09-21). The deck the second PnR used
carried, verbatim:

    EM-derived strap floor applied (pdn_em_sizing.json): Metal4 3x stripes
    (pitch 51.2um, width 1.6 kept), Metal5 2x stripes (pitch 76.59um, width 1.6
    kept)

— R-0915-111's lever doing exactly what it was ruled to do: no strap widened,
the stripe count tripled, and `PDN_GRID_PRESENT` after pdngen. And the step row
a reviewer actually reads said:

    one-shot EM resize: Metal4 1.6->3.95um (2.4688x short), Metal5 1.6->1.77um
    (1.1062x short); PnR re-run once (407s).

Both sentences are about the same run. The first is the remedy; the second is
the SHORTFALL the width arithmetic derived before the stripe planner answered.
A reader of the row alone would conclude the flow widened two straps by 2.5x
and 1.1x, when it widened nothing. The FAIL verdict was honest — the second PnR
did fail — but the sentence was not.

So the deck records what it applied, the record is persisted beside the
arithmetic it came from, and the row reports both halves in the order a reader
needs them: SHORT BY ..., APPLIED ...
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()




# ------------------------------------------------- the deck records the remedy



def test_the_record_is_persisted_beside_the_arithmetic():
    assert '_szd["applied"] = _pdn_em_floor["applied"]' in SRC
    assert 'pdn_em_sizing.json' in SRC


def test_post_route_signoff_does_not_redispatch_pnr():
    """Step 25 must audit the routed geometry without changing its subject."""
    main = inspect.getsource(R.main)
    assert '_pdn_em_first_pass_resize(' not in main
    assert '_pnr_redispatched' not in main
    assert '_pnr_step_passed = _pnr_chain_continues(_pnr_row)' in main


# --------------------------------------------------------- both directions





def test_the_shortfall_is_not_misreported_as_an_applied_remedy():
    main = inspect.getsource(R.main)
    assert 'one-shot EM resize: SHORT BY' not in main
    assert '"pdn_em_resize", _pnr_redispatched.status' not in main


def test_signoff_keeps_the_original_pnr_row():
    main = inspect.getsource(R.main)
    assert '_pnr_row = next((s for s in reversed(plan) if s.name == "pnr"), None)' in main
    assert '_chain_ok = _pnr_step_passed' in main
