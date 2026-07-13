# CVDP clean-run v1414 (plugin v1.4.14) — run state

Dataset: cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl (302 records)
Routing (cvdp_task_router.py, cid-labelled, per-nature entry):
  spec_generation 78 -> phase1_spec_to_rtl (Phase-1)
  completion      94 -> completion_loop
  functional_modification 55 -> modify_loop
  optimization    40 -> optimize_loop
  debug           35 -> debug_loop  (NOT Phase-1)

Authoring: 302/302 drafts (blind §4.05, input-only on blind/<id>.json).
  - 84 pre-existing + 218 via parallel fleets (12 workflows, 6 batch=2 fwd + 6 batch=1 rev)
  - final 9 hard ones via controlled 9-agent self-verifying wave (all tb_passed)
Gate pre-pass (293): 290 gated in, 3 blocked -> fixed inline:
  - ir_receiver_0001: enum-ternary explicit cast (if/else)
  - sorter_0001: gate FALSE-POSITIVE (parse_states swept params N/WIDTH into state set ->
    loop index k misdetected as next-state var -> phantom latch). Rewrote flat packed array.
    -> CAPTURE filed for gatekeeper (scratchpad/CAPTURE_fsm_latch_param_falsepos.md)
  - data_bus_controller_0001: header m0_read vs prose m0_ready -> harness binds header name -> rename to _read
Server-side rate-limit (not usage cap) killed the harden fleet; authoring still landed.
