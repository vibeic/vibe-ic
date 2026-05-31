# Vibe-IC Canonical Flow v2.2.0

**Plugin version:** 0.2.2 · **Supersedes:** `CANONICAL_FLOW_v2.0.0.md`,
`PHASE_VS_STAGE_VS_INDUSTRY_TAXONOMY.md`, `docs/tutorials/33_step_flow_overview.md`,
`docs/design/STANDARD_FLOW.md` (all stop at the 33-step / 54-entity model and predate the
81-protocol Phase-1 dispatch, the Phase-2 scaffold bridge, and the doc→GDS LVS sign-off chain).

> **Source of truth = the runners, not this prose.** Every step below is cited to the actual
> step marker in its `*_one_shot_runner.py`. When a runner changes, regenerate this doc from the
> markers (`grep -noE '\[[0-9]+[a-z0-9]*/[0-9]+\]'` per runner) — do not hand-drift it.

---

## 0. Entry paths + orchestrator

`programs/vibe_ic_one_shot_runner.py` is the top orchestrator. Two entry paths, one handoff:

```
Path A: NL prompt / dialogue ─┐
                              ├─► Phase 1 ─► generated_docs/L1-L23 JSON ─► Phase 2 ─► Phase 3
Path B: vendor design docs ───┘        (the ONLY universal handoff format)
```

Orchestrator sequence (`vibe_ic_one_shot_runner.py`): **Phase 1 → Phase 2 (=2a+2b) → Analog
(after Phase 2, so L5_ADI_SPEC is populated; non-blocking) → Phase 3.** FAIL gating: Phase 1
FAIL halts before 2; Phase 2 FAIL halts before 3; Phase 3 FAIL → verdict FAIL but report emitted.

| Phase | Transform | Runner | Gate |
|---|---|---|---|
| **P0 pre-flight** | env / PDK / tool availability | `mcp_server_health_check`, `eda_doctor` | tools reachable |
| **Phase 1** | any input → L1-L23 JSON (+ human MD) | `phase1_doc_one_shot_runner.py` | 24 L-docs + completeness/parity |
| **Phase 2** | L1-L23 → verified RTL → (gate netlist / FPGA SOF) | `phase2_one_shot_runner.py` | lint/synth/conformance/TB + final_audit |
| **Analog A1-A8** | L1/L5 → sized block → hardmacro (parallel to P2) | `analog_one_shot_runner.py` | per-block DRC/LVS + corners |
| **Mixed-signal** | digital + analog co-sim | skill `mixed-signal-cosim` (no dedicated runner) | M1-M4 co-sim |
| **Phase 3** | netlist → synth → PnR → GDS → DRC → LVS | `phase3_one_shot_runner.py` | DRC 0 + LVS + STA + tapeout checklist |

---

## 1. Phase 1 — 15 steps (`phase1_doc_one_shot_runner.py`, the `[N/15]` markers)

| Marker | Step | Output |
|---|---|---|
| `[1/15]` | Extract text from `input/docs/` (PDF/DOC/XLSX/…) | `input_doc/` (capped at 2 MB/doc for the O(n²) scans, v0.1.91) |
| `[2/15]` | L1_DATASHEET | `generated_docs/L1_DATASHEET.json` |
| `[3/15]` | L2_FRS | L2 |
| `[4/15]` | L3_CMD_PROTOCOL | L3 |
| `[5/15]` | L4_REGMAP | L4 |
| `[6/15]` | L5_ADI_SPEC | L5 |
| `[7/15]` | L6_CONTROL_LOGIC | L6 |
| `[8/15]` | L7_TEST_DEBUG | L7 |
| `[9/15]` | L8_RTL_CONSTANTS | L8_RTL_CONSTANTS |
| `[10/15]` | L9_INTEGRATION_SPEC | L9 |
| `[11/15]` | L10_TEST_CASES | L10 |
| `[12/15]` | L11_OTP_CONTENT | L11 |
| `[13/15]` | L12_BEHAVIORAL_SEQUENCES | L12 |
| `[14/15]` | L13_LAB_CALIBRATION | L13 |
| `[14b/15]` | L8_TIMING_WAVEFORM (+ `14b2` width, `14b3` encoding, `14b7` universal constants, `14b4` L6 FSM, `14b5` L12 seq) | L8_TIMING_WAVEFORM + overlays |
| `[14c/15]` | L14-L18 protocol spec extract (+ `14c0` L9, `14c1` L1 meta, `14c1b` L17 handshake, `14c2` L3 mirror, `14c3` L17/L18/L8_TIMING/L9 batch synth, `14c4` universal doc facts, `14c5` residual cleanup) | L14-L18 |
| `[14d/15]` | L19-L23 skeleton emit | L19-L23 |
| **`[14e/15]`** | **serial_peripheral_protocol class synth (R53/R54/R55)** — the protocol detector→synth dispatch | per-protocol L-doc overlays |
| `[14e2/15]` | bus_interconnect_protocol Tier-2 synth (TileLink/Wishbone/Avalon/OCP/AXI-Stream) | bus-protocol overlays |
| `[14e3/15]` | Universal packet/PDU L10↔L3 opcode-consistency sweep | L10 cleaned |
| `[15/15]` | Coverage / parity report | `reports/phase1/` |

