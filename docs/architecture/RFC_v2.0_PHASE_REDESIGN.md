# RFC v2.0 — Phase Redesign（Phase 1/2a/2b/3 → Phase 1/2/3）

**Status**: PROPOSED
**Date**: 2026-05-23
**Author**: reyerchu
**Companion docs**:
- `RENAME_MAPPING_v2.0.0.md`（執行用對照表）
- `CANONICAL_FLOW_v2.0.0_PROPOSED.md`（新 layout 規格書）
- `PHASE_VS_STAGE_VS_INDUSTRY_TAXONOMY.md`（決策背景）
- `CANONICAL_FLOW_v1.6.45.md`（現況 baseline）

---

## 1. Summary

把現況的 **Phase 1 / Phase 2a / Phase 2b / Phase 3 / 平行 Analog / 平行 Mixed-signal / Manufacturing** 七桶分類，重劃為 **Phase 1 / Phase 2 / Phase 3** 三桶，分類原則從「**做哪些 skill**」改為「**產出什麼 deliverable**」：

| Phase | Deliverable | 對應里程碑 |
|---|---|---|
| **Phase 1** | 結構化 L1-L13 JSON | Spec freeze |
| **Phase 2** | 驗證過的 RTL + gate-level netlist + FPGA SOF | RTL / 功能 freeze |
| **Phase 3** | 簽核完成的 GDS + foundry handoff + 量產 | Tapeout / 物理 freeze |

兩個入口（design docs / dialogue）統一收歸 Phase 1，內部以 `phase1/input_doc/` 與 `phase1/input_prompt/` 子目錄區分。Analog A1-A9 與 Mixed-signal M1-M4 拆進對應 Phase（Layout P）。

---

## 2. Motivation

### 2.1 現況 Phase 2 桶語意混雜
Phase 2 同時涵蓋「spec 抽取」與「RTL/synth」兩種本質完全不同的工作，內部被迫切成 2a/2b——這本身就是現有分類顆粒度不對的證據。

### 2.2 兩個入口不對稱
- Path A（dialogue）叫 Phase 1
- Path B（design docs）叫 Phase 2a

兩者輸出完全一樣（都是 L1-L13），但命名不對稱。新人第一次看就誤解兩者是不同階段。

### 2.3 Phase 邊界與真實里程碑對不起來
真實 IC 專案的三個 freeze gate 是：**spec freeze → RTL freeze → tapeout**。現況 Phase 1 只涵蓋 spec freeze 的一條 path、Phase 2 跨越 spec freeze + RTL freeze、Phase 3 只到 tapeout 前。重劃後三個 Phase 邊界對齊三個 freeze gate，PM / 投資人 / foundry 都看得懂。

---

## 3. New Phase Definitions

### Phase 1 — Spec → Structured Data
- **Input**：任何形式（vendor docs / OTP / PDK / 自然語言 prompt）
- **Process**：兩條入口殊途同歸
  - `input_doc/`：17 skills 從 design docs 抽取
  - `input_prompt/`：PM Agent ↔ user dialogue（fact-graph engine）
- **Output**：`phase1/generated_docs/L1-L13.json`（機器可讀）+ `human_docs/L*.md`（人類可讀）
- **Acceptance gate**：L1-L13 全 PASS、phase1_input_vs_generated_completeness_check PASS
- **涵蓋 entities**：18 skills（1 dialogue + 17 doc extraction）+ A1（analog spec extraction）= **19 entities**

### Phase 2 — Structured Data → Verified Netlist
- **Input**：`phase1/generated_docs/L*.json`（唯一輸入；不再讀 vendor docs）
- **Process**：P0 pre-flight + Steps 1-13（RTL gen → lint → CDC → sim → formal → FPGA early prototype → SDC → synth → pre-layout STA → DFT → post-DFT opt → LEC）+ A2-A4（analog topology / netlist / corner sweep）
- **Output**：post-DFT gate-level netlist、FPGA SOF（on-board PASS）、A2-A4 analog 中間 deliverable
- **Acceptance gate**：LEC PASS（RTL ≡ post-DFT netlist）+ FPGA on-board PASS
- **涵蓋 entities**：P0 + 13 digital + 3 analog = **17 entities**

### Phase 3 — Sign-off → Tapeout → Manufacturing
- **Input**：Phase 2 的 verified netlist + A4 corner-passing analog sizing
- **Process**：Steps 14-40（pre-PnR Yosys 收尾 → floorplan → CTS → routing → SPEF → post-route STA → IR/EM/antenna/SI → post-layout sim/SPICE → DRC/LVS/ERC → ECO → power → fill → tapeout checklist → GDS → foundry handoff → FPGA final → fab → wafer sort → packaging → final test）+ A5-A9（analog layout / PV / resim / hardmacro / co-sim）+ M1-M4（mixed-signal）
- **Output**：signed-off GDS、foundry handoff package、wafer/packaged die
- **Acceptance gate**：tapeout_checklist 4/4 PASS + flow_compliance_check `Overall: PASS`
- **涵蓋 entities**：27 digital (Steps 14-40) + 5 analog (A5-A9) + 4 mixed-signal = **36 entities**

