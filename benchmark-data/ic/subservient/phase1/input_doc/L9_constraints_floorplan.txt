---
layer: L9
ic: subservient
status: draft
written_at: 2026-05-22
sources:
  - reference/data/sky130.tcl (CLOCK_PERIOD = 10)
  - reference/data/openlane_common.tcl (CLOCK_PORT = i_clk)
  - reference/data/gf180.tcl (TBV — file exists, content not yet inspected)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 描述物理約束目標,不描述具體 placement 結果"
  r2_blackbox: "PASS — 引用工具設定檔(對外規格)而非 OpenLane run 內部產物"
  r3_multiple_correct: "PASS — 允許不同 floorplan / placement,只要落在 target 內"
---

# L9 — Constraints / Floorplan

## 9.1 Synopsys Design Constraints (SDC)

### 9.1.1 主時脈定義

```sdc
set_units -time ns
create_clock [get_ports i_clk]  -name core_clock  -period <PERIOD>
```

### 9.1.2 各 PDK 對應的 `<PERIOD>`

| PDK / library | `<PERIOD>` (ns) | 對應頻率 |
|---|---|---|
| `sky130_fd_sc_hd`(主) | **10** | 100 MHz |
| `sky130_fd_sc_hdll` / `_ls` / `_ms` | 10(預設) | 100 MHz |
| `sky130_fd_sc_hs` | 8(預設) | 125 MHz |
| `gf180mcu_*` | **20** | 50 MHz |

> **Multi-corner sign-off**:每個 library 須在 SS / TT / FF 三 corner 全部簽核通過。Timing derating 使用 OpenLane / PDK 預設(無須在 SDC 明寫)。

### 9.1.3 I/O delay
- `set_input_delay` / `set_output_delay`:使用 **clock period 的 20%** 作為預設(例:`sky130_fd_sc_hd` 10 ns → 2 ns I/O delay)
- Plugin 可依需要 override;若 override,須於 declaration.json 註記

### 9.1.4 不在 SDC 約束的事
- ❌ False path / multi-cycle path(若 SRAM macro 跨 cycle 取資料,Plugin 可自加,但須在 L7 證明等價)

## 9.1B Synthesis Fanout Limit(非 SDC,合成階段約束)

對 SoC-class 設計,fanout 限制由 OpenLane / PDK 預設處理(無特殊覆寫;預設值適用於 ~2-3 kGE 規模設計)。

## 9.2 Floorplan

### 9.2.1 Core Utilization

| PDK | `FP_CORE_UTIL` | `PL_TARGET_DENSITY` |
|---|---|---|
| SKY130 | 35-45%(依 SRAM 佔比浮動;Plugin 自選範圍) | 預設 |
| GF180MCU | 30-40%(densities slightly lower) | 0.5 |

> SRAM(1 KiB)在 std-cell composed 配置下,佔總 core area 約 50-70%;Plugin 應預留足夠 routing track。

### 9.2.2 Pad 配置(L3 對齊)

| 邊 | 訊號 group |
|---|---|
| North (N) | SRAM data bus(寬度大,routing 友善) |
| South (S) | SRAM addr + control |
| East (E) | `i_clk`、`i_rst` |
| West (W) | GPIO pin(s) |

> Pad sequence 在同一邊內由 Plugin 自選;只要符合邏輯區隔即可。

### 9.2.3 Die size
- 不指定。由 Plugin 依 `FP_CORE_UTIL` 與 SRAM 佔比推算決定。

## 9.3 Power Network (PDN)

| 設定 | 值 |
|---|---|
| `FP_PDN_VOFFSET` | 7(對齊 SKY130 預設) |
| `FP_PDN_HOFFSET` | 7 |
| Power straps width / layer | OpenLane / PDK 預設 |
| 核心 ring + power ring | OpenLane / PDK 預設 |

> 未列項目使用 **OpenLane / PDK 預設**;對 subservient(~2-3 kGE + 1 KiB SRAM)規模足夠。

## 9.4 簽核 (Signoff) 目標

完整流程結束後須通過:

- ✅ STA 在 9.1 列舉的所有 corner 全 setup + hold ≥ 0
- ✅ DRC clean(magic + KLayout)
- ✅ LVS clean(magic + netgen)
- ✅ Antenna check clean
- ✅ Power network 無 disconnected port
- ✅ Firmware(blinky + hello)gate-level simulation 通過

## 9.5 不在 L9 約束的事
- ❌ Cell placement 具體座標
- ❌ Routing 具體 layer 分配
- ❌ Clock tree topology
- ❌ Buffer insertion 策略
- ❌ SRAM macro 具體 placement(若選 macro)— 由 Plugin floorplan 決定
