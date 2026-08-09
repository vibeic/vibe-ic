# RESULT — spm × sky130A (Benchmark IC cell, plugin v1.10.18, 2026-08-09)

_IC: `spm` — serial-parallel integer multiplier (N=32, unsigned, LSB-first,
1-cycle latency, active-high reset). PDK: sky130A (`sky130_fd_sc_hd`).
Plugin: **v1.10.18** — the version that BOTH produced and measured this run.
Container: `ghcr.io/vibeic/vibeic-eda:0.2.78`
(`sha256:c2820aa30de70a42b5943244c39c30796fa9b50e39c89b98794294c867ed0eef`,
image identity enforced with `--require-image`, recorded in
`reports/container_image.json`). Design input: the 9 shared L1–L9 documents in
`benchmark-data/ic/spm/input/docs/`, byte-identical (sha256-compared) to the
copy this run read. This cell supersedes `v1.9.94_sky130A`, retired in the same
commit that lands this one._

## VERDICT

**VERDICT:** PASS_WITH_WAIVERS

`flow_compliance_check.py --strict` at plugin v1.10.18, exit code **0**:

```
Steps: 63 total (36/41 executed PASS, 3 DEFERRED via waiver, 4 VACUOUS-PASS excluded from executed)
  PASS=36  FAIL=0  MISSING=0  WAIVED-DEFERRED=3  SKIPPED=19  VACUOUS-PASS=4  INCOMPLETE=1
Overall: PASS_WITH_WAIVERS  (strict=True)
```

The run's own orchestrator record agrees rather than contradicting it —
`reports/orchestrator/vibe_ic_one_shot.json` reads `PASS_WITH_WAIVERS`
(phase1 PASS, phase2 PASS_WITH_WAIVERS, analog SKIPPED, phase3
PASS_WITH_WAIVERS, mixed_signal SKIPPED), and
`reports/orchestrator/phase3_one_shot.json` reads `steps_verdict: PASS`,
`completion_audit_verdict: PASS_WITH_WAIVERS`, "5 of 5 declared sign-off
gate(s) PASSED". Producer stamp: `plugin_version: 1.10.18`.

## Evidence — re-derived from the raw artefacts, not from any summary

Every number below was read out of the tool's own product (report database,
netgen report, STA report, GDS file), not out of a runner summary or an agent
report.

- **GDS**: `phase3/stage4/gds/spm.gds`, **1,616,344 bytes**,
  `sha256:ee758fccab3ddbe43a987e6a264c64dd83d5d5146ca6530edd0e77f21badc063`.
  Substance measured by walking the GDS records: 102,959 records, 48
  structures, 17,295 BOUNDARY + 2,442 SREF + 82 TEXT elements over 18 layers —
  i.e. real geometry, not an empty stream.
- **Sign-off DRC**: **0 violations**. Re-run FRESH by hand for this record —
  KLayout invoked directly in the container on the SHIPPED GDS with the PDK's
  own sign-off deck (`/foss/pdks/sky130A/libs.tech/klayout/drc/sky130A.lydrc`),
  exit 0, and the regenerated report database contains **0 `<item>` entries**,
  matching the run's own `reports/phase3/drc_signoff.rpt` byte-for-byte in
  size. Non-vacuity is independently established:
  `reports/phase3/drc_vacuous.json` records 17,295 shapes actually loaded, so
  the 0 is "the deck ran over the geometry and found nothing", not "the deck
  read nothing".
- **LVS** (netgen, power-aware): `reports/phase3/lvs.rpt` line 903 —
  *"Final result: Circuits match uniquely."* The compared gate netlist is
  power-aware: PDK rails `VPWR`/`VGND`/`VPB`/`VNB` are top-level ports and
  per-cell PG connectivity was patched onto **2,442 instances**, so the power
  network is LVS-verified rather than dropped.
- **Post-route multi-corner STA on real per-corner SPEF**
  (`reports/phase3/sta_mcorner_ocv.rpt`):
  - setup: worst slack **+4.56 ns** MET — process SS,
    `sky130_fd_sc_hd__ss_100C_1v60.lib`, `spm.max.spef`
  - hold: worst slack **+0.38 ns** MET — process FF,
    `sky130_fd_sc_hd__ff_n40C_1v95_ccsnoise.lib`, `spm.min.spef`
