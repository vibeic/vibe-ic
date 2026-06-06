# Vibe-IC — 全部步驟：Phase → Stage → Step（v2.3.0・繁體中文）

整條流程的每一步，以 **Phase → Stage → Step** 階層組織，主軸為**單一連續編號 1 → 44**
（自 Stage 1 的 Spec-to-RTL 起算）。Phase 1 的文件生成步驟以 **D1–D5** 標示（前置，
不計入 1→44）；兩條並行支線 **Analog A1–A9** 與 **Mixed-signal M1–M4** 同時進行。

v2.3.0 重點（對齊業界標準流程，發佈前一次到位）：

- **Step 14 歸入 Stage 2**：它是合成→PnR 的交接 QA（合成階段收尾），非實體設計步驟；標註「開源 Yosys 專用」。
- **新 Step 28：PERC / Reliability sign-off**：ESD 焊環＋放電拓樸、latch-up well-tap、跨電壓域保護——比照業界 Calibre-PERC 獨立簽核 deck，升為強制編號步驟（原 28–41 順移）。
- **新 Step 35：DFM screen**：CMP 密度窗＋redundant-via 比率（DEF 確定性計數）＋ OPC/RET/SRAF/PSM 以 `FOUNDRY_SIDE` 具名揭露（mask 合成屬 foundry 端；≤28nm 升級為設計者協作項）。
- **新 Step 44：可靠度驗證（HTOL）**：長時操作壽命 qual，與 Step 43 的 burn-in（嬰兒期篩選）區分。
- 每步新增**輸入 / 輸出**兩欄（輸出取自 flow yaml 的 required_outputs）。

**Phase → Stage 對照**

- **Phase 1** — 規格與文件：兩條入口（**Agent 路徑**・**doc-gen 路徑 D1–D5**）＋ 選用的架構探索前端
- **Phase 2** — RTL → 合成：Stage 1（RTL+驗證）・Stage 2（約束+合成+DFT+交接閘）
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

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| D1 | 匯入與文字萃取 → L1–L13 | 把 prompt 或既有文件收進 `input_doc/` 並確定性萃取核心設計層。 | 使用者文件 / prompt | `L1`–`L13` JSON |
| D2 | 產生 L1–L13 核心設計層文件 | 從文件確定性地萃取出核心設計層（datasheet、規格、暫存器圖等）。 | D1 純文字 | `L1_DATASHEET` … `L13` |
| D3 | 產生 L14–L23 文件 | 補上協定、時序、power intent（L21）、skeleton 等延伸層。 | L1–L13 | `L14`–`L23` JSON |
| D4 | 協定類別合成 | 偵測 IC 屬於哪一種協定類別（81 類）並合成對應協定事實。 | 輸入文件全文 | `ic_class` + 協定事實 |
| D5 | Coverage 報告 | 核對輸入文件的內容是否完整落入 L 文件。 | 輸入文件 + L 文件 | parity / coverage 報告 |

### 架構探索前端（選用，匯入 Step 1）

| 前端 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|
| architecture-explore | 設計空間探索（pipeline 深度／平行度／記憶體 vs PPA，Pareto 篩選）。 | L 文件 + 效能目標 | 架構決策（餵 Step 1） |
| hls-c2rtl | C/C++/SystemC 經 HLS 轉 RTL（開源 XLS 等）。 | C/SystemC 模型 | RTL（進 Step 2 起照常驗證） |
| SpinalHDL/Chisel 前端 | `eda_spinalhdl_gen` 由 Scala HDL 產 Verilog。 | SpinalHDL 原始碼 | Verilog RTL |

---

## Phase 2 — RTL → 合成

### Stage 1 — RTL 產生與驗證

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| 1 | Spec-to-RTL | 依 L 系列設計文件撰寫可合成的 RTL（SoC/CPU 類可走 IP-catalog 重用＋膠合層路徑）。 | L1–L23 文件 | `rtl/*.v(.sv)`・coverage 報告 |
| 2 | 🔁 Lint | 靜態檢查 RTL 風格與常見錯誤，可自動修復的先修。 | RTL | lint 報告（hygiene / ROM-init） |
| 3 | 🔁 CDC / RDC check | 檢查跨時脈域 / 跨重置域的訊號交握是否安全。 | RTL | CDC/RDC 報告（crossing / async / reset-dep） |
| 4 | 🔁 Simulation | 產生 per-IC oracle testbench 跑功能模擬（golden 比對）並量測覆蓋率。 | RTL・L10 測項 | sim log・results.xml・coverage 報告 |
| 5 | 🔁 Formal verification | 以形式化方法證明關鍵性質恆成立（`all_proved` 需 .sby + SymbiYosys 證據鏈）。 | RTL・L3 約束 | `.sby`・formal results・full-stack TB 結果 |
| 6 | FPGA early prototype | 合成前期把設計放上 FPGA 驗證真實行為（早期行為原型）。 | RTL・板卡約束 | `.sof`・map 報告・FPGA 驗證 audit |

