# Vibe-IC 標準 IC 設計流程

> ⚠️ **已被 `docs/architecture/CANONICAL_FLOW_v2.2.0.md` 取代**（plugin v0.2.2）。本文件的 33-step
> 逐步規格仍可作後段參考，但流程總覽以新版（對齊 runner 實際 step 標記）為準。

**版本**：v1.0
**日期**：2026-04-12
**定位**：給定 Design Documents，產出 production-ready IC (GDS + FPGA SOF)

---

## 輸入 / 輸出定義

### 輸入（Design Document Suite）

| 檔案 | 必要 | 內容 |
|---|---|---|
| `<IC>-datasheet.md` | ✅ | 完整規格書（18 節）|
| `<IC>-appnote.md` | ✅ | 應用筆記 |
| `spec.json` | ✅ | 結構化機器可讀規格（下述 schema）|

#### `spec.json` 最小 schema

```json
{
  "design_name": "bench-a",
  "top_module": "bench-a_synth_wrapper",

  "clock": {
    "name": "clk",
    "frequency_mhz": 5,
    "period_ns": 200
  },

  "supply": {
    "vdd_min_v": 3.0,
    "vdd_typ_v": 3.3,
    "vdd_max_v": 3.6
  },

  "temperature": {
    "min_c": -40,
    "max_c": 85
  },

  "pdk": {
    "name": "GF180MCU",
    "node_nm": 180,
    "standard_cell_library": "gf180mcu_fd_sc_mcu7t5v0",
    "corners": ["tt_025C_3v30", "ss_125C_3v00", "ff_n40C_3v60"]
  },

  "target": {
    "utilization_pct": 40,
    "max_wns_ns": 0,
    "dft_coverage_pct": 85,
    "drc_violations": 0,
    "lvs_clean": true
  },

  "interfaces": ["I2C", "SPI"],

  "reset": {
    "name": "rst_n",
    "active_low": true
  },

  "fpga": {
    "board": "DE10-Nano",
    "device": "5CSEBA6U23I7",
    "family": "Cyclone V"
  }
}
```

### 輸出

| 檔案 | 說明 |
|---|---|
| `<design>.gds` | GDSII tape-out 檔（sign-off clean 才產出）|
| `<design>.sof` | FPGA bitstream |
| `status.json` | 每步 PASS/FAIL/WARN + metrics |
| `reports/` | 每步的詳細報告 |
| `convergence.json` | ECO 迭代記錄 |

---

## 標準流程（4 Stage, 33 Steps）

```
═══════════════════════════════════════════════════════════════
  Stage 1 — RTL Generation + Verification (Steps 01-06)
═══════════════════════════════════════════════════════════════

  01. Spec-to-RTL          從 spec.json + datasheet 產出 RTL
  02. Lint                 RTL 品質檢查（0 errors required）
  03. CDC / RDC            時脈域 / 重置域檢查
  04. Simulation           功能驗證（cocotb testbench）
  05. Formal               形式驗證（assertions proved）
  06. FPGA early prototype FPGA 快速原型（Quartus compile + 基本功能）

═══════════════════════════════════════════════════════════════
  Stage 2 — Synthesis + DFT (Steps 07-13)
═══════════════════════════════════════════════════════════════

  07. Constraint setup     從 spec.json 產生 SDC + PVT matrix
  08. SDC validation       SDC lint / constraint sanity check
  09. Synthesis            Yosys + PDK mapped netlist
  10. Pre-layout STA       合成後 timing 驗證（multi-corner）
  11. DFT insertion        Scan chain + ATPG
  12. Post-DFT optimization Resynthesis / buffering
  13. Equivalence check    RTL ≡ post-DFT netlist (LEC)

═══════════════════════════════════════════════════════════════
  Stage 3 — Physical Design + Sign-off (Steps 14-24)
═══════════════════════════════════════════════════════════════

  14. Floorplan + PDN      面積規劃 + 電源網路
  15. Clock planning       Clock tree 目標（skew/latency/buffer）
  16. Placement            Global + detailed placement
  17. CTS                  Clock tree synthesis
  18. Post-CTS hold fixing Buffer insertion for hold violations
  19. Routing              Global + detailed route
  20. Post-route STA       Multi-corner multi-mode sign-off timing
  21. IR Drop              靜態 + 動態電源完整性
  22. EM check             Electromigration 壽命驗證
  23. Antenna check        Gate oxide 保護
  24. Physical Verification DRC + LVS + ERC（全部 clean）

  ↺ ECO Closure Loop
      Timing fail  → 回 Step 16 或 09
      DRC fail     → 回 Step 19
      LVS fail     → 回 Step 09
      IR/EM fail   → 回 Step 14
      Max 3 iterations per category

═══════════════════════════════════════════════════════════════
  Stage 4 — Output + Validation (Steps 25-28)
═══════════════════════════════════════════════════════════════

  25. Power analysis       Pre/post-layout 功耗估計
  26. Tapeout checklist    最終 sign-off 確認
  27. GDSII output         只有 Step 24 全 clean 才產出
  28. FPGA final sign-off  Quartus recompile + on-board test
```

