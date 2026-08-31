# Vibe-IC — 全部步驟：Phase → Stage → Step（繁體中文）

整條流程的每一步，以 **Phase → Stage → Step** 階層組織，主軸為**單一連續編號 1 → 44**
（自 Stage 1 的 Spec-to-RTL 起算）。Phase 1 的文件生成步驟以 **D1–D5** 標示（前置，
不計入 1→44）；兩條並行支線 **Analog A1–A9** 與 **Mixed-signal M1–M4** 同時進行。

**Phase → Stage 對照**

- **Phase 1** — 規格與文件：兩條入口（**Agent 路徑**・**doc-gen 路徑 D1–D5**）＋ 選用的架構探索前端
- **Phase 2** — RTL → 合成：Stage 1（RTL+驗證）・Stage 2（約束+合成+DFT+交接閘）
- **Phase 3** — 實體 → Tapeout：Stage 3（實體+簽核）・Stage 4（輸出+Tapeout）・Stage 5（製造與測試）
- **並行** — Analog A1–A9・Mixed-signal M1–M4

**兩條出口路徑。** 編號 1→44 的序列是兩條路徑共用的；另有五個路徑專屬步驟不是，
它們帶 `ip`／`ic` 後綴而非編號，因為不計入循序步驟數。

- **走哪一條** — 由 **0.5ic**（引入送件樣板）決定：拿到投片方的格位樣板就走
  chip/IC 路徑；具名的 `NO_TEMPLATE.txt` 則走 cell/IP 路徑。
- **cell/IP 路徑** — 交付物是別人拿去擺放的區塊，終點在 **37.5ip**（Digital
  Hardmacro Generation：LEF + Liberty + GDS + Verilog），**不會**接到 Step 38，
  也不進入 Stage 5。
- **chip/IC 路徑** — 交付物是可投片的裸晶，額外加入 **15.5ic**（pad ring）、
  **26.5ic**（die finishing：seal ring + 晶粒識別）與 **37.5ic**（shuttle
  precheck），然後才走 Step 38 與 Stage 5。

只跑 Step 1–38 得到的是**裸晶**：沒有 pad ring、沒有 seal ring、沒有晶粒識別。
對 IP 交接而言這是正確的，但那不是一顆可投片的晶片。

---

## Phase 1 — 規格與文件

兩條入口，最終都產出餵給 Phase 2 的同一批 L 系列設計文件：

- `phase1/input_prompt/` —— 自由文字 / 自然語言 → **Agent 路徑**
- `phase1/input_doc/` —— 既有文件 / 結構化 YAML → **doc-gen 路徑**（D1–D5）

### Agent 路徑（輸入是自由文字時）

| Agent | 做什麼 |
|---|---|
| **IC Expert Agent** | Phase-1 的唯一入口：以白話直接面對使用者、把自然語言需求轉成設計事實（缺什麼就白話一次問一題），再以矽智財專業審查每一層、補上合理預設值、做跨層一致性檢查。 |

流程：使用者自由文字 → IC Expert Agent → 定稿 L 系列文件。

### doc-gen 路徑 D1–D5（輸入是既有文件時）

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| D1 | 匯入與文字萃取 → L1–L13 | 把 prompt 或既有文件收進 `input_doc/` 並確定性萃取核心設計層。 | 使用者文件 / prompt | `L1`–`L13` JSON | 確定性萃取器 | `phase1_all_l_docs_present_check`<br>skills：`datasheet-gen`・`frs-gen`・`cmd-protocol-gen`・`regmap-gen`・`adi-spec-gen`・`control-logic-gen`・`test-debug-gen`・`timing-waveform-gen`・`rtl-constants-gen`・`integration-spec-gen`・`test-cases-gen`・`calibration-gen`・`behavioral-sequences-gen`・`lab-calibration-gen`・`otp-content-gen`・`doc-consistency-check`・`schematic-gen`・`phase1` |
| D2 | 產生 L1–L13 核心設計層文件 | 從文件確定性地萃取出核心設計層（datasheet、規格、暫存器圖等）。 | D1 純文字 | `L1_DATASHEET` … `L13` | 確定性萃取器 | — |
| D3 | 產生 L14–L27 文件 | 補上協定、時序、power intent（L21）、skeleton 等延伸層。 | L1–L13 | `L14`–`L27` JSON | overlay 萃取器 | — |
| D4 | 協定類別合成 | 偵測 IC 屬於哪一種協定類別（86 類）並合成對應協定事實。 | 輸入文件全文 | `ic_class` + 協定事實 | is_<proto> + <proto>_synth | — |
| D5 | Coverage 報告 | 核對輸入文件的內容是否完整落入 L 文件。 | 輸入文件 + L 文件 | parity / coverage 報告 | parity 報告器 | — |