### Stage 2 — 約束、合成、DFT 與交接閘

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| 7 | Constraint setup | 撰寫時序約束（SDC）與 PVT 角點矩陣；power intent 由 L21 建模。 | L8 時序・L21・PDK liberty | `*.sdc`・`pvt_matrix.json` |
| 8 | 🔁 SDC validation | 驗證時序約束的正確性、完整性與例外（false_path/multicycle）正當性。 | SDC・L8 | SDC 檢查報告 |
| 9 | Synthesis | RTL 合成並做技術映射（dfflibmap + abc -liberty）為標準元件閘級網表。 | RTL・SDC・liberty | `synth/netlist.v`・面積統計 |
| 10 | 🔁 Pre-layout STA | 佈局前多角點靜態時序分析（SS/TT/FF）。 | 網表・SDC・liberty | pre-PnR 時序報告 + 摘要 |
| 11 | DFT insertion | 插入掃描鏈並產生測試圖樣（開源 Fault：scan + stuck-at ATPG + TAP；MBIST/LBIST/壓縮不在開源範圍）。 | 網表 | scan 網表・ATPG 覆蓋率報告 |
| 12 | Post-DFT optimization | 插入 DFT 後重新最佳化時序與面積。 | scan 網表 | `post_dft_netlist.v` |
| 13 | 🔁 Equivalence check | 形式化證明閘級網表與 RTL 功能等價（LEC）。 | RTL・post-DFT 網表 | LEC 報告 |
| 14 | 🔁 Synthesis handoff gate | 合成→PnR 交接 QA：合成腳本與網表審核（**開源 Yosys 專用**；合成階段收尾閘）。 | synth 腳本・網表 | handoff 審核報告 |

---

## Phase 3 — 實體設計 → Tapeout

### Stage 3 — 實體設計與簽核

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| 15 | Floorplan + PDN | 規劃晶片平面配置與電源網路；插入 tapcell（latch-up well-tie，SKY130 14µm 規則）。 | 網表・hardmacro LEF（`pdk_local/` 自動納入） | `floorplan.def`・PDN |
| 16 | Clock planning | 規劃時脈樹的分佈策略。 | floorplan | `clock_plan.json` |
| 17 | Placement | 擺放標準元件（全域 + 細部）。 | floorplan・網表 | `placed.def` |
| 18 | Spare-cell + ECO-prep insertion | 預置備用元件與 ECO 預備，讓日後修 bug 只需改金屬層。 | placed.def | `spare_cells.json`・覆蓋率報告 |
| 19 | CTS | 建構時脈樹、平衡時脈偏移。 | placed.def・clock plan | `post_cts.def`・時脈樹報告 |
| 20 | 🔁 Post-CTS hold fixing | 修復時脈樹建好後出現的 hold 違規（繞線後 runner 會再跑一次 hold 修復）。 | post_cts.def | `post_hold.def` |
| 21 | Routing | 完成所有訊號繞線（全域 + 細部）。 | post_hold.def | `routed.def`・router DRC 報告 |
| 22 | Parasitic extraction | 萃取繞線後的寄生 RC（SPEF）。 | routed.def・tech LEF | SPEF |
| 23 | 🔁 Post-route STA | 真實寄生參數簽核級時序分析（MMMC＝per-corner 迴圈，每角獨立報告）。 | 網表・SPEF・SDC・多角 liberty | post-route 時序報告・`per_corner/` |
| 24 | 🔁 IR drop | 電源網路壓降分析，依 5%-VDD 預算判 PASS/FAIL。 | routed.def（PSM） | IR 報告（worst µV + 預算判定） |
| 25 | 🔁 EM check | 檢查電流密度、確保金屬線壽命。 | routed.def（PSM -enable_em） | EM 報告 + 分段電流 |
| 26 | 🔁 Antenna check | 檢查並修復製程天線效應。 | routed.def | antenna 報告 |
| 27 | 🔁 Signal integrity | 串擾 / 雜訊影響分析（SPEF 耦合電容篩查，advisory tier 明示）。 | SPEF | SI 報告（含 >0.9 耦合 watch-list） |
| 28 | 🔁 PERC / Reliability sign-off | **（新）** ESD 焊環＋放電拓樸、latch-up well-tap、跨電壓域保護的強制簽核；元件物理尺寸留具名 manual-review。 | routed.def・24–27 報告 | `perc_equivalent.json`・PERC memo・gate 判定 |
| 29 | Post-layout gate-level sim | 帶 SDF 延遲的閘級模擬，確認佈局後功能正確（無 SDF 重模擬即誠實 SKIP）。 | 閘級網表・SDF・TB | post-sim 結果 |
| 30 | Post-layout SPICE verification | 關鍵路徑與 analog 區塊的電晶體級模擬比對。 | SPICE deck・SPEF | SPICE 比對報告 |
| 31 | 🔁 Physical verification | DRC / LVS / ERC / 密度（逐層 CMP 窗）實體規則簽核；LVS 走 Magic 抽取 + netgen 真比對。 | GDS・閘級網表・PDK deck | 簽核 DRC・LVS・ERC 報告 |
| 32 | 🔁 ECO | 簽核發現問題時的工程變更修復迴圈。 | 簽核報告 | ECO log 或 no-ECO flag |

