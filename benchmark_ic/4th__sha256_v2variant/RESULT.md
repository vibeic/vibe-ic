# Vibe-IC End-to-End Result — `4th__sha256_v2variant`

**IC**: sha256 (NIST FIPS-180-4 SHA-256/SHA-224 hash accelerator, memory-mapped register interface)
**Run date**: 2026-05-26
**Container**: `iic-eda` (hpretl/iic-osic-tools)
**Target PDK**: SKY130A (`sky130_fd_sc_hd`), clock 25.9 ns, util/density 0.25
**Agent**: fresh Vibe-IC field agent, full Phase 1 → Phase 2 → Analog → Phase 3 flow

---

## Final Verdict

**Overall: PARTIAL — genuine GDS produced; blocked on (a) expected half-duplex-TB mismatch in Phase 2 and (b) std-cell-internal DRC + one STA setup path in Phase 3.**

- Engineering reality: a **real, fully placed-and-routed SHA-256 GDSII** was produced from genuine open-source RTL with **0 detailed-routing (TritonRoute) violations**. The flow is NOT tapeout-clean (DRC FAIL + 1 STA setup path + LVS not run), but every artifact is authentic — nothing stubbed or fabricated.
- Orchestrator verdict per `flow_compliance_check`: **FAIL** in both Phase 2 and Phase 3 (blocking FAILs present).

### halted_at + reason
- **Phase 2 halted_at**: `reference_tb` / `fpga_burn` — the half-duplex AID-protocol reference TB and pre-burn structural gates. **EXPECTED, NOT a design defect** (see below).
- **Phase 3 halted_at**: `drc` — 83,866 klayout violations, of which **83,193 are std-cell-library-internal** (sky130 flat-DRC artifact) and only **673 are user/routing-attributable**. LVS WAIVED (needs SPICE extraction).

---

## Per-Phase Status

### Phase 1 — Docs → L1-L13  ✅ PASS
- Top orchestrator's `_need_phase1()` **skipped** phase1 for Path-B docs (as the run notes warned). Ran explicitly: `phase1_one_shot_runner.py . --mode docs`.
- Emitted **14 L-docs** to `phase1/generated_docs/L*.json`, extraction coverage **100.0%** (168/168 literals), 0 TODO stubs.
- Port contract in L3/L9 matches the secworks SHA-256 interface exactly (clk, reset_n, cs, we, address[8], write_data[32], read_data[32], error).

### Phase 2 — RTL → SOF → reference-TB  ⚠️ FAIL (mixed; expected blockers)
- IC class detected: `digital_arithmetic_primitive`. The runner **WAIVED rtl_gen** (no deterministic generator for this class) and recommended skill `catalog-glue-author` with an IP-catalog match: `crypto/sha256_core v0.80 (BSD-2-Clause, secworks/sha256)`.
- Close-loop: pulled the genuine IP via `ip_catalog_pull.py` (4 files, BSD-2-Clause, all-permissive, SHA256-attested in `plugin_output/declaration.json`) and AI-authored a thin `chip_top` integration wrapper (instantiates unmodified `sha256` 1:1, per L8.8.4 single-module freedom). `iverilog -g2012` parse rc=0.
- **PASS**: phase1_precheck, detect_ic_class, full_stack_tb_gen, yosys_synth (11380 cells, top=chip_top), qsf_gen, sdc_gen, otp_image_check, **fpga_compile (real Quartus `chip_top.sof`, 3.2 MB, 0 errors)**, phase2_manifests.
- **FAIL (expected, NOT defects)**:
  - `reference_tb` — iverilog error: `port 'id_bus' is not a port of u_dut`. The hardcoded **AID-class half-duplex reference TB** (`aid_class_reference_tb.v`) references `reset_n/id_bus` board pins that a pure crypto core has no contract for. Per run notes, this is EXPECTED; **no `id_bus` port was fabricated**.
  - `fpga_burn` — `burn_blocked_structural_gates_fail` (8 half-duplex-protocol structural gates, e.g. `protocol_ip_simulation_required_check`). Same root cause; not burned.
  - `final_audit` — wants `phase1/analog/analog_block_list.json` (pure-digital design; no analog track applies).

