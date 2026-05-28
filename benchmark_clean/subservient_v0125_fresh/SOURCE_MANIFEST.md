# SOURCE_MANIFEST — subservient_v0125_fresh (FRESH BLIND benchmark, v0.1.25)

> **REUSED-IP / SoC-integration IC.** A full RISC-V SoC is not generatable
> from a datasheet, so spec-to-RTL WAIVED → the genuine upstream SERV core
> + servile wrapper were pulled via `catalog-glue-author` (**REUSED-IP**),
> and ONLY the chip-top integration wrapper + GPIO + the Wishbone→8-bit-SRAM
> bridge were AI-authored from L1-L9 spec (**GENERATED**).
>
> The "doc→silicon" production-readiness credit applies **ONLY to the
> GENERATED portion**. The REUSED-IP portion (the SERV RV32I datapath) is
> reported here separately and honestly — it was **not** generated, and the
> upstream SERV/subservient RTL was **never read as a Phase-1/2 input**
> (only `input/docs/L1-L9.md` fed Phase 1/2 authoring). The SERV repo is
> the verify-stage golden oracle only.

## Honest GENERATED vs REUSED-IP split

| Category | Modules | LOC (approx) | Source |
|---|---|---|---|
| **GENERATED** (doc→RTL) | `chip_top` (L9 name-bridge wrapper), `subservient` (SoC integration + WB→8b-SRAM bridge), `gpio_periph` | ~340 | AI-authored from `input/docs/L1-L9` only |
| **REUSED-IP** (pulled, unmodified) | SERV core (18 files) + servile wrapper (4 files) | ~4,000 | github.com/olofk/serv @ release/1.4.0 |

The genuine RV32I bit-serial datapath (fetch / decode / ALU / branch /
load-store / CSR / register file) is REUSED-IP, NOT generated.

---

## GENERATED modules (production-readiness credit applies)

### `subservient.v`  —  SHA256-16 `e9089bde867320db`  (GENERATED)
- **License:** Apache-2.0
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

### `gpio_periph.v`  —  SHA256-16 `1f0a3facf6d9e7b2`  (GENERATED)
- **License:** Apache-2.0
- **Satisfies:** **L3** `o_gpio` ≥1-bit output; **L8.2.4** GPIO peripheral;
  **L2** "firmware bit-banged GPIO/UART". Memory-mapped at SRAM byte
  `MEMSIZE-1` (Plugin convention, R3-permitted; not a chip register per
  L4/L5 N/A).

### `chip_top.v`  —  SHA256-16 `0d681a3a69a8cee1`  (GENERATED)
- **License:** Apache-2.0
- **Author:** Vibe-IC close-loop sub-agent (chip-top name-bridge wrapper)
- **Satisfies:** **L9** `top_module="chip_top"` contract — thin 1:1 port
  wrapper around `subservient` so the synthesised top name matches L9
  while the SoC integration module keeps its natural name `subservient`.
- **What it contains (all authored):** parameter pass-through (MEMSIZE,
  RESET_PC, WITH_CSR), single `subservient` instantiation with
  port-by-port connection; no added logic. Required because the runner's
  yosys_synth uses `-top chip_top` per L9.
- **Plugin-gap context:** this wrapper would not be needed if
  phase2 runner auto-detected the actual top from the emitted RTL or
  auto-wrapped when L9.top_module ≠ emitted top. Filed as a plugin
  observation in the close-loop report.

---

## REUSED-IP modules (reported separately — NOT generation credit)

- **IP:** `serv` (the world's smallest RISC-V CPU) + its `servile` convenience wrapper
- **License:** **ISC** (serv core) / **Apache-2.0** (servile) — both permissive, audited PASS
- **Canonical URL:** https://github.com/olofk/serv
- **Pinned commit/tag:** `release/1.4.0`
- **Pull method:** local mirror `/home/reyerchu/ic_documents/open_ic/serv` via `ip_catalog_pull.py` (provenance in `provenance.jsonl`)
- **Catalog match:** `cpu/serv v1.4.0` confidence 0.45 — pattern
  "L2.cpu_isa starts with 'rv32i' AND L2.cpu_arch contains 'bit-serial'".
- **Satisfies (per L-doc):** **L2/L8.2.1** RV32I bit-serial CPU ISA behaviour
  (regulated by RISC-V standard + SERV reference; explicitly *not* re-derived
  from spec per L8.2.1); **L8.2.2** servile wrapper; **L8.2.5** RF-RAM interface.

| File (REUSED-IP, unmodified) | SHA256-16 | role |
|---|---|---|
| serv_top.v | c35b88bed5732309 | SERV core top |
| serv_aligner.v | adeff8f442db6c93 | instruction aligner |
| serv_alu.v | 2e0c31b5b992618e | bit-serial ALU |
| serv_bufreg.v | 76404174ec92c6cf | operand buffer 1 |
| serv_bufreg2.v | 6586c95a64a064ff | operand buffer 2 |
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
| serv_debug.v | 815a6b0da1a49d41 | debug (pulled, not instantiated) |
| serv_synth_wrapper.v | ca429e8f6867acb1 | synth wrapper (pulled, not instantiated) |
| servile.v | 3ae38ac0da93e459 | servile wrapper top |
| servile_arbiter.v | 69d57d934956fdfa | I/D bus arbiter |
| servile_mux.v | 38ca38dade5805eb | data-bus mux |
| servile_rf_mem_if.v | 599cabd2bbdee988 | RF/mem if |

---

## Pruned spurious catalog matches (honesty)

- **`arithmetic/fpu_single v1.0.0`** — PRUNED (6 files removed:
  `fpu.v, except.v, post_norm.v, pre_norm.v, pre_norm_fmul.v, primitives.v`).
  Reason: subservient is SERV **bit-serial RV32I, integer-only**
  (L2 isa_extensions default = `[I, Zifencei]`; the **F** extension is NOT
  selected). The catalog F-match was a false positive (the matcher saw the
  `rv32` prefix). Confidence was 0.45 — same as serv — but L2 explicitly
  rules out F.

## License compliance audit
- spdx_set: **ISC** (serv) + **Apache-2.0** (servile + GENERATED) — all permissive, `all_permissive=true`. No GPL/AGPL/SSPL.

## Provenance
- See `plugin_output/declaration.json` (`ip_catalog_used`, `pulled_ip_files`, `license_compliance_audit`)
- See `provenance.jsonl` for per-file pull records (when emitted by `ip_catalog_pull.py`)

## Functional evidence
- `iverilog -g2012 -t null -Wall *.v` → clean parse on the full GENERATED + REUSED-IP RTL set.
- See `reports/orchestrator/phase2_one_shot.json` for downstream gate verdicts.