---

## 每步詳細規格

### Stage 1 — RTL Generation + Verification

#### Step 01: Spec-to-RTL

**輸入**：`spec.json` + `<IC>-datasheet.md`
**工具**：AI Agent（`spec-to-rtl` skill）
**輸出**：`rtl/<module>.sv`（所有模組）、`rtl/README.md`
**Pass 標準**：至少 1 個 .sv 檔、top module 名匹配 spec.json
**Fail 動作**：重新執行 spec-to-rtl

#### Step 02: Lint

**輸入**：`rtl/*.sv`
**工具**：Verilator `--lint-only`
**輸出**：`reports/02_lint.log`
**Pass 標準**：0 errors（warnings 可接受）
**Fail 動作**：`rtl-repair` skill 修復

#### Step 03: CDC / RDC

**輸入**：`rtl/*.sv`
**工具**：Yosys flatten + clock domain analysis / SymbiYosys CDC
**輸出**：`reports/03_cdc.log`
**Pass 標準**：
- 單時脈域：自動 PASS（N/A）
- 多時脈域：0 unresolved CDC violations
**Fail 動作**：加 synchronizer / handshake

#### Step 04: Simulation

**輸入**：`rtl/*.sv` + `sim/test_*.py`
**工具**：cocotb + Verilator（或 Icarus）
**輸出**：`reports/04_sim.log`、`sim/results.xml`
**Pass 標準**：所有 test case PASS
**Fail 動作**：修 RTL 或修 testbench

#### Step 05: Formal

**輸入**：`rtl/*.sv` + `scripts/*.sby`（assertion files）
**工具**：SymbiYosys + Yices/Z3
**輸出**：`reports/05_formal_*.log`
**Pass 標準**：所有 sby config proved
**Fail 動作**：修 assertion 或修 RTL

#### Step 06: FPGA Early Prototype

**輸入**：`rtl/*.sv` + `spec.json`（fpga 區段）
**工具**：Quartus（map → fit → asm → sta）
**輸出**：`fpga/<design>.sof`、`reports/06_fpga_early.log`
**Pass 標準**：SOF 產出、0 errors、Fmax > target frequency
**Fail 動作**：RTL 修改（resource / timing 問題）
**注意**：此步驟與 Stage 2 可平行

---

### Stage 2 — Synthesis + DFT

#### Step 07: Constraint Setup

**輸入**：`spec.json`
**工具**：Python script（`gen_constraints.py`）
**輸出**：
- `constraints/<design>.sdc`（時序約束）
- `constraints/pvt_matrix.json`（PVT corners 定義）
- `constraints/mcmm.json`（Multi-Corner Multi-Mode 定義）

