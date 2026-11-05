#!/usr/bin/env python3
"""R-0915-84(a) — the repair optimised against a wire-load model.

MEASURED (opentitan_aes x sky130A, 2026-09-16). On ALL FOUR passes of the
post-route DRV loop, OpenROAD printed this immediately after the census:

    [INFO RCX-0045] Extract 41087 nets, ...
    SDR_DRV_BY_KIND: total=41956 max_capacitance=5805
    [WARNING EST-0027] no estimated parasitics. Using wire load models.

The census is sound: `read_spef` feeds STA, and R-0915-83's refusal proves it.
But the RESIZER keeps its own parasitics source and `read_spef` does not set
it, so `repair_design` / `repair_timing` ran on a WIRE LOAD MODEL while being
GRADED on the extracted SPEF. Four passes moved DRV 41,956 -> 19,013 -> 2,647
-> 1,896 and never closed, which is what a repair whose model disagrees with
its grader looks like. The same run's three-way table showed the scale of the
disagreement: the estimate under-reads extraction by 1.3x on a 0.8 um net and
7.2x on a 1,375 um one.

`estimate_parasitics -global_routing` is the resizer's own source, and is what
ORFS runs before its repair steps.

THE FIXTURE IS THE SHIPPING LOG. A test that only asserts on emitted text can
drift away from the failure it was written for, so the RED fixture here is the
four real occurrences and the GREEN one is a log of the same shape with the
warning absent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

sys.path.insert(0, str(Path(__file__).resolve().parent))

RED_LOG = """\
SDR_DRV_BY_KIND: total=41956 max_capacitance=5805
[WARNING EST-0027] no estimated parasitics. Using wire load models.
SDR_DRV_BY_KIND: total=19013 max_capacitance=4983
[WARNING EST-0027] no estimated parasitics. Using wire load models.
SDR_DRV_BY_KIND: total=2647 max_capacitance=599
[WARNING EST-0027] no estimated parasitics. Using wire load models.
SDR_DRV_BY_KIND: total=1896 max_capacitance=437
[WARNING EST-0027] no estimated parasitics. Using wire load models.
"""

GREEN_LOG = """\
SDR_DRV_BY_KIND: total=41956 max_capacitance=5805
SDR_RSZ_PARASITICS: estimate_parasitics -global_routing OK
SDR_DRV_BY_KIND: total=19013 max_capacitance=4983
SDR_RSZ_PARASITICS: estimate_parasitics -global_routing OK
"""


def blind_passes(log: str) -> list[int]:
    """Which passes repaired on wire load models, by the tool's own warning."""
    out, pending = [], None
    for ln in log.split("\n"):
        m = re.match(r"SDR_DRV_BY_KIND: total=(\d+)", ln)
        if m:
            pending = int(m.group(1))
        # THE TOOL'S OWN WARNING, not the token. The deck's own disclosure
        # line names EST-0027 so a reader knows what to look for, and a
        # detector that matched the bare token would count that disclosure as
        # the failure it warns about.
        elif ln.lstrip().startswith("[WARNING EST-0027]") and pending is not None:
            out.append(pending)
            pending = None
    return out




# ───────────────── the fixture detector works both ways ────────────────────

def test_the_detector_finds_all_four_blind_passes_in_the_shipping_log():
    """RED fixture. If this ever stops finding four, the fixture rotted."""
    assert blind_passes(RED_LOG) == [41956, 19013, 2647, 1896]


def test_the_detector_finds_none_in_a_clean_log():
    """GREEN fixture, and the control that keeps the detector from being a
    function that always returns a non-empty list."""
    assert blind_passes(GREEN_LOG) == []


# ───────────────── the deck gives the resizer a source ─────────────────────







# ───────────────────────── it still grades ─────────────────────────────────