**The `[14e/15]` block is the 81-protocol-class engine** (this session, v0.1.84→v0.2.2). Each protocol
ships a content-only `is_<proto>(blob)` detector + `<proto>_protocol_synth.py` overlay, dispatched
by ic_class. Families: serial (SPI/I2C/I3C/UART/1-Wire/JTAG/SWD/QSPI/SMBus/MIPI-SPMI-RFFE), automotive
(CAN/CAN-FD/LIN/FlexRay/SENT/PSI5/Modbus/RS-485/CANopen), memory (DDR3/4/5/LPDDR5/HBM3/GDDR6/ONFI/
eMMC/SD-MMC/UFS/NVMe/HyperBus), display (HDMI/MIPI/DSI/CSI-2/DisplayPort/eDP), PCIe family
(PCIe/Gen5/CXL/NVLink/UCIe), USB (2.0/USB4), networking (Ethernet/800G/HDLC/SpaceWire/AFDX/Auto-Eth/
InfiniBand/FibreChannel/PROFIBUS/PROFINET/IO-Link/EtherCAT), wireless (BLE/NFC/Zigbee/LoRa), audio
(I2S/SoundWire/S-PDIF/A2B), data-converter (JESD204), debug (CoreSight), timing (PTP), aerospace
(MIL-STD-1553/ARINC429), bus (AHB-APB/AXI-ACE-CHI/TileLink/Wishbone/Avalon/OCP/AXI-Stream), security (TPM).
**Guard:** every module-level detector is auto-covered by `tests/test_protocol_detector_no_misfire.py`
(no foreign-benchmark fire; derived-sibling allowlist in `protocol_detector_lib.DERIVED_SIBLING_CROSS_FIRES`).

---

## 2. Phase 2 — RTL authoring + verification (`phase2_one_shot_runner.py`, `step_*`)

| Order | Step (`def step_*`) | Notes |
|---|---|---|
| 1 | `step_phase1` | re-run/ingest Phase 1 if needed |
| 2 | `step_rig_topology_skeleton` | scaffold topology |
| 3 | `step_rtl_gen` | **WAIVES for ic_class with `rtl_gen=null`** → AI fills the `spec-to-rtl` role inside the pipeline (digital_arithmetic_primitive / digital_cmd_driven / serial_peripheral_protocol / bus_interconnect_protocol / processor_cpu / unknown). `phase2_scaffold_gen.py` emits top/regs/fsm/tb/soc_wrap/cocotb scaffold deterministically. |
| 4 | `step_full_stack_tb_gen` | self-checking TB generation |
| 5 | `step_reference_tb` | reference-TB conformance (eco_loop up to 3 retries) |
| 6 | `step_yosys_synth` | gate-level synth |
| 7 | `step_qsf_gen` / `step_sdc_gen` | FPGA project + constraints |
| 8 | `step_otp_image_check` | OTP image (if applicable) |
| 9 | `step_fpga_compile` | Quartus/yosys FPGA build → `.sof` |
| 10 | `step_fpga_burn` | program board (hardware path) |
| 11 | `step_usb_hid_tester_verify` | host-side protocol-tester acceptance |
| 12 | `step_emit_phase2_manifests` | phase2 manifests |
| 13 | `step_final_audit` | aggregate audit gate |

Surrounding deterministic gates (fire around the AI authoring step): `rtl_hygiene_lint --fix`,
`spec_conformance_check`, `chip_top_gate_wrapper_gen`, MCP `eda_lint`/`eda_synth`/`eda_cocotb`.

---

## 3. Analog A1-A8 (`analog_one_shot_runner.py`, parallel to Phase 2)

| Step | Name | Output |
|---|---|---|
| A1 | spec_extract | `analog/<block>/A1_spec.json` |
| A2 | topology_select | `A2_topology.json` |
| A3 | netlist_gen | `<block>.sp` |
| A4 | corner_sweep | `A4_corners.json` |
| A5 | layout (Magic) | `A5_layout.json` (needs DRC-clean + LVS-match flags) |
| A6 | post_layout_resim | `A6_postsim.json` |
| A7 | hardmacro_gen | `{.lef,.lib,.gds,.v}` → feeds Phase 3 |
| A8 | hw_verify (HIL) | `A8_hw_verify.json` |

