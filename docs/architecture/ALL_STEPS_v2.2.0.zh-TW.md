# Vibe-IC — 全部 Phase / Stage / Step（v2.2.0，窮舉版・繁體中文）

**Plugin 0.2.6.** 每一個 phase、stage、step 的完整列舉。有**兩套並存視角**：**(A)** runner ground-truth
標記（`[N/15]` / `def step_*`，程式實際印出的）；**(B)** 33-step Stage 模型（簽核視角）。兩套皆完整列於下；
敘事版見 `CANONICAL_FLOW_v2.2.0.md`。**真實來源 = runner。英文正本：`ALL_STEPS_v2.2.0.md`（歧義以英文為準）。**

---

## 0. 入口 + 編排器 + 預檢

| ID | 項目 | 位置 |
|---|---|---|
| P0 | 預檢（環境 / PDK / 工具可用性） | `mcp_server_health_check`、`eda_doctor` |
| — | Path A：NL prompt / 對話 → Phase 1 | `phase1_doc_one_shot_runner.py` |
| — | Path B：既有文件 → Phase 1（docs 模式） | 同上 |
| — | 編排器：Phase 1 → Phase 2(=2a+2b) → Analog（P2 後）→ Phase 3 | `vibe_ic_one_shot_runner.py` |

---

## A. RUNNER-MARKER 視角（ground truth）

**整條循序流程 Phase 1 → 2 → 3 用「一套連續全域步號」**（Phase 3 **不**重數、是全域 50-55）。Analog A1-A8 /
Mixed M1-M4 與 Phase 2 **並行**，保留原生 A*/M* id。由 `FLOW_STEPS_GENERATED.md` 自動產生（`flow_doc_emit.py`
重生）。§B 是另一套正交的 33-step 矽流程模型（自有 1→33）。

### A.1 Phase 1 — 全域步 1-34（15 主標記 + 19 子步，`phase1_doc_one_shot_runner.py`）

| # | 標記 | 步驟 |
|---|---|---|
| 1 | `[1/15]` | 文字萃取（input/docs → input_doc；2 MB 掃描上限，v0.1.91） |
| 2 | `[2/15]` | L1_DATASHEET |
| 3 | `[3/15]` | L2_FRS |
| 4 | `[4/15]` | L3_CMD_PROTOCOL |
| 5 | `[5/15]` | L4_REGMAP |
| 6 | `[6/15]` | L5_ADI_SPEC |
| 7 | `[7/15]` | L6_CONTROL_LOGIC |
| 8 | `[8/15]` | L7_TEST_DEBUG |
| 9 | `[9/15]` | L8_RTL_CONSTANTS |
| 10 | `[10/15]` | L9_INTEGRATION_SPEC |
| 11 | `[11/15]` | L10_TEST_CASES |
| 12 | `[12/15]` | L11_OTP_CONTENT |
| 13 | `[13/15]` | L12_BEHAVIORAL_SEQUENCES |
| 14 | `[14/15]` | L13_LAB_CALIBRATION |
| 15 | `[14b/15]` | L8_TIMING_WAVEFORM |
| 16 | `[14b2/15]` | L8 協定寬度萃取（R19） |
| 17 | `[14b3/15]` | L8 編碼表 overlay（R41） |
| 18 | `[14b4/15]` | L6 FSM / 控制邏輯 overlay（R42） |
| 19 | `[14b5/15]` | L12 行為序列 overlay（R43） |
| 20 | `[14b6/15]` | L17/L18/L8_TIMING/L9 批次 synth（R46）— 已棄用 → 14c3 |
| 21 | `[14b7/15]` | L8_RTL_CONSTANTS 通用協定常數（R48） |
| 22 | `[14c/15]` | L14-L18 協定規格萃取 |
| 23 | `[14c0/15]` | L9 integration_spec overlay（R40） |
| 24 | `[14c1/15]` | L1 協定 metadata overlay（R23） |
| 25 | `[14c1b/15]` | L17 handshake_pairs overlay（R27） |
| 26 | `[14c2/15]` | L3 從 L14-L18 鏡射協定（R21） |
| 27 | `[14c3/15]` | L17/L18/L8_TIMING/L9 批次 synth（R46 搬移） |
| 28 | `[14c4/15]` | L1/L2/L6/L7/L12 通用協定 doc facts（R50） |
| 29 | `[14c5/15]` | L4/L5/L10/L14/L15 殘餘清理（R52） |
| 30 | `[14d/15]` | L19-L23 skeleton 產出 |
| 31 | `[14e/15]` | serial_peripheral_protocol 類別 synth（R53/R54/R55）— **81-protocol detector→synth dispatch** |
| 32 | `[14e2/15]` | bus_interconnect_protocol Tier-2 synth（TileLink/Wishbone/Avalon/OCP/AXI-Stream） |
| 33 | `[14e3/15]` | 通用 packet/PDU L10↔L3 opcode 一致性掃描 |
| 34 | `[15/15]` | Coverage / parity 報告 |

