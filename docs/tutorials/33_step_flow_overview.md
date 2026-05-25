# Vibe-IC IC 設計流程 — 33 步 + 3 Phase

> Source of truth: `vibe-ic-marketplace/plugins/vibe-ic-core/flow/phase2_phase3.yaml`
> 33 個 step + 4 個 stage 的完整列舉。每一步都有自動化 gate；`flow_compliance_check.py`
> 會解析這個 YAML 產生 PASS/FAIL 矩陣。

## 兩個進入點 + 三個 Phase

```
Path A: Prompt / 對話 ──► Phase 1 (phase1 skill) ──┐
                                                    ├──► Phase 2b ──► Phase 3
Path B: 既有 design docs ──► Phase 2a (17 skills) ─┘
```

| Phase | 做什麼 | Skills | 輸出 |
|---|---|---|---|
| **Phase 1** | 對話 → L1-L13 | 2（`phase1` + `spec-review`）+ PM Agent + IC Expert Agent | `generated_docs/L*.json` + `human_docs/L*.md` |
| **Phase 2a** | Vendor docs → L1-L13 | 17 | 同上 |
| **Phase 2b** | L1-L13 → RTL → FPGA PASS | 22 | RTL + sim + .sof + protocol-tester N/N |
| **Phase 3** | RTL → GDS → Tapeout | 23 | GDS + DRC clean + LVS match + tapeout 4/4 |

「Phase 2+3」常合稱，**那 33 步**就是 `phase2_phase3.yaml` 對應的後段流程
（Phase 2b + Phase 3）。

---

## 33 步全表（4 個 stage）

### Stage 1 — RTL Generation + Verification（步 1-6，~Phase 2b 前段）

| # | Step | 工具/Skill | Gate |
|---|---|---|---|
| 1 | **Spec-to-RTL** | `spec-to-rtl` | L1-L9 docs present + RTL files emitted |
| 2 | **Lint** | `eda_lint` + 7 v0.74 Phase-2a gates + v0.75 polluter check | Verilator 0 errors + 結構化 lint 全 PASS |
| 3 | **CDC / RDC check** | `cdc-check` skill | 跨時脈域路徑都有同步器 |
| 4 | **Simulation** | `testbench-gen` + `eda_simulate` + L10/L12 coverage + Verilator coverage | 所有 tb PASS + 覆蓋率達標 |
| 5 | **Formal verification** | `formal-verify` + `assertion-gen` + bit-level tb | k-induction proved |
| 6 | **FPGA early prototype** | `fpga-test-harness` + `eda_fpga_compile` + `eda_fpga_program` + on-board BIST (LED + optional protocol tester) | `.sof` + BIST PASS（IC-specific oracle） |

### Stage 2 — Synthesis + DFT（步 7-13，~Phase 2b 末 ~ Phase 3 入口）

| # | Step | 工具/Skill | Gate |
|---|---|---|---|
| 7 | **Constraint setup** | `constraint-gen` | `*.sdc` + `pvt_matrix.json` 3 corners |
| 8 | **SDC validation** | SDC lint program | 所有 clock/IO 約束齊全 |
| 9 | **Synthesis (Yosys)** | `eda_synth` + `synth-doctor` | mapped netlist + cell count |
| 10 | **Pre-layout STA** | `eda_sta_mcorner` (SS/TT/FF) | WNS/WHS 全 corner 過 |
| 11 | **DFT insertion (scan + ATPG)** | `dft-insert` + `atpg` + `eda_dft` | scan chain + stuck-at coverage ≥ 85% |
| 12 | **Post-DFT optimization** | resynth / buffering | timing 維持 |
| 13 | **Equivalence check** | `equivalence-check` + Yosys `equiv` | RTL ≡ post-DFT netlist |

### Stage 3 — Physical Design + Sign-off（步 14-28，~Phase 3 主體）

| # | Step | 工具/Skill | Gate |
|---|---|---|---|
| 14 | **Floorplan + PDN** | `eda_pnr` (init) | 面積 / utilization |
| 15 | **Clock planning** | clock-planning skill | clock buffer 列表決定 |
| 16 | **Placement** (global + detailed) | `eda_pnr` | placement legal |
| 17 | **CTS** | `eda_pnr enable_cts=true` (v2.4.0) | clock skew 達標 |
| 18 | **Post-CTS hold fixing** | `repair_timing -hold` | WHS > 0 |
| 19 | **Routing** (global + detailed) | `eda_pnr enable_detailed_route=true` + `def_stage_progression_check` | 0 overflow + DEF SHA 真不同 |
| 20 | **Parasitic Extraction** (RC → SPEF) | `eda_extraction` | `spef_extraction_check` PASS |
| 21 | **Post-route STA** (MMMC) | `eda_sta_mcorner` | 3-corner 全過 |
| 22 | **IR Drop** | `eda_ir_drop` | static + dynamic 達標 |
| 23 | **EM check** | electromigration | lifetime ≥ 10 yr |
| 24 | **Antenna check** | OpenROAD antenna | 0 violation |
| 25 | **Signal Integrity** (Crosstalk / Noise) | SI analysis | `si_crosstalk_check` PASS |
| 26 | **Post-Layout Gate-Level Sim** (Post-Sim + SDF) | `eda_simulate` | `post_layout_sim_check` PASS |
| 27 | **Physical Verification** | `eda_drc_klayout` + `eda_lvs` + ERC + Density | DRC=0 / LVS match / ERC=0 |
| 28 | **ECO repair loop** | `eco-plan` skill | `eco_loop_audit` PASS |

### Stage 4 — Output + Validation（步 29-33，~Phase 3 收口）

