---
layer: L3
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - reference/src/rtl/sha256.v module header
  - reference/data/sky130.tcl (CLOCK_PORT = clk)
r1_r2_r3_compliance:
  r1: "PASS — port list 對外契約"
  r2: "PASS — 引用 module header + OpenLane config(對外規格)"
  r3: "PASS — IO cell 型別 / pad placement 由 Plugin 自選"
---

# L3 — External Interface

## Module 對外端口

| 訊號 | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `clk` | 1 | input | 系統時脈;所有資料於上升沿同步取樣 |
| `reset_n` | 1 | input | 同步 reset,**active-LOW**;assert(0)時內部歸 idle |
| `cs` | 1 | input | Chip select;`cs=1` 啟用 register file 存取 |
| `we` | 1 | input | Write enable;`we=1` 寫入 / `we=0` 讀取 |
| `address` | 8 | input | Register file address(範圍 `0x00 - 0x27`,完整 map 見 L5) |
| `write_data` | 32 | input | 寫入資料 |
| `read_data` | 32 | output | 讀出資料(只在 `cs=1` 且 `we=0` 時 valid) |
| `error` | 1 | output | 錯誤旗標(read undefined address 等);0 = no error |

## Reset 與 Boot 流程

1. 上電 → `reset_n = 0`(active-LOW assert)
2. 內部 state machine 進入 idle,所有 register 歸預設,STATUS.READY 設為 1
3. `reset_n = 1` → chip 可接受第一個 CTRL 命令

## Physical Pad Placement(供 OpenLane floorplan 參考)

| 邊 | 訊號 group |
|---|---|
| **North (N)** | `address[7:0]` + `write_data[31:0]`(寫入 bus,佔大邊) |
| **South (S)** | `read_data[31:0]` + `error`(讀出 bus) |
| **East (E)** | `clk`、`reset_n` |
| **West (W)** | `cs`、`we`(控制訊號) |

> Pad ordering 同一邊內由 Plugin 自選;只要符合邏輯區隔即可。

## 不在 L3 約束的事

- ❌ IO cell 型別(由 PDK 預設)
- ❌ ESD strategy(由 PDK 預設)
- ❌ Pad sequence 同一邊內順序
- ❌ Optional bus protocol wrapper(Plugin 可自行加 Wishbone / APB / AXI4-Lite wrapper,但不強制)