→ **Phase 1 = 全域步 1-34**（15 主標記 + 19 子/overlay/dispatch）。Phase 2 接續 35。

### A.2 Phase 2 — step 函式（`phase2_one_shot_runner.py`）— **全域步 35-49**

> 連續全域編號（不從 1 重數；接續 Phase 1 的 34 個標記）。自動產生於 `FLOW_STEPS_GENERATED.md`。

| # | Step | 說明 |
|---|---|---|
| 35 | `step_phase1` | 必要時重跑/匯入 Phase 1 |
| 36 | `step_rig_topology_skeleton` | 拓樸 scaffold |
| 37 | `step_rtl_gen` | 對 `rtl_gen=null` 的 ic_class WAIVE → `spec-to-rtl` 角色；`phase2_scaffold_gen.py` 產出 top/regs/fsm/tb/soc_wrap/cocotb |
| 38 | `step_full_stack_tb_gen` | 自檢 TB |
| 39 | `step_reference_tb` | reference-TB 一致性（eco_loop ≤3 retries） |
| 40 | `step_yosys_synth` | gate-level 合成 |
| 41 | `step_qsf_gen` | FPGA 專案 |
| 42 | `step_sdc_gen` | 約束 |
| 43 | `step_otp_image_check` | OTP image（若有） |
| 44 | `step_fpga_compile` | FPGA build → `.sof` |
| 45 | `step_fpga_burn` | 燒錄板子 |
| 46 | `step_usb_hid_tester_verify` | host 端協定測試器驗收 |
| 47 | `step_emit_phase2_manifests` | manifests |
| 48 | `step_final_audit` | 彙整審查 |
| 49 | `step_phase3` | 端到端執行時串接進 Phase 3 |

環繞 gate：`rtl_hygiene_lint --fix`、`spec_conformance_check`、`chip_top_gate_wrapper_gen`、
MCP `eda_lint`/`eda_synth`/`eda_cocotb`。

### A.3 Phase 3 — step 函式（`phase3_one_shot_runner.py`）— **全域步 50-55（不是 1-6）**

> Phase 3 是後端；其 step 函式接續全域計數 — **不**從 1 重數。

| # | Step | 工具（開源） |
|---|---|---|
| 50 | `step_synth` | yosys（+ tie-cell pass：`setundef -zero; hilomap; splitnets; clean`） |
| 51 | `step_pnr` | OpenROAD（floorplan→PDN→place→CTS→route） |
| 52 | `step_gds` | KLayout（`def2gds`） |
| 53 | `step_drc` | KLayout sky130 deck |
| 54 | `step_lvs` | netgen / yosys_equiv — LVS 簽核鏈（§C） |
| 55 | `step_canonicalize_artefacts` | 正規化輸出（+ §D 的簽核 emitter） |

### A.4 Analog A1–A8（`analog_one_shot_runner.py`，與 Phase 2 並行）