### 流片路徑選擇（決定走 chip/IC 還是 cell/IP）

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 0.5ic | Submission template ingest（路徑選擇） | 取得並存放投片方公開的專案樣板 — 格位尺寸、晶粒識別 cell，以及該格位的 pad 清單。這一步決定走哪條路：有格位樣板就走 chip/IC 路徑（15.5ic・26.5ic・37.5ic）；具名的 `NO_TEMPLATE.txt` 則走 cell/IP 路徑（37.5ip）。宣告為外部輸入且不主動探測，因為它是取得的、不是產生的 — 流程因此仍能誠實說出「從未取得」。 | 投片方公開的專案樣板（外部） | `input/submission_template/slots/*.yaml`（或具名的 `NO_TEMPLATE.txt`）・`submission_template.json` | —（讀檔，不需 EDA 工具） | `submission_template_ingest`・`submission_template_check` |

### 架構探索前端（選用，匯入 Step 1）

| 前端 | 做什麼 | 輸入 | 輸出 |
|---|---|---|---|
| architecture-explore | 設計空間探索（pipeline 深度／平行度／記憶體 vs PPA，Pareto 篩選）。 | L 文件 + 效能目標 | 架構決策（餵 Step 1） |
| hls-c2rtl | C/C++/SystemC 經 HLS 轉 RTL（開源 XLS 等）。 | C/SystemC 模型 | RTL（進 Step 2 起照常驗證） |
| SpinalHDL/Chisel 前端 | `eda_spinalhdl_gen` 由 Scala HDL 產 Verilog。 | SpinalHDL 原始碼 | Verilog RTL |

前端優先序（**工件驅動**）：已有 RTL ＞ C/SystemC 模型（hls-c2rtl）＞ SpinalHDL/Chisel ＞ 純 prompt（Step 1 spec-to-RTL）。以現有工件為準，不憑空選路徑。

---

## Phase 2 — RTL → 合成

### Stage 1 — RTL 產生與驗證

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 1 | Spec-to-RTL | 依 L 系列設計文件撰寫可合成的 RTL（SoC/CPU 類可走 IP-catalog 重用＋膠合層路徑，例如 Caravel 類 harness 平台）。 | L1–L27 文件 | `rtl/*.v(.sv)`・coverage 報告 | —（AI 依 L 文件撰寫；SoC 類走 IP-catalog） | skills：`spec-to-rtl` |
| 2 | 🔁 RTL 驗證（改寫保真度＋Lint） | 先證明跨層 PPA 候選 RTL 與 Step 1 基準 RTL 等價，再做靜態風格與錯誤檢查；Step 13 仍負責另一個 RTL 對 netlist 的等價關係。改寫判定無條件執行，沒有搜尋時也會明確寫出 NOT_APPLICABLE，不會把缺席誤讀為成功。 | 基準＋候選 RTL | `rewrite_equivalence_check.json` · lint 報告（hygiene / ROM-init） | Yosys 等價檢查＋Verilator lint | `crosslayer_search_space`・`crosslayer_rewrite_equivalence`・`crosslayer_rewrite_equivalence_check`・`rtl_hygiene_lint`・`rom_init_lint`…<br>skills：`rtl-review` |
| 3 | 🔁 CDC / RDC check | 檢查跨時脈域 / 跨重置域的訊號交握是否安全。 | RTL | CDC/RDC 報告（crossing / async / reset-dep） | 自研 CDC/RDC 掃描 | `cdc_crossing_check`・`cdc_async_input_check`・`reset_dependency_check`<br>skills：`cdc-check`・`rdc-check` |
| 4 | 🔁 Simulation | 產生 per-IC oracle testbench 跑功能模擬（golden 比對）並量測覆蓋率；L21 申告 power domain 時，TB 建議涵蓋 power-state 切換情境（開源無 UPF-aware sim，結構驗證歸 M2）。 | RTL・L10 測項 | sim log・results.xml・coverage 報告 | iverilog/vvp・Verilator coverage<br>`eda_simulate` | `testbench_gen`・`coverage_closure`・`l10_tb_conformance_check`・`l12_tb_coverage_check`…<br>skills：`testbench-gen` |
| 5 | 🔁 Formal verification | 以形式化方法證明關鍵性質恆成立：安全不變量做無界證明、功能性質做有界模型檢查並揭露界深（`all_proved` 需 .sby + SymbiYosys 證據鏈）。 | RTL・L3 約束 | `.sby`・formal results・full-stack TB 結果 | SymbiYosys（ABC pdr / bmc3）<br>`eda_formal` | `formal_property_run`・`assertion_property_check`・`bit_level_full_stack_tb_check`・`formal_proof_evidence_check`<br>skills：`assertion-gen`・`formal-verify` |
| 6 | FPGA early prototype | 合成前期把設計放上 FPGA 驗證真實行為（早期行為原型）。 | RTL・板卡約束 | `.sof`・map 報告・FPGA 驗證 audit | Quartus<br>`eda_synth` | `fpga_test_harness_gen`・`debug_first_pass`・`quartus_map_audit`・`fpga_verification_audit`<br>skills：`fpga-test-harness` |

