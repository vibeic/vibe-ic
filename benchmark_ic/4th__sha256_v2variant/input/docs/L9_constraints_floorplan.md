---
layer: L9
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - reference/data/sky130.tcl(原始 OpenLane config — 對外公開)
r1_r2_r3_compliance:
  r1: "PASS — 物理約束 target,不指定具體 placement 結果"
  r2: "PASS — 引用 reference OpenLane config tcl"
  r3: "PASS — 允許不同 floorplan / placement,只要落 target 內"
---

# L9 — Constraints / Floorplan

## 9.1 Synopsys Design Constraints (SDC)

### 9.1.1 主時脈

```sdc
set_units -time ns
create_clock [get_ports clk]  -name core_clock  -period 25.9
```

### 9.1.2 Multi-corner sign-off

| Std-cell library | `<PERIOD>` (ns) | 對應頻率 |
|---|---|---|
| `sky130_fd_sc_hd`(主)| **25.9** | ~38.6 MHz |

> 9-corner sign-off:每個 PVT corner(SS/TT/FF × min/nom/max RCX)setup + hold 全 ≥ 0。

### 9.1.3 I/O delay

- `set_input_delay` / `set_output_delay` 使用 clock period 的 20%(預設 ~5.2 ns)
- Plugin 可依需要 override

### 9.1.4 不在 SDC 約束的事
- ❌ False path / multi-cycle path(若有需要,Plugin 自加 + L7 證明等價)

## 9.1B Synthesis Constraints(非 SDC)

| 參數 | 值 | 來源 |
|---|---|---|
| `SYNTH_MAX_FANOUT` | **8** | reference data/sky130.tcl |

## 9.2 Floorplan

| 設定 | 值 | 來源 |
|---|---|---|
| `FP_CORE_UTIL` | **20** | reference data/sky130.tcl |
| `PL_TARGET_DENSITY` | **0.25** | reference data/sky130.tcl |

### 9.2.1 Pad 配置(對齊 L3)

| 邊 | 訊號 group |
|---|---|
| North (N) | `address[7:0]` + `write_data[31:0]` |
| South (S) | `read_data[31:0]` + `error` |
| East (E) | `clk`、`reset_n` |
| West (W) | `cs`、`we` |

### 9.2.2 Die size
- 不指定。由 Plugin 依 `FP_CORE_UTIL` 推算。

## 9.3 Power Network(PDN)

未明示者使用 **OpenLane / PDK 預設**。對 sha256 (~3 kGE) 規模足夠。

## 9.4 簽核 (Signoff) 目標

完整流程結束後須通過:

- ✅ 9-corner STA setup + hold ≥ 0
- ✅ DRC clean(magic + KLayout)
- ✅ LVS clean(magic + netgen)
- ✅ Antenna check clean
- ✅ Functional NIST FIPS-180-4 test vectors 100% PASS

## 9.5 不在 L9 約束的事
- ❌ Cell placement 具體座標
- ❌ Routing layer 分配
- ❌ Clock tree topology
- ❌ Buffer insertion 策略
