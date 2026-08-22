# car14 evidence (pre-STA)

## Image / flag verification (MEASURED)
- 0.2.52 fault chain --help: NO --skip-boundary (only --skip-synth). fault 0.9.4.
- 0.2.54 fault chain --help: HAS --skip-boundary. Quote:
  "--skip-boundary  Insert the internal scan chain only; do not insert a
   boundary-scan register. Correct for a fixed-pinout wrapper, whose ports are
   not chip pads. (Default: boundary scan is inserted)"
- Pinned image for both runs: ghcr.io/vibeic/vibeic-eda:0.2.54 (fresh containers
  vibeic-eda-car14 / vibeic-eda-car14-ctrl, VIBEIC_EDA_IMAGE set to same).

## Deterministic rule (chip-agnostic)
- floorplan_contract.is_fixed_pinout_wrapper(project, top): fixed-pinout iff an
  FP_DEF_TEMPLATE (fixed pin-placement template DEF) governs the top module.
- On REAL caravel input: is_fixed_pinout=True, def_template=
  fixed_dont_change/user_project_wrapper.def, design_name=user_project_wrapper,
  fp_sizing=absolute, die=2920x3520 → decide auto -> skip_boundary=True.
- Synthetic non-caravel (top_wrap/1234x5678) also True; padframe_chip (no
  template) False → reads input, hardcodes nothing.

## Run B (skip-boundary=auto) — DFT step (phase3), MEASURED
- fault chain: 33 internal + 0 boundary scan cells; input flops=33;
  chain covers every flop=True; area 325→358 instances (+10.15%).
  [r13 with boundary: 33 internal + 606 boundary, +707.69%]
- tool stdout: "Boundary scan register NOT inserted (--skip-boundary): the chain
  is the 33 internal flip-flop(s) only. Total scan-chain length: 33"
- LEC: yosys equiv PASS (RTL vs post_dft_netlist.v)
- PnR routes post_dft_netlist.v (POST-DFT), 33 internal + 0 boundary.
- Coverage (preserved): coverage_pct=60.5336 (raw), test_coverage_pct=89.5897
  (#603 sign-off), excluded=936, faults_total=1443 (r13=2886; the ~1443 fewer
  are the removed boundary cells' faults). Scan of testable logic unchanged.

## STA (PENDING) — fill from:
- reports/phase3/sta/post_route_summary.json
- phase3/stage3/sta/sta_mcorner_ocv.rpt  (SS setup worst slack, TNS)
- runB = skip-boundary (fix); control_boundary = boundary (VIBEIC_DFT_SKIP_BOUNDARY=off)

## PR target
- /home/reyerchu/vibe-ic, origin=vibeic/vibe-ic, branch off FRESH origin/main.
- Plugin path: vibe-ic-marketplace/plugins/vibe-ic/programs/
- My edited plugin_work files are a STRICT SUPERSET of origin/main marketplace
  versions (0 lines only-in-origin) → copying = pure additions, no collision.
- 4 files: floorplan_contract.py, fault_scan_chain_insert.py,
  design_one_shot_runner.py, tests/test_issue604_skip_boundary_fixed_pinout.py
