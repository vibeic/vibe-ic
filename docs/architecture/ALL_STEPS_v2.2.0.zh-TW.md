# Vibe-IC — 全部步驟：Phase → Stage → Step（v2.2.0・繁體中文）

整條流程的每一步，以 **Phase → Stage → Step** 階層組織，主軸為**單一連續編號 1 → 41**
（自 Stage 1 的 Spec-to-RTL 起算）。Phase 1 的文件生成步驟以 **D1–D5** 標示（前置，
不計入 1→41）；兩條並行支線 **Analog A1–A9** 與 **Mixed-signal M1–M4** 同時進行。

**Phase → Stage 對照**

- **Phase 1** — 規格與文件：兩條入口（**Agent 路徑**・**doc-gen 路徑 D1–D5**）
- **Phase 2** — RTL → 合成：Stage 1（RTL+驗證）・Stage 2（合成+DFT）
- **Phase 3** — 實體 → Tapeout：Stage 3（實體+簽核）・Stage 4（輸出+Tapeout）・Stage 5（製造與測試）
- **並行** — Analog A1–A9・Mixed-signal M1–M4

---

## Phase 1 — 規格與文件

兩條入口，最終都產出餵給 Phase 2 的同一批 L 系列設計文件：

- `phase1/input_prompt/` —— 自由文字 / 自然語言 → **Agent 路徑**
- `phase1/input_doc/` —— 既有文件 / 結構化 YAML → **doc-gen 路徑**（D1–D5）

### Agent 路徑（輸入是自由文字時）

| Agent | 做什麼 |
|---|---|
| **PM Agent** | 面對使用者：把自然語言需求轉成設計事實，缺什麼就用白話一次問一題，確認後交棒。 |
| **IC Expert Agent** | 在 PM 後方：以矽智財專業審查每一層、補上合理預設值、做跨層一致性檢查。不直接面對使用者。 |

流程：使用者自由文字 → PM Agent → IC Expert Agent → 定稿 L 系列文件。

### doc-gen 路徑 D1–D5（輸入是既有文件時）

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| D1 | 匯入與文字萃取 | 把 prompt 或既有文件收進 `input_doc/` 並抽出純文字。 | `phase1_doc_one_shot_runner` |
| D2 | 產生 L1–L13 核心設計層文件 | 從文件確定性地萃取出核心設計層（datasheet、規格、暫存器圖等）。 | 決定性萃取器 |
| D3 | 產生 L14–L23 文件 | 補上協定、時序、skeleton 等延伸層。 | overlay 萃取器 |
| D4 | 協定類別合成 | 偵測 IC 屬於哪一種協定類別（81 類）並合成對應協定事實。 | `is_<proto>` + `<proto>_synth` |
| D5 | Coverage 報告 | 核對輸入文件的內容是否完整落入 L 文件。 | `phase1` parity 報告 |

---

## Phase 2 — RTL → 合成

### Stage 1 — RTL 產生與驗證

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| 1 | Spec-to-RTL | 依 L 系列設計文件撰寫可合成的 RTL。 | `spec-to-rtl` skill |
| 2 | 🔁 Lint | 靜態檢查 RTL 風格與常見錯誤，可自動修復的先修。 | `eda_lint` + `rtl_hygiene_lint` |
| 3 | 🔁 CDC / RDC check | 檢查跨時脈域 / 跨重置域的訊號交握是否安全。 | `cdc-check` + `rdc-check` |
| 4 | 🔁 Simulation | 產生 testbench 跑功能模擬並量測覆蓋率。 | `testbench-gen` + `eda_simulate` |
| 5 | 🔁 Formal verification | 以形式化方法證明關鍵性質（assertion）恆成立。 | `formal-verify` + `assertion-gen` |
| 6 | FPGA early prototype | 提早把設計放上 FPGA 驗證真實行為。 | `eda_fpga_compile` / `eda_fpga_program` → `.sof` |

