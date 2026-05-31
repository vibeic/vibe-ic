# Vibe-IC — 全部步驟，按 Stage、依順序（v2.2.0・繁體中文）

**Plugin 0.2.6.** 一份清單。整條流程的每一步，**按 stage 分組、依執行順序、單一連續編號（1 → 38）**。
兩條並行支線（Analog、Mixed-signal）列在主流程之後。真實來源 = runner。**英文正本：`ALL_STEPS_v2.2.0.md`。**

> runner 的*內部實作標記*（Phase 1 `[1/15]`…`[15/15]` + 19 子步；Phase 2/3 `def step_*`）是更細的程式視角，
> 自動產生於 **`FLOW_STEPS_GENERATED.md`**（由 `flow_doc_emit.py`）。它們對應到下面的 stage；本文件是
> 單一、給人看的順序清單。

Stage 對照：**0** 規格/文件（Phase 1）· **1** RTL+驗證 · **2** 合成+DFT · **3** 實體+簽核（Phase 3）·
**4** 輸出+Tapeout。（Phase 對應：Phase 1 = Stage 0；Phase 2 ≈ Stage 1-2；Phase 3 ≈ Stage 3-4。）

---

## Stage 0 — 規格與文件（Phase 1）

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| 1 | 匯入與文字萃取（prompt 或既有文件 → `input_doc/`） | `phase1_doc_one_shot_runner`（`[1/15]`） |
| 2 | 產生 L1–L13 核心設計層文件 | 決定性萃取器（`[2/15]`–`[14/15]`） |
| 3 | 產生 L14–L23 協定 / 時序 / skeleton 文件 | `[14b/15]`–`[14d/15]` overlay |
| 4 | 協定類別合成 dispatch（81 類） | `[14e/15]`–`[14e3/15]`（`is_<proto>` + `<proto>_synth`） |
| 5 | Coverage / parity 報告 | `[15/15]` |

## Stage 1 — RTL 產生與驗證（Phase 2 前段）

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| 6 | Spec-to-RTL（由 L-docs 撰寫 RTL） | `spec-to-rtl` skill（runner 對 `rtl_gen=null` 類別 WAIVE `step_rtl_gen`） |
| 7 | Lint | `eda_lint` + hygiene gates |
| 8 | CDC / RDC check | `cdc-check` |
| 9 | Simulation | `testbench-gen` + `eda_simulate` + 覆蓋率 |
| 10 | Formal verification | `formal-verify` + `assertion-gen`（無 model 則 informational waiver） |
| 11 | FPGA early prototype | `eda_fpga_compile` / `eda_fpga_program` + on-board BIST → `.sof` |

## Stage 2 — 合成與 DFT（Phase 2 後段）

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| 12 | Constraint setup | `constraint-gen` → `*.sdc` + 3-corner PVT |
| 13 | SDC validation | SDC lint |
| 14 | Synthesis（Yosys） | `eda_synth` + `synth-doctor`（+ tie-cell pass） |
| 15 | Pre-layout STA | `eda_sta_mcorner`（SS/TT/FF） |
| 16 | DFT insertion（scan + ATPG） | `dft-insert` + `atpg` + `eda_dft` |
| 17 | Post-DFT optimization | resynth / buffering |
| 18 | Equivalence check（LEC） | `equivalence-check` + Yosys `equiv` |

## Stage 3 — 實體設計與簽核（Phase 3）

| # | 步驟 | 工具 / 方式 | 開源狀態 |
|---|---|---|---|
| 19 | Floorplan + PDN | `eda_pnr`（init） | ✅ |
| 20 | Clock planning | clock-planning skill | ✅ |
| 21 | Placement（global + detailed） | `eda_pnr` | ✅ |
| 22 | CTS | `eda_pnr enable_cts=true` | ✅ |
| 23 | Post-CTS hold fixing | `repair_timing -hold` | ✅ |
| 24 | Routing（global + detailed） | `eda_pnr enable_detailed_route=true` | ✅ |
| 25 | 寄生萃取 → SPEF | OpenRCX `extract_parasitics -ext_model_file rules.openrcx.sky130A.nom.magic` | ✅ FIXED v0.2.5（真實 268 KB SPEF） |
| 26 | Post-route STA（MMMC） | `eda_sta_mcorner` | ✅ |
| 27 | IR drop | OpenROAD PSM `analyze_power_grid` | ✅ FIXED v0.2.4 |
| 28 | EM check | PSM `-enable_em` | ✅ FIXED v0.2.4 |
| 29 | Antenna check | OpenROAD `check_antennas` | ✅ FIXED v0.2.4 |
| 30 | Signal integrity（crosstalk） | SPEF coupling-cap 篩查（Cc/(Cc+Cg)） | ✅ WIRED v0.2.6（advisory） |
| 31 | Post-layout gate-level sim（+SDF） | `eda_simulate` | ✅ |
| 32 | Physical verification（DRC / LVS / ERC + PERC-equiv） | KLayout DRC + LVS 簽核鏈（見下）+ Magic ERC + `perc_equivalent` 彙整 | ✅ DRC/LVS/ERC；PERC-equiv（~70% 自動） |
| 33 | ECO repair loop | `eco-plan` | ✅ |