### Analog (A1-A9)  ⏭️ SKIPPED
- Pure-digital crypto core; no analog blocks. All A1-A9 / M1-M4 steps SKIPPED-CONDITION. Correct.

### Phase 3 — synth → PnR → GDS → DRC → LVS  ⚠️ FAIL (real GDS produced)
Driven directly on the genuine RTL/netlist (as instructed — Phase 3 pushed forward despite Phase 2's half-duplex FAIL).
- **synth**  ✅ PASS — yosys 0.62 mapped to **9959 `sky130_fd_sc_hd__` cells** → `chip_top_synth.v`.
- **pnr**    ✅ PASS — OpenROAD floorplan→place→CTS→hold-fix→route. DEF `chip_top.def` = **10466 placed components**. **TritonRoute detailed routing converged to 0 routing violations** (4149 → 880 → 107 → 29 → 8 → **0** across 5 opt iterations). ~20 min route runtime.
- **gds**    ✅ PASS — `chip_top.gds` (8.32 MB). klayout structural read: top=`chip_top`, **10466 instances**, 76 cell masters, 41 layers — a genuine full layout.
- **drc**    ❌ FAIL — klayout real sky130A runset (`sky130A.lydrc`). **83,866 total** = **83,193 std-cell-library-internal** (li.3 spacing=78021, li.1 width=4735 — the well-known flat-DRC-over-abutted-std-cells artifact) + **673 genuine user/routing violations**. Routing itself was DRT-clean (0); the bulk count is foundry-cell-internal, not custom-layout error. Still, NOT signed-off clean.
- **lvs**    🔶 WAIVED — requires SPICE-extracted netlist + reference; deferred to dedicated extraction flow. netgen IS available; not re-run this pass.
- **sta**    1 setup path **VIOLATED** (slack -64.75 ns) + reset-recovery path MET (+18.78 ns). Synthesis was not timing-driven-tightened to 25.9 ns; a long combinational path remains. Real timing gap, not fabricated.

---

## Key Artifact Paths (canonical project)
- L docs:        `phase1/generated_docs/L1..L13 (14 files).json`
- Pulled IP RTL: `phase2/stage1/rtl/{sha256,sha256_core,sha256_w_mem,sha256_k_constants}.v` (secworks, BSD-2-Clause)
- AI wrapper:    `phase2/stage1/rtl/chip_top.v` (AI-authored, attribution header)
- IP provenance: `plugin_output/declaration.json` (SHA256-attested pulls + license audit)
- Post-synth:    `phase2/stage2/synth/chip_top_synth.v` (9959 sky130 cells)
- FPGA bitstream:`phase2/stage1/fpga/output_files/chip_top.sof` (3.2 MB, Quartus 0 errors)
- Routed DEF:    `phase3/stage3/pnr/chip_top.def` (10466 components)
- **GDSII**:     `phase3/stage3/pnr/chip_top.gds` + `phase3/stage4/gds/chip_top.gds` (8.32 MB)
- STA:           `phase3/stage3/pnr/sta.rpt`
- DRC report:    `phase3/stage3/pnr/routed.drc.rpt` (klayout XML)
- Reports:       `reports/orchestrator/{phase2,phase3}_one_shot.json`, `reports/final_summary.md`
- Phase3 staging:`/home/reyerchu/AI_IC_design/_vibeic_phase3_sha256_v2variant/` (inside container bind-mount; see close-loop #2)

---

## MCP-EDA / Real-Tool Sanity (STEP 4)
All tools present in `iic-eda` and confirmed to have genuinely executed:

| Tool | Used for | Result |
|---|---|---|
| **yosys 0.62** | Phase2 + Phase3 synthesis | OK — sky130-mapped netlist, 0 fatal errors |
| **openroad** (incl. TritonRoute DRT, OpenSTA) | floorplan/place/CTS/route/STA/GDS | OK — routing converged to 0 DRT violations; 1 STA setup path violated |
| **klayout** | sign-off DRC (sky130A.lydrc) + GDS read | OK — ran, reported 83,866 (mostly std-cell-internal) |
| **netgen** | LVS | Available; LVS WAIVED (no SPICE extraction this pass) |
| **iverilog** | RTL parse sanity | OK — `iverilog -g2012 -t null rtl/*.v` rc=0 |
| **Quartus Prime** | FPGA compile (phase2) | OK — `chip_top.sof` produced, 0 errors / 32 warnings |
| **magic** | (not invoked this run) | Available |

Notable tool errors (non-fatal): OpenROAD via-analyzer skipped (missing `/foss/pdks/sky130A/...` RC file); SPEF extraction produced no `chip_top.spef` (rc=0, known limitation) → LVS deferred.

---

## Close-Loop Actions (≤3 iters, all minimal + evidence-backed)
1. **Phase 1 explicit run** — orchestrator skipped phase1 for Path-B docs; re-ran `phase1_one_shot_runner --mode docs`. → 14 L-docs, 100% coverage.
2. **catalog-glue-author (Phase 2 rtl_gen WAIVE)** — pulled genuine secworks/sha256 BSD-2-Clause IP via `ip_catalog_pull.py` + authored `chip_top.v` wrapper. iverilog rc=0. → yosys + Quartus both PASS, real SOF. (Did NOT fabricate `id_bus` to satisfy the AID reference TB.)
3. **Phase 3 path-translation + density fix** —
   - (a) First phase3 synth FAILed: the project lives outside the `iic-eda` bind-mount (`/home/reyerchu/AI_IC_design → /foss/designs` only), so container `cd` into the synth dir failed. Fix: staged the working tree under the mount at `/home/reyerchu/AI_IC_design/_vibeic_phase3_sha256_v2variant` and re-ran.
   - (b) First placement hung (overflow stuck ~0.97) because `--util 20` was passed to `global_placement -density 20.0` (invalid; the flag expects a fraction). Fix: re-ran with `--util 0.25` (matches L9 PL_TARGET_DENSITY). → placement/route/GDS all completed; routing converged to 0 DRT violations.
   - Artifacts copied back into the canonical project tree.

No fabrication, no stubbing, no waive-without-evidence at any step.

---

## Honest Assessment
- **What is genuinely real**: NIST-standard secworks SHA-256 RTL (battle-tested, OpenLane-CI-proven), synthesized to ~10k sky130 cells, fully placed and **routed clean (0 TritonRoute violations)**, with an authentic 8.3 MB GDSII containing 10466 instances. An FPGA bitstream was also produced and Quartus-compiled with 0 errors. This is a substantively complete digital backend.
- **What is NOT tapeout-clean**:
  1. **Phase 2 half-duplex-TB / fpga_burn FAIL** — architectural mismatch between the plugin's AID-peripheral verification model and a pure crypto core. Expected per the run brief; recorded honestly, not patched away. A crypto-appropriate verification path would drive the NIST FIPS-180-4 test vectors against the register interface (L7), which the AID reference TB does not do.
  2. **Phase 3 DRC FAIL** — 673 genuine user violations + ~83k std-cell-internal counts. The std-cell-internal bulk is a klayout flat-DRC artifact; the 673 user violations and the routing geometry would need a DRC-clean ECO pass to sign off.
  3. **1 STA setup path violated (-64.75 ns)** — synthesis was not timing-tightened; needs timing-driven synth/place or pipelining to close at 25.9 ns.
  4. **LVS not executed** — needs SPICE extraction + reference netlist; netgen is available for a follow-up pass.
- **Bottom line**: The flow produced a real GDS on genuine RTL end-to-end. It is a valid engineering milestone but **not** a clean tapeout — the remaining items (DRC ECO, STA closure, LVS, crypto-functional verification) are real, bounded follow-up work, not blockers fabricated or hidden.