(Older docs listed "A1-A9"; the runner ships **A1-A8**. Mixed-signal **M1-M4** is skill-level
`mixed-signal-cosim`, no dedicated `*_one_shot_runner.py`.)

---

## 4. Phase 3 — physical design + sign-off (`phase3_one_shot_runner.py`, `step_*`)

| Step | Name | Tool (open-source substitute) |
|---|---|---|
| 1 | `step_synth` | yosys (sky130/gf180) — **+ tie-cell pass** (see § 5) |
| 2 | `step_pnr` | OpenROAD (floorplan → PDN → place → CTS → route) |
| 3 | `step_gds` | KLayout streamout (`def2gds`; OpenROAD no longer streams GDS) |
| 4 | `step_drc` | KLayout sky130 deck |
| 5 | `step_lvs` | netgen / yosys_equiv — **the sign-off chain in § 5** |
| 6 | `step_canonicalize_artefacts` | normalize outputs |

Tapeout gate: `tapeout-checklist` (DRC/LVS/STA/IR/EM/antenna/ERC/LEC/DFT) + `flow_compliance_check`.

---

## 5. The LVS sign-off chain — NEW in this era (v0.1.96 → v0.2.2)

This is the part **entirely missing from the old docs**. `step_lvs` is no longer a single
yosys_equiv call; it is a layered chain whose every layer was hardened by the 7 doc→GDS pilots:

1. **Structural LEC (default)** — `eda_lvs mode=yosys_equiv` (`equiv_simple`+`equiv_induct`).
   Residual "unproven" cells = yosys SAT-model gap on PDK primitives (Category-D tool limit,
   NOT a mismatch). No yosys flag closes it for all cells.
2. **Device-level coverage** — to cover the SAT gap: `eda_extraction` (magic ext2spice) +
   `eda_lvs mode=netgen` + `lvs_netgen_setup_emit.py` (power-net globalization). Compares
   transistors → no SAT-model concept. Reaches device-class-exact (HDLC 20937=20937; sha256 12148=12148).
3. **Powered-netlist closure** — OpenROAD `write_verilog -include_pwr_gnd` (after `global_connect`)
   gives the schematic side real VPWR/VGND/VPB/VNB → eliminates the tie-cell disconnected-node residual.
4. **Top-level port labels** — Route A (canonical): `magic_port_extract_emit.py` (`export PDK` +
   `port makeall`). Route B (fallback): `lvs_def_port_seed.py` (parse DEF PINS). (Route A is required;
   B is an audit hint — empirically confirmed.)
5. **Sign-off guard (MANDATORY)** — `lvs_signoff_guard.py`: RAISES on a claimed match against a
   PORTLESS extracted top `.subckt` (the vacuous / silent-false-positive condition). Run before
   trusting ANY LVS match.

Synth tie-cell pre-step (§ 4 step 1): `setundef -zero; hilomap -hicell conb_1 HI -locell conb_1 LO;
splitnets; clean` (NO `opt_clean` — it deletes tie cells). Without it, constant nets fail TritonRoute
DRT-0305. The bare MCP `eda_synth` path lacks this (backlog `ORGANIC-20260531-mcp-eda-synth-missing-hilomap-tiecells`);
`phase3_one_shot_runner` does it automatically. Forward-validated SENT→QSPI→HDLC→SpaceWire.

---

## 5b. Phase-3 sign-off checks — gap status

`step_drc`/`step_lvs` are the headline gates, but a complete sign-off runs more checks. The rows
below are the **sign-off checks and their status** (not every physical-design step — placement /
CTS / routing / output / ECO are covered in § 4 and the § 6 pilots and pass). **None of the gaps
below is a circuit-design error** — they are script-ordering / cascading / environment /
report-schema issues. Severities + root causes (audited):

> **Step-number caveat (this is why "step 23" looked missing):** two numberings exist. The IDs
> below follow the **sign-off-audit** scheme (SPEF 22 / STA 23 / IR 24 / EM 25 / Antenna 26 /
> SI 27 / DRC-LVS-ERC 30 / fill 33). The repo's `33_step_flow_overview.md` numbers the SAME
> checks differently (SPEF 20 / STA 21 / IR 22 / EM 23 / Antenna 24 / SI 25 / PV 27). Reconcile to
> one scheme when `flow_doc_emit.py` lands (§ 8). **Step 23 = Post-route STA**, listed below as
> PASS — it was absent earlier only because the gap-focused draft omitted passing checks.

