Foundry handoff package — auto-generated skeleton (v1.6.36).

Required artefacts:
  mask_spec.json              — mask layer table + reticle config
  wat_plan.json               — WAT probe plan + PCM structures
  scribe_line_layout.gds      — foundry-supplied PCM/scribe layout
  corner_test_vectors.json    — ATE corner test kit

TODO entries inside each JSON mark fields that the production team
+ foundry-interface engineer must fill in before tape-out. Substance
gate `foundry_handoff_package_check` (Step 35) audits completeness.

Authored design facts auto-included:
  cell_count    = -1
  die_area_um2  = None
  process_nm    = None
  pdk           = unknown