### Stage 2 — 合成與 DFT

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| 7 | Constraint setup | 撰寫時序約束（SDC）與 PVT 角點矩陣。 | `constraint-gen` → `*.sdc` |
| 8 | 🔁 SDC validation | 驗證時序約束本身的正確性與完整性。 | SDC lint + `sdc_validator_check` |
| 9 | Synthesis | 把 RTL 合成為標準元件閘級網表。 | `eda_synth` + `synth-doctor` |
| 10 | 🔁 Pre-layout STA | 佈局前多角點靜態時序分析。 | `eda_sta`（SS/TT/FF） |
| 11 | DFT insertion | 插入掃描鏈與測試邏輯並產生測試圖樣。 | `dft-insert` + `atpg` + `eda_dft` |
| 12 | Post-DFT optimization | 插入 DFT 後重新最佳化時序與面積。 | resynth / buffering |
| 13 | 🔁 Equivalence check | 形式化證明閘級網表與 RTL 功能等價。 | `equivalence-check` + Yosys `equiv` |

---

## Phase 3 — 實體設計 → Tapeout

### Stage 3 — 實體設計與簽核

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| 14 | 🔁 pre-PnR Yosys gate | 進佈局前確認合成腳本與網表符合 PnR 要求。 | `yosys_script_template_check` + `yosys_hilomap_required_check` |
| 15 | Floorplan + PDN | 規劃晶片平面配置與電源網路。 | `eda_pnr`（init） |
| 16 | Clock planning | 規劃時脈樹的分佈策略。 | `cts-plan` skill |
| 17 | Placement | 擺放標準元件（全域 + 細部）。 | `eda_pnr` |
| 18 | Spare-cell + ECO-prep insertion | 預置備用元件與 ECO 預備，讓日後修 bug 只需改金屬層。 | `eda_pnr` + spare-cell 檢查 |
| 19 | CTS | 建構時脈樹、平衡時脈偏移。 | `eda_pnr enable_cts=true` |
| 20 | 🔁 Post-CTS hold fixing | 修復時脈樹建好後出現的 hold 違規。 | `hold-fix`（`repair_timing -hold`） |
| 21 | Routing | 完成所有訊號繞線（全域 + 細部）。 | `eda_pnr enable_detailed_route=true` |
| 22 | Parasitic extraction | 萃取繞線後的寄生 RC（SPEF）。 | OpenRCX `extract_parasitics` |
| 23 | 🔁 Post-route STA | 用真實寄生參數做簽核級時序分析。 | `eda_sta`（MMMC） |
| 24 | 🔁 IR drop | 分析電源網路壓降是否在允許範圍。 | OpenROAD PSM `analyze_power_grid` |
| 25 | 🔁 EM check | 檢查電流密度、確保金屬線壽命。 | PSM `-enable_em` |
| 26 | 🔁 Antenna check | 檢查並修復製程天線效應。 | OpenROAD `check_antennas` + `repair_antennas` |
| 27 | 🔁 Signal integrity | 分析串擾 / 雜訊對訊號的影響。 | SPEF coupling-cap 篩查 |
| 28 | Post-layout gate-level sim | 帶 SDF 延遲的閘級模擬，確認佈局後功能正確。 | `eda_simulate` |
| 29 | Post-layout SPICE verification | 對關鍵路徑與 analog 區塊做電晶體級模擬比對。 | `ams-sim` + `eda_spice` |
| 30 | 🔁 Physical verification | DRC / LVS / ERC 等實體規則簽核。 | KLayout DRC + LVS + Magic ERC |
| 31 | 🔁 ECO | 簽核發現問題時的工程變更修復迴圈。 | `eco-plan` |

### Stage 4 — 輸出與 Tapeout

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| 32 | Power analysis | 分析全晶片功耗（pre/post-layout）。 | `power-analysis` |
| 33 | Metal fill | 插入金屬填充以滿足密度規則。 | OpenROAD `filler_placement` |
| 34 | Tapeout checklist | 最終簽核清單逐項確認。 | `tapeout-checklist` + `signoff_audit` |
| 35 | GDSII output | 產出交付晶圓廠的 GDSII 資料。 | `eda_gds` + `def2gds` |
| 36 | Foundry handoff | 整理交付晶圓廠的完整資料包。 | `tapeout-checklist` + handoff 檢查 |
| 37 | FPGA final sign-off | 最終 FPGA 重編譯與板上驗證。 | recompile + on-board test |