| Step | Check | What it is (one line) | Open-source status | Severity |
|---|---|---|---|---|
| 22 | **SPEF** (OpenRCX) | per-wire R/C "parasitic" extract — feeds STA/IR/EM/SI | `extract.tcl` must call `global_route` + `set_wire_rc` first, else no SPEF | 🔶 medium (script order) |
| 23 | **Post-route STA** (MMMC) | multi-corner static timing sign-off | runs once SPEF exists; pilots report setup slack +X ns **MET** (3-corner) | 🟢 none (passes) |
| 24 | **IR drop** (PSM) | power-grid voltage-droop under switching current | cascading-missing: unlocks once SPEF (22) exists | 🔶 medium (cascade) |
| 25 | **EM** | electromigration — current density erodes metal over time | cascading-missing: needs SPEF (22) | 🔶 medium (cascade) |
| 27 | **SI** | crosstalk — a net's transition couples to neighbours | cascading-missing: needs SPEF (22) | 🔶 medium (cascade) |
| 26 | **Antenna** | long routed metal accumulates plasma charge → gate punch-through | OpenROAD router already runs it; report not on the audit path | 🟢 low (done, report-path) |
| 30 | **DRC / LVS / ERC** | foundry rule check / layout-vs-schematic / electrical-rule | sky130 PDK ships only Calibre decks; open-source needs KLayout/Magic decks wired (this era added the device-level netgen LVS chain in §5) | 🔴 high (env / deck) |
| 33 | **Metal fill** | dummy metal for CMP density uniformity | runner lacks the fill stage → no `filled.def` | 🔶 medium (missing stage) |
| 18 | **Spare cells** | tied-off ECO spares for metal-only late fixes | 30 spares placed correctly; `spare_cells.json` missing a `rows[]` field → audit can't read | 🟢 low (report schema) |
| 5 | **Formal** | SAT/model-checking proof (vs sampled simulation) | `altsyncram` primitive has no formal model → INFORMATIONAL waiver (function covered by post-layout sim, step 28) | 🟢 none (waived) |

**Doctrine:** treat each like the LVS chain (§5) — separate the *design-correctness* signal (here:
clean) from the *tool/script/report* signal (here: the actionable gaps). The actionable fixes
(SPEF `extract.tcl` ordering; the IR/EM/SI cascade it unblocks; open-source DRC/LVS decks; the
metal-fill stage; the `spare_cells.json` schema field) are tracked in
`ORGANIC-20260531-phase3-signoff-chain-open-source-gaps`.

---

## 6. doc→GDS pilot evidence (7 pilots, real sky130A GDS)

| Pilot | Archetype | ic_class | LVS stop point |
|---|---|---|---|
| i2s | streaming-rx | digital_cmd_driven | **device-level exact 4499=4499** (3 SAT-unproven → 0; 0 tie cells, port-label floor) |
| ahb_apb | bus-bridge | bus_interconnect | — |
| ufs | storage-framer | serial_peripheral | — |
| sent | sensor-decoder | digital_arithmetic_primitive | structural all-proven 1388/1388 |
| qspi | command-controller | serial_peripheral | structural all-proven 1434/1434 |
| hdlc | packet-framer | digital_cmd_driven | **device-level exact 20937=20937** (SAT gap → 0) |
| spacewire | link credit-flow-control | digital_arithmetic_primitive | **device-level exact 6676=6676 / powered 6164=6164** (99 SAT-unproven → 0; port-label floor) |

**All three device-level-closed pilots (i2s + hdlc + spacewire) now share one stop point** — the
§5 LVS chain end-to-end: structural-LEC SAT residual → device-level netgen (covers it to
device-class-exact, every SAT-unproven cell → 0) → powered-netlist (eliminates the tie-cell
power-pin node; N/A for i2s, which has 0 tie cells) → residual = the Category-D port-label floor
(`port makeall` / sign-off LVS), with `lvs_signoff_guard` correctly refusing a vacuous portless
match. No pilot now stops at the structural-SAT gap.

---

## 7. Project folder layout (unchanged from v2.0.0)

```
<project>/
  input/{docs,phase1_prompt.md}      input_doc/            (Phase 1 in/extracted)
  phase1/{generated_docs,human_docs,claude_extracted}/L*.json|md
  phase2/stage1/{rtl,scaffold,fpga}/  phase2/stage2/synth/
  analog/<block>/{A1_spec.json,…,<block>.{sp,lef,lib,gds,v}}
  phase3/stage{1..4}/{synth,pnr,gds,drc,lvs}/  phase3/stage5_manufacturing/
  reports/{phase1,phase2,phase3,orchestrator}/
```

---

## 8. Keeping this current

This doc is **derived**, not authoritative. The live runner-marker step lists are
auto-generated by **`programs/flow_doc_emit.py`** (shipped v0.2.3) into
**`FLOW_STEPS_GENERATED.md`** — the same pattern as `INDEX.md`. Regenerate after any runner
change with `python3 flow_doc_emit.py`; a freshness gate (`flow_doc_emit.py --check`, pinned by
`tests/test_flow_doc_emit.py`) fails CI if the committed file drifts. This narrative doc + the
curated 33-step / LVS-chain / sign-off tables stay hand-authored and link to the generated file.