### Stage 2 — 約束、合成、DFT 與交接閘

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 7 | Constraint setup | 撰寫時序約束（SDC）與 PVT 角點矩陣；power intent 由 L21 建模並輸出 UPF（交接工件——開源工具不消費 UPF，結構驗證歸 M2）。 | L8 時序・L21・PDK liberty | `*.sdc`・`pvt_matrix.json`・`<top>.upf`（選用，L21 有 power domain 時） | —（UPF 由 `l21_to_upf_emit` 腳本產出，非 EDA 引擎） | `sdc_syntax_check`・`pvt_matrix_check`・`l21_to_upf_emit`・`upf_syntax_check`<br>skills：`constraint-gen` |
| 8 | 🔁 SDC validation（含 derived-clock 守門） | 驗證時序約束的正確性、完整性與例外（false_path/multicycle）正當性；手動 ICG／暫存器分頻時脈必須有對應 `create_generated_clock`（無分頻時脈時 vacuous PASS——即條件不適用時自動通過：設計中沒有分頻電路，此檢查自動跳過）。 | SDC・L8・RTL | SDC 檢查報告・`derived_clock_sdc.json` | — | `sdc_syntax_check`・`sdc_validator_check`・`sdc_exception_correlation_check`・`derived_clock_sdc_required_check`<br>skills：`sdc-validator` |
| 9 | Synthesis | RTL 合成並做技術映射（dfflibmap + abc -liberty）為標準元件閘級網表。 | RTL・SDC・liberty | `synth/netlist.v`・面積統計 | Yosys + abc<br>`eda_synth` | `synth_wrapper_gen`・`synth_netlist_check`・`provenance_check`<br>skills：`synth-doctor` |
| 10 | 🔁 Pre-layout STA | 佈局前多角點靜態時序分析（SS/TT/FF）＋合成後功耗預覽（gate-level vectorless、預設 toggle rate，`analysis_mode` 欄揭露；與 Step 33 post-layout 可選 VCD vector 的精度不同）。 | 網表・SDC・liberty | pre-PnR 時序報告 + 摘要・`pre_pnr_power_preview.rpt` | OpenSTA<br>`eda_sta` | `sta_report_check`<br>skills：`sta-review` |
| 11 | DFT insertion | 插入掃描鏈並產生測試圖樣（開源 Fault：scan + stuck-at ATPG + TAP；MBIST/LBIST/壓縮不在開源範圍）。 | 網表 | scan 網表・ATPG 覆蓋率報告 | Fault (scan+ATPG+TAP)<br>`eda_dft` | `fault_atpg_run`・`dft_atpg_coverage_check`<br>skills：`dft-insert`・`atpg` |
| 12 | Post-DFT optimization | 插入 DFT 後重新最佳化時序與面積；輸出的網表必須真的保留 scan chain，不能只是路徑存在（2026-08-08：修補 flow_matrix dimension-2 缺口——舊的 files_exist-only gate 對空檔、把 DFT 前網表冒充貼上、或 scan chain 悄悄消失的網表都會放行；Step 13 的 LEC 抓不到 scan chain 消失，因為 scan insertion 本來就設計成功能上透明）。 | scan 網表 | `post_dft_netlist.v` | Yosys resynth | `dft_post_optimization_scan_survival_check`<br>skills：`synth-doctor` |
| FS1 | ISO-26262 FMEDA 診斷覆蓋率（僅安全設計） | 對已宣告的安全機制（ECC/parity）做故障注入：在受保護路徑注入 stuck-at 故障，量測診斷覆蓋率對 ASIL 門檻。非安全設計不適用。 | RTL・已宣告安全機制・ASIL | fmeda_coverage 報告（量測 DC） | iverilog 故障注入 | `fmeda_fault_injection_coverage`・`fmeda_coverage_check` |
| DT1 | 轉態延遲故障（at-speed LOC）ATPG | 在 scan-cut 網表的 2-time-frame launch-on-capture 展開上，為轉態故障產生 launch-capture 雙圖樣，並評定轉態測試覆蓋率。組合／無掃描設計不適用。 | scan-cut 網表・時脈 | 轉態覆蓋率報告 | Yosys SAT（`sat -prove`） | `transition_fault_atpg_run`・`transition_coverage_check` |
| DT2 | 路徑延遲故障（at-speed 時序評級）ATPG | 以真實佈局後時序從繞線後網表列出最長的 K 條 launch-on-capture 路徑，逐路徑產生並評級 launch-capture 雙圖樣（robust 與 non-robust）；證明無圖樣可產的路徑排除不計。繞線後網表與寄生尚未存在時不適用。 | 繞線後網表・SPEF・SDC・scan cut | 路徑延遲覆蓋率報告 | OpenSTA + Yosys SAT（`sat -prove`） | `path_delay_fault_atpg_run`・`path_delay_coverage_check` |
| DT3 | 小延遲缺陷（SDD）at-speed 分級 | 以每條時序關鍵路徑的真實佈局後 slack 為缺陷分級：只有偵測路徑餘裕很緊時，small delay 才會在 at-speed 被抓到——經低 slack 路徑偵測為強抓、經寬鬆路徑為弱抓。餘裕充裕的設計誠實得低分（其餘裕遮掉小延遲）。描述性分級、無 floor。路徑延遲與轉態覆蓋率尚未存在時不適用。 | 路徑延遲覆蓋率・轉態覆蓋率・SDC | SDD 覆蓋率報告 | OpenSTA + Yosys SAT（`sat -prove`） | `sdd_atpg_run`・`sdd_coverage_check` |
| 13 | 🔁 Equivalence check | 形式化證明閘級網表與 RTL 功能等價（LEC）。 | RTL・post-DFT 網表 | LEC 報告 | Yosys equiv | `lec_equivalence_check`<br>skills：`equivalence-check` |
| 14 | 🔁 Synthesis handoff gate | 合成→PnR 交接 QA：合成腳本與網表審核（**開源 Yosys 專用**；合成階段收尾閘）。 | synth 腳本・網表 | handoff 審核報告 | Yosys 腳本/網表審核 | `yosys_hilomap_required_check`・`yosys_script_template_check` |

