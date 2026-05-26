---
layer: L2
ic: subservient
status: draft
written_at: 2026-05-22
sources:
  - reference/README.md
  - reference/doc/*.png (5 block diagrams — subservient.png / subservient_core.png / subservient_externals.png / subservient_fpga.png / subservient_tb.png)
  - reference_serv/doc/overview.rst + interface.rst
  - reference/subservient.core (FuseSoC dependency graph)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 描述 SoC 級功能與資料路徑語意,不描述模組階層內部訊號"
  r2_blackbox: "PASS — 引用對外公開文件(README + datasheet RST + block diagram PNG + FuseSoC manifest);未閱讀 RTL 內部"
  r3_multiple_correct: "PASS — Plugin 可自選 memory 介面、bus 介面、GPIO 實作"
---

# L2 — Architecture / Functional Spec

## 系統功能 (Functional Specification)

`subservient` 為**完整可獨立 tapeout 的 minimal RISC-V SoC**,核心由 SERV CPU + 共享 SRAM + GPIO peripheral 組成。

```
firmware(.hex)→ external memory preload → release reset
              → SERV CPU 從 RESET_PC 開始執行 → 透過共享 SRAM 取 instructions
              → 計算結果寫入 SRAM 或透過 GPIO/UART 輸出
```

## SoC 主要組成

| 組件 | 角色 | 來源 |
|---|---|---|
| **SERV core**(via servile wrapper) | RV32I bit-serial CPU(每 cycle 處理 1 個 bit) | reference_serv(沿用其 datasheet 規格) |
| **Shared SRAM** | 同時擔任 I-mem + D-mem + RF(register file);避免分立 memory 大幅省 area | subservient_core 內 |
| **GPIO peripheral** | 至少 1 個 GPIO pin;可作為 simple output debug bit 或 UART tx |
| **Servile wrapper** | 將 SERV core 與 SRAM-based RF 黏合;含 RF interface adapter |

## CPU ISA(SERV 規格借用)

| 屬性 | 值 |
|---|---|
| Base ISA | **RV32I**(必備) |
| 必含子集 | **Zifencei**(instruction fence) |
| 可選 extensions | C(compressed)、M(multiply/divide)、Zicsr(CSR + timer IRQ) |
| Architecture | **Bit-serial**(每 clock 處理 1 個位元;最大 latency = 32 cycles per 32-bit operation) |
| Reset Vector | `0x00000000`(預設;範圍 `0x00000000 ~ 0xFFFFFFFC`) |
| Reset Strategy | `"MINI"`(SERV 預設;最小必要 reset) |

Plugin 必須在 `declaration.json` 聲明採用的 ISA extension set(影響 firmware 兼容性與 area)。

## 記憶體配置 (Memory Map)

- 整顆 chip 共用**單一 SRAM** 提供 instruction memory + data memory + register file
- SRAM 大小由 `memsize` parameter 決定(預設 1024 bytes = 1 KiB)
- RF(register file)、I-mem 與 D-mem **共用同一 SRAM**;**具體位址分配由 Plugin 自選**(可上端、下端或交錯)— 此處不指定,屬 implementation choice
- Reset 時 SRAM 預期已被外部 preload(透過 FPGA tooling 或 ATE 寫入)

⚠️ **R1 注意**:上述 memory map 只規定「共用 SRAM」這個架構決策(spec-level),具體 RF 起始位址、I-mem 與 D-mem 邊界等屬 Plugin 設計自由度,不在 L2 spec 範圍。
- Reset 時 SRAM 預期已被外部 preload(透過 FPGA tooling 或 ATE 寫入)

## 同步行為

| 訊號 | 行為 |
|---|---|
| `i_clk` | 系統時脈,所有資料於上升沿同步取樣 |
| `i_rst` | **同步 reset, active-high**;assert 期間 SERV 內部 SERV-MINI 狀態歸零、SRAM 內容保留(由外部 preload) |
| Reset 解除 | 一個 cycle 內,SERV 從 `RESET_PC` 開始 fetch 第一條指令 |

## 演算法 / 結構選擇空間(Plugin 自由度)

Plugin 可自由選擇:
- ✅ SRAM 實作為 macro(若 PDK 提供)或 std-cell-based latch array
- ✅ Servile wrapper 內部 RF interface adapter 的時序
- ✅ GPIO 的 output drive strength / IO buffer
- ✅ 是否包含可選 SERV extensions(C / M / Zicsr) — Plugin 在 declaration.json 聲明

但 **SERV core 本身的 ISA 行為**(RV32I 指令語意、bit-serial 結構)是 RISC-V 國際標準 + SERV reference design 規定的事,**不允許**改變。

## 不在 L2 約束的事

- ❌ 不指定具體 module hierarchy(servile vs serv_top vs serv_rf_top — Plugin 自選)
- ❌ 不指定 SRAM 介面 protocol(generic 1-port read/write vs. dual-port — Plugin 自選)
- ❌ 不指定 GPIO 數量(預設 1 pin;若 PDK 條件允許可擴展)
- ❌ 不指定 latency cycle 數(bit-serial 本質就是 32 cycle per 32-bit op;不需再特別 spec)
