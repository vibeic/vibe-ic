# Phase 1 Brief — lowRISC Ibex RV32IMC Core (benchmark IC #6)

Implement the lowRISC Ibex RV32IMC processor core — the **'small' configuration**
(2-stage pipeline, 3-cycle fast multiplier, no instruction cache, FF-based
register file, machine-mode only) — as a **sky130A digital IC**, driven from the
staged reference documents in `input/docs/`.

## Intended implementation path

- **Reuse of the staged vendor RTL is the intended path**: `input/vendor_rtl/`
  contains the ORFS-proven pruned Ibex source set (23 HDL files: 20 ibex
  `*.sv` modules + `prim_clock_gating.v` + the two `prim_assert` include
  headers) that ORFS CI runs nightly on sky130hd. The expected flow is **catalog-glue**: pull the vendored
  RTL into the project RTL tree and author only the integration wrapper /
  chip-top and flow config from the L1-L9 spec — not from-scratch RTL authoring.
- Top module: `ibex_core` (per the staged ORFS reference flow).
- Include dir required: `input/vendor_rtl/vendor/lowrisc_ip/prim/rtl/`
  (prim_assert macros).

## Targets

- **Clock**: 10 ns period on `clk_i` (100 MHz), per the staged ORFS constraint
  `input/constraints/constraint.sdc` (input/output delay = 20% of period).
- **PDK**: sky130A (ORFS reference uses sky130hd standard cells).
- **Sign-off** = synth → PnR → GDS → DRC / LVS / STA, all gates honest
  (no NONFATAL-swallowed routing, no waiver without classification).

## Ground truth

- Architecture / ISA / pipeline behavior: the staged `ibex_*.rst` docs
  (lowRISC upstream documentation, reStructuredText).
- Parameter / CSR ground truth: `input/docs/ibex_pkg.sv`.
- Functional oracle: Verilator-based simple_system + riscv-arch-test
  (the upstream UVM DV environment is VCS-bound and NOT usable here).
