---
layer: L1
ic: subservient
status: draft
written_at: 2026-05-22
sources:
  - reference/README.md
  - reference/subservient.core (FuseSoC manifest)
  - reference/data/sky130.tcl + openlane_common.tcl
  - reference_serv/doc/overview.rst + interface.rst (借用作 SERV sub-module spec)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 描述 SoC-level 產品意圖與 tapeout target,不描述模組階層或實作"
  r2_blackbox: "PASS — 引用 README + datasheet + FuseSoC manifest + OpenLane config(均對外公開規格);未閱讀 RTL"
  r3_multiple_correct: "PASS — 允許 Plugin 選擇不同 memory 配置 / cell 階層"
---

# L1 — Product & Tapeout Metadata

## 產品基本資訊

| 欄位 | 值 |
|---|---|
| product_name | `subservient` |
| product_family | minimal RISC-V SoC(MCU class) |
| 功能一句話描述 | Minimal SERV-based RISC-V SoC,單一共享 SRAM(I-mem + D-mem + RF)+ GPIO peripheral,專為 ASIC tapeout(OpenMPW shuttle 級規模)設計 |
| 應用情境 | OpenMPW / chipIgnite shuttle tapeout、超小規模 embedded MCU、教學用 RISC-V MCU、IoT minimal compute node |
| 設計起源 | award-winning SERV core(world's smallest RISC-V CPU)+ subservient SoC wrapper;**已實際進入 OpenMPW shuttle tapeout** |

## Tapeout 目標

| 欄位 | 值 |
|---|---|
| 目標 PDK | open-source(SKY130 primary;GF180MCU secondary) |
| Target Std-Cell Library (SKY130) | `sky130_fd_sc_hd`(主) |
| Target Std-Cell Library (GF180MCU) | `gf180mcu_*`(secondary) |
| Target clock period — SKY130 | **10 ns (100 MHz)** |
| Target clock period — GF180MCU | **20 ns (50 MHz)**(已從 reference/data/gf180.tcl 確認:CLOCK_PERIOD=20) |
| Target memsize(SRAM) | **1024 bytes 預設**(可參數化;典型 256 / 1024 / 2048) |
| Tapeout status | 已在 OpenMPW shuttle 跑過 sign-off;baseline 預期可重現 production-ready GDS |

## 面積估算(來自 SERV overview.rst)

| 平台 | LUT/FF | 等效 |
|---|---|---|
| Lattice iCE40 | 198LUT/164FF | — |
| Cyclone10LP | 239LUT/164FF | — |
| Artix-7 | 125LUT/164FF | — |
| **CMOS** | — | **~2.1 kGE**(excluding RF) |

整個 subservient SoC 包含 1 KiB SRAM,SRAM 通常以 macro 或 std-cell array 佔比超過邏輯部分,實際 die area 由 baseline 跑出後決定。

## 量產 (Production-readiness) 期望

- 必須在指定 PDK 上 sign-off:DRC clean、LVS clean、antenna clean
- STA 在 SS/TT/FF 9-corner 全 setup + hold ≥ 0
- area / power 落在 baseline ±30% 容差(asymmetric,只限 upper bound,參照 spm pilot L7 修正)
- functional:能成功跑 `blinky.hex` / `hello.hex` firmware,GPIO 輸出符合預期(serial UART pattern over GPIO 也支援)

## 不在 L1 約束的事

- ❌ 不指定 die size(由 Plugin 依 floorplan target 推算)
- ❌ 不指定 SRAM 是 macro 還是 std-cell composed(由 Plugin 自選)
- ❌ 不指定具體 RV ISA extensions(預設 RV32IZifencei;C/M/Zicsr 可選,Plugin 在 declaration.json 聲明)
