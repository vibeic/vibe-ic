---
layer: L9
ic: spm
status: draft
written_at: 2026-05-22
sources:
  - reference/src/spm.sdc (clock + period)
  - reference/config.json (PDK + floorplan target + PDN setting)
  - reference/pin_order.cfg (pad sides)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅描述物理約束目標,不描述具體 placement 結果"
  r2_blackbox: "PASS — 引用工具設定檔(對外規格)而非 OpenLane run 內部產物"
  r3_multiple_correct: "PASS — 允許不同 floorplan / placement,只要落在 target 內"
---

# L9 — Constraints / Floorplan

## 9.1 Synopsys Design Constraints (SDC)

### 9.1.1 主時脈定義

```sdc
set_units -time ns
create_clock [get_ports clk]  -name core_clock  -period <PERIOD>
```

### 9.1.2 各 PDK / library 對應的 `<PERIOD>`

| Std-cell library | `<PERIOD>` (ns) | 對應頻率 |
|---|---|---|
| `sky130_fd_sc_hd` | 10 | 100 MHz |
| `sky130_fd_sc_hdll` | 10 | 100 MHz |
| `sky130_fd_sc_hs` | 8 | 125 MHz |
| `sky130_fd_sc_ls` | 10 | 100 MHz |
| `sky130_fd_sc_ms` | 10 | 100 MHz |
| `gf180mcu_*` | 24 | ~41.7 MHz |

> **Multi-corner sign-off**:每個 library 均須在 **SS(slow / worst-case)、TT(typical)、FF(fast)三 corner** 全部 sign-off 通過。Timing derating 使用 OpenLane / PDK 預設值(無須在 SDC 明寫)。

### 9.1.3 I/O delay
- `set_input_delay` / `set_output_delay`:使用 **clock period 的 20%** 作為預設(例:`sky130_fd_sc_hd` 10 ns → 2 ns I/O delay)
- Plugin 可依需要 override;若 override,須於 declaration.json 註記

### 9.1.4 不在 SDC 約束的事
- ❌ False path / multi-cycle path(Plugin 若有需要可自加,但須在 L7 證明等價)

## 9.1B Synthesis Fanout Limit(非 SDC,合成階段約束)

下表為**合成階段**的 fanout 限制(對應 OpenLane 的 `MAX_FANOUT_CONSTRAINT`),**不屬於** SDC timing constraint,而是合成器 hint:

| library | `MAX_FANOUT_CONSTRAINT` |
|---|---|
| `sky130_fd_sc_ls` | 5 |
| `gf180mcu_*` | 4 |
| 其他 | 工具預設 |

## 9.2 Floorplan

### 9.2.1 Core Utilization

| PDK family | `FP_CORE_UTIL` | `PL_TARGET_DENSITY` |
|---|---|---|
| SKY130 | 45% | 工具預設 |
| GF180MCU | 40% | 0.5 |

### 9.2.2 Pad 配置

| 邊 | 訊號 | 備註 |
|---|---|---|
| North (N) | `x[size-1:0]` 全部位元 | 北邊 pad 之間最小間距 0.1 µm |
| South (S) | `rst` | |
| East (E) | `clk` | |
| West (W) | `p`、`y` | 輸出與序列輸入相鄰,西側順序由 Plugin 自選 |

### 9.2.3 Die size
- 不指定。由 Plugin 依照 `FP_CORE_UTIL` 與 pad ring 推算決定。

## 9.3 Power Network (PDN)

| 設定 | 值 |
|---|---|
| `FP_PDN_VOFFSET` | 7 |
| `FP_PDN_HOFFSET` | 7 |
| `FP_PDN_SKIPTRIM` | true(略過 PDN trimming pass) |
| Power straps layer | 由 PDK 預設 |

> 未列項目(power straps width、core ring、power ring、density 等)使用 **OpenLane / PDK 預設**;對 spm-class 小設計足夠 sign-off 通過。

## 9.4 簽核 (Signoff) 目標

完整流程結束後須通過:

- ✅ STA 在 9.1 列舉的所有 corner met
- ✅ DRC clean(magic + KLayout)
- ✅ LVS clean(magic + netgen)
- ✅ Antenna check clean
- ✅ Power network 無 disconnected port

## 9.5 不在 L9 約束的事
- ❌ Cell placement 具體座標
- ❌ Routing 具體 layer 分配
- ❌ Clock tree topology
- ❌ Buffer insertion 策略
