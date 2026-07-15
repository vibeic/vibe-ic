---
layer: L1
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - reference/README.md
  - reference/data/sky130.tcl
  - reference/Releases.md
  - NIST FIPS-180-4 SHA-2 family standard(公開規格)
r1_r2_r3_compliance:
  r1: "PASS — 產品意圖 + tapeout target,不含實作細節"
  r2: "PASS — 引用 README + OpenLane config + NIST 標準(對外公開規格)"
  r3: "PASS — 多種 SHA-256 實作演算法皆允許(iterative / unrolled / pipelined)"
---

# L1 — Product & Tapeout Metadata

## 產品基本資訊

| 欄位 | 值 |
|---|---|
| product_name | `sha256` |
| product_family | cryptographic hash accelerator |
| 功能一句話描述 | NIST FIPS-180-4 SHA-256 + SHA-224 雙模式硬體 hash 引擎,memory-mapped register 介面 |
| 應用情境 | IoT / 嵌入式 security MAC、blockchain mining helper、authenticated storage、firmware integrity check |
| 設計起源 | secworks/sha256(award-winning open-source crypto IP,ISC license,**OpenLane SKY130 CI 持續 PASS**) |

## Tapeout 目標

| 欄位 | 值 |
|---|---|
| 目標 PDK | SKY130 主目標(已有 reference SKY130 sign-off CI) |
| Target Std-Cell Library | `sky130_fd_sc_hd` |
| Target clock period | **25.9 ns (~38.6 MHz)** — 對應 reference OpenLane config;ASIC tape-out 過往可達 250 MHz |
| Floorplan core utilization | 20% |
| Placement target density | 0.25 |
| Synthesis MAX_FANOUT | 8 |

## 效能參考(來自 README)

| 平台 | 數值 |
|---|---|
| ASIC 250 MHz | 達成過 |
| Altera Cyclone V LUTs | 2811 |
| Xilinx Artix-7 LUTs | 2012 |
| **每個 512-bit block 計算延遲** | **66 cycles** |

## 量產(production-readiness)期望

- DRC / LVS / antenna 全 clean
- 9-corner STA 全 setup + hold ≥ 0
- 通過 NIST FIPS-180-4 標準 test vector(7 個 official test vectors:single-block + multi-block + 1M repeats)
- area / power 落在 reference baseline ±30% 區間(asymmetric upper bound,對齊先前 pilot L7 修正)

## 不在 L1 約束的事

- ❌ 不指定具體 round-implementation(iterative vs unrolled — 由 Plugin 自選)
- ❌ 不指定 die size(由 Plugin 依 FP_CORE_UTIL 推算)
- ❌ 不指定 padding 邏輯(由 SW 處理,per README)
