# Vibe-IC Canonical Flow v2.0.0

**Status**: ACTIVE (since 2026-05-23, RFC v2.0 implemented on branch v2.0-phase-redesign)
**Predecessor**: `archive/CANONICAL_FLOW_v1.6.45.md`
**Companion**: `RFC_v2.0_PHASE_REDESIGN.md`、`RENAME_MAPPING_v2.0.0.md`
**Source of truth**: `vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml` + `programs/_path_layout.py`

> 通過後本檔取代 `CANONICAL_FLOW_v1.6.45.md`；舊檔搬到 `docs/architecture/archive/`。

---

## 1. 三 Phase 定義

| Phase | Contract | Deliverable | Acceptance gate |
|---|---|---|---|
| **Phase 1** | 任何輸入 → 結構化 L1-L13 JSON | `phase1/generated_docs/L*.json` + `phase1/human_docs/L*.md` | L1-L13 PASS + completeness check PASS |
| **Phase 2** | L1-L13 → verified gate-level netlist + FPGA SOF | `phase2/stage2/synth/post_dft_netlist.v` + `phase2/stage1/fpga/final/*.sof` | LEC PASS + FPGA on-board PASS |
| **Phase 3** | netlist → signed-off GDS → tapeout → manufacturing | `phase3/stage4/gds/*.gds` + `phase3/stage5_manufacturing/final_test_yield.json` | tapeout_checklist 4/4 PASS + flow_compliance_check `Overall: PASS` |

---

## 2. 兩入口統一收進 Phase 1

```
Path A (docs):     input/<vendor docs> ──► phase1/input_doc/ ──┐
                                                                ├──► phase1/generated_docs/L*.json ──► Phase 2
Path B (prompt):   prompt / dialogue   ──► phase1/input_prompt/┘
```

唯一的 universal handoff format = `phase1/generated_docs/L*.json`。Phase 2 不接受任何其他格式輸入。

---

## 3. Project Folder Layout

見 `RFC_v2.0_PHASE_REDESIGN.md` §4。摘錄頂層 whitelist：

```
<project>/
├── input/                              raw vendor docs / PDK / OTP / prompt
├── phase1/                             結構化 spec
├── phase2/                             RTL → verified netlist
├── phase3/                             sign-off → tapeout → manufacturing
├── reports/                            分層摘要
├── waivers.json
├── provenance.jsonl
└── rig_topology.json
```

`top_level_layout_check` gate enforce 此 whitelist；多餘檔案 FAIL。

---

## 4. 54 entities 對應到新 Phase

> 與 v1.6.45 相比，**每個 step 的語意完全沒變**，只是被重新分到不同 Phase 桶。Step 編號維持原狀。

### Phase 1 — 19 entities

| 編號 | 名稱 | 入口 | 新路徑 |
|---|---|---|---|
| — | Phase 1 dialogue (PM Agent ↔ user) | input_prompt | `phase1/input_prompt/` |
| — | datasheet-gen | input_doc | `phase1/generated_docs/L1.json` 系 |
| — | frs-gen | input_doc | `phase1/generated_docs/L2.json` 系 |
| — | cmd-protocol-gen | input_doc | … |
| — | regmap-gen | input_doc | |
| — | adi-spec-gen | input_doc | |
| — | control-logic-gen | input_doc | |
| — | test-debug-gen | input_doc | |
| — | timing-waveform-gen | input_doc | |
| — | rtl-constants-gen | input_doc | |
| — | integration-spec-gen | input_doc | |
| — | test-cases-gen | input_doc | |
| — | calibration-gen | input_doc | |
| — | behavioral-sequences-gen | input_doc | |
| — | lab-calibration-gen | input_doc | |
| — | otp-content-gen | input_doc | |
| — | doc-consistency-check | input_doc | |
| — | schematic-gen | input_doc | |
| **A1** | Analog Spec Extraction | （source: L1/L5） | `phase1/analog/<block>/spec.json` |

### Phase 2 — 17 entities

| 編號 | 名稱 | Stage | 🔁 |
|---|---|---|:--:|
| **P0** | Structural-RTL pre-flight (77 gates) | stage_p0 |  |
| 1 | Spec-to-RTL | stage1 |  |
| 2 | Lint | stage1 | 🔁 |
| 3 | CDC / RDC check | stage1 | 🔁 |
| 4 | Simulation | stage1 | 🔁 |
| 5 | Formal verification | stage1 | 🔁 |
| 6 | FPGA early prototype | stage1 |  |
| 7 | Constraint setup (SDC + PVT) | stage2 |  |
| 8 | SDC validation | stage2 | 🔁 |
| 9 | Synthesis (Yosys) | stage2 |  |
| 10 | Pre-layout STA | stage2 | 🔁 |
| 11 | DFT insertion (scan + ATPG) | stage2 |  |
| 12 | Post-DFT optimization | stage2 |  |
| 13 | Equivalence check (LEC) | stage2 | 🔁 |
| **A2** | Analog Topology Selection | （analog parallel） |  |
| **A3** | Analog Netlist Generation | （analog parallel） |  |
| **A4** | Analog Corner Sweep (PVT) | （analog parallel） |  |

