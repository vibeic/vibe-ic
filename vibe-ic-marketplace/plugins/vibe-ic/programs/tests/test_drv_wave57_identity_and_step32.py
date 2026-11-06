"""Review wave 57 on DRVWIRE 98cdcab70 and ruling R-0929-DRV-IDENTITY.

* An in-flow DRV capture binds the identity that exists then: the design-state
  digests, the run's code identity recorded at run start and the Phase-1 spec
  version.  GDS / LVS-netlist identity is "bound at" the final post-stream
  capture -- neither missing evidence nor NOT_MEASURED in flow -- and every
  other capture still has to bind it.  Fed the PLAN's own identity (not a
  synthetic one) a clean run can reach a complete in-flow verdict.
* Step 32 never reads another round's report, and its DRV verdict never
  blocks the handoff of an adopted candidate (R-0929-STEP32-ADOPT); it is
  Step 32's own verdict.
* The zero-segment proof is for port-to-PAD nets only (no core load).
* The plan's postroute_repair stage row follows step 32's adoption.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from test_drv_signoff_judge import _file

_PROGRAMS = Path(__file__).resolve().parent.parent
_TESTS = Path(__file__).resolve().parent
for _p in (str(_PROGRAMS), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)















# --- step 32 -----------------------------------------------------------------



def test_step32_never_reads_the_previous_rounds_report(tmp_path, monkeypatch):
    import librelane_postroute_repair as repair
    project = tmp_path
    stale = project / repair.REPORT_REL
    _file(project, repair.REPORT_REL, json.dumps({"adopted": "32-cand07", "site": "after_direct_route"}))
    repair._clear_declared_repair(project)       # what run()/run_in_chain do first
    assert not stale.exists()










# --- annotation --------------------------------------------------------------



# --- the plan's postroute_repair row ---------------------------------------------



# --- review wave 58: a window run records its own identity ---------------------