- **DFT / ATPG**: stuck-at test coverage **100.0%** — 1,832 of 1,832 faults
  over 916 fault points, **0 faults excluded as untestable** (an excluded
  fault would inflate the ratio; there are none). Scan chain: 65 internal +
  34 boundary = 99 cells, and the internal chain length equals the flop count.
- **Equivalence**: RTL vs synthesized netlist LEC **equivalent**, 64 compared
  points, 0 non-equivalent, 0 unproven; post-layout LEC (synth netlist vs PnR
  netlist) present in `reports/phase3/lec_post_layout.json`.
- **Functional simulation**: the run's own oracle testbench, **28 of 28
  vectors passed** (`reports/phase2/coverage/coverage_actual.json`, transcript
  at `phase2/stage1/sim_full_stack/oracle_run/oracle.log`).
- **Floorplan**: 176 × 176 µm die, 2,442 placed instances.
- **Source provenance**: `SOURCE_MANIFEST.md` — 1 module, `spm`,
  **GENERATED**; 0 REUSED-IP.

## The 4 VACUOUS-PASS steps — what each one did NOT check

A VACUOUS-PASS is a step that returned no failure because it had nothing
applicable to measure. It is counted separately from PASS on purpose and it is
excluded from the "36/41 executed PASS" ratio. Three of these four are genuine
inapplicability; the first is not, and is disclosed as such.

1. **Step D1 — Phase 1 Doc Extraction.** Gate `phase1_expert_parse_track`
   returned VACUOUS_PASS because **the AI sub-track of the Phase-1 expert
   track never delivered a reading** (state `HANDOFF_EMITTED`: the handoff pack
   was written to `reports/audit/phase1/expert_parse_track_pack/` and no
   `ic-expert-agent` consumed it). The gate says so itself: the deterministic
   findings it does report "are a floor, not coverage". So the expert
   expectation over the L-docs was **not examined on this run**. This is the
   one vacuity here that hides an unchecked property rather than an absent
   one.
2. **Step 5 — Formal verification / bit-level full-stack TB.**
   `bit_level_full_stack_tb_check` returned VACUOUS_PASS with the reason: the
   IC has no command protocol and no opcodes (`L3_CMD_PROTOCOL` is empty) and
   no L4/L5 register-map protocol, so an opcode-driven bit-level full-stack
   testbench is genuinely N/A for this arithmetic primitive. Structural
   inapplicability, matching the runner's own `full_stack_tb_gen` SKIP.
3. **Step FS1 — ISO-26262 FMEDA diagnostic coverage.** Both
   `fmeda_fault_injection_coverage` and `fmeda_coverage_check` returned
   VACUOUS_PASS: "no declared safety mechanism (ECC/parity/lockstep) found".
   This design declares none, so there is no diagnostic coverage to compute.
   Genuine N/A.
4. **Step 14 — Synthesis handoff gate.** `yosys_script_template_check`
   returned VACUOUS_PASS because the run emitted **no `.ys` script file** to
   inspect: synthesis was driven by an inline `yosys -p` command. The gate
   then extracted that inline command from the synth log and verified it
   conformant (hilomap + flatten present) across 1 log, and the sibling
   `yosys_tiecell_recipe_order_check` passed. So the property was checked by
   another route; only the template-file form of the check was vacuous.

## The 3 WAIVED-DEFERRED steps — open work, not credit

All three are `review_required: true`. None is a silent pass; each is a slot
credited via a waiver that a production tapeout review must close.

1. **Step 4 — Simulation / coverage.** The functional half PASSED (28/28
   oracle vectors above). The **coverage** half is deferred:
   `verilator_coverage_measure` reports `cap:verilator_coverage_toolchain` —
   *"'verilator' is not on PATH, so no line/toggle/branch coverage could have
   been produced on this host"* — and returns PASS_WITH_WAIVERS rather than
   certifying the step. **So this cell ships with NO measured line, toggle or
   branch coverage.** Note the gap is host-side, not absolute: Verilator 5.051
   *is* installed in the run's own container (`/foss/tools/bin/verilator`), and
   the gate runs on the host. That is a plugin gap, reported upstream
   separately; it was deliberately NOT hand-patched here, because patching the
   run that produces a published number is exactly the move the no-mix rule
   exists to prevent.
