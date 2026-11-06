#!/usr/bin/env python3
"""Step 39 — `phase2/stage1/fpga/final/*.sof` must be producible.

DEFECT (measured on v1.7.36, HEAD 44259eac3)
--------------------------------------------
Three paths competed for one concept and none agreed:

  * `flow/phase1_phase2_phase3.yaml:1839` declares step 39's required output as
    `phase2/stage1/fpga/final/*.sof`;
  * `fpga_on_board_attestation_check`'s docstring documents
    `bitstream_path: "phase2/stage1/fpga/final/<name>.sof"`;
  * `_path_layout.fpga_final_dir()` pointed at a THIRD path,
    `phase3/stage4/fpga`, whose only consumer was a bare `mkdir` in
    phase3_one_shot_runner.

A plugin-wide grep found no code that ever copied a `.sof` into any `final`
directory, and `on_board_pass.json`'s `bitstream_path` came from fpga_burn's own
provenance — always `output_files/`. So the declared artefact was UNPRODUCIBLE,
and after #455 made `required_outputs` ALL-of-N, a genuinely successful on-board
sign-off was reported MISSING. Reproduced by driving the real emitter with
compile+burn+tester all PASS and then calling
`flow_compliance_check.check_step` on the real step-39 spec:

    STATUS: MISSING
      required_outputs missing: ['phase2/stage1/fpga/final/*.sof']
      (satisfied: 1/2 — the gate passed, but every declared output must be
       produced, not just one)

DIRECTION-1 GUARDS (must hold on BOTH trees)
--------------------------------------------
* the anti-fabrication rule: no burn ⇒ no bitstream fields synthesised;
* step 6 keeps declaring `output_files/*.sof`, so the early prototype and the
  final sign-off stay distinguishable (staging is a COPY, not a move);
* the attestation's sha256 must match the file `bitstream_path` names, or every
  run flips to bitstream-hash-mismatch.
"""
from __future__ import annotations

from pathlib import Path

import yaml

import _path_layout as _pl

FLOW = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"




def _step(step_id: str) -> dict:
    doc = yaml.safe_load(FLOW.read_text())
    return [s for s in doc["steps"] if str(s["id"]) == step_id][0]






# ---------------------------------------------------------------------------
# The declared artefact must exist after a real burn
# ---------------------------------------------------------------------------











def test_path_layout_final_dir_matches_the_declaration():
    """`fpga_final_dir` must name the path the flow and the attestation
    checker already document, not a third one nothing writes to."""
    decl = [o for o in _step("39")["required_outputs"] if o.endswith(".sof")]
    assert decl == ["phase2/stage1/fpga/final/*.sof"]
    rel = _pl.fpga_final_dir(Path("/p")).relative_to(Path("/p"))
    assert str(rel) == "phase2/stage1/fpga/final"


# ---------------------------------------------------------------------------
# DIRECTION-1 GUARDS — behaviour that must NOT change
# ---------------------------------------------------------------------------