**自動產生邏輯**：
```python
# 從 spec.json 產生 SDC
clock_period = spec["clock"]["period_ns"]
sdc = f"create_clock -name {spec['clock']['name']} -period {clock_period} [get_ports {spec['clock']['name']}]"

# PVT matrix
corners = spec["pdk"]["corners"]  # ["tt_025C_3v30", "ss_125C_3v00", "ff_n40C_3v60"]

# MCMM
modes = ["functional"]
if spec["target"]["dft_coverage_pct"] > 0:
    modes.append("scan")
```

**Pass 標準**：SDC + PVT + MCMM 檔案產出
**Fail 動作**：spec.json 不完整 → 回 Phase 1

#### Step 08: SDC Validation

**輸入**：`constraints/<design>.sdc` + `rtl/*.sv`
**工具**：OpenSTA constraint checks / 自寫 sdc_lint.py
**驗證項目**：
- [ ] 所有 clock 有定義
- [ ] 所有 I/O 有 timing constraint 或 false path
- [ ] 無 unconstrained path
- [ ] Clock name 與 RTL port name 匹配
- [ ] Generated clock 正確
**Pass 標準**：0 unconstrained paths、0 name mismatches
**Fail 動作**：修 SDC 或修 spec.json

#### Step 09: Synthesis

**輸入**：`rtl/*.sv` + `constraints/<design>.sdc`
**工具**：Yosys + PDK liberty
**輸出**：`results/synth_<design>.v`（mapped netlist）
**Pass 標準**：cell count > 0、無 latch inference（除非 spec 允許）
**Fail 動作**：`synth-doctor` skill 分析 + 修 RTL

#### Step 10: Pre-layout STA

**輸入**：`results/synth_<design>.v` + SDC + PVT corners
**工具**：OpenSTA
**輸出**：`reports/10_sta_prelayout_<corner>.rpt`
**Pass 標準**：WNS ≥ 0（所有 corners）
**Fail 動作**：
- WNS > -10% period → 可繼續（P&R 有望修）
- WNS < -10% period → 回 Step 09 re-synth（constraint / cell 問題）

#### Step 11: DFT Insertion

**輸入**：`results/synth_<design>.v` + liberty + cell verilog model
**工具**：Fault（chain → cut → atpg）
**輸出**：`results/scan_<design>.v`（scan-chained netlist）、ATPG coverage
**Pass 標準**：scan chain 插入成功、coverage ≥ spec.target.dft_coverage_pct
**Fail 動作**：調整 scan config / clock gating 策略

#### Step 12: Post-DFT Optimization

**輸入**：`results/scan_<design>.v`
**工具**：Yosys re-optimization（abc + buffer）
**輸出**：`results/opt_scan_<design>.v`
**Pass 標準**：cell count < 1.2x pre-DFT
**Fail 動作**：調整 scan chain configuration

#### Step 13: Equivalence Check

**輸入**：RTL vs post-DFT netlist
**工具**：Yosys equiv_make / equiv_simple
**輸出**：`reports/13_equiv.log`
**Pass 標準**：equiv proved（或 WARN 如果開源工具無法 conclusively prove）
**Fail 動作**：人工審閱 diff

---

### Stage 3 — Physical Design + Sign-off

#### Step 14: Floorplan + PDN

**輸入**：post-DFT netlist + LEF + liberty
**工具**：OpenROAD
**輸出**：floorplan DEF
**Pass 標準**：utilization ≤ spec.target.utilization_pct、PDN 完整
**Fail 動作**：調整 die size / utilization

#### Step 15: Clock Planning

**輸入**：SDC + floorplan DEF
**工具**：OpenROAD + 自定義 script
**內容**：
- Clock source location 確認
- Target skew < 100ps（或 spec 定義）
- Buffer list 選擇
- Clock gating cell 配置
**Pass 標準**：clock plan 產出
**Fail 動作**：調整 constraint

#### Step 16: Placement

**輸入**：floorplan DEF + post-DFT netlist
**工具**：OpenROAD（global_placement + detailed_placement）
**輸出**：placed DEF
**Pass 標準**：check_placement 通過、0 overlap
**Fail 動作**：調整 density / utilization

#### Step 17: CTS

