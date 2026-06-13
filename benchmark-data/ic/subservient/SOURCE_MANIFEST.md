# SOURCE_MANIFEST — subservient (corrected-protocol benchmark IC #4)

> **FIRST REUSED-IP / SoC-integration benchmark IC.** A full RISC-V SoC is
> NOT generatable from a datasheet, so spec-to-RTL WAIVED → the genuine
> upstream SERV core + servile wrapper were pulled via `catalog-glue-author`
> (**REUSED-IP**), and ONLY the chip-top integration wrapper + GPIO + the
> Wishbone→8-bit-SRAM bridge + OpenLane/SDC glue were AI-authored from the
> L1-L9 spec (**GENERATED**).
>
> The "doc→silicon" production-readiness credit applies **ONLY to the
> GENERATED portion**. The REUSED-IP portion (the SERV RV32I datapath) is
> reported here separately and honestly — it was **not** generated, and the
> upstream SERV/subservient RTL was **never read as a Phase-1/2 input**
> (only the public datasheet / README / FuseSoC manifest / OpenLane config
> fed Phase 1). The SERV repo is the verify-stage golden oracle only.

## Honest GENERATED vs REUSED-IP split

| Category | Modules | LOC (approx) | Source |
|---|---|---|---|
| **GENERATED** (doc→RTL) | `subservient` (chip-top + WB→8b-SRAM bridge), `gpio_periph` | ~290 | AI-authored from `input/docs/L1-L9` only |
| **REUSED-IP** (pulled, unmodified) | SERV core (18 files) + servile wrapper (4 files) | ~4,000 | github.com/olofk/serv @ release/1.4.0 |

**The genuine RV32I bit-serial datapath (fetch / decode / ALU / branch /
load-store / CSR / register file) is REUSED-IP, NOT generated.** This run is
deliberately MORE rigorous than the upstream `subservient_e2e` golden, whose
own `subservient_core.v` *stubbed* the SERV datapath (its declaration flags
firmware execution as `open_items`). Here the **real SERV core executes a
real RV32I program** and the GPIO toggles (functional sim PASS, below).

---

## GENERATED modules (production-readiness credit applies)

