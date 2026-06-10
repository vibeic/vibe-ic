# PLAN — benchmark IC #6: lowRISC Ibex (clean-room re-baseline)

Status: SETUP ONLY — staged 2026-06-10. No phase runner has been executed in
this directory.

## 1. Configuration choice

**Ibex 'small'**: RV32IMC, 2-stage pipeline, 3-cycle fast multiplier
(`RV32MFast`), no instruction cache, FF register file, machine-mode only,
no PMP. Reference size ≈ **26.6 kGE**; the ORFS CI rules cap for this exact
source set on sky130hd is ≈ **21k standard-cell instances**
(`input/reference_flow/orfs_rules.json`). This is the configuration the staged
vendor RTL implements out of the box (default parameters in
`vendor_rtl/ibex_pkg.sv` + `ibex_core` parameter defaults).

## 2. Why Ibex as #6

- **Lowest toolchain risk**: the staged source set is exactly what ORFS CI
  builds nightly on sky130hd (`flow/designs/src/ibex_sv` +
  `flow/designs/sky130hd/ibex`), i.e. a *proven* open-flow sky130 path with a
  known-good 10 ns SDC, utilization (50%), placement and CTS knobs
  (`reference_flow/orfs_config.mk`).
- **Exercises the SV frontend gap**: real-world SystemVerilog (packages, enums,
  interfaces-free but macro-heavy, `prim_assert.sv`) — ORFS itself uses
  `SYNTH_HDL_FRONTEND = slang`; our flow must demonstrate an equivalent
  yosys(+slang/sv2v) path. This is a deliberate stress on the plugin's SV
  ingestion, not an incidental one.

### Honest caveats (RESULT.md MUST disclose both)

1. **Same `processor_cpu` IC class as subservient (#3)** — this does not add a
   new IC class to the benchmark matrix; it adds depth (a real 2-stage RV32IMC
   vs SERV-style bit-serial) on the same class.
2. **Prior Ibex runs exist** (`benchmark_ic/2nd__ibex`, `benchmark_ic/4th__ibex`).
   This directory is a **clean-room re-baseline**: nothing was copied from those
   run dirs; every staged byte comes from upstream
   (The-OpenROAD-Project/OpenROAD-flow-scripts and lowRISC/ibex) fetched fresh
   on 2026-06-10. The RESULT must state both the prior-run existence and the
   clean-room provenance.

## 3. Staged inputs and provenance

| Staged path | Upstream source | Commit |
|---|---|---|
| `input/vendor_rtl/` (32 files: 23 HDL — 20 ibex `*.sv` + prim_clock_gating.v + 2 prim_assert headers — plus README/LICENSE/BUILD) | ORFS `flow/designs/src/ibex_sv/` | ORFS `8abc6a9035ca36490a1577867addca732a87cee8` (fetched 2026-06-10, HEAD of master, dated 2026-06-08); the set itself is **lowRISC/ibex `77d801001554cce8fe69e742e96539eecbe74425`** per its README ("pruned to only those source files which are used") |
| `input/constraints/constraint.sdc` | ORFS `flow/designs/sky130hd/ibex/constraint.sdc` | same ORFS commit — top `ibex_core`, clock `clk_i` @ **10.0 ns**, io_pct 0.2 |
| `input/reference_flow/orfs_config.mk` | ORFS `config.mk` | same — sky130hd, slang frontend, CORE_UTILIZATION 50, SWAP_ARITH_OPERATORS 1, OPENROAD_HIERARCHICAL 1 |
| `input/reference_flow/orfs_rules.json` | ORFS `rules-base.json` | same — ORFS CI pass/fail envelope (clk 10 ns context) |
| `input/docs/ibex_*.rst` (18 files) | lowRISC/ibex `doc/01_overview/*`, `doc/02_user/{integration,system_requirements}`, `doc/03_reference/{pipeline_details,instruction_fetch,instruction_decode_execute,load_store_unit,register_file,cs_registers,exception_interrupts,pmp,performance_counters,verification}` | lowRISC/ibex `b58952d7f72d03b083e7de6309b4492ad3f374f1` (HEAD, 2026-06-09) |
| `input/docs/ibex_pkg.sv` | lowRISC/ibex `rtl/ibex_pkg.sv` | same lowRISC HEAD commit |

**Known version skew (disclosed)**: `input/docs/ibex_pkg.sv` (HEAD, 728 lines)
differs from `input/vendor_rtl/ibex_pkg.sv` (ORFS-pinned `77d80100`, 508
lines). The *vendor* copy is the build ground truth (it is what synthesizes);
the *docs* copy is the L1-L9 documentation ground truth for parameters/CSRs at
the doc snapshot. Phase 1 extraction must treat the vendor RTL as authoritative
where the two disagree; conformance checking against the docs copy must flag
(not fail on) skew-only deltas.

## 4. Oracle plan

- **Primary**: Verilator **simple_system** style harness — compile the staged
  vendor RTL + a minimal ibex_top/simple_system wrapper, run bare-metal RISC-V
  programs, check magic-address / register-dump outcomes.
- **Compliance**: vendored **riscv-arch-test** (RV32IMC subset) run under the
  same Verilator harness; pass/fail by signature comparison.
- **NOT usable**: the upstream UVM DV environment (`dv/uvm/core_ibex`) is
  Synopsys-VCS-bound — out of scope for this open-tool benchmark; this is a
  tool-substitution disclosure per the open-benchmark methodology
  (VCS→Verilator/iverilog must be stated in RESULT.md §3).
- Gate-level: post-synth/post-PnR equivalence (LEC) + the same oracle programs
  on the gate netlist where runtime permits.

## 5. Known unfinished items from 4th__ibex (targets for this run)

- **Real DRC/LVS sign-off was never achieved** in the 4th-gen run — GDS was
  produced but DRC/LVS never reached an honest PASS. #6 target: full
  DRC/LVS/STA sign-off with honest gates.
- **STA: -4.13 ns WNS at a 20 ns clock** on the multdiv chain in the 4th-gen
  run. The ORFS reference proves 10 ns is achievable on this exact source set
  with proper repair (ADDER_MAP_FILE cleared, SWAP_ARITH_OPERATORS, TNS_END
  100%, REMOVE_ABC_BUFFERS). #6 target: meet the staged **10 ns** SDC, using
  the staged ORFS knobs as the reference recipe.

## 6. Clean-room statement

This directory was created 2026-06-10 from upstream sources only:

- `https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts` @
  `8abc6a9035ca36490a1577867addca732a87cee8` (sparse: `flow/designs/src/ibex_sv`,
  `flow/designs/sky130hd/ibex`)
- `https://github.com/lowRISC/ibex` @
  `b58952d7f72d03b083e7de6309b4492ad3f374f1` (sparse: `doc`, `rtl/ibex_pkg.sv`)

**No file, report, RTL, constraint, script, or note was copied from
`benchmark_ic/2nd__ibex` or `benchmark_ic/4th__ibex`**, and no generated
artifact from any prior Ibex run is referenced. All Phase 1/2/3 outputs must be
regenerated from this staged input set.