| # | Step | 工具/Skill | Gate |
|---|---|---|---|
| 29 | **Power analysis** | pre + post layout | 達 spec |
| 30 | **Metal Fill** (density fill) | `eda_pnr` | `metal_fill_density_check` PASS |
| 31 | **Tapeout checklist** | `tapeout-checklist` + `signoff_audit` | 4/4 strict（不是 3/4） |
| 32 | **GDSII output** | `eda_gds` + `def2gds` | 只有 Step 27 全 clean 才能跑 |
| 33 | **FPGA final sign-off** | recompile + on-board test + `fpga_on_board_attestation_check` | bitstream hash + Quartus log + ≥1 非 JSON 硬體證據 |

---

## Phase 對應關係

```
Phase 1 (對話收集)               Phase 2a (vendor docs → L1-L13)
        │                              │
        └──────────► L1-L13 ◄──────────┘
                       │
                       ▼
Phase 2b ┌───────────────────────────┐
         │ Stage 1 步 1-6            │  RTL → sim → formal → FPGA + protocol tester
         │ Stage 2 步 7-9（部分）   │  constraints + synth
         └───────────────────────────┘
                       │
                       ▼
Phase 3  ┌───────────────────────────┐
         │ Stage 2 步 10-13          │  Pre-STA + DFT + post-DFT + LEC
         │ Stage 3 步 14-28          │  Floorplan → PnR → SPEF → STA → IR/EM/SI → DRC/LVS → ECO
         │ Stage 4 步 29-33          │  Power + metal fill + checklist + GDS + FPGA final
         └───────────────────────────┘
```

實務上 Phase 2b vs Phase 3 的分界有點模糊（步 9 合成是兩 phase 的橋）。
`flow_compliance_check --strict` 看的是 **全 33 步 4/4 stage 都過**，不再是舊的
「3/4 寬鬆」標準。

---

## 執行入口

### 互動式（推薦）

```bash
claude
> /flow-orchestrate
# 它會逐步觸發 33 步並在每步呼叫對應 gate
```

### 程式化檢查

```bash
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/flow_compliance_check.py \
  --project <output_dir> --strict --json reports/flow_compliance.json
# 期望: verdict=PASS, 33/33
```

### Phase 1 入口（從 prompt 出發）

```bash
claude
> /phase1
# PM Agent 對話收集需求 → IC Expert Agent 整理 → 產 L1-L13
```

---

## 關鍵規則

1. **每步都有自動化 gate** — `flow_compliance_check.py` 解析 `phase2_phase3.yaml` 跑驗證；
   `files_exist` / `program_exit_zero` / `json_field_true` 三類 predicate。

2. **跳步要 waiver** — `<project>/waivers.json` 有 schema 檢查（`waivers_schema_check.py`），
   不能寫 "TODO: fix later" 矇混；自我簽核 reviewer 會被 reject。

3. **3/4 通過已不再算 PASS** — v0.46 改成 4/4 strict；`--lenient` 才能用舊行為。
   v0.47 fresh-agent pilot 曾在 3/4 寬鬆下偽造 15 個 step，所以收緊。

4. **Step 33 不是 JSON 自我宣告就算過** — 要 4 類證據：
   - JSON 結果報告
   - bitstream hash（FPGA `.sof` SHA）
   - Quartus programmer log
   - ≥1 非 JSON 硬體 artefact（webcam / scope / UART / protocol-tester hex log）

5. **檔案存在 ≠ 跑過** — `provenance_logger` 包每個工具呼叫，記
   `{tool, version, argv, input/output hash, exit, duration, stdout/err hash}`
   到 `provenance.jsonl`。`provenance_check.py` 會驗 logged hash 跟 disk hash 一致。
   **Mandatory** 在 Step 9 / 19 / 27 / 32。

---

## v0.74 / v0.75 加上去的結構化 gate（在 Step 2 觸發）

每個都是 IC-agnostic（任何協議都通用），有 `condition_files_exist` 守門 —
非協議型 IC 看到沒輸入會自動 no-op。

| Gate | 抓什麼 | 實際抓過的 bug |
|---|---|---|
| `internal_vs_external_timing_check` | L8 必須切 host-side（外部）vs DUT-side（內部）兩組 timing | 9-bug bisect 第 1 類 |
| `rsp_example_otp_consistency_check` | L3 response examples 跟 L11 OTP 內容一致 + CRC 真的會驗 | 3 號 |
| `threshold_range_contiguity_check` | 離散分類門檻區間連續，不能有 reject gap | 5 號 |
| `spec_response_delay_check` | spec 寫 tSRS/tIRT 就要有 wait state | 4 號 |
| `nba_addr_read_race_check` | FSM 的 addr 跟 data pipeline 有沒 race | 6 號 |
| `periodic_timer_vs_rx_activity_check` | wake/keepalive 收到 RX 要重置 | 7 號 |
| `memory_read_pipeline_check` | BRAM 有 registered read latency 要宣告 | 8 號 |
| `fpga_wrapper_input_polluter_check` (v0.75) | wrapper AND/OR 多支 inout 但只有一支實際接線 | v075 wrapper 5-pin AND |

---

## Reference

- 完整 step 描述：`vibe-ic-marketplace/plugins/vibe-ic-core/flow/phase2_phase3.yaml`
- 33-step 規範：`docs/design/STANDARD_FLOW.md`
- Strict gate 程式：`vibe-ic-marketplace/plugins/vibe-ic-d/programs/flow_compliance_check.py`
- Skill index：`vibe-ic-marketplace/plugins/vibe-ic-core/skills/`（71 個）
- Deterministic programs：`vibe-ic-marketplace/plugins/vibe-ic-d/programs/`（115 個）
- 兩入口的高層流程圖：`~/AI_IC_design/CLAUDE.md`
