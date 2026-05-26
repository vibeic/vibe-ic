---
layer: L7
ic: spm
status: draft
written_at: 2026-05-22
sources:
  - reference/config.json (clock targets, PDK list)
  - reference/src/spm.sdc (timing constraint)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 只列驗證目標與覆蓋率要求,不列具體 testbench 寫法"
  r2_blackbox: "PASS — 不引用 reference 內部結構"
  r3_multiple_correct: "PASS — 驗證以 functional equivalence + 時序+物理為準,不要求 GDS 像素一致"
---

# L7 — Verification Plan

## 7.0 Plugin Declaration Requirements

Plugin 在開始 RTL 設計前,**必須**於 `plugin_output/declaration.json` 聲明下列項目;L7 比對程序須讀此檔以正確配對 reference 輸出:

| 欄位 | 必填 | 範例值 | 說明 |
|---|---|---|---|
| `bit_order` | ✅ | `"LSB_first"` / `"MSB_first"` | serial 輸入/輸出位元順序 |
| `reset_polarity` | ✅ | `"active_high"` | 必須與 L3 一致 |
| `latency_cycles` | ✅ | 整數 | reset 解除後到第一個有效 product bit 的 cycle 數 |
| `integer_encoding` | ✅ | `"signed_2c"` / `"unsigned"` | 以 baseline truth-table 驗證為準 |
| `multiplier_algorithm` | ⚠️ 資訊性 | 例 `"carry_save_bit_serial"` | 純資訊,非 sign-off 條件 |
| `size_param` | ✅ | `32`(primary)/ `8 / 16`(secondary) | Plugin 跑的位寬設定 |

## 7.1 Functional Verification

### 7.1.1 主要驗證目標
證明 `p_serial_stream = signed_2c_mul(x, y_serial_stream)` 對所有合法 `(x, y)` 組合成立。

### 7.1.2 測試覆蓋要求

**Functional 等價是 binary PASS/FAIL,不能用百分比表達。** 覆蓋率(toggle / branch)是次要資訊指標,非 sign-off gate。

| 測試類別 | 判定 | 範圍 |
|---|---|---|
| Random multiplication functional equivalence | **100% PASS (binary)** | 隨機 ≥ 10000 組 `(x, y)`,**全部**對 golden model 一致 |
| 邊角 (corner) — operand | 100% PASS | `x = 0`、`y_stream = 0`、`x = MAX_POS`、`x = MIN_NEG`、`y = MAX_POS`、`y = MIN_NEG`、`x = -1`、`y = -1` |
| 邊角 — 連續輸入 | 100% PASS | 連續多筆乘法計算之間,內部狀態應正確 reset 或銜接 |
| Reset 行為 | 100% PASS | reset 期間 / reset 解除瞬間 / reset 在計算進行中 assert 三種情況 |
| Toggle / branch coverage(資訊性) | ≥ 95% | 同 random run;非 sign-off gate |

### 7.1.4 Sign-off Levels by `size` Parameter

| Level | `size` | sign-off 必過 | 備註 |
|---|---|---|---|
| **Primary**(必過,tape-out gate) | 32 | ✅ 全 corner + 全 quality metric + functional 100% | reference baseline 對應位寬 |
| **Secondary**(建議過,不阻擋 tape-out) | 8 / 16 | functional 100% 一致即可 | robustness 加值,不要求 STA / DRC sign-off |

