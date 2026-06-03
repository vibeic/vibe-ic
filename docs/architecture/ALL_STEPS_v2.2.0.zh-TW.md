# Vibe-IC — 全部步驟，按 Stage、依順序（v2.2.0・繁體中文）

一份清單：整條流程的每一步，按 stage 分組、依執行順序，**單一連續編號 1 → 33，自 Stage 1
（Spec-to-RTL）起算**。Phase 1 文件生成是字母前置步（**D1–D5**，不計入 1→33）。兩條並行支線
—— Analog（A1–A9）與 Mixed-signal（M1–M4）—— 列在主流程之後。真實來源 = runner；更細的
程式層標記自動產生於 `FLOW_STEPS_GENERATED.md`。

Stage 對照：**D** 規格/文件（Phase 1）· **1** RTL+驗證 · **2** 合成+DFT ·
**3** 實體+簽核 · **4** 輸出+Tapeout。

---

## Phase 1（前置）— 規格與文件 · D1–D5（不計入 1→33）

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| D1 | 匯入與文字萃取（prompt 或既有文件 → `input_doc/`） | `phase1_doc_one_shot_runner` |
| D2 | 產生 L1–L13 核心設計層文件 | 決定性萃取器 |
| D3 | 產生 L14–L23 協定 / 時序 / skeleton 文件 | overlay 萃取器 |
| D4 | 協定類別合成 dispatch（81 類） | `is_<proto>` + `<proto>_synth` |
| D5 | Coverage / parity 報告 | `phase1` parity 報告 |

## Stage 1 — RTL 產生與驗證

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| 1 | Spec-to-RTL（由 L-docs 撰寫 RTL） | `spec-to-rtl` skill |
| 2 | Lint | `eda_lint` + hygiene gates |
| 3 | CDC / RDC check | `cdc-check` |
| 4 | Simulation | `testbench-gen` + `eda_simulate` |
| 5 | Formal verification | `formal-verify` + `assertion-gen` |
| 6 | FPGA early prototype | `eda_fpga_compile` / `eda_fpga_program` → `.sof` |

## Stage 2 — 合成與 DFT

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| 7 | Constraint setup | `constraint-gen` → `*.sdc` |
| 8 | SDC validation | SDC lint |
| 9 | Synthesis（Yosys） | `eda_synth` + `synth-doctor` |
| 10 | Pre-layout STA | `eda_sta_mcorner`（SS/TT/FF） |
| 11 | DFT insertion（scan + ATPG） | `dft-insert` + `atpg` + `eda_dft` |
| 12 | Post-DFT optimization | resynth / buffering |
| 13 | Equivalence check（LEC） | `equivalence-check` + Yosys `equiv` |

## Stage 3 — 實體設計與簽核

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| 14 | Floorplan + PDN | `eda_pnr`（init） |
| 15 | Clock planning | `clock-planning` skill |
| 16 | Placement（global + detailed） | `eda_pnr` |
| 17 | CTS | `eda_pnr enable_cts=true` |
| 18 | Post-CTS hold fixing | `repair_timing -hold` |
| 19 | Routing（global + detailed） | `eda_pnr enable_detailed_route=true` |
| 20 | 寄生萃取 → SPEF | OpenRCX `extract_parasitics` |
| 21 | Post-route STA（MMMC） | `eda_sta_mcorner` |
| 22 | IR drop | OpenROAD PSM `analyze_power_grid` |
| 23 | EM check | PSM `-enable_em` |
| 24 | Antenna check | OpenROAD `check_antennas` |
| 25 | Signal integrity（crosstalk） | SPEF coupling-cap 篩查 |
| 26 | Post-layout gate-level sim（+SDF） | `eda_simulate` |
| 27 | Physical verification（DRC / LVS / ERC + PERC-equivalent） | KLayout DRC + LVS 簽核鏈 + Magic ERC + `perc_equivalent` |
| 28 | ECO repair loop | `eco-plan` |

## Stage 4 — 輸出與 Tapeout

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| 29 | Power analysis | pre + post layout |
| 30 | Metal fill（density fill） | OpenROAD `filler_placement` |
| 31 | Tapeout checklist | `tapeout-checklist` + `signoff_audit` |
| 32 | GDSII output | `eda_gds` + `def2gds` |
| 33 | FPGA final sign-off | recompile + on-board test + attestation |

---

## 並行支線 — Analog A1–A9（`analog_one_shot_runner.py`，與 Stage 1–3 並行）

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| A1 | spec_extract | → `A1_spec.json` |
| A2 | topology_select | `analog-topology-select` → `A2_topology.json` |
| A3 | netlist_gen | → `<block>.sp` |
| A4 | corner_sweep | `ams-sim` → `A4_corners.json` |
| A5 | layout（Magic） | → `A5_layout.json` |
| A6 | 逐區塊實體驗證（DRC + LVS） | `analog_a6_block_pv_check` |
| A7 | post-layout resim | → `A7_postsim.json` |
| A8 | hardmacro_gen | → `{.lef,.lib,.gds,.v}`（餵回 Stage 3） |
| A9 | hw_verify（HIL）/ co-sim | → `A9_hw_verify.json` |

## 並行支線 — Mixed-signal M1–M4（`mixed-signal-cosim` skill，無專屬 runner）

| # | 步驟 | 工具 / 方式 |
|---|---|---|
| M1 | top merge | `mixed_signal_m1_top_merge_check.py` |
| M2 | co-sim setup | `mixed-signal-cosim` skill |
| M3 | co-sim run | `mixed-signal-cosim` skill |
| M4 | integration verify | `mixed-signal-cosim` skill |

---

## 總計

**33 個循序步驟** —— Stage 1：1–6 · Stage 2：7–13 · Stage 3：14–28 · Stage 4：29–33 ——
前置 **Phase 1（D1–D5）**，外加 **9 個 Analog（A1–A9）** 與 **4 個 Mixed-signal（M1–M4）** 並行步驟。

預檢：P0（`mcp_server_health_check`、`eda_doctor`）。編排器 `vibe_ic_one_shot_runner.py`
跑 Phase 1 → Phase 2 → Analog → Phase 3。

> 摘要之外的細節：runner 即時程式層標記見 `FLOW_STEPS_GENERATED.md`；LVS 簽核鏈與
> PERC-equivalent 覆蓋見 `PERC_SIGNOFF_MEMO.md`。英文正本：`ALL_STEPS_v2.2.0.md`。