2. **Step 6 — FPGA early prototype.** `ENV_UNAVAILABLE`
   (`fpga-board-prototype-capgap-v1.0.18`). The runner honestly self-reports a
   deliberate FPGA skip (`reports/phase2/fpga/quartus_map_audit.json`
   `verdict=SKIP`, `sof_present=false`): no DE10-class board-pin contract for
   this IC class and no Quartus on the host. The natural verdict was MISSING
   (`phase2/stage1/fpga/output_files/*.sof` not produced).
3. **Step 39 — FPGA final sign-off (recompile + on-board test).** Same
   capability gap, same ticket. The natural verdict was a failed JSON gate
   (`all_scenarios_passed = False`). The on-board `.sof` — early prototype and
   final sign-off both — is DEFERRED to board bring-up and is **not** claimed
   as executed-PASS.

## Also disclosed

- **1 INCOMPLETE step — P0 structural-RTL umbrella.** 210 of 246 registered
  checkers returned a verdict; **36 never ran at all** because argparse
  rejected the umbrella's argv (they require `--rtl-dir` / `--rtl-files` /
  `--masks` / `--top-module` / `--out-dir` that the umbrella does not supply).
  What those 36 audit is UNCHECKED on this run. This is `INCOMPLETE`, not
  `FAIL`; it does not affect the gate's exit code, and it is a plugin-wide
  condition present on every current run, not something specific to this cell.
- **19 SKIPPED-CONDITION steps** — the analog A1–A9 and mixed-signal M1–M4
  tracks plus their dependants, all gated on
  `phase1/analog/analog_block_list.json`, which a pure-digital IC does not
  produce.
- **The six benchmark-verify pillars are NOT all closed on this run.**
  `reports/BENCHMARK_VERIFICATION_REPORT.md` is the program's own output and
  is published here unedited: Pillar 5 (analog) N/A, Pillar 6
  (Design-for-ECO) **PASS** (`spare_cell_coverage.json` status=PASS,
  `spare_preservation.json` `all_keep_attr_intact=true`, 0 spares removed),
  and Pillars 1–4 **PENDING** because the one-shot runner does not emit their
  declared inputs (`reports/functional_coverage.json`,
  `reports/code_coverage.json`, `reports/hw_test.json`, `cross_check/**`). The
  pillar aggregate therefore reads NOT-COMPLETE. That is a scope statement
  about the benchmark-verify inputs, not a contradiction of the flow verdict
  above — the report says so in its own header — and it is published rather
  than omitted so the gap is auditable.
- **Three non-final tool invocations** appear in `provenance.jsonl` with a
  non-zero exit — 3 of 35 recorded invocations: one OpenROAD PnR attempt, one
  OpenSTA call, one Yosys call — each followed by a successful invocation in
  the same close-loop. The sign-off artefacts above come from the successful
  runs; the failures are retained in provenance rather than scrubbed.

## Why this cell was re-measured today

`spm × sky130A` was reported FAIL earlier on 2026-08-09. That FAIL came from
the audit binary, not the design: v1.10.14 (#901) made the completion audit
read each gate's own JSON for vacuity signals, and it marked a whole step
VACUOUS_PASS when a single one of its gates was legitimately inapplicable —
cascading into `PASS_VOIDED_BY_DEPENDENCY` and an overall FAIL whose
`failed_gate_count` was 0. It was withdrawn in v1.10.18.

This cell is not that run re-labelled. It is a **fresh clean-room run**
executed end-to-end by v1.10.18 (`vibe_ic_one_shot_runner`, 226 s, phase 1
from the L1–L9 documents onward), so the producing version and the measuring
version are the same and the folder name means what it says. As a separate
control, the earlier v1.10.16-produced run in `_c14_spm_sky130A` was re-audited
under v1.10.18 on its own byte-identical artefacts and returned
PASS_WITH_WAIVERS, exit 0, with the same tally (36/0/0/3/19/4/1) — confirming
the withdrawal was complete. That control run is not published; this one is.

## Scope

One cell — `spm × sky130A` on plugin v1.10.18. Nothing here is claimed for any
other IC, any other PDK, or any other plugin version. Tool substitutions in
force for the whole open-source flow (Yosys + OpenROAD + KLayout + netgen +
OpenSTA + Icarus/fault in place of a commercial toolchain) are recorded in
`provenance.jsonl` with per-invocation versions and exit codes.