### 統計
| Phase | Entities | 佔比 |
|---|---:|---:|
| Phase 1 | 19 | 26% |
| Phase 2 | 17 | 24% |
| Phase 3 | 36 | 50% |
| **總計** | **72** | **100%** |

> 註：舊 54 entities + 17 phase2a skills 算單獨 entities = 72。或維持 54 entities（phase2a 17 skills 收為 1 個 "phase1 doc-extraction stage"）：Phase 1 = 3 / Phase 2 = 17 / Phase 3 = 36 = 56。兩種算法都可，敘事用前者（每 skill 算一個 entity）較直覺。

---

## 4. New Project Folder Layout（Layout P 完整版）

```
<project>/
├── input/                          raw vendor docs / PDK / OTP / prompt 原文
│
├── phase1/                         Phase 1 = 結構化 spec
│   ├── input_doc/                    入口 A：vendor docs 抽取的 verbatim 引文（原 phase2a/extracted_docs）
│   ├── input_prompt/                 入口 B：dialogue 紀錄 + fact-graph (原 tools/phase1_fg/ 拉進專案)
│   ├── generated_docs/L*.json        ← UNIVERSAL HANDOFF（唯一機器可讀 spec）
│   ├── human_docs/L*.md              人類 review 用
│   ├── extraction_patterns.json
│   ├── extraction_patterns.auto.json
│   ├── completeness_check_config.json
│   ├── ai_deep_review_patches.json
│   └── analog/<block>/spec.json      A1 analog spec extraction
│
├── phase2/                         Phase 2 = RTL → verified netlist
│   ├── stage1/                       Steps 1-6
│   │   ├── rtl/                        Step 1 output
│   │   ├── rtl.pre_gen_backup/
│   │   ├── sim/                        Step 4
│   │   ├── sim_full_stack/             Step 5 bit-level TB
│   │   ├── formal/                     Step 5 SBY
│   │   ├── tb/
│   │   └── fpga/                       Step 6
│   ├── stage2/                       Steps 7-13
│   │   ├── constraints/                Step 7 SDC + PVT
│   │   ├── synth/                      Steps 9 / 12
│   │   └── dft/                        Step 11 scan + ATPG
│   └── analog/<block>/               A2-A4
│       ├── topology.md                 A2
│       ├── *.sp                        A3
│       └── corner_results.json         A4
│
├── phase3/                         Phase 3 = sign-off + tapeout + manufacturing
│   ├── stage3/                       Steps 14-30
│   │   ├── pnr/                        Steps 15-20, 32
│   │   ├── cts/                        Steps 16, 18
│   │   ├── extracted/                  Step 21 SPEF
│   │   ├── eco/                        Step 30
│   │   ├── spice/                      Step 28
│   │   ├── sta/                        Steps 10, 22
│   │   └── sim_postlayout/             Step 27
│   ├── stage4/                       Steps 31-36
│   │   ├── gds/                        Step 34
│   │   └── foundry_handoff/            Step 35
│   ├── stage5_manufacturing/         Steps 37-40
│   │   ├── mask_set_received.json      Step 37
│   │   ├── wafer_lot_received.json     Step 37
│   │   ├── wafer_sort_yield.json       Step 38
│   │   ├── wafer_map.csv               Step 38
│   │   ├── packaging_log.json          Step 39
│   │   ├── final_test_yield.json       Step 40
│   │   └── burn_in_results.json        Step 40
│   ├── analog/<block>/               A5-A9
│   │   ├── layout.mag                  A5
│   │   ├── drc_clean.flag              A6
│   │   ├── lvs_match.flag              A6
│   │   ├── pre_vs_post.json            A7
│   │   └── (cosim hooks)               A9
│   ├── analog/hardmacro/<block>/     A8 packaged hardmacro
│   │   ├── *.lef *.lib *.gds *.v
│   └── mixed_signal/                 M1-M4
│       ├── top_merged.gds              M1
│       └── cosim/                      M3 AMS co-sim
│
├── reports/                        分層摘要
│   ├── phase1/                       原 reports/phase2a/
│   ├── phase2/                       原 reports/phase2b/
│   ├── phase3/                       Steps 14-40 + analog A5-A9 + M1-M4
│   ├── audit/                        flow_compliance.json, tapeout_checklist.json
│   ├── orchestrator/                 one_shot runners 的 JSON + log
│   ├── final_summary.md              chip-AGNOSTIC
│   └── chip_specific_summary.md      chip-specific
│
├── waivers.json
├── provenance.jsonl
└── rig_topology.json
```

**Top-level whitelist**（`top_level_layout_check` gate 強制）:
- 4 目錄：`input/ phase1/ phase2/ phase3/`（+ `reports/`）
- 3 metadata 檔：`waivers.json provenance.jsonl rig_topology.json`