---

## Phase 3 — 實體設計 → Tapeout

### Stage 3 — 實體設計與簽核

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 15 | Floorplan + PDN | 規劃晶片平面配置與電源網路；插入 tapcell（latch-up well-tie，SKY130 14µm 規則）。 | 網表・hardmacro LEF（`pdk_local/` 自動納入，經 IP 整合檢查：LEF/GDS/Liberty 對齊＋corner 覆蓋＋L21 電源域一致；macro LEF 建議含 obstruction 層） | `floorplan.def`・PDN | OpenROAD (init_floorplan+pdngen+tapcell)<br>`eda_pnr` | `phase3_backend_step`・`floorplan_pdn_check`・`ip_integration_check` |
| 15.5ic | Pad ring（僅 chip/IC 路徑） | 在核心外圍擺放 I/O pad ring，讓晶粒可以打線出腳。cell/IP 路徑不執行。 | `floorplan.def` | `padring.def`・`padring.json` | OpenROAD／PDK I/O 元件庫 | `pad_ring_gen`・`pad_ring_check` |
| 16 | Clock planning | 規劃時脈樹的分佈策略。 | floorplan | `clock_plan.json` | OpenROAD CTS 規劃 | `clock_plan_check`<br>skills：`cts-plan` |
| 17 | Placement | 擺放標準元件（全域 + 細部）。 | floorplan・網表 | `placed.def` | OpenROAD (global+detailed place)<br>`eda_pnr` | `placement_legality_check`<br>skills：`placement-optimize` |
| 18 | Spare-cell + ECO-prep insertion | 預置備用元件與 ECO 預備，讓未來真正的實體變更可只改金屬層。Step 32 是獨立流程，不會取用這個 spare pool。 | placed.def | `spare_cells.json`・覆蓋率報告 | OpenROAD<br>`eda_pnr` | `spare_cell_coverage_check`（preservation 改在 Step 34 審核：備用元件必須存活的優化步驟都跑完之後） |
| 19 | CTS | 建構時脈樹、平衡時脈偏移。 | placed.def・clock plan | `post_cts.def`・時脈樹報告 | OpenROAD CTS<br>`eda_pnr` | `cts_quality_check` |
| 20 | 🔁 Post-CTS hold fixing | 修復時脈樹建好後出現的 hold 違規（繞線後 runner 會再跑一次 hold 修復）。 | post_cts.def | `post_hold.def` | OpenROAD repair_timing -hold | `hold_closure_check`<br>skills：`hold-fix` |
| 21 | Routing | 完成所有訊號繞線（全域 + 細部）。 | post_hold.def | `routed.def`・router DRC 報告 | OpenROAD TritonRoute<br>`eda_pnr` | `drc_report_check`・`def_stage_progression_check`・`provenance_check` |
| 22 | Parasitic extraction | 萃取繞線後的寄生 RC（SPEF）；當 PDK 未附 coupling captable 時，依繞線幾何以解析式補上側向耦合電容，介電係數為已揭露的通用假設。 | routed.def・tech LEF | SPEF（含耦合電容） | OpenRCX<br>`eda_extraction` | `spef_extraction_check`・`provenance_check` |
| 23 | 🔁 Post-route STA | 真實寄生參數簽核級時序分析（MMMC＝per-corner 迴圈，每角獨立報告）。 | 網表・SPEF・SDC・多角 liberty | post-route 時序報告・`per_corner/` | OpenSTA（per-corner 迴圈）<br>`eda_sta` | `sta_report_check`<br>skills：`sta-review` |
| 24 | 🔁 IR drop（靜態 + 動態） | 電源網路壓降分析：靜態，外加 VCD 向量化動態 IR（依真實切換 VCD 加權的壓降）。 | routed.def（PSM）・VCD | 靜態 + 動態 IR 報告 | OpenROAD PSM（`read_vcd`） | `ir_drop_report_check`・`dynamic_ir_drop_check`<br>skills：`ir-drop-triage` |
| 25 | 🔁 EM check | 檢查電流密度、確保金屬線壽命。 | routed.def（PSM -enable_em） | EM 報告 + 分段電流 | OpenROAD PSM -enable_em | `em_report_check`<br>skills：`em-check` |
| 26 | 🔁 Antenna check | 檢查並修復製程天線效應。 | routed.def | antenna 報告 | OpenROAD check_antennas/repair | `antenna_report_check` |
| 26.5ic | Die finishing — seal ring + 晶粒識別（僅 chip/IC 路徑） | 加上 PDK 自帶的 seal ring 與 shuttle 的晶粒識別 cell。位置在天線檢查**之後**、實體驗證**之前**，因此 Step 31 簽核的那顆晶粒就是出貨的那顆。cell/IP 路徑不執行。 | `routed.def` | `die_finished.def`（或具名的 `die_finishing.SKIPPED.txt`）・`die_finishing.json` | PDK 自帶 seal-ring 產生器（KLayout／Magic），只呼叫、不重寫 | `die_finishing_gen`・`die_finishing_check` |
| 27 | 🔁 Signal integrity | 串擾 / 雜訊影響分析（SPEF 耦合電容篩查，advisory tier 明示）。 | SPEF | SI 報告（含 >0.9 耦合 watch-list） | 自研 SPEF 耦合篩查（OpenSTA 視窗 advisory） | `si_crosstalk_check` |
| 28 | 🔁 PERC / Reliability sign-off | ESD 焊環＋放電拓樸、latch-up well-tap、跨電壓域保護的強制簽核；對應 PERC 四類——netlist 檢查＋netlist 驅動的 layout 檢查（自動化）、電流密度＋P2P 電阻（具名 manual-review）。manual-review 由資深實體設計／可靠度工程師簽核，準則記入 `perc_equivalent.json`（categories[].status=MANUAL_REVIEW＋`review_criteria`：PDK Jmax 表、ESD 放電路徑 P2P 上限、Vhold>Vdd、L21 跨域契約等具名限值），結果回填 checklist[].confirmed。 | 閘級網表・routed.def・L21 power intent・L3 ESD 規格・24–27 報告 | `perc_equivalent.json`・PERC memo・gate 判定 | 自研 PERC-equivalent（DEF 驅動） | `perc_signoff_check` |
| 29 | Post-layout gate-level sim | 帶 SDF 延遲的閘級模擬，確認佈局後功能正確（無 SDF 重模擬即誠實 SKIP）。 | 閘級網表・SDF・TB | post-sim 結果 | iverilog + SDF<br>`eda_simulate` | `post_layout_sim_check` |
| 30 | Post-layout SPICE verification | 電晶體級 ngspice 對 Liberty 時序的比對：單一代表性 cell 加上前 N 條 STA 關鍵路徑（每個相異終點取最差一條；抽出的 subckt 逐級串接、帶真實 net cap；逐路徑 SPICE vs STA 延遲並彙總）。 | SPICE deck・SPEF・STA paths | cell + top-N path SPICE 比對報告 | ngspice + OpenSTA<br>`eda_spice` | `spice_correlation_check`<br>skills：`ams-sim` |
| 31 | 🔁 Physical verification | DRC / LVS / ERC / 密度實體規則簽核；密度在此屬**規則符合性**（KLayout deck 逐層 CMP 窗；執行驗證歸 Step 34、優化建議歸 Step 35）；LVS 走 Magic 抽取 + netgen 真比對（含 macro 的設計——如 Caravel 類 harness——可對 macro blackbox：Magic 以 `lef write -hide` 將 macro 遮為介面殼、netgen 補充 setup 以同名 blackbox 比對；waiver 依據＝device-level match＋KLayout 交叉驗證，由 `signoff_waiver_emit` 寫入專案 `waivers.json`，Step 36 checklist 以 open_waivers 交叉引用為 reviewer to-do）。 | GDS・閘級網表・PDK deck | 簽核 DRC・LVS・ERC 報告 | KLayout DRC・Magic ext2spice + netgen LVS・OpenROAD ERC<br>`eda_drc_klayout`・`eda_lvs` | `erc_density_check`<br>skills：`drc-fix`・`lvs-triage`・`perc-check` |
| 32 | 🔁 繞線後時序修復 pass | 多角落 `repair_design` + `repair_timing -setup`，接著對已繞線的 DEF 跑**完整的** `global_route` + `detailed_route`。**這不是 ECO**：它重繞整顆設計而非保留既有實作，而且我們沒有已發行的版本可供變更。**它並沒有取用 Step 18 的 spare cells** —— 產生器裡沒有 spare-cell 參照，也沒有 `dont_touch`/`preserve`。 | 簽核報告 | `repair_log.json` 或 `no_repair_needed.flag` | OpenROAD 繞線後修復 | `postroute_timing_repair_audit`<br>skills：`sta-review` |