### Stage 4 — 輸出與 Tapeout

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| 33 | Power analysis | 全晶片功耗簽核（post-layout vectorless OpenSTA report_power；VCD 向量模式可選）。 | 網表・SDC・liberty（＋選用 VCD） | power 報告（leakage+dynamic, analysis_mode） |
| 34 | Metal fill | 標準元件列 filler placement（white-space 填充）；逐層金屬 CMP 密度由 Step 31 的 KLayout deck 篩查。 | routed.def | `filled.def`・密度報告 |
| 35 | DFM screen | **（新）** 可製造性篩查：CMP 密度窗＋redundant-via 比率（single-cut 比例 advisory）；OPC/RET/SRAF/PSM 以 FOUNDRY_SIDE 具名揭露（≤28nm 為設計者協作項）。 | routed.def・密度報告 | `dfm_screen.json`（via 統計＋foundry-side 清單） |
| 36 | Tapeout checklist | 最終簽核清單逐項確認（實質判定：DRC 計數、證據鏈）。 | 全部簽核報告 | `tapeout_checklist.json` |
| 37 | GDSII output | 產出交付晶圓廠的 GDSII（僅當 Step 31 PV 全淨）。 | routed.def・merged GDS | 簽核級 `*.gds` |
| 38 | Foundry handoff | foundry 實體 mask kit：mask spec＋WAT 計畫＋scribe PCM＋corner ATE 向量（chip-specific；foundry 待供欄位以 `PENDING_FOUNDRY_*` 具名）。 | GDS・netlist 統計・L10 測項 | `mask_spec.json`・`wat_plan.json`・scribe・`corner_test_vectors.json` |
| 39 | FPGA final sign-off | 最終 FPGA 重編譯與板上驗證（板上 attestation，含硬體證據）。 | RTL・板卡 | final `.sof`・`on_board_pass.json` |

### Stage 5 — 製造與測試（post-fab；僅在收到矽晶時觸發）

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| 40 | Fabrication | 晶圓廠光罩與晶圓製造（外部；OPC/RET 屬 foundry 端 mask 合成）。 | foundry handoff kit | mask/wafer 收貨 attestation |
| 41 | Wafer sort / probe test | 晶圓針測、挑出良品裸晶；獨立重算良率並比對目標。 | wafer lot・probe 卡 | `wafer_sort_yield.json`・`wafer_map.csv` |
| 42 | Packaging | 封裝（wirebond / FC-CSP / WLCSP）。 | 良品裸晶 | `packaging_log.json` |
| 43 | Final test | 封裝後最終測試（functional + parametric + burn-in 嬰兒期篩選）。 | 封裝品・ATE 圖樣 | `final_test_yield.json`・`burn_in_results.json` |
| 44 | Reliability qualification | **（新）** HTOL 長時壽命 qual（device-hours／failures／FIT attestation；車規/醫療等級必跑，消費級 MPW 可休眠）。 | HTOL 爐結果 | `htol_results.json` 判定 |