**步 32 — LVS 簽核鏈**（`step_lvs` 之下）：(1) structural LEC `eda_lvs yosys_equiv` →
(2) device-level `eda_extraction` + netgen → (3) powered-netlist `write_verilog -include_pwr_gnd` →
(4) port labels `magic_port_extract_emit`（Route A）/ `lvs_def_port_seed`（Route B）→
(5) **強制** `lvs_signoff_guard`（對 portless/vacuous match 直接 RAISE）。

**步 32 — PERC-equivalent 覆蓋**（`perc_equivalent.{rpt,json}` + `PERC_SIGNOFF_MEMO.md`，v0.2.7）：
商用 Calibre PERC 的開源替代。AUTOMATED：antenna / IR / EM / floating-nets（讀步 27-30/ERC 的判決）。
GUARDBAND：EM 電流密度（<0.5 mA/µm）+ ≥2×2 via。MANUAL_REVIEW（**絕不**自動 PASS、附待辦清單）：
ESD pad-ring 存在性、latch-up/well-tap、跨電壓域 — 對 core-only macro（無 pad ring）/ 單電源設計自動標 `N/A`。

## Stage 4 — 輸出與 Tapeout（Phase 3 收口）

| # | 步驟 | 工具 / 方式 | 開源狀態 |
|---|---|---|---|
| 34 | Power analysis | pre + post layout | ✅ |
| 35 | Metal fill（density fill） | OpenROAD `filler_placement` → `filled.def` | ✅ FIXED v0.2.4 |
| 36 | Tapeout checklist | `tapeout-checklist` + `signoff_audit`（4/4 strict） | ✅ |
| 37 | GDSII output | `eda_gds` + `def2gds`（只有 step 32 全 clean 才產出） | ✅ |
| 38 | FPGA final sign-off | recompile + on-board test + attestation | ✅ |

---

## 並行支線 — Analog A1–A8（`analog_one_shot_runner.py`，與 Stage 1-3 並行）

| # | 步驟 | 輸出 |
|---|---|---|
| A1 | spec_extract | `analog/<block>/A1_spec.json` |
| A2 | topology_select | `A2_topology.json` |
| A3 | netlist_gen | `<block>.sp` |
| A4 | corner_sweep | `A4_corners.json` |
| A5 | layout（Magic） | `A5_layout.json`（DRC-clean + LVS-match） |
| A6 | post_layout_resim | `A6_postsim.json` |
| A7 | hardmacro_gen | `{.lef,.lib,.gds,.v}` → 餵回 Stage 3 |
| A8 | hw_verify（HIL） | `A8_hw_verify.json` |

## 並行支線 — Mixed-signal M1–M4（skill `mixed-signal-cosim`，無專屬 runner）

| # | 步驟 |
|---|---|
| M1 | top merge（`mixed_signal_m1_top_merge_check.py`） |
| M2 | co-sim setup |
| M3 | co-sim run |
| M4 | integration verify |

---

## 總計

**38 個循序步驟**（Stage 0：1-5 · Stage 1：6-11 · Stage 2：12-18 · Stage 3：19-33 ·
Stage 4：34-38）**+ 8 個 Analog（A1-A8）+ 4 個 Mixed-signal（M1-M4）**，後兩者並行。

> 預檢：P0（`mcp_server_health_check`、`eda_doctor`）。編排器：`vibe_ic_one_shot_runner.py`
> 跑 Phase 1 → Phase 2 → Analog → Phase 3。

本文件是**衍生**清單。runner 的即時實作標記自動產生於 `FLOW_STEPS_GENERATED.md`
（`flow_doc_emit.py --check` 漂移就 CI fail）。