### Stage 4 — 輸出與 Tapeout

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 33 | Power analysis | 全晶片功耗簽核（post-layout vectorless OpenSTA report_power；VCD 向量模式可選）。 | 網表・SDC・liberty（＋選用 VCD） | power 報告（leakage+dynamic, analysis_mode） | OpenSTA report_power（＋選用 VCD） | `power_report_check`<br>skills：`power-analysis` |
| 34 | Metal fill | 標準元件列 filler placement（white-space 填充）；密度在此屬**執行驗證**（`metal_fill_density_check` 閘擁有密度判定；規則符合性歸 Step 31、優化建議歸 Step 35）。 | routed.def | `filled.def`・密度報告 | OpenROAD filler_placement<br>`eda_pnr` | `metal_fill_density_check`・`spare_cell_preservation_check` |
| 35 | DFM screen | 可製造性篩查：redundant-via 比率（single-cut 比例 advisory）＋密度**優化建議**（僅交叉引用 Step 34 閘結果，永不重複 FAIL）；OPC/RET/SRAF/PSM 以 FOUNDRY_SIDE 具名揭露（≤28nm 升級為 DESIGNER_COLLAB_REVIEW 設計者協作項；節點由 `dfm_screen_check` 自 `input/pdk/liberty` 檔名推導，記入同一 `dfm_screen.json` 的 process_nm／advanced_node／foundry_side 欄）。 | routed.def・密度報告 | `dfm_screen.json`（via 統計＋foundry-side 清單） | 自研 DEF via 統計＋密度交叉引用 | `dfm_screen_check` |
| 36 | Tapeout checklist | 最終簽核清單逐項確認（實質判定：DRC 計數、證據鏈）。 | 全部簽核報告 | `tapeout_checklist.json` | —（清單彙整） | `tapeout_signoff_check`<br>skills：`tapeout-checklist` |
| 37 | GDSII output | 產出交付晶圓廠的 GDSII（僅當 Step 31 PV 全淨）。 | routed.def・merged GDS | 簽核級 `*.gds` | Magic/KLayout stream-out<br>`eda_gds` | `gds_size_check`・`provenance_check` |
| 37.5ip | Digital hardmacro generation（cell/IP 路徑終點） | 把簽核完成的區塊打包成可重用 hardmacro。**cell/IP 路徑在此結束** — 沒有 Step 38、沒有 Stage 5。 | 簽核級 `*.gds` | `hardmacro/*.lef`・`*.lib`・`*.gds`・`*.v`・`documentation/ip/*/IP_DATASHEET.md`・`IP_INTEGRATION_GUIDE.md`・`RELEASE_NOTES.md`・`ERRATA.md`・`DELIVERABLES_MANIFEST.md`・`documentation_manifest.yaml` | abstract + Liberty + stream-out | `digital_hardmacro_gen`・`digital_hardmacro_check`・`ip_release_docs_gen`・`release_docs_check` |
| 37.5ic | Tape-out precheck — 我們自己的 general ladder，加上該 PDK 若有 shuttle precheck 時投片方自己的拒絕（僅 chip/IC 路徑） | 同一份 GDS，兩隻手臂。凡走到這一步的設計都跑我們的 general ladder；當該 PDK 有 shuttle precheck 且該投片方的樣板確實已取得時，再額外跑投片方自己的容器——那是外部權威，不是我們自訂的標準。PDK 沒有 shuttle precheck 不是另一條路徑，只是同一步少一隻手臂；登錄檔說有、但樣板從未取得，判為 `NOT_DETERMINED`，絕不靜默略過。兩隻手臂意見相左時，這一步拒絕並同時記下兩邊的裁決，而不是偏袒其中一邊。 | 簽核級 `*.gds`・`tapeout_declaration.json` | `tapeout_precheck.json`・`general_precheck.json`・`shuttle_precheck.json`・`SIGNOFF_*.html`・`BRIEF_*.html` | 投片方的 precheck 容器（僅第二隻手臂） | `tapeout_precheck` → `general_precheck` + `tapeout_readiness_check` |
| 38 | Foundry handoff | foundry 實體 mask kit：mask spec＋WAT 計畫＋scribe PCM＋corner ATE 向量（chip-specific；foundry 待供欄位以 `PENDING_FOUNDRY_*` 具名——由 Step 36 checklist 追蹤、foundry 回覆後回填）。 | GDS・netlist 統計・L10 測項 | `mask_spec.json`・`wat_plan.json`・scribe・`corner_test_vectors.json` | —（pack 產生器） | `foundry_handoff_package_check`<br>skills：`tapeout-checklist` |
| 39 | FPGA final sign-off | 最終 FPGA 重編譯與板上驗證（板上 attestation，含硬體證據）。 | RTL・板卡 | final `.sof`・`on_board_pass.json` | Quartus + 板上量測 | `bringup_plan_gen`・`fpga_on_board_attestation_check`<br>skills：`fpga-test-harness` |