### Stage 5 — 製造與測試（post-fab；僅在收到矽晶時觸發）

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| 38 | Fabrication | 晶圓廠光罩與晶圓製造（外部）。 | `manufacturing_fab_intake_check` |
| 39 | Wafer sort / probe test | 晶圓針測、挑出良品裸晶。 | `wafer_sort_yield_check` |
| 40 | Packaging | 封裝（wirebond / FC-CSP / WLCSP）。 | `packaging_intake_check` |
| 41 | Final test | 封裝後最終測試（functional + parametric + burn-in）。 | `final_test_attestation_check` |

---

## 並行支線

### Analog A1–A9（與 Stage 1–3 並行）

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| A1 | Analog spec extraction | 從 L 文件抽出每個 analog 區塊的規格。 | `analog-spec-extract` → `spec.json` |
| A2 | Topology selection | 依規格選擇電路拓樸。 | `analog-topology-select` |
| A3 | Netlist generation | 產生 SPICE netlist。 | `eda_xschem_netlist` → `<block>.sp` |
| A4 | Corner sweep | 跑 PVT 角點掃描確認規格全角點達標。 | `eda_spice_corner` |
| A5 | Analog layout | 完成 analog 佈局。 | `eda_analog_layout` |
| A6 | Block physical verification | 逐區塊 DRC + LVS（合併前）。 | `analog_a6_block_pv_check` |
| A7 | 🔁 Post-layout resimulation | 萃取寄生後再模擬、比對佈局前後規格。 | `analog-extraction-resim` |
| A8 | Hardmacro generation | 打包成 LEF + Liberty + GDS + Verilog 餵回 Stage 3。 | `analog-hardmacro-gen` |
| A9 | 🔁 Co-simulation / HW verification | 數位+類比混合模擬與硬體迴圈驗證。 | `mixed-signal-cosim` + `eda_spice` |

### Mixed-signal M1–M4（存在 analog 區塊時觸發）

| # | 步驟 | 做什麼 | 工具 / 方式 |
|---|---|---|---|
| M1 | 頂層整合 | 數位 + 類比 GDS 合併與 macro 擺放。 | `mixed_signal_merge_check` |
| M2 | 電源域驗證 | 檢查跨電源域的 level-shifter / isolation。 | 電源域檢查群 |
| M3 | Mixed-signal 驗證 | AMS 共模擬與介面訊號完整性。 | `mixed_signal_cosim_check` |
| M4 | Mixed-signal sign-off | 頂層實體驗證與最終判定。 | `mixed_signal_signoff_check` |

---

## 總計

| Phase | Stages | Steps |
|---|---|---|
| Phase 1 — 規格與文件 | 兩條入口（Agent・doc-gen） | D1–D5 + PM Agent・IC Expert Agent |
| Phase 2 — RTL → 合成 | Stage 1・Stage 2 | 1–13 |
| Phase 3 — 實體 → Tapeout | Stage 3・Stage 4・Stage 5 | 14–41 |
| 並行 | Analog・Mixed-signal | A1–A9・M1–M4 |

**41 個循序步驟**（Stage 1：1–6・Stage 2：7–13・Stage 3：14–31・Stage 4：32–37・
Stage 5：38–41），外加 Phase 1（Agent 路徑與 doc-gen 路徑 D1–D5）與兩條並行支線
（Analog A1–A9・Mixed-signal M1–M4）。預檢：P0（環境健檢）。
編排器 `vibe_ic_one_shot_runner.py` 依序執行 Phase 1 → Phase 2 → Analog → Phase 3。

英文正本：`ALL_STEPS_v2.2.0.md`。