| Step | 名稱 | 輸出 |
|---|---|---|
| A1 | spec_extract | `analog/<block>/A1_spec.json` |
| A2 | topology_select | `A2_topology.json` |
| A3 | netlist_gen | `<block>.sp` |
| A4 | corner_sweep | `A4_corners.json` |
| A5 | layout（Magic） | `A5_layout.json`（需 DRC-clean + LVS-match flag） |
| A6 | post_layout_resim | `A6_postsim.json` |
| A7 | hardmacro_gen | `{.lef,.lib,.gds,.v}` → 餵回 Phase 3 |
| A8 | hw_verify（HIL） | `A8_hw_verify.json` |

### A.5 Mixed-signal M1–M4（skill 層級，無專屬 runner）

| Step | 名稱 | 位置 |
|---|---|---|
| M1 | top merge | `mixed_signal_m1_top_merge_check.py` + skill `mixed-signal-cosim` |
| M2 | co-sim setup | skill `mixed-signal-cosim` |
| M3 | co-sim run | skill `mixed-signal-cosim` |
| M4 | integration verify | skill `mixed-signal-cosim` |

---

## B. 33-STEP STAGE 模型 — 全部 33 步、連續（簽核視角，`33_step_flow_overview.md`）

**每一步 1→33、零跳號。** Stage 為一欄（S1 RTL+驗證 / S2 synth+DFT / S3 實體+簽核 / S4 輸出+驗證）。
（§A 是 runner-marker 視角；下方 §D 是*子集* — 只列有開源缺口的簽核檢查。）

| # | Stage | Step | 工具/Skill | Gate |
|---|---|---|---|---|
| 1 | S1 | Spec-to-RTL | `spec-to-rtl` | L1-L9 齊 + RTL 產出 |
| 2 | S1 | Lint | `eda_lint` + Phase-2a gates + polluter check | Verilator 0 errors |
| 3 | S1 | CDC / RDC check | `cdc-check` | 跨時脈域路徑已同步 |
| 4 | S1 | Simulation | `testbench-gen` + `eda_simulate` + coverage | 全 tb PASS + 覆蓋率 |
| 5 | S1 | Formal verification | `formal-verify` + `assertion-gen` | k-induction 證明（無 model 則 informational waiver） |
| 6 | S1 | FPGA early prototype | `fpga-test-harness` + `eda_fpga_compile/program` + on-board BIST | `.sof` + BIST PASS |
| 7 | S2 | Constraint setup | `constraint-gen` | `*.sdc` + 3-corner `pvt_matrix.json` |
| 8 | S2 | SDC validation | SDC lint | clock/IO 約束齊全 |
| 9 | S2 | Synthesis（Yosys） | `eda_synth` + `synth-doctor`（+ tie-cell pass） | mapped netlist + cell count |
| 10 | S2 | Pre-layout STA | `eda_sta_mcorner`（SS/TT/FF） | WNS/WHS 全 corner |
| 11 | S2 | DFT insertion（scan + ATPG） | `dft-insert` + `atpg` + `eda_dft` | scan chain + stuck-at ≥85% |
| 12 | S2 | Post-DFT optimization | resynth / buffering | timing 維持 |
| 13 | S2 | Equivalence check | `equivalence-check` + Yosys `equiv` | RTL ≡ post-DFT netlist |
| 14 | S3 | Floorplan + PDN | `eda_pnr`（init） | 面積 / utilization |
| 15 | S3 | Clock planning | clock-planning skill | clock-buffer 列表 |
| 16 | S3 | Placement（global + detailed） | `eda_pnr` | placement legal |
| 17 | S3 | CTS | `eda_pnr enable_cts=true` | clock skew |
| 18 | S3 | Post-CTS hold fixing | `repair_timing -hold` | WHS > 0 |
| 19 | S3 | Routing（global + detailed） | `eda_pnr enable_detailed_route=true` + `def_stage_progression_check` | 0 overflow + DEF SHA 真不同 |
| 20 | S3 | Parasitic Extraction（RC→SPEF） | `eda_extraction`（OpenRCX，captable `rules.openrcx.sky130A.nom.magic`） | `spef_extraction_check`（FIXED v0.2.5 — 真實 268 KB SPEF） |
| 21 | S3 | Post-route STA（MMMC） | `eda_sta_mcorner` | 3-corner 過 |
| 22 | S3 | IR Drop | OpenROAD PSM `analyze_power_grid` | `ir_drop_report_check`（FIXED v0.2.4） |
| 23 | S3 | EM check | PSM `-enable_em` | `em_report_check`（FIXED v0.2.4） |
| 24 | S3 | Antenna check | OpenROAD `check_antennas` | 0 violation（report-path FIXED v0.2.4） |
| 25 | S3 | Signal Integrity（crosstalk/noise） | SI 真實 SPEF coupling 篩查 | `si_crosstalk_check`（v0.2.6 接真實 SPEF） |
| 26 | S3 | Post-Layout Gate-Level Sim（+SDF） | `eda_simulate` | `post_layout_sim_check` PASS |
| 27 | S3 | Physical Verification | `eda_drc_klayout` + `eda_lvs` + ERC | DRC=0 / LVS device-exact / ERC floating-net |
| 28 | S3 | ECO repair loop | `eco-plan` | `eco_loop_audit` PASS |
| 29 | S4 | Power analysis | pre + post layout | 達 spec |
| 30 | S4 | Metal Fill（density fill） | OpenROAD `filler_placement` → `filled.def` | `metal_fill_density_check`（FIXED v0.2.4） |
| 31 | S4 | Tapeout checklist | `tapeout-checklist` + `signoff_audit` | 4/4 strict |
| 32 | S4 | GDSII output | `eda_gds` + `def2gds` | 只有 step 27 全 clean 才產出 |
| 33 | S4 | FPGA final sign-off | recompile + on-board test + `fpga_on_board_attestation_check` | bitstream hash + 硬體證據 |