### Stage 5 — 製造與測試（post-fab；僅在收到矽晶時觸發）

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 40 | Fabrication | 晶圓廠光罩與晶圓製造（外部；OPC/RET 屬 foundry 端 mask 合成）。 | foundry handoff kit | mask/wafer 收貨 attestation | 外部晶圓廠 | `manufacturing_fab_intake_check` |
| 41 | Wafer sort / probe test | 晶圓針測、挑出良品裸晶；獨立重算良率並比對目標。 | wafer lot・probe 卡 | `wafer_sort_yield.json`・`wafer_map.csv` | ATE + probe card（外部） | `wafer_sort_yield_check` |
| 42 | Packaging | 封裝（wirebond / FC-CSP / WLCSP）。 | 良品裸晶 | `packaging_log.json` | 封裝廠（外部） | `packaging_intake_check` |
| 43 | Final test | 封裝後最終測試（functional + parametric + burn-in 嬰兒期篩選）。 | 封裝品・ATE 圖樣 | `final_test_yield.json`・`burn_in_results.json` | ATE（外部） | `final_test_attestation_check` |
| 44 | Reliability qualification | HTOL 長時壽命 qual（device-hours／failures／FIT attestation；車規/醫療等級必跑；消費級 MPW 可休眠＝DEFERRED，不阻塞 tapeout）。 | HTOL 爐結果 | `htol_results.json` 判定 | HTOL 爐（外部） | `htol_attestation_check` |