**輸入**：placed DEF + clock plan
**工具**：OpenROAD `clock_tree_synthesis`
**輸出**：CTS DEF + CTS report
**Pass 標準**：skew < target、insertion delay reasonable
**Fail 動作**：調整 buffer list / sink clustering

#### Step 18: Post-CTS Hold Fixing

**輸入**：CTS DEF
**工具**：OpenROAD `repair_timing -hold`
**輸出**：hold-fixed DEF
**Pass 標準**：hold slack ≥ 0（FF corner）
**Fail 動作**：增加 buffer / 調整 placement

#### Step 19: Routing

**輸入**：hold-fixed DEF
**工具**：OpenROAD（global_route + detailed_route）
**輸出**：routed DEF + route DRC report
**Pass 標準**：0 route DRC violations
**Fail 動作**：增加 routing layers / 調整 congestion

#### Step 20: Post-route STA

**輸入**：routed DEF + SPEF + SDC + PVT corners
**工具**：OpenSTA（multi-corner multi-mode）
**MCMM 驗證**：
- Functional mode: setup @ SS corner、hold @ FF corner
- Scan mode: setup/hold @ TT corner
**輸出**：`reports/20_sta_<corner>_<mode>.rpt`
**Pass 標準**：WNS ≥ 0 且 TNS = 0（所有 corner × mode）
**Fail 動作**：→ ECO closure loop

#### Step 21: IR Drop

**輸入**：routed DEF + liberty
**工具**：OpenROAD PSM `analyze_power_grid`
**輸出**：`reports/21_ir_drop.rpt`
**Pass 標準**：worst voltage drop < 10% VDD
**Fail 動作**：回 Step 14 調整 PDN stripe

#### Step 22: EM Check

**輸入**：routed DEF + switching activity 估計
**工具**：OpenROAD PSM / 估計法
**輸出**：`reports/22_em.rpt`
**Pass 標準**：所有 wire Javg < foundry EM limit
**Fail 動作**：加寬 power stripe / signal wire

#### Step 23: Antenna Check

**輸入**：routed DEF
**工具**：OpenROAD `check_antennas`
**輸出**：`reports/23_antenna.rpt`
**Pass 標準**：0 net + 0 pin violations
**Fail 動作**：OpenROAD `repair_antennas` / reroute

#### Step 24: Physical Verification

**輸入**：GDS（從 DEF 轉出）
**工具**：
- DRC：KLayout + foundry rule deck
- LVS：Netgen（netlist vs CDL）
- ERC：Netgen / KLayout
**輸出**：`reports/24_drc.rpt`、`reports/24_lvs.rpt`、`reports/24_erc.rpt`
**Pass 標準**：DRC 0 violations + LVS MATCH + ERC clean
**Fail 動作**：
- DRC fail → 回 Step 19
- LVS fail → 回 Step 09（嚴重）
- ERC fail → 回 Step 14

---

### ECO Closure Loop

```
Sign-off fail detected
  ↓
Classify violation type:
  ├─ Timing (setup/hold) → re-place (Step 16) or re-synth (Step 09)
  ├─ DRC                 → re-route (Step 19)
  ├─ LVS                 → re-synth (Step 09)
  ├─ IR/EM               → re-PDN (Step 14)
  └─ Antenna             → repair_antennas + re-route (Step 19)
  ↓
Re-run from fallback step through sign-off
  ↓
Record iteration metrics (WNS, TNS, DRC count, power, area)
  ↓
Check convergence:
  - Δ(cost) < threshold → accept
  - Oscillation detected → escalate to human
  - Max 3 iterations per category
```

---

### Stage 4 — Output + Validation

#### Step 25: Power Analysis

**輸入**：routed DEF + switching activity
**工具**：OpenSTA power report / Yosys estimate
**輸出**：`reports/25_power.rpt`
**Pass 標準**：total power < spec budget（如有）
**Note**：informational，不 block tape-out

#### Step 26: Tapeout Checklist