> **編號注意：** Stage-3 簽核檢查另有一套簽核稽核編號（§D 用）：SPEF 22 / STA 23 / IR 24 / EM 25 /
> Antenna 26 / SI 27 / DRC-LVS-ERC 30 / fill 33，與上面這套 33-step 編號不同（SPEF 20 / STA 21 /
> IR 22 / EM 23 / Antenna 24 / SI 25 / PV 27 / fill 30）。同樣的檢查、兩套 id；待 `flow_doc_emit.py` 統一。

---

## C. LVS 簽核鏈（Phase-3 `step_lvs` 之下，v0.1.96→v0.2.2 新增）

| 層 | 內容 | 工具 |
|---|---|---|
| 1 | Structural LEC（預設） | `eda_lvs mode=yosys_equiv`（equiv_simple + equiv_induct）— SAT-model unproven = Category-D 落差 |
| 2 | Device-level 覆蓋 | `eda_extraction`（magic ext2spice）+ `eda_lvs mode=netgen` + `lvs_netgen_setup_emit.py` |
| 3 | Powered-netlist 收尾 | OpenROAD `write_verilog -include_pwr_gnd`（global_connect 後） |
| 4 | 頂層 port label | Route A `magic_port_extract_emit.py`（port makeall）/ Route B `lvs_def_port_seed.py`（DEF seed） |
| 5 | Sign-off guard（強制） | `lvs_signoff_guard.py` — 對 portless / vacuous match 直接 RAISE |

---

## D. Phase-3 簽核檢查 — 缺口狀態（子集；簽核稽核編號）

> **這是子集、不是完整步驟清單** — 只列有開源缺口的 Phase-3 簽核檢查（這也是為何 14-21 / 28 / 29 /
> 31 / 32 在*這裡*缺席：它們沒缺口）。完整連續 1→33 在 **§B**。狀態為 v0.2.6（修法已出 — 見 backlog
> `ORGANIC-20260531-phase3-signoff-chain-open-source-gaps`）：

