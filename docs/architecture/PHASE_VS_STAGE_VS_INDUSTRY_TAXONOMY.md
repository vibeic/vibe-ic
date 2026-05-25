# Vibe-IC 步驟分類對照：Phase vs Stage 0-4 vs 業內傳統

**Source of truth**：`docs/architecture/CANONICAL_FLOW_v1.6.45.md`
**Generated**：2026-05-23
**範圍**：54 entities = 40 main-track steps + 9 analog (A1-A9) + 4 mixed-signal (M1-M4) + 1 P0 pre-flight

---

## 三種分類方式的定義

- **Phase**：目前 vibe-ic 的對外分類（Phase 1 / 2a / 2b / Analog / Mixed-signal / 3 / Manufacturing）
- **Stage（假設改成 0-4）**：替代方案
  - Stage 0 = Spec / Architecture
  - Stage 1 = Front-end（RTL + Verification）
  - Stage 2 = Synthesis / DFT
  - Stage 3 = Back-end + Signoff
  - Stage 4 = Tapeout / Manufacturing
- **業內傳統**：IC 業最常用的口語分類（Spec / Front-end / Synth+DFT / Back-end / Signoff / Tapeout / Post-silicon）

---

## Path A 入口（Prompt 模式）

| # | Step / Skill | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| — | Phase 1：PM Agent ↔ user dialogue → L1-L13 JSON + human MD | **Phase 1** | Stage 0 | **Spec / Architecture** |

## Phase 2a — 既有文件 → L1-L13（17 skills，無編號 step）

| Skill 群 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|
| datasheet-gen / frs-gen / cmd-protocol-gen / regmap-gen / adi-spec-gen / control-logic-gen / test-debug-gen / timing-waveform-gen / rtl-constants-gen / integration-spec-gen / test-cases-gen / calibration-gen / behavioral-sequences-gen / lab-calibration-gen / otp-content-gen / doc-consistency-check / schematic-gen | **Phase 2a** | Stage 0 | **Spec / Architecture** |

## Pre-flight

| Step | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| P0 | Structural-RTL pre-flight (77 gates) | Phase 2b | Stage 1 | Front-end (lint/structural) |

## stage1 — RTL + Verification（Steps 1-6）

| # | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| 1 | Spec-to-RTL | Phase 2b | Stage 1 | **Front-end (RTL design)** |
| 2 | Lint 🔁 | Phase 2b | Stage 1 | Front-end (RTL QA) |
| 3 | CDC / RDC check 🔁 | Phase 2b | Stage 1 | Front-end (RTL QA) |
| 4 | Simulation 🔁 | Phase 2b | Stage 1 | **Front-end (Functional verif)** |
| 5 | Formal verification 🔁 | Phase 2b | Stage 1 | Front-end (Functional verif) |
| 6 | FPGA early prototype | Phase 2b | Stage 1 | Front-end (Prototype / HW emul) |

## stage2 — Synthesis + DFT（Steps 7-13）

| # | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| 7 | Constraint setup (SDC + PVT) | Phase 2b | Stage 2 | **Synthesis / DFT** |
| 8 | SDC validation 🔁 | Phase 2b | Stage 2 | Synthesis / DFT |
| 9 | Synthesis (Yosys) | Phase 2b | Stage 2 | **Synthesis / DFT** |
| 10 | Pre-layout STA 🔁 | Phase 2b | Stage 2 | Synthesis / DFT (early timing) |
| 11 | DFT insertion (scan + ATPG) | Phase 2b | Stage 2 | **DFT** |
| 12 | Post-DFT optimization | Phase 2b | Stage 2 | Synthesis / DFT |
| 13 | Equivalence check (LEC) 🔁 | Phase 2b | Stage 2 | Synthesis / DFT |

## stage_analog — A1-A9（與 phase2b 平行）

| # | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| A1 | Analog Spec Extraction | Analog | Stage 0 | Spec / Architecture |
| A2 | Topology Selection | Analog | Stage 1 | **Analog Front-end (schematic)** |
| A3 | Netlist Generation | Analog | Stage 1 | Analog Front-end |
| A4 | Corner Sweep (PVT) | Analog | Stage 1 | Analog Front-end (sim) |
| A5 | Layout (Magic) | Analog | Stage 3 | **Analog Back-end (layout)** |
| A6 | Physical Verification (DRC+LVS) | Analog | Stage 3 | Analog Signoff |
| A7 | Post-Layout Resim 🔁 | Analog | Stage 3 | Analog Signoff |
| A8 | Hardmacro Gen (LEF/LIB/GDS/V) | Analog | Stage 3 | Analog Back-end (handoff) |
| A9 | Co-Sim / HW Verification 🔁 | Analog | Stage 3 | Mixed-signal Signoff |

## stage3 — Physical Design + Signoff（Steps 14-30）

| # | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| 14 | pre-PnR Yosys gate 🔁 | Phase 3 | Stage 2 | Synthesis 收尾 |
| 15 | Floorplan + PDN | Phase 3 | Stage 3 | **Back-end (Physical design)** |
| 16 | Clock planning | Phase 3 | Stage 3 | Back-end |
| 17 | Placement | Phase 3 | Stage 3 | Back-end |
| 18 | CTS | Phase 3 | Stage 3 | Back-end |
| 19 | Post-CTS hold fixing 🔁 | Phase 3 | Stage 3 | Back-end |
| 20 | Routing | Phase 3 | Stage 3 | Back-end |
| 21 | Parasitic Extraction (SPEF) | Phase 3 | Stage 3 | Back-end |
| 22 | Post-route STA 🔁 | Phase 3 | Stage 3 | **Signoff (Timing)** |
| 23 | IR Drop 🔁 | Phase 3 | Stage 3 | **Signoff (Power)** |
| 24 | EM check 🔁 | Phase 3 | Stage 3 | Signoff (Reliability) |
| 25 | Antenna check 🔁 | Phase 3 | Stage 3 | Signoff |
| 26 | Signal Integrity 🔁 | Phase 3 | Stage 3 | Signoff |
| 27 | Post-Layout Gate-Level Sim | Phase 3 | Stage 3 | Signoff (Functional) |
| 28 | Post-Layout SPICE Verif | Phase 3 | Stage 3 | Signoff (AMS correlation) |
| 29 | Physical Verif (DRC/LVS/ERC) 🔁 | Phase 3 | Stage 3 | **Signoff (Physical)** |
| 30 | ECO 🔁 | Phase 3 | Stage 3 | Back-end (repair loop) |

## stage_mixed_signal — M1-M4

| # | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| M1 | Top-Level Integration (A+D GDS merge) | Mixed-sig | Stage 3 | Back-end (Integration) |
| M2 | Power Domain + Level Shifter | Mixed-sig | Stage 3 | Signoff (Power) |
| M3 | AMS Verification (cosim + RNM + SI) | Mixed-sig | Stage 3 | Signoff (AMS) |
| M4 | Mixed-Signal Sign-Off | Mixed-sig | Stage 3 | Signoff |

## stage4 — Output + Validation（Steps 31-36）

| # | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| 31 | Power analysis | Phase 3 | Stage 3 | Signoff (Power) |
| 32 | Metal Fill | Phase 3 | Stage 3 | Back-end (density) |
| 33 | Tapeout checklist | Phase 3 | Stage 4 | **Tapeout (sign-off gate)** |
| 34 | GDSII output | Phase 3 | Stage 4 | **Tapeout (GDS release)** |
| 35 | Foundry Handoff (mask/WAT/scribe) | Phase 3 | Stage 4 | **Tapeout (Foundry handoff)** |
| 36 | FPGA final sign-off | Phase 3 | Stage 4 | Tapeout (HW final ack) |

## stage5_manufacturing — Steps 37-40

| # | 名稱 | Phase | Stage 0-4 | 業內傳統 |
|---|---|---|---|---|
| 37 | Fabrication (wafer fab) | Manufacturing | Stage 4 | **Manufacturing (Fab)** |
| 38 | Wafer Sort / Probe Test | Manufacturing | Stage 4 | **Post-silicon (Wafer test)** |
| 39 | Packaging (assembly) | Manufacturing | Stage 4 | Manufacturing (Assembly) |
| 40 | Final Test (ATE + burn-in) | Manufacturing | Stage 4 | **Post-silicon (Final test)** |

---

## 統計表（各分類桶的 step 數）

| 分類 | 桶 | Step 數 | 涵蓋 |
|---|---|---:|---|
| **Phase（現況）** | Phase 1 | 1 | dialogue → L1-L13 |
| | Phase 2a | 17 (skills) | docs → L1-L13 |
| | Phase 2b | 14 | P0 + Steps 1-13 |
| | Analog | 9 | A1-A9 |
| | Mixed-signal | 4 | M1-M4 |
| | Phase 3 | 23 | Steps 14-36 |
| | Manufacturing | 4 | Steps 37-40 |
| **Stage 0-4（假設）** | Stage 0 Spec | 19 | Phase 1 + Phase 2a 17 skills + A1 |
| | Stage 1 Front-end | 9 | P0 + Steps 1-6 + A2-A4 |
| | Stage 2 Synth/DFT | 8 | Steps 7-13 + Step 14 |
| | Stage 3 Back-end+Signoff | 24 | Steps 15-32 + A5-A9 + M1-M4 |
| | Stage 4 Tapeout/Mfg | 8 | Steps 33-40 |
| **業內傳統** | Spec / Architecture | 19 | Phase 1 + Phase 2a + A1 |
| | Front-end (RTL + Verif) | 9 | P0 + 1-6 + A2-A4 |
| | Synthesis / DFT | 8 | 7-14 |
| | Back-end (Physical) | 10 | 15-21, 30, 32, A5/A8 |
| | Signoff | 13 | 22-29, 31, A6/A7, M1-M4 |
| | Tapeout / Handoff | 4 | 33-36 + A9 |
| | Post-silicon / Mfg | 4 | 37-40 |

---

## 觀察

1. **Phase 2b 是現況最不均勻的桶**——它涵蓋了 Stage 1（Front-end RTL/Verif）+ Stage 2（Synth/DFT）兩個本來業界會切開的東西，外加 P0。改 Stage 0-4 後這 14 步會被乾淨切成 9 + 5。
2. **Phase 3 也是不均勻**——涵蓋 Back-end + Signoff + Tapeout 三個業界明確分開的階段（23 步全擠一桶）。Stage 0-4 會切成 16 + 7。
3. **Phase 2a + Phase 1 + A1** 本質上都是 spec/architecture 階段，業界會合併在「Spec」一桶；現況分成三個 phase。
4. **業內傳統分類最細**（7 桶），對 IC designer 最直覺；**Phase 1/2/3 最粗**（3 桶，但內部已被迫切出 2a/2b 顯示桶不夠用）；**Stage 0-4** 是中間平衡點。

---

## 後續可做的分析

- skill 命名 / program 前綴影響表：若從 `phase1/phase2a/phase2b/phase3` 改成 `stage0..4` 會動到幾個檔案
- 對外行銷層 vs 內部技術 taxonomy 雙軌並行的命名 mapping 表
- 各 Stage 對應到的 EDA tool 與 deliverable 清單
