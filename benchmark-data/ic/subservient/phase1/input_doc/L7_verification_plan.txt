---
layer: L7
ic: subservient
status: draft
written_at: 2026-05-22
sources:
  - reference/README.md (simulation targets + firmware test files)
  - reference/sw/blinky.S / hello.S (firmware test cases for functional verification)
  - reference/data/sky130.tcl (clock + corner targets)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 只列驗證目標與覆蓋率要求,不列具體 testbench 寫法"
  r2_blackbox: "PASS — 不引用 reference RTL 內部結構;使用 firmware-level 對外可觀察行為"
  r3_multiple_correct: "PASS — 採 functional + 時序 + 物理判定;不要求 GDS 像素一致"
---

# L7 — Verification Plan

## 7.0 Plugin Declaration Requirements

Plugin 在開始 RTL 設計前,**必須**於 `plugin_output/declaration.json` 聲明:

| 欄位 | 必填 | 範例值 |
|---|---|---|
| `top_module` | ✅ | `"subservient"` (含 GPIO) 或 `"subservient_core"` (no GPIO) |
| `isa_extensions` | ✅ | `["I", "Zifencei"]` 必含;`["C", "M", "Zicsr"]` 任選擴展 |
| `memsize_bytes` | ✅ | `1024`(primary)或 `256`/`512`/`2048` |
| `reset_polarity` | ✅ | `"active_high"` |
| `clock_port_name` | ✅ | `"i_clk"`(來自 openlane_common.tcl) |
| `sram_interface_protocol` | ✅ | 例:`"generic_8bit_addr_data_we"` |
| `gpio_pin_count` | ✅ | 整數 ≥ 1 |
| `rf_storage` | ✅ | `"shared_sram"`(本 chip 設計選擇) |

## 7.1 Functional Verification

### 7.1.1 Primary functional tests

**透過 firmware 執行驗證**:用 reference/sw/ 提供的 firmware hex 跑模擬與 FPGA 板測:

| Test firmware | 預期結果 | 涵蓋範圍 |
|---|---|---|
| `blinky.hex` | GPIO 輸出規則性 toggle | I-mem fetch、D-mem store、簡單 loop、GPIO write |
| `hello.hex` | GPIO 輸出 "Hello" UART 字串(115200 baud rate by firmware bit-banging) | I-mem fetch、字串資料 read、循環、計時迴圈 |

### 7.1.2 RV32I 指令覆蓋

| Test class | 必過判定 |
|---|---|
| 整套 RV32I 指令(40+ 條)單元測試 | 100% PASS(可用 RISC-V Compliance suite 或 SERV 內附 testbench) |
| Zifencei 指令 | PASS |
| (若 Plugin 選 M) Mul/Div 指令 | PASS |
| (若 Plugin 選 Zicsr) CSR access + timer IRQ | PASS |
| (若 Plugin 選 C) 16-bit compressed 指令 | PASS |

### 7.1.3 Reset 與 Boot

| 情境 | 預期 |
|---|---|
| Reset 解除後 N cycle 內取得第一條 instruction | N ≤ SERV-MINI 策略決定的最大 boot latency(典型 < 10 cycle) |
| Reset assert 中 SRAM 內容保留 | ✅ |
| `i_rst` glitch 不應導致 instruction fetch race | ✅(同步 reset 保證) |

## 7.2 Timing Verification (STA — Multi-corner)

| Corner family | Clock period | 必過 |
|---|---|---|
| `sky130_fd_sc_hd` SS / TT / FF | 10 ns | setup + hold ≥ 0 |
| `gf180mcu_*` SS / TT / FF | 24 ns(TBV) | setup + hold ≥ 0 |

> Hold-fix 允許工具(OpenLane)自動 buffer-based 修復;最終 hold slack ≥ 0 即視為通過。

## 7.3 Physical Verification

| 項目 | 要求 |
|---|---|
| DRC | 100% clean(magic + KLayout) |
| LVS | 100% clean(magic + netgen) |
| Antenna check | 100% clean |
| Power network | 無 disconnected ports |
| GDS XOR(magic vs klayout) | 0 difference |

## 7.4 Quality Metrics (與 reference baseline 對照)

> ⚠️ **Baseline status (pilot finding)**:reference subservient 在 LibreLane v2.4.12 / sky130_fd_sc_hd / 10 ns 跑通 DRC/LVS/Antenna 但 **STA 有 2/9 corner setup 違規**(`max_ss_100C_1v60` slack -0.226 ns,`nom_ss_100C_1v60` slack -0.103 ns)。意思:**reference 自己也不是「完美 sign-off」狀態**。完整 snapshot 見 `baseline/baseline_metrics.json`。

### 7.4.1 Baseline 實測 (top=`subservient`, memsize=1024, sky130_fd_sc_hd, TT corner)

| 指標 | Baseline |
|---|---|
| stdcell count | **1,502** |
| stdcell area | **12,775 µm²** |
| die area | **34,269 µm²** |
| total power (TT) | **2.26 mW** |
| setup WS @ worst corner (max_ss) | **-0.226 ns** ⚠️(SS 違規) |
| setup WS @ TT | +3.12 ns |
| hold WS @ worst corner (min_ff) | +0.10 ns |
| max_slew violations | 8 |
| max_fanout violations | 13 |
| antenna / DRC / LVS / XOR | 0 / clean / clean / 0 |

### 7.4.2 Sign-off Acceptance Range

> Plugin 應該**至少匹配** baseline(area / power 在 baseline × 1.3 內);若 Plugin **修好 SS corner** + **修好 max_slew/max_fanout violations**,則屬於 Plugin 對 reference 的工程改進。

| 指標 | 接受區間 | sign-off gate |
|---|---|---|
| stdcell count(資訊性) | baseline × [0.5, 2.0] = [751, 3004] | ❌ 否 |
| stdcell area | (0, baseline × 1.3] = ≤ 16,608 µm² | ✅ |
| total power (TT) | (0, baseline × 1.3] = ≤ 2.94 mW | ✅ |
| area × Fmax(主 PPA) | baseline × [0.7, 1.5] | ✅ |
| Fmax @ TT | ≥ 1/(target × 1.05) = ≥ 95 MHz | ✅ |
| setup slack(全 9 corner) | ≥ 0(**Plugin 必須優於 baseline 的 -0.226 ns**) | ✅ |
| hold slack(全 9 corner) | ≥ 0 | ✅ |
| DRC / LVS / antenna | clean | ✅ |
| max_slew / max_cap / max_fanout viols | **0**(Plugin 必須優於 baseline 的 8+13) | ✅ |
| Firmware functional (blinky + hello) | 100% PASS | ✅ |

## 7.5 不在 L7 約束的事

- ❌ 具體 testbench framework(cocotb / Verilator / iverilog 任選)
- ❌ 是否做 gate-level simulation(建議,非強制)
- ❌ 是否做 power-aware leakage corner(僅在做 production 才強制)