**消失的舊頂層**：
- `phase2a/` → 併進 `phase1/`
- `phase2b/` → 改名 `phase2/`
- `analog/` → 散到 `phase1/analog/ phase2/analog/ phase3/analog/`
- `manufacturing/` → 改成 `phase3/stage5_manufacturing/`
- `phase3/mixed_signal/` → 保留在 phase3 內

---

## 5. Breaking Changes Summary

| 類別 | 動作 | 數量 |
|---|---|---:|
| Skill 目錄改名 | rename | 6 |
| Program 檔名改名 | rename | 22 |
| Slash command | rename + 1 個刪除 (`/vibe-ic-phase2a` 併入 `/vibe-ic-phase1`) | 6 → 5 |
| Flow YAML | 重寫（內含 184 phase token） | 1 檔 |
| `_path_layout.py` | 重寫（內含 126 phase token + 新 layout 路徑） | 1 檔 |
| 其他 source 內容引用 | sed + 人工 review | 253 files / 2,113 tokens |
| Test fixture | mechanical rename | 668 files / 3,784 tokens |
| Docs | 重寫 CLAUDE.md §11 + README + CANONICAL_FLOW | 約 20 files |
| 舊 benchmark output | **全部刪除重跑**（沒有 backwards-compat） | 197 目錄 |
| `community/backlogs/ORGANIC-*.yaml`（未送 13 個） | id 前綴改寫 | 13 files |

無 backwards-compat（user 已確認尚未 release）。

---

## 6. Migration Execution Order

依賴關係決定執行順序：

```
T0  freeze main branch（建 `v2.0-rename` branch）
T1  寫 `_path_layout.py` v2 + `flow/phase1_phase2_phase3.yaml`（authoritative source）
T2  git mv 所有 skill 目錄 + program 檔
T3  全域 sed： `phase2a` → `phase1_doc`、`phase2b` → `phase2`（注意先後順序，phase2a 必須先換）
T4  重寫每個 one_shot_runner（phase1 / phase2 / phase3 / phase23 / vibe_ic）
T5  重寫 flow_compliance_check.py（verdict 字串、stage_label 對應）
T6  重寫 commands/*.md（5 個 slash command）
T7  重寫 CLAUDE.md §11 + CANONICAL_FLOW v2.0.0
T8  跑 1819 個現有 test → 補 / 改至全綠
T9  選 1 個 benchmark 從 phase1 跑到 phase3 → flow_compliance_check `Overall: PASS`
T10 刪除舊 benchmark output 目錄（197 個）
T11 改寫 community/backlogs/ORGANIC-*.yaml id 前綴
T12 merge `v2.0-rename` → main + git tag `v2.0.0`
```

**估時**：2-3.5 工作天（前估）。

---

## 7. Acceptance Criteria

- [ ] `flow_compliance_check.py <project> --strict` 在 1 個 benchmark 上 `Overall: PASS`
- [ ] 1819 unit tests 全綠
- [ ] `_path_layout.py` 是唯一路徑來源；grep 確認無 hardcode `phase2a / phase2b / manufacturing`
- [ ] CLAUDE.md §11 SOLE ACCEPTANCE CRITERION 與新 verdict 字串完全一致
- [ ] `top_level_layout_check` gate 強制新 4 目錄 whitelist
- [ ] Phase 1 兩個入口（`/vibe-ic-phase1 docs <path>` 與 `/vibe-ic-phase1 prompt "..."`）皆 PASS
- [ ] `CANONICAL_FLOW_v2.0.0.md` 上架，`v1.6.45.md` 移到 `docs/architecture/archive/`

---

## 8. Rejected Alternatives

### 8.1 Layout (T) — Track-orthogonal
保留 `analog/` 和 `mixed_signal/` 在 top-level，與 phase1/2/3 並列。
- **棄用理由**：破壞「Phase 是最高層唯一分類」敘事。對外解釋會多一句「但 analog 是 cross-cutting 不在 phase 編號內」，正是這次重劃要消除的混雜。

### 8.2 Phase1a / Phase1b 子編號
原 user 提案是 `phase1a (docs) / phase1b (dialogue)`。
- **棄用理由**（user 選 C）：兩條 path 殊途同歸都吐 L1-L13，沒必要在 Phase 編號層級暴露入口差異。改成 `phase1/input_doc/` 與 `phase1/input_prompt/` 子目錄就夠。

### 8.3 Stage 0-4 平行重劃
順便把內部 `stage1 / stage2 / stage3 / stage4 / stage5_manufacturing` 改成 `stage0 / stage1 / stage2 / stage3 / stage4`。
- **棄用理由**：scope creep。本 RFC 只動 Phase 層級。內部 stage 標籤現況沿用（stage1/2 在 phase2 內，stage3/4/5 在 phase3 內），不影響對外敘事。日後若要再切，獨立 RFC 處理。

### 8.4 維持現況 + 文件加註
僅在 CLAUDE.md 多寫一段「Phase 2a 其實是 spec 階段，請當作 Phase 1 看」。
- **棄用理由**：技術債轉移到讀者。命名 = 系統的 API，API 該對的時候就要改對。
