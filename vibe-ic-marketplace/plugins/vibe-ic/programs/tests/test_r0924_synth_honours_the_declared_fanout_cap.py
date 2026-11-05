#!/usr/bin/env python3
"""Synthesis must honour the fanout cap the run itself declares.

THE MEASURED DEFECT (subservient x gf180mcuD, run2). The stock `abc -liberty`
script — the one the flow uses, WITHOUT `-constr` — ends `&nf {D}; &put`: it
buffers nothing and sizes nothing. So synthesis emitted a net with **207
loads** driven by one `clkinv_1`; that inverter alone cost **16.03 ns** of a
28.00 ns path, and Step 10 pre-layout STA read **-8.85 ns** against the
design's OWN 20 ns period — blocking nine downstream steps on a netlist the
flow had not yet repaired. The run's own SDC declared `set_max_fanout 10` the
whole time; nothing enforced it until `repair_design`, which runs in PnR,
AFTER the gate that fails for its absence.

MEASURED FIX — re-measured with the runner's EXACT command (`-D 20000` /
`-D 24000`, as the runner emits it), step-10 basis, one arm at a time:
    subservient  -8.85 VIOLATED (tns -2044.80)  ->  +2.55 MET (tns 0.00)
                 2,510 cells / 61,600 area      ->  2,653 / 66,271
    spm          +15.93 MET                     ->  +15.59 MET (no cell added)
The recipe is the stock mapping + ABC's `buffer -N <cap>` ONLY. The `-constr`
tail's `upsize {D}; dnsize {D}` is the synth-time sizing the in-source
post-route A/B measured as a regression, so it is NOT taken (an earlier cut of
this branch took it, and its +4.36 was measured WITHOUT the runner's -D).

AND ONE LADDER FOR THE CAP. Before this, the AUTO-SDC path resolved the cap
from design-declared sources only, so on ONE PDK subservient got 10 (its L9
happens to defer the cap to the PDK default) and spm got none (its L9 says
nothing). The AUGMENT path already had the other two tiers. Same file, two
ladders, one PDK.

UNREAD IS NOT EMPTY — the rule that nearly cost me a wrong conclusion: reading
the cap on the HOST returns None for every design because `pdk_compat.py`
lives in the CONTAINER, which reads exactly like "this PDK declares none". A
tier that could not be CONSULTED must say so.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


RUNNER = PROGRAMS / "phase3_one_shot_runner.py"


# --- the recipe itself -----------------------------------------------------




# --- the ONE ladder --------------------------------------------------------










# --- unread is not empty ---------------------------------------------------










# --- the wiring ------------------------------------------------------------
def test_every_abc_site_in_step_synth_carries_the_bound():
    """A SIBLING to the behaviour above, not a substitute for it: if one of the
    four `abc -liberty` sites in `step_synth` is left un-bounded, that path
    silently goes back to emitting unbounded fanout."""
    tree = ast.parse(RUNNER.read_text())
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "step_synth")
    sites, bounded = 0, 0
    for node in ast.walk(fn):
        if isinstance(node, ast.JoinedStr):
            txt = "".join(v.value for v in node.values
                          if isinstance(v, ast.Constant)
                          and isinstance(v.value, str))
            names = {v.value.id for v in node.values
                     if isinstance(v, ast.FormattedValue)
                     and isinstance(v.value, ast.Name)}
            if "abc -liberty" in txt:
                sites += 1
                if "_abc_fanout" in names:
                    bounded += 1
    assert sites >= 4, f"expected the four known abc sites, found {sites}"
    assert bounded == sites, (
        f"{sites - bounded} of {sites} abc site(s) in step_synth do not carry "
        f"the fanout bound")




# --- mutation --------------------------------------------------------------




def test_the_fanout_notes_have_their_own_channel():
    """They are NOT reference-flow knobs. Mixing them made two existing
    assertions about an EMPTY `reference_flow_qor_knobs` list fail — correctly,
    because `reference_flow_qor_knobs` means "what the design's staged flow
    asked for" and a PDK-derived cap is not that."""
    tree = ast.parse(RUNNER.read_text())
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "step_synth")
    src = ast.get_source_segment(RUNNER.read_text(), fn) or ""
    assert '"synth_max_fanout": _fo_notes' in src, (
        "the cap's disclosure must reach the step's extras under its own key")
    # and nothing about the cap may be appended to the knob list
    for line in src.splitlines():
        if "_rf_notes.append" in line:
            assert "fanout" not in line.lower() or "FASTROUTE" in line, (
                f"a fanout-cap note leaked into the knob list: {line.strip()}")