### 7.1.3 Reference 比對
- **Golden model**:Python / C 直接計算 `x * y`(signed 2's complement);Plugin 產出 RTL 的 serial 輸出位元流,依照 Plugin 在 L2 聲明的位元順序(LSB-first 或 MSB-first)組回整數後比對
- **Formal equivalence check (optional but recommended)**:若 Plugin RTL 與 reference RTL 對於相同 `(size, clk, rst, x, y)` 序列產出相同 `p` 序列,則 formally 等價

## 7.2 Timing Verification (STA)

### 7.2.1 必要的 STA 通過條件

| PDK Corner | Clock Period | Setup | Hold |
|---|---|---|---|
| `sky130_fd_sc_hd` | 10 ns | met | met |
| `sky130_fd_sc_hdll` | 10 ns | met | met |
| `sky130_fd_sc_hs` | 8 ns | met | met |
| `sky130_fd_sc_ls` | 10 ns | met | met(MAX_FANOUT_CONSTRAINT = 5) |
| `sky130_fd_sc_ms` | 10 ns | met | met |
| `gf180mcu_*` | 24 ns | met | met(MAX_FANOUT_CONSTRAINT = 4) |

### 7.2.2 失敗判定
任一 corner 出現 negative slack(setup or hold)即不可接受。

> 允許工具(OpenLane)自動 buffer-based hold-fix(CTS 後常規流程);只要最終 hold slack ≥ 0 即視為通過。

## 7.3 Physical Verification

| 項目 | 要求 |
|---|---|
| DRC | 100% clean(magic + KLayout 兩種引擎均通過) |
| LVS | 100% clean(magic + netgen) |
| Antenna check | 100% clean |
| Power network | 無 disconnected ports |

## 7.4 Quality Metrics (與 reference baseline 對照)

> ✅ **Baseline status**:`size = 32` / `sky130A` / `sky130_fd_sc_hd` / TT corner / 10 ns 已跑通 LibreLane v2.4.12 sign-off(43 秒,DRC/LVS/Antenna 全 clean)。完整 metric snapshot 見 `baseline/baseline_metrics.json`。

### 7.4.1 Baseline 數值 (size = 32, sky130_fd_sc_hd, TT corner, 10 ns)

| 指標 | Baseline 實測 |
|---|---|
| stdcell count | **461** |
| stdcell area | **3,642.24 µm²** |
| die area | **11,317.8 µm²** |
| core area | **8,051.47 µm²** |
| total power | **1.31 mW** |
| setup WNS | +6.01 ns(slack) |
| hold WNS | +0.11 ns(slack) |
| 估算 Fmax @ TT | **~250 MHz** |
| wirelength | 5,836 µm |
| antenna / DRC / LVS / max-slew/cap/fanout | 全 0(clean) |

### 7.4.2 Sign-off Acceptance Range

> **Asymmetric range rationale (post-pilot v1 fix)**:area / power 為「**越低越好**」指標,只設 upper bound(超出 = 設計太肥/太耗);若 Plugin 用更優演算法做得更小/更省電,**應視為 sign-off 加分而非失敗**。下限只保留在「雙向指標」(Fmax、area×Fmax)。

| 指標 | 接受區間 | 絕對門檻 (baseline = spm pilot) | 是否 sign-off gate |
|---|---|---|---|
| stdcell count(資訊性,跨演算法不可比) | baseline × [0.5, 2.0] | [230, 920] | ❌ 否(僅資訊) |
| stdcell area | **(0, baseline × 1.3]** | ≤ 4,735 µm² | ✅ 是 |
| total power (TT corner) | **(0, baseline × 1.3]** | ≤ 1.70 mW | ✅ 是 |
| **area × Fmax**(主 PPA 指標,雙向) | baseline × [0.7, 1.5] | — | ✅ 是 |
| Maximum operating frequency | ≥ 1/(target clock × 1.05) | ≥ 95 MHz @ 10 ns target | ✅ 是 |
| setup / hold slack(全 corner) | ≥ 0 | ≥ 0 ns | ✅ 是 |
| DRC / LVS / antenna | clean | clean | ✅ 是 |

> **R3 釐清**:stdcell count 容差放寬至 ±100%,因為跨演算法(Wallace / ripple / Booth)的 cell count 本就不可比;area × Fmax 為更標準化的跨演算法主指標。**不**要求 GDS 像素一致或 cell 階層命名一致。

## 7.5 不在 L7 約束的事

- ❌ 具體 testbench framework(cocotb / Verilator / iverilog 任選)
- ❌ Assertion 寫法(SVA / PSL 任選)
- ❌ 覆蓋率收集工具
- ❌ 是否做 gate-level simulation(建議但非強制)
