---
layer: L3
ic: subservient
status: draft
written_at: 2026-05-22
sources:
  - reference/README.md ("exposes a port intended to be connected to an SRAM" + GPIO pin)
  - reference/doc/subservient_externals.png (interface block diagram)
  - reference/data/openlane_common.tcl (CLOCK_PORT = i_clk)
  - reference/data/sky130.tcl (CLOCK_PERIOD = 10 ns)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅描述對外 chip-level port 與 pad placement"
  r2_blackbox: "PASS — 引用 README 描述 + OpenLane config + externals block diagram;未閱讀 RTL"
  r3_multiple_correct: "PASS — IO cell 型別、pad sequence、SRAM 介面具體 protocol 由 Plugin 自選"
---

# L3 — External Interface

## Module 對外端口

> 來源:`reference/README.md` 描述「`subservient` exposes a port intended to be connected to an SRAM, and a GPIO pin」,加上 `openlane_common.tcl` 確認 `CLOCK_PORT = i_clk`。具體訊號表如下(基於 SoC top 對外契約;Plugin 自行決定每個 group 的具體位寬與 sub-port 數量):

| Port group | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `i_clk` | 1-bit | input | 系統時脈;所有資料於上升沿同步 |
| `i_rst` | 1-bit | input | 同步 reset,**active-high**;assert 後一個 cycle SERV 內部歸零 |
| **SRAM port group** | (groupings see below) | bidirectional | 連接外部 SRAM(I-mem + D-mem + RF 共用) |
| `o_gpio` | ≥ 1-bit | output | GPIO 輸出;預設 1 pin,可作為 simple debug bit 或 UART tx |
| (optional) `i_gpio` | optional | input | GPIO 輸入(若 Plugin 採雙向 GPIO) |

### SRAM port group sub-ports(典型實作)

下列為「典型 SRAM port 細項」,但**具體訊號名稱與排列由 Plugin 在 declaration.json 聲明**,只要能滿足與外部 SRAM 連接即可:

| Sub-port | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `o_sram_addr` | ~10-bit(對應 `memsize = 1024 bytes`,8-bit 每位元組 → 10-bit address) | output | 位址 |
| `o_sram_data` (or `o_sram_wdata`) | 8-bit | output | 寫入資料(typical) |
| `i_sram_data` (or `i_sram_rdata`) | 8-bit | input | 讀取資料(typical) |
| `o_sram_we` | 1-bit | output | 寫入啟用 |
| `o_sram_cyc` | 1-bit | output | 匯流排 cycle 有效 |

## Design Parameters

| Parameter | 預設值 | 合法範圍 |
|---|---|---|
| `memsize` | 1024 | 256 / 512 / 1024 / 2048(以 byte 為單位) |
| `RESET_PC` | `0x00000000` | `0x00000000` ~ `0xFFFFFFFC`(SERV 規格) |
| `WITH_CSR` | 1(預設,enable timer + IRQ) | 0 / 1 |

## Physical Pad Placement(供 OpenLane floorplan 參考)

對齊 reference 的 OpenLane config 預期 pad 排列(若 reference 未明示則由 Plugin 自選,只要符合下列邏輯區隔):

| 邊 | 包含訊號 |
|---|---|
| **North (N)** | SRAM data bus(寬度大,放主要一邊以利 routing) |
| **South (S)** | SRAM addr + control(we / cyc) |
| **East (E)** | `i_clk` / `i_rst` |
| **West (W)** | GPIO pin(s) |

## Reset Polarity 與 Boot 流程

1. 上電 → `i_rst = 1`(synchronous active-high reset assert)
2. 外部 tester / FPGA framework 寫入 firmware hex 到 SRAM(`memsize` bytes 範圍)
3. `i_rst = 0` → SERV 從 `RESET_PC` 開始 fetch 第一條指令
4. SERV 透過 SRAM port 取 instruction → 執行 → write back 到 SRAM 或 GPIO

## 不在 L3 約束的事

- ❌ IO cell 型別與 ESD 策略(PDK 預設)
- ❌ 同一邊內 pad 順序(只要符合邏輯區隔)
- ❌ SRAM bus protocol 具體名稱(Wishbone-classic / generic / custom — Plugin 自選並 declare)
- ❌ Reset 觸發後 boot 真正開始指令執行的精確 cycle 數(SERV "MINI" 策略決定)