> 流程外實驗室步驟（不列編號）：PFA/EFA（FIB/SEM/EMMI 破壞性失效分析）、silicon characterization（shmoo）——資料來自外部設備，plugin 提供 `wafer_map_pattern_classify` 等根因分析層。

---

## 並行支線

### Analog A1–A9（與 Stage 1–3 並行）

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| A1 | Analog spec extraction | 從 L 文件抽出每個 analog 區塊的規格。 | L5 ADI 規格 | `spec.json` | 確定性 spec 萃取 | `analog_a1_spec_extract_check`<br>skills：`analog-spec-extract` |
| A2 | Topology selection | 依規格選擇電路拓樸。 | spec.json | `topology.md` | AI 拓樸選擇 | `analog_a2_topology_select_check`<br>skills：`analog-topology-select` |
| A3 | Netlist generation | 產生 SPICE netlist。 | topology・PDK models | `<block>.sp` | xschem netlist<br>`eda_xschem_netlist` | `analog_netlist_pdk_check`<br>skills：`analog-netlist-gen` |
| A4 | Corner sweep | PVT 角點掃描 + 蒙地卡羅良率（`mc_yield_pct` ≥95% 閘）。 | `.sp`・PDK corner libs | `corner_results.json`（executed/derived 計數） | ngspice（corner + MC）<br>`eda_spice_corner` | `analog_a4_corner_sweep_check`<br>skills：`analog-sizing-loop` |
| A5 | Analog layout | 完成 analog 佈局。 | netlist | `layout.mag` / GDS | Magic layout<br>`eda_analog_layout` | `analog_a5_layout_check`<br>skills：`analog-layout` |
| A6 | Block physical verification | 逐區塊 DRC + LVS（合併前；頂層 PV 會遮蔽的區塊級錯誤在此抓）。 | block GDS・netlist | DRC clean / LVS match flags | Magic DRC + netgen LVS | `analog_a6_block_pv_check`<br>skills：`drc-fix`・`lvs-triage` |
| A7 | 🔁 Post-layout resimulation | 萃取寄生後再模擬、比對佈局前後規格（>10% 劣化回 A3）。 | layout 寄生・spec | `pre_vs_post.json` | Magic 抽取 + ngspice<br>`eda_spice_corner` | `analog_pre_vs_post_layout_check`<br>skills：`analog-extraction-resim` |
| A8 | Hardmacro generation | 打包成 LEF + Liberty + GDS + Verilog 餵回 Stage 3（LEF 建議帶 obstruction 層——Magic `lef write -hide` 或 abstract 含 obs——避免頂層繞線闖入 macro 內部）。 | layout・特徵化結果 | 四件套 hardmacro | Magic/abstract + 特徵化 | `analog_hardmacro_check`<br>skills：`analog-hardmacro-gen` |
| A9 | 🔁 Co-simulation / HW verification | 數位+類比混合模擬與硬體迴圈驗證。 | hardmacro・數位 RTL | cosim / HW 量測結果 | iverilog + ngspice 共模擬<br>`eda_spice`・`eda_simulate` | `mixed_signal_cosim_check`・`analog_hw_spice_correlation_check`<br>skills：`mixed-signal-cosim`・`analog-hw-tuning-loop` |

### Mixed-signal M1–M4（存在 analog 區塊時觸發）

觸發時機：**A8 hardmacro 完成**且 **Stage 3 接近收尾**（routed/GDS 可合併）時執行——hardmacro 需先於 floorplan 產出，但 M1 的 GDS 合併要等數位側佈線完成。若 hardmacro 延遲至 Stage 3 已進入 Step 31，M1 改等 hardmacro 最終 GDS，並重跑 Step 31 頂層 LVS（增量驗證——僅 macro 介面變更範圍）。

| # | 步驟 | 做什麼 | 輸入 | 輸出 | 工具 (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| M1 | 頂層整合 | 數位 + 類比 GDS 合併與 macro 擺放；merged GDS 跑頂層 LVS（Magic 抽取 + netgen，macro blackbox）。 | 數位 GDS・hardmacro GDS | `top_merged.gds`・merge/LVS 報告 | KLayout merge + Magic/netgen top-LVS | `mixed_signal_top_lvs_run`（產出者）・`mixed_signal_merge_check`（gate）<br>skills：`analog-flow-orchestrate`・`flow-orchestrate` |
| M2 | 電源域驗證 | 跨電源域 level-shifter / isolation 結構驗證，外加跨電源域訊號穿越檢查：由電源域定義推導 isolation/level-shifter 需求並稽核 UPF 策略。 | L21・merged 設計 | power_domain / level_shifter / isolation / signal-crossing 報告 | 結構驗證程式群 | `power_domain_crossing_check`・`level_shifter_required_check`・`isolation_cell_required_check`・`power_domain_signal_crossing_check`<br>skills：`ir-drop-triage` |
| M3 | Mixed-signal 驗證 | AMS 共模擬與介面訊號完整性。 | merged 設計・cosim TB | cosim 結果・interface SI 報告 | AMS 共模擬 | `mixed_signal_cosim_check`・`mixed_signal_interface_si_check`<br>skills：`mixed-signal-cosim`・`ams-sim` |
| M4 | Mixed-signal sign-off | 頂層實體驗證與最終判定（M1–M3 彙整）。 | M1–M3 報告 | `signoff.json` | 彙整判定 | `mixed_signal_signoff_check`<br>skills：`tapeout-checklist` |