| Step | 檢查 | 狀態（v0.2.6） | 嚴重度 |
|---|---|---|---|
| 22 | SPEF（OpenRCX） | **WORKS**（先前「ENV-BLOCKED」是誤判）— sky130A **確實**附 OpenRCX captable（`/foss/pdks/sky130A/libs.tech/openlane/rules.openrcx.sky130A.{min,nom,max}.magic`）；`extract_parasitics -ext_model_file` + `write_spef` 在真實 routed DEF 上萃取（spm：1370 rc segments / 330 nets / 1700 caps）。先前 RCX-0107「0 segments」是空（無繞線）DEF，不是缺 captable。 | 🟢 works |
| 23 | Post-route STA（MMMC） | 通過；pilot 回報 slack +X ns MET | 🟢 無 |
| 24 | IR drop（PSM） | **FIXED** — OpenROAD PSM `analyze_power_grid`（直接讀 DEF SPECIALNETS；不需 SPEF — 級聯前提是錯的）→ `reports/phase3/ir_drop.{rpt,json}` | 🟢 fixed |
| 25 | EM | **FIXED** — PSM `-enable_em` → `em.{rpt,json}` | 🟢 fixed |
| 26 | Antenna | **FIXED** — `check_antennas` 重導到 `antenna.{rpt,json}`（report-path） | 🟢 fixed |
| 27 | SI（crosstalk） | **接真實 SPEF**（v0.2.6）— 從 OpenRCX SPEF 算 per-net coupling ratio Cc/(Cc+Cg)（spm：503 nets / max 0.99 / mean 0.66 / 80 coupling-dominated）+ 最壞 capacitive-divider 噪聲界。coupling ratio 為 advisory（driven victim 可承受）；`violations_count=0`（完整 pass/fail 需 timing-window/driver-strength SI 工具）。無 SPEF 時退回 decoupled-C。 | 🟢 screen（真實 Cc） |
| 30 | DRC / LVS / ERC | **PARTIAL** — KLayout sky130 DRC + Magic floating-net ERC + device-level LVS（§C）皆接上/通過；完整 Calibre PERC（latch-up/ESD）環境緩議 | 🔶 partial |
| 33 | Metal fill | **FIXED** — OpenROAD `filler_placement` → `phase3/stage3/pnr/filled.def` + `density.{rpt,json}` | 🟢 fixed |
| 18 | Spare cells | **FIXED** — `spare_cells.json` 補上 `rows[]`（由既有 placement 推導；placement 不變） | 🟢 fixed |
| 5 | Formal | 確認 INFORMATIONAL waiver（altsyncram 無 model）— 無程式變更 | 🟢 無 |

**沒有一個是電路設計錯誤** — 全是腳本順序 / 級聯 / 環境 / 報告格式問題。可行修法追蹤於
`ORGANIC-20260531-phase3-signoff-chain-open-source-gaps`。

---

## E. 總計

| 視角 | 數量 | 全域步號 |
|---|---|---|
| Phase 1 runner 標記 | 34（15 主 + 19 子） | 1–34 |
| Phase 2 step 函式 | 15 | 35–49 |
| Phase 3 step 函式 | 6 | 50–55 |
| **循序流程總計** | **55** | **1–55（連續、不重數）** |
| Analog（並行） | A1–A8（8） | A1–A8 |
| Mixed-signal（並行） | M1–M4（4） | M1–M4 |
| 33-step Stage 模型（§B，獨立） | 33 | Stage 1:6 / 2:7 / 3:15 / 4:5 |
| LVS 簽核鏈層數（§C） | 5 | — |
| Phase-3 簽核檢查（§D 子集） | 10 | — |

---

## F. 保持更新

本文件是**衍生的**列舉。§A 的 runner-marker 表現在由 **`programs/flow_doc_emit.py`**（v0.2.3 出）自動產生到
**`FLOW_STEPS_GENERATED.md`** — runner 一改就跑 `python3 flow_doc_emit.py`；`flow_doc_emit.py --check`
（`tests/test_flow_doc_emit.py`）漂移就 CI fail。§B 的 33-step 模型、§C LVS 鏈、§D 簽核表仍人工策展
（無法從 marker 推導）；把兩套 Stage-3 編號統一進 generator 是剩下的 follow-up。
