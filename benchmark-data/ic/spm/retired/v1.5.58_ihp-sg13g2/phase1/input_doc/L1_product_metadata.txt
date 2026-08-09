---
layer: L1
ic: spm
status: draft
written_at: 2026-05-22
sources:
  - reference/config.json
  - reference/src/spm.sdc
  - reference/pin_order.cfg
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅描述產品意圖,不描述實作"
  r2_blackbox: "PASS — 僅引用對外可觀察設定(PDK targets, clock period, floorplan target)"
  r3_multiple_correct: "PASS — 允許多種合格實作"
---

# L1 — Product & Tapeout Metadata

## 產品基本資訊

| 欄位 | 值 |
|---|---|
| 產品名稱 (product_name) | `spm` |
| 產品分類 (product_family) | digital arithmetic primitive |
| 功能一句話描述 | 可配置位寬的 signed 整數乘法器,並行 multiplicand × 序列 multiplier → 序列 product |
| 應用情境 | 教學/驗證用 standard-cell 數位 IP,可作為 SoC 內 streaming arithmetic engine |
| 設計起源 | OpenLane reference design;**已多次 sign-off 通過、可作為 production-ready 對照組** |

## Tapeout 目標

| 欄位 | 值 |
|---|---|
| 目標 PDK family | open-source(SKY130 主目標,GF180MCU 為次目標) |
| Target Std-Cell Libraries (SKY130) | `sky130_fd_sc_hd`(主)、`sky130_fd_sc_hdll`、`sky130_fd_sc_hs`、`sky130_fd_sc_ls`、`sky130_fd_sc_ms` |
| Target Std-Cell Libraries (GF180MCU) | `gf180mcu_*`(任一 corner library) |
| Target clock period — SKY130 通用 | 10 ns (100 MHz) |
| Target clock period — SKY130 high-speed (`sky130_fd_sc_hs`) | 8 ns (125 MHz) |
| Target clock period — GF180MCU | 24 ns (~41.7 MHz) |
| Floorplan core utilization (SKY130) | 45% |
| Floorplan core utilization (GF180MCU) | 40% |
| Floorplan placement target density (GF180MCU) | 0.5 |
| PDN vertical / horizontal offset | 7 / 7 |
| 特殊 PDN 處理 | `FP_PDN_SKIPTRIM = true`(略過 power-strap trimming) |

## 量產 (Production-readiness) 期望

- 必須在指定 PDK 上 sign-off:DRC clean、LVS clean、STA met
- 必須對外時序滿足 L9 SDC 約束
- area / power 應落在「**reference 對照組 ±30%**」範圍內(若超出需 justify)
- 通過 functional equivalence check(對照 reference RTL 的 truth table)

## 不在 L1 約束的事

- ❌ 不指定 die size(Plugin 可自選)
- ❌ 不指定 pad ring 數量(由 L3 port list 自然決定)
- ❌ 不指定 routing layer 數(由 PDK 預設)