**輸入**：所有前步驟的 status
**工具**：`tapeout-checklist` skill
**驗證項目**：
- [ ] STA clean（所有 corner × mode）
- [ ] DRC clean
- [ ] LVS clean
- [ ] ERC clean
- [ ] Antenna clean
- [ ] IR drop OK
- [ ] EM OK
- [ ] DFT coverage ≥ target
- [ ] Lib / PVT consistency confirmed
**Pass 標準**：所有 checklist 項目 ✅
**Fail 動作**：列出缺失項目，不產出 GDS

#### Step 27: GDSII Output

**輸入**：routed DEF + cell GDS
**工具**：KLayout
**輸出**：`<design>_tapeout.gds`
**前提**：Step 26 PASS
**Fail 動作**：不產出（回到 sign-off loop）

#### Step 28: FPGA Final Sign-off

**輸入**：最終 RTL（與 GDS 同版本）+ spec.json FPGA 區段
**工具**：Quartus compile + on-board test
**輸出**：`<design>.sof` + `reports/28_fpga_test.rpt`
**Pass 標準**：SOF 產出 + 功能測試 PASS
**Fail 動作**：RTL 與 ASIC 流程不一致 → 嚴重問題

---

## 工具鏈對照

| Step | 工具 | Plugin Skill |
|---|---|---|
| 01 | AI Agent | `spec-to-rtl` |
| 02 | Verilator | `rtl-review` |
| 03 | Yosys / SymbiYosys | `cdc-check`, `rdc-check` |
| 04 | cocotb + Verilator | `testbench-gen` |
| 05 | SymbiYosys | `formal-verify`, `assertion-gen` |
| 06 | Quartus | `fpga-test-harness` |
| 07 | Python gen | **NEW: `constraint-gen`** |
| 08 | OpenSTA / custom | **NEW: `sdc-validator`** |
| 09 | Yosys | `synth-wrapper-gen`, `synth-doctor` |
| 10 | OpenSTA | `sta-review` |
| 11 | Fault | `dft-insert`, `atpg` |
| 12 | Yosys | `synth-doctor` |
| 13 | Yosys LEC | `equivalence-check` |
| 14 | OpenROAD | `placement-optimize` |
| 15 | OpenROAD + script | `cts-plan` |
| 16 | OpenROAD | `placement-optimize` |
| 17 | OpenROAD | `cts-plan` |
| 18 | OpenROAD | **NEW: `hold-fix`** |
| 19 | OpenROAD | — (routing) |
| 20 | OpenSTA | `sta-review` (MCMM) |
| 21 | OpenROAD PSM | `ir-drop-triage` |
| 22 | OpenROAD PSM | **NEW: `em-check`** |
| 23 | OpenROAD | — (antenna) |
| 24 | KLayout + Netgen | `drc-fix`, `lvs-triage` |
| 25 | OpenSTA / Yosys | **NEW: `power-analysis`** |
| 26 | Checklist script | `tapeout-checklist` |
| 27 | KLayout | — |
| 28 | Quartus + Python | `fpga-test-harness` |

### 需要新建的 5 個 skills

1. **`constraint-gen`** — 從 spec.json 自動產生 SDC + PVT matrix + MCMM
2. **`sdc-validator`** — SDC lint / constraint sanity check
3. **`hold-fix`** — Post-CTS hold fixing strategy
4. **`em-check`** — Electromigration analysis
5. **`power-analysis`** — Pre/post-layout 功耗估計

---

## Metrics（每步記錄）

```json
{
  "step": "20_post_route_sta",
  "iteration": 1,
  "timestamp": "2026-04-12T12:00:00",
  "status": "PASS",
  "metrics": {
    "wns_ns": 8.684,
    "tns_ns": 0,
    "hold_wns_ns": 0.234,
    "cells": 2701,
    "area_um2": 89200,
    "power_mw": null,
    "drc_violations": 0
  }
}
```

---

*Vibe-IC Standard IC Design Flow v1.0 — 2026-04-12*
*Input: Design Documents → Output: Production-ready GDS + FPGA SOF*
*33 steps, 4 stages, ECO closure loops, multi-corner multi-mode sign-off*
