"""R-0915-63: an output owed by a step the design declares N/A is not owed.

MEASURED 2026-09-16, run33 on main 7700250eb. Phase 3 refused to dispatch::

    [preflight] pnr: REFUSED TO RUN: 1 declared input(s) ABSENT —
      phase2/stage2/synth/post_dft_netlist.v (owed by step 12, read by step 15)

and 18 steps went MISSING; the run went from PASS=34/MISSING=0 to
PASS=9/MISSING=18. The ONLY difference from the green run before it was ONE
FIELD of `phase2/stage2/synth/post_dft_not_run.json`::

    run32   capability_flag "cap:post_dft_scan_optimization"  -> excused
    run33   capability_flag null                              -> REFUSED

R-0915-57 rightly replaced a capability-gap skip with a DESIGN-DECLARED one —
a STRONGER statement, since the design's L20 says it has no DFT at all — and
`_declared_sibling_self_skip_for_missing` knew only how to honour the weaker.

SO THERE ARE NOW TWO GROUNDS, and the capability flag is NOT restored:
  (a) unchanged — a sibling marker with an OPEN `capability_flag` entitled to
      defer that output;
  (b) new — the marker carries `reason_class: DESIGN_DECLARED_NA` and a
      `declaration` naming an L-doc and its field/value pairs, AND THIS SIDE
      RE-READS THAT DOCUMENT and checks the bytes agree.

(b) IS NOT A PROSE MATCH. The marker's `reason` already names L20 and its
fields in English and it would have been easy to read that; granting a
DESIGN_DECLARED_NA from a sentence is exactly the #2272 regression, where a
clue was treated as a declaration. The marker is a POINTER to evidence.

chip-AGNOSTIC: synthetic projects in tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


import flow_compliance_check as F  # noqa: E402

OWNED = "phase2/stage2/synth/post_dft_netlist.v"
NO_DFT = {"dft_present": False, "scan_chains": [], "bist_mbist": [],
          "jtag_tap": None}


def _l20(project, fields):
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(
        json.dumps({"doc_id": "L20", "fields": fields}))






# ── the marker states the facts, and does not re-mint a capability ───────







# ── POSITIVE: run33's exact case, now excused ────────────────────────────





# ── NEGATIVE: the three the ruling names, and two more ───────────────────















def test_ground_a_is_untouched(tmp_path):
    """The capability-gap path keeps working for a flag that IS registered and
    IS entitled to the output it claims."""
    flag, outputs = next(
        (f, o) for f, o in F._DECLARED_CAPABILITY_GAP_FLAGS.items() if o)
    owned = outputs[0]
    _l20(tmp_path, NO_DFT)
    payload = {"verdict": "SKIPPED-CONDITION", "reason": "tool absent",
               "tool_attempted": True, "capability_flag": flag,
               "skips_required_output": owned}
    p = tmp_path / Path(owned).parent / "sibling_not_run.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload))
    assert F._declared_sibling_self_skip_for_missing(tmp_path, [owned]), \
        f"ground (a) must still excuse {owned} under {flag}"
