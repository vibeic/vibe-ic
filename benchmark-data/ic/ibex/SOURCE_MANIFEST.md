# ibex — SOURCE_MANIFEST (REUSED-IP vs GENERATED)

Top module (chip-level) = `chip_top` (GENERATED wrapper).
Synthesizable functional top = `ibex_core` (REUSED-IP), 'small' config.

## REUSED-IP — lowRISC Ibex, Apache-2.0 (copied as-is from input/vendor_rtl/)
Cloned upstream commit 77d801001554cce8fe69e742e96539eecbe74425 (per vendor_rtl/README.md).
Copied verbatim into phase2/stage1/rtl/ — NOT authored, NOT modified.

| file | role |
|------|------|
| ibex_core.sv | core top (instantiated by chip_top) |
| ibex_pkg.sv | parameter / enum package |
| ibex_if_stage.sv, ibex_prefetch_buffer.sv, ibex_fetch_fifo.sv | IF stage |
| ibex_id_stage.sv, ibex_decoder.sv, ibex_compressed_decoder.sv, ibex_controller.sv | ID stage |
| ibex_ex_block.sv, ibex_alu.sv, ibex_multdiv_fast.sv, ibex_multdiv_slow.sv | EX |
| ibex_load_store_unit.sv | LSU |
| ibex_wb_stage.sv | WB |
| ibex_cs_registers.sv, ibex_csr.sv, ibex_counter.sv | CSR / perf counters |
| ibex_register_file_ff.sv | FF register file |
| ibex_pmp.sv | PMP (disabled in 'small' config but compiled) |
| syn/rtl/prim_clock_gating.v | yosys-friendly clock gate primitive |
| vendor/lowrisc_ip/prim/rtl/prim_assert.sv | prim_assert macros (include) |
| vendor/lowrisc_ip/prim/rtl/prim_assert_dummy_macros.svh | prim_assert dummy macros (include) |

Total REUSED-IP: 20 ibex *.sv + 1 prim_clock_gating.v + 2 prim_assert includes = 23 HDL files.

## GENERATED — authored this run from L1-L23 + input/phase1_prompt.md
| file | role |
|------|------|
| phase2/stage1/rtl/chip_top.sv | chip-level integration wrapper around ibex_core ('small' config params) |

## Tool substitution
- Synth: Synopsys DC / Cadence Genus (doc-listed) → yosys (+ slang frontend per ORFS `SYNTH_HDL_FRONTEND=slang`). OSS substitute.
- Sim: Synopsys VCS / Verilator (doc-listed) → iverilog where the runner uses it. NOTE: input docs state Ibex SV is NOT iverilog-compatible and "Yosys cannot be used directly" without the slang frontend (sv2v/yosys-slang). Tooling-gap risk captured.

