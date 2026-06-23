#!/usr/bin/env python3
"""phase2_one_shot_runner — public-name shim over design_one_shot_runner.

WHY THIS FILE EXISTS
--------------------
The top orchestrator ``vibe_ic_one_shot_runner.py`` resolves each phase's
runner by the uniform convention ``programs/<phase>_one_shot_runner.py``
(``_phase_runner("phase1")`` → ``phase1_one_shot_runner.py``, likewise
``phase3``). The v1.1.95 rename (#76) moved the phase-2 author to
``design_one_shot_runner.py`` but did NOT leave a ``phase2_one_shot_runner.py``
behind, so ``_phase_runner("phase2")`` resolved to a non-existent file and
EVERY orchestrator-driven phase-2 step halted with
``can't open file '.../phase2_one_shot_runner.py'`` (phase-1 PASS, phase-2
"No such file"). That broke the documented `vibe_ic_one_shot_runner.py`
entry point for all chip classes (surfaced by the Shape-B benchmark runner
path).

This thin shim restores the ``<phase>_one_shot_runner.py`` convention by
re-exporting ``design_one_shot_runner.main`` verbatim — identical CLI args,
identical ``reports/phase2_one_shot.json`` output, ZERO behavioural change.
``design_one_shot_runner.py`` remains the canonical author; this is only the
convention-named entry the orchestrator (and any external caller using the
documented name) resolves.
"""
from __future__ import annotations

import sys

from design_one_shot_runner import main

if __name__ == "__main__":
    sys.exit(main())