### `subservient.v`  —  SHA256 `ff85a6e0c872061c…`  (GENERATED)
- **License:** Apache-2.0 (author's choice; compatible with reused ISC/Apache-2.0)
- **Author:** Vibe-IC `catalog-glue-author` skill, from `input/docs/L1-L9`
- **Satisfies:**
  - **L3** chip-top port contract — `i_clk`, `i_rst` (sync active-high),
    SRAM port group (`o_sram_addr[9:0]`, `o_sram_wdata[7:0]`,
    `i_sram_rdata[7:0]`, `o_sram_we`, `o_sram_cyc`), `o_gpio`.
  - **L2** single shared-SRAM architecture (I-mem + D-mem external + on-die RF)
    + bit-serial integration; **L8.2.2/8.2.5** servile + RF-RAM integration.
  - **L9** `memsize=1024`, `RESET_PC=0`, `WITH_CSR=1`, clock_port `i_clk`.
- **What it contains (all authored):** servile instantiation + parameterization;
  a Wishbone-32-word → external-8-bit-byte SRAM bridge FSM (4 byte
  accesses/word, correct read-latency skew); on-die RF SRAM instantiation;
  GPIO peripheral wiring; lint tie-offs.

### `gpio_periph.v`  —  SHA256 `88d8c8c5415887fd…`  (GENERATED)
- **License:** Apache-2.0
- **Satisfies:** **L3** `o_gpio` ≥1-bit output; **L8.2.4** GPIO peripheral;
  **L2** "firmware bit-banged GPIO/UART". Memory-mapped at SRAM byte
  `MEMSIZE-1` (Plugin convention, R3-permitted; not a chip register per L5 N/A).

---

## REUSED-IP modules (reported separately — NOT generation credit)

- **IP:** `serv` (the world's smallest RISC-V CPU) + its `servile` convenience wrapper
- **License:** **ISC** (serv core) / **Apache-2.0** (servile) — both permissive, audited PASS
- **Canonical URL:** https://github.com/olofk/serv
- **Pinned commit/tag:** `release/1.4.0`
- **Pull method:** local mirror `/home/reyerchu/ic_documents/open_ic/serv` (provenance in `provenance.jsonl`)
- **Catalog match:** `cpu/serv v1.4.0` confidence 0.45 — pattern
  "L2.cpu_isa starts with 'rv32i' AND L2.cpu_arch contains 'bit-serial'".
- **Satisfies (per L-doc):** **L2/L8.2.1** RV32I bit-serial CPU ISA behaviour
  (regulated by RISC-V standard + SERV reference; explicitly *not* re-derived
  from spec per L8.2.1); **L8.2.2** servile wrapper; **L8.2.5** RF-RAM interface.

| File (REUSED-IP, unmodified) | SHA256 (16) | role |
|---|---|---|
| serv_top.v | c35b88bed5732309 | SERV core top |
| serv_aligner.v | adeff8f442db6c93 | instruction aligner |
| serv_alu.v | 2e0c31b5b992618e | bit-serial ALU |
| serv_bufreg.v / serv_bufreg2.v | 76404174… / 6586c95a… | operand buffers |
| serv_compdec.v | b1799ad9c5f10756 | compressed decoder |
| serv_csr.v | 2dd7167ed44817d9 | CSR (Zicsr) |
| serv_ctrl.v | eb198ba7594f918d | control / PC |
| serv_decode.v | eac5b2097ebd1f45 | instruction decode |
| serv_immdec.v | 80ec5a265194eb40 | immediate decode |
| serv_mem_if.v | a4fbd74579447710 | load/store unit |
| serv_rf_if.v | 63fd0d2ec2f89201 | RF interface |
| serv_rf_ram.v | 779ad3243dfa648f | RF SRAM storage |
| serv_rf_ram_if.v | abb39b6bdf4d335b | RF-RAM adapter |
| serv_rf_top.v | 89faedf7530c3430 | RF top |
| serv_state.v | f7f981a28ed92243 | bit-serial state |
| servile.v | 3ae38ac0da93e459 | servile wrapper top |
| servile_arbiter.v | 69d57d934956fdfa | I/D bus arbiter |
| servile_mux.v | 38ca38dade5805eb | data-bus mux |
| servile_rf_mem_if.v | 599cabd2bbdee988 | RF/mem if |

(serv_debug.v, serv_synth_wrapper.v also pulled into the tree but not
instantiated by the GENERATED integration — servile uses serv_top directly.)

---

## Pruned spurious catalog matches (honesty)

- **`arithmetic/fpu_single v1.0.0`** — PRUNED (6 files removed:
  `fpu.v, except.v, post_norm.v, pre_norm.v, pre_norm_fmul.v, primitives.v`).
  Reason: subservient is SERV **bit-serial RV32I, integer-only**
  (L2 isa_extensions = `[I, Zifencei]`; the **F** extension is NOT selected).
  The catalog F-match was a false positive (matcher saw the `rv32` prefix).
  Not picorv32 (no picorv32 match surfaced; serv is the correct bit-serial core).

## License compliance audit
- spdx_set: **ISC** (serv) + **Apache-2.0** (servile + GENERATED) — all permissive, `all_permissive=true`. No GPL/AGPL/SSPL.

## Functional evidence (GENERATED glue + genuine REUSED-IP core)
- `iverilog -g2012` parse: clean. `verilator --lint-only`: clean.
- **Functional sim** (`sim/functional_gpio_sim.log`): real rv32i program
  (li/li/sb/xori/delay/loop, `sb t0,0(0x3ff)`) executed by the genuine SERV
  core → **fetch_reads=4172, gpio_mailbox_writes=87, gpio toggled high↔low →
  FUNCTIONAL_PASS**.
- **Yosys synth** (sky130_fd_sc_hd): 3389 cells, 57,210 µm². SERV is bit-serial
  → the RF SRAM maps to flops (1303 enabled-DFFs = the 576×2-bit RF) — a known
  SERV-SoC characteristic; this is larger than the L7 baseline because the
  GENUINE full RV32I core + flop-RF is synthesized (the golden stubbed it).