---

## 總計

| Phase | Stages | Steps |
|---|---|---|
| Phase 1 — 規格與文件 | 兩條入口（Agent・doc-gen）＋架構探索前端 | D1–D5 + IC Expert Agent |
| Phase 2 — RTL → 合成 | Stage 1・Stage 2 | 1–14 |
| Phase 3 — 實體 → Tapeout | Stage 3・Stage 4・Stage 5 | 15–44 |
| 並行 | Analog・Mixed-signal | A1–A9・M1–M4 |

**44 個循序步驟**（Stage 1：1–6・Stage 2：7–14・Stage 3：15–32・Stage 4：33–39・
Stage 5：40–44），外加 Phase 1（Agent 路徑與 doc-gen 路徑 D1–D5）與兩條並行支線
（Analog A1–A9・Mixed-signal M1–M4）。不計入 1→44 的路徑專屬步驟：0.5ic（路徑選擇）・15.5ic・26.5ic・37.5ic（僅 chip/IC 路徑）與 37.5ip（cell/IP 路徑終點）；一個設計只走其中一條，不會兩條都走。
預檢：P0（環境健檢）。條件式字母步驟：FS1（ISO-26262 FMEDA 診斷覆蓋率，僅安全設計）·
DT1（轉態延遲故障 ATPG，僅掃描設計）· DT2（路徑延遲故障 at-speed ATPG，掃描設計且繞線完成後）· DT3（小延遲缺陷 at-speed 分級，接 DT2 後）。
編排器 `vibe_ic_one_shot_runner.py` 依序執行 Phase 1 → Phase 2 → Analog → Phase 3。

範圍外（婉拒並記錄理由）：OPC/RET 之「設計者執行」（mask 合成屬 foundry 端——已在 Step 35 以 FOUNDRY_SIDE 具名揭露＋Step 40 註記）、商用硬體仿真器（FPGA 路徑涵蓋）、
MBIST/LBIST/EDT 壓縮（開源無引擎）、BSR/BSDL、自動 clock-gating
（sky130 無特徵化 ICG cell；手動 RTL clock gating 可行——分頻/gated clock 的 SDC 宣告由 Step 8 的 `derived_clock_sdc_required_check` 守門）、via-doubling/CAA（商用 DFM）。

**E1–E3 外部實驗室步驟（保留編號，未列入 44 步；升級車規/醫療等級時啟用）**：

| # | 步驟 | 說明 |
|---|---|---|
| E1 | PFA / EFA | FIB／SEM／EMMI 失效分析（外部實驗室） |
| E2 | Silicon characterization | shmoo plot・電壓/頻率掃描特性化 |
| E3 | 溫度循環／機械應力測試 | JESD22 類環境應力（外部實驗室） |

## 附錄：實測工時參考（量感用）

數字取自實際 sky130 開源流程本機跑批的 orchestrator 報告（`reports/orchestrator/*_one_shot.json` 的 `duration_s` 欄；設計規模 0.5k–21k cells），**非估算**。時間隨設計、約束與機器變動，僅供建立量感；與 cell 數非線性。

| 階段 | 實測範圍 | 樣本 |
|---|---|---|
| Step 9 Synthesis（Yosys） | ~0.4 s – 21 s | 0.5k cells（lpc）→ 20k cells（cv32e40p） |
| Step 15–22 PnR（OpenROAD 全程） | ~3 s – 31 min | 3.4k cells（subservient）→ 21k cells（sha256） |
| Step 37 GDS 寫出 | ~2 – 4 s | 全部樣本 |
| Step 31 DRC（KLayout sky130 deck） | ~8 – 84 s | 0.5k → 20k cells |
| Step 31 LVS（Magic＋netgen） | 本批樣本走輕量/跳過路徑，故無代表性數字；含 macro 真比對（如 Caravel 類 harness）為**分鐘級到小時級**，依 macro 數量而異（現場曾因此將 timeout 設為 4 小時） | — |
| Step 40–43 製造端（fab/sort/pkg/final test） | 外部週期，數週級 | 無本地實測 |

授權與 IP：全流程僅依賴開源工具（Apache-2.0 專案；商用工具防火牆與產出物歸屬見 repo 根目錄 `README.md` §IP ownership 與 `CONTRIBUTING.md` 的 DCO/專利承諾）。

英文正本：`ALL_STEPS_v1.4.14.md`。
