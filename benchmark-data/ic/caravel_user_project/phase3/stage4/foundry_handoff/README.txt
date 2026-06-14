Foundry handoff package — auto-generated skeleton (v1.1).
Design name: caravel_r11
Design: caravel_user_project
PDK: sky130a
GDS: phase3/stage4/gds/user_project_wrapper.gds (92967798 B)

Required artefacts:
  mask_spec.json              — mask layer table + reticle config
  wat_plan.json               — WAT probe plan + PCM structures
  scribe_line_layout.gds      — foundry-supplied PCM/scribe layout
                                (see scribe_line_layout.PENDING_FOUNDRY.txt)
  corner_test_vectors.json    — ATE corner test kit

PENDING_FOUNDRY_* entries inside each JSON mark fields the foundry /
production team supplies before tape-out (open items). Substance
gate `foundry_handoff_package_check` (Step 35) audits completeness.

Authored design facts auto-included:
  cell_count    = 1
  die_area_um2  = None
  process_nm    = 130
  pdk           = sky130a
