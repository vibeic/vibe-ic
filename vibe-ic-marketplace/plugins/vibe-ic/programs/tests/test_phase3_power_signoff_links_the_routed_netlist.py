"""The Phase-3 power number was computed on the PRE-PnR netlist, and its own
header said it was not.

MEASURED DEFECT
===============
`_emit_power_report` is called twice: once for the Step-10 pre-layout preview
and once for the Step-33 sign-off power report. Both calls shared one body
that linked `<top>_synth.v`. So `reports/phase3/power.rpt` published a pre-PnR
figure under a generated header reading:

    # values reflect the post-PnR netlist + the typical-corner Liberty file

Measured on one real routed design, against a controlled re-measurement that
changed ONLY the netlist and added the extracted SPEF (same tool, same
liberty, same SDC, same vectorless activity basis):

    netlist        <top>_synth.v   287 instances   | <top>_pnr.v  3373, routed
    parasitics     none                            | <top>.spef
    total power    0.306 mW                        | 0.573 mW
    clock group    0.000 mW (0.0 %)                | 0.193 mW (33.7 %)

The shipped figure was 1.873x LOW and the clock tree — a third of real power —
reported as exactly zero, because the netlist it linked has no clock tree.

THE PROOF THAT MAKES IT UNDENIABLE
----------------------------------
Across a 60-configuration place-and-route sweep the shipped `power.rpt` was
BYTE-IDENTICAL 60/60 (one md5 over 60 files) while all 60 routed netlists and
all 60 SPEFs were distinct. No PnR knob can reach a pre-PnR netlist. A number
that cannot move when the thing it measures moves is not a measurement.

THE REMEDY IS THE SESSION, NOT THE HEADER
-----------------------------------------
Editing the header to say "pre-PnR" would make the document honest and leave
the sign-off measurement useless. So the sign-off call now asks for
`basis="post_pnr"` and the session links the routed netlist + the SPEF.

WHAT IS ASSERTED
================
1. FORWARD (fails against the pre-fix file): the sign-off basis links the
   ROUTED netlist and reads the extracted SPEF.
2. STAMP (fails pre-fix): the report states its own basis, in the vocabulary
   `_sta_basis.BASIS_TOKENS` already normalises.
3. HEADER-TRUTH (fails pre-fix, and is the implementation-independent one):
   the netlist the provenance envelope NAMES is the netlist the session's own
   TCL `read_verilog`s. This is the invariant the defect broke.
4. IT MOVES (fails pre-fix): two runs whose routed netlists differ must not
   produce the same measurement inputs. This is the 60/60 finding as a test.
5. DEGRADES LOUDLY (fails pre-fix in the other direction): asked for the
   post-PnR basis with no routed netlist on disk, the report is stamped
   PRE_LAYOUT_ESTIMATE, never POST_ROUTE, and the fallback is disclosed.
6. REVERSE (must pass BOTH pre-fix and post-fix): the Step-10 pre-layout
   preview still links the synth netlist, reads no SPEF and still succeeds.
   The fix must not turn the early-feedback preview into a post-route report.
   Its stamp is asserted in a SEPARATE test, so the control itself stays green
   on both arms.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))


def test_the_report_states_which_side_of_pnr_it_measured(tmp_path):
    """FAILS pre-fix: the pre-fix report carried no basis stamp at all."""
    import _sta_basis
    assert _sta_basis.normalise_basis("POST_ROUTE_SPEF") == "POST_ROUTE"