### Phase 3 — 36 entities（含 18 數位 + 7 mfg + 5 analog + 4 mixed-sig + 2 misc）

| 編號 | 名稱 | Stage | 🔁 |
|---|---|---|:--:|
| 14 | pre-PnR Yosys gate | stage3 | 🔁 |
| 15 | Floorplan + PDN | stage3 |  |
| 16 | Clock planning | stage3 |  |
| 17 | Placement | stage3 |  |
| 18 | CTS | stage3 |  |
| 19 | Post-CTS hold fixing | stage3 | 🔁 |
| 20 | Routing | stage3 |  |
| 21 | Parasitic Extraction (SPEF) | stage3 |  |
| 22 | Post-route STA | stage3 | 🔁 |
| 23 | IR Drop | stage3 | 🔁 |
| 24 | EM check | stage3 | 🔁 |
| 25 | Antenna check | stage3 | 🔁 |
| 26 | Signal Integrity | stage3 | 🔁 |
| 27 | Post-Layout Gate-Level Sim | stage3 |  |
| 28 | Post-Layout SPICE Verif | stage3 |  |
| 29 | Physical Verif (DRC/LVS/ERC) | stage3 | 🔁 |
| 30 | ECO | stage3 | 🔁 |
| 31 | Power analysis | stage4 |  |
| 32 | Metal Fill | stage4 |  |
| 33 | Tapeout checklist | stage4 |  |
| 34 | GDSII output | stage4 |  |
| 35 | Foundry Handoff | stage4 |  |
| 36 | FPGA final sign-off | stage4 |  |
| 37 | Fabrication | stage5_manufacturing |  |
| 38 | Wafer Sort / Probe Test | stage5_manufacturing |  |
| 39 | Packaging | stage5_manufacturing |  |
| 40 | Final Test | stage5_manufacturing |  |
| **A5** | Analog Layout (Magic) | analog (in phase3) |  |
| **A6** | Analog Physical Verif (DRC+LVS) | analog (in phase3) |  |
| **A7** | Post-Layout Resim | analog (in phase3) | 🔁 |
| **A8** | Hardmacro Generation | analog (in phase3) |  |
| **A9** | Co-Sim / HW Verification | analog (in phase3) | 🔁 |
| **M1** | Top-Level Integration (A+D merge) | mixed_signal (in phase3) |  |
| **M2** | Power Domain + Level Shifter | mixed_signal (in phase3) |  |
| **M3** | AMS Verification | mixed_signal (in phase3) |  |
| **M4** | Mixed-Signal Sign-Off | mixed_signal (in phase3) |  |

---

## 5. v2.0.0 vs v1.6.45 改變的核心

| 項目 | v1.6.45 | v2.0.0 |
|---|---|---|
| Phase 數 | 7 桶（1 / 2a / 2b / analog / mixed_signal / 3 / manufacturing） | **3 桶（1 / 2 / 3）** |
| 入口統一 | 兩入口分屬不同 phase | 兩入口都收 Phase 1 |
| analog 軌道 | top-level，與 phase 並列 | 散到 phase1/2/3 內 |
| mixed_signal 軌道 | 在 phase3 下（已合理） | 維持在 phase3 下 |
| manufacturing | top-level | 移到 phase3/stage5_manufacturing/ |
| Phase 邊界 = 真實 milestone | ❌ 不是 | ✅ 對應 spec freeze / RTL freeze / tapeout |
| Slash command 數 | 8 | 5 |
| 每 Phase deliverable 統一 contract | ❌ | ✅ |

每個 step 的**演算法、I/O、closed-loop 行為完全沒改變**，只是被重新 tag 到不同 Phase。

---

## 6. Compliance & sign-off

```bash
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py <project> --strict
```

Verdict 字串改為新 Phase 命名（CLAUDE.md §11 同步改寫）：

- **`Overall: PASS`** — Phase 1 + Phase 2 + Phase 3 全部 entity PASS。production tapeout-ready。
- **`Overall: PASS_WITH_WAIVERS`** — 結構性完成，N 個 entity 用 `waivers.json` deferred。narrate as "executed PASS = X/(total − N), deferred = N pending foundry sign-off"。
- **`Overall: FAIL`** — 不完成，繼續做。

---

## 7. Out-of-date predecessors

通過後 archive：
- `CANONICAL_FLOW_v1.6.45.md` → `docs/architecture/archive/CANONICAL_FLOW_v1.6.45.md`
- `vibe_ic_34_steps_io_and_validation.md` → 同 archive
- `docs/design/STANDARD_FLOW.md` → 重寫或 archive

新增：
- `CANONICAL_FLOW_v2.0.0.md`（去掉 _PROPOSED 後綴）
- `RFC_v2.0_PHASE_REDESIGN.md`（決策紀錄保留）
- `RENAME_MAPPING_v2.0.0.md`（archive 為 v2.0.0 migration 歷史）
