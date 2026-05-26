# Step 14 — Pre-PnR Yosys gate (OUR vs REF)

## What we ran
- Plugin `rtl_precheck_gate.py --rtl-dir OUR/phase2/stage1/rtl --l12-json L12 …`
  (the pre-burn/pre-PnR aggregator that runs every static auditor) on OUR RTL.
- yosys synthesizability confirmation (OUR RTL elaborates + maps cleanly to sky130 —
  see step 9, exit 0, 286 cells).

## OUR result — PASS (6/6 auditors)
`rtl_precheck_gate` summary: `auditors_total 6, passed 6, failed 0, skipped 0,
overall_pass: true` (exit 0). Per auditor:
- tristate_self_rx_mask_check — PASS
- pulse_decoder_edge_check — PASS
- packet_length_check_present — PASS
- otp_write_lock_gate_check — PASS (0 write-enable sites)
- l12_sequence_implementation_check — PASS (INFO: no L12 sequences declared — empty)
- timer_freeze_after_state_check — PASS

OUR RTL also synthesizes cleanly with yosys (step 9) — no synthesis errors, fully
mappable to sky130_fd_sc_hd. Pre-PnR ready.

## REF result
REF passed the equivalent gate at phase2 (its `reports/phase2/gates/*` and
`synth_netlist.json` pass=true) and its netlist proceeds into phase3 PnR. The same
static auditors apply; spm is a flat datapath with no protocol/FSM/OTP logic for them
to flag.

## Verdict: MATCH (both pass pre-PnR gate)
OUR RTL passes the full pre-PnR static-auditor aggregator (6/6) and synthesizes cleanly;
REF passes its equivalent gate. MATCH.
