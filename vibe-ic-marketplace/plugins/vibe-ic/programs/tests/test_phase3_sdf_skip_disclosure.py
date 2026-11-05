#!/usr/bin/env python3
"""Step 29 — the skip-marker must disclose what ACTUALLY happened.

Defect (HIGH, dimension 6 (skip discipline)), second half: whenever
`phase3/stage3/sim_postlayout/results.log` was absent, the runner wrote ONE
canned `sdf_sim_skipped.json`:

    verdict:        SKIPPED-CONDITION
    capability_flag: cap:sdf_annotated_gatelevel_sim
    reason:          "... the open-tool runner emits the SDF but does not
                      drive a back-annotated sim (#437d) ..."

That reason has been FALSE since v1.3.94 — the runner DOES call
`sdf_gate_sim.run()` — and `flow_compliance_check._PLATFORM_CAPABILITY_GAPS` is
literally empty with the comment "29 SDF -> iverilog $sdf_annotate gate sim".
Because the marker carried a `capability_flag` plus a `skips_required_output`
naming both step-29 outputs, `_declared_sibling_self_skip_for_missing` promoted
the step from MISSING to SKIPPED-CONDITION — so a compile failure, an aborted
simulator or a missing routed netlist all came out looking like a disclosed
platform gap.

`_sdf_sim_skip_disclosure` now derives (capability_flag, reason) from what
`sdf_gate_sim.run()` actually returned. Only an observed missing simulator
toolchain keeps a flag; every input/producer failure gets flag=None, which the
#675-strict promoter refuses, so the step stays MISSING (red).
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


_STEP29_OUTPUTS = [
    "phase3/stage3/sim_postlayout/results.log",
    "phase3/stage3/sim_postlayout/pass.flag",
]
_STALE_FALSE_CLAIM = "does not"






# ── discriminators: these FAIL on the pre-fix program ──────────────────────











def test_no_code_path_hardcodes_the_retired_capability_flag():
    """Belt-and-braces on the WRITER, not just the helper: comment prose may
    still discuss `cap:sdf_annotated_gatelevel_sim` (this commit explains why it
    was retired), but no executable line may emit it."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "cap:sdf_annotated_gatelevel_sim" not in code
    assert "back-annotated sim (#437d)" not in code




# ── direction-1 guards: must PASS on BOTH trees ───────────────────────────





test_guard_strict_promoter_still_requires_flag_and_ownership = \
    guard_strict_promoter_still_requires_flag_and_ownership
test_guard_platform_capability_gaps_stays_empty_for_step_29 = \
    guard_platform_capability_gaps_stays_empty_for_step_29