> 流程外實驗室步驟（不列編號）：PFA/EFA（FIB/SEM/EMMI 破壞性失效分析）、silicon characterization（shmoo）——資料來自外部設備，plugin 提供 `wafer_map_pattern_classify` 等根因分析層。

---

## 並行支線

### Analog A1–A9（與 Stage 1–3 並行）

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| A1 | Analog spec extraction | 從 L 文件抽出每個 analog 區塊的規格。 | L5 ADI 規格 | `spec.json` |
| A2 | Topology selection | 依規格選擇電路拓樸。 | spec.json | `topology.md` |
| A3 | Netlist generation | 產生 SPICE netlist。 | topology・PDK models | `<block>.sp` |
| A4 | Corner sweep | PVT 角點掃描 + 蒙地卡羅良率（`mc_yield_pct` ≥95% 閘）。 | `.sp`・PDK corner libs | `corner_results.json`（executed/derived 計數） |
| A5 | Analog layout | 完成 analog 佈局。 | netlist | `layout.mag` / GDS |
| A6 | Block physical verification | 逐區塊 DRC + LVS（合併前；頂層 PV 會遮蔽的區塊級錯誤在此抓）。 | block GDS・netlist | DRC clean / LVS match flags |
| A7 | 🔁 Post-layout resimulation | 萃取寄生後再模擬、比對佈局前後規格（>10% 劣化回 A3）。 | layout 寄生・spec | `pre_vs_post.json` |
| A8 | Hardmacro generation | 打包成 LEF + Liberty + GDS + Verilog 餵回 Stage 3。 | layout・特徵化結果 | 四件套 hardmacro |
| A9 | 🔁 Co-simulation / HW verification | 數位+類比混合模擬與硬體迴圈驗證。 | hardmacro・數位 RTL | cosim / HW 量測結果 |

### Mixed-signal M1–M4（存在 analog 區塊時觸發）

| # | 步驟 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|---|
| M1 | 頂層整合 | 數位 + 類比 GDS 合併與 macro 擺放；merged GDS 跑頂層 LVS（Magic 抽取 + netgen，macro blackbox）。 | 數位 GDS・hardmacro GDS | `top_merged.gds`・merge/LVS 報告 |
| M2 | 電源域驗證 | 跨電源域 level-shifter / isolation 結構驗證（另有 DEF 級跨域簽核檢查）。 | L21・merged 設計 | power_domain / level_shifter / isolation 報告 |
| M3 | Mixed-signal 驗證 | AMS 共模擬與介面訊號完整性。 | merged 設計・cosim TB | cosim 結果・interface SI 報告 |
| M4 | Mixed-signal sign-off | 頂層實體驗證與最終判定（M1–M3 彙整）。 | M1–M3 報告 | `signoff.json` |

---

## 總計

| Phase | Stages | Steps |
|---|---|---|
| Phase 1 — 規格與文件 | 兩條入口（Agent・doc-gen）＋架構探索前端 | D1–D5 + PM Agent・IC Expert Agent |
| Phase 2 — RTL → 合成 | Stage 1・Stage 2 | 1–14 |
| Phase 3 — 實體 → Tapeout | Stage 3・Stage 4・Stage 5 | 15–44 |
| 並行 | Analog・Mixed-signal | A1–A9・M1–M4 |

**44 個循序步驟**（Stage 1：1–6・Stage 2：7–14・Stage 3：15–32・Stage 4：33–39・
Stage 5：40–44），外加 Phase 1（Agent 路徑與 doc-gen 路徑 D1–D5）與兩條並行支線
（Analog A1–A9・Mixed-signal M1–M4）。預檢：P0（環境健檢）。
編排器 `vibe_ic_one_shot_runner.py` 依序執行 Phase 1 → Phase 2 → Analog → Phase 3。

範圍外（婉拒並記錄理由）：OPC/RET 之「設計者執行」（mask 合成屬 foundry 端——已在 Step 35 以 FOUNDRY_SIDE 具名揭露＋Step 40 註記）、商用硬體仿真器（FPGA 路徑涵蓋）、
MBIST/LBIST/EDT 壓縮（開源無引擎）、PFA/EFA、BSR/BSDL、自動 clock-gating
（sky130 無特徵化 ICG cell；手動 RTL clock gating 可行）、via-doubling/CAA（商用 DFM）。

英文正本：`ALL_STEPS_v2.3.0.md`。
