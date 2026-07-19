---
layer: L8
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - fakeram45_2048x39 macro datasheet(input/pdk_local/fakeram45/ LEF + Liberty)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅定義硬巨集之整合契約"
  r2_blackbox: "PASS — 引用巨集對外 datasheet(pin list / 時序 / 尺寸)"
  r3_multiple_correct: "PASS — 巨集擺放/邏輯分割由實作與工具自選"
---

# L8 — Submodule / Hard-Macro Integration

## 8.1 SRAM 硬巨集:`fakeram45_2048x39` × 20

| 項目 | 值 |
|---|---|
| 組態 | 2048 words × 39 bit,single-port,synchronous |
| 讀取延遲 | 1 cycle(`ce_in=1, we_in=0` 之上升沿取位址,次拍 `rd_out` 有效) |
| 寫入 | `ce_in=1, we_in=1` 上升沿寫入;`w_mask_in[38:0]` 位元遮罩(全 1 = full-word write 合法) |
| Pin list | `clk, ce_in, we_in, addr_in[10:0], wd_in[38:0], w_mask_in[38:0], rd_out[38:0]` |
| 物理尺寸 | 206.910 × 219.800 µm(LEF `SIZE`) |
| 資產 | `input/pdk_local/fakeram45/`:`.lib`(typical)、`.lef`(abstract)、`.v`(行為模型,僅模擬用) |
| 誠實聲明 | FakeRAM45 為 **abstract macro**(OpenROAD-flow-scripts Nangate45 平台之標準 placeholder):無真實電晶體 GDS、無 memory-compiler 簽核 — 與 Kimi K3 Nangate45 demo 同一限制 |

整合規則:

- 20 顆 instance,bank 選擇邏輯由實作自訂(host_bank 0..19 之解碼契約見 L3/L4)。
- 未選中的 bank 應 `ce_in=0`(省功耗;非功能性要求)。
- 巨集之 `w_mask_in` 可綁定全 1。
- 巨集擺放(placement)、pin 朝向、halo/channel 由 PnR 工具/實作自選(L9 的 die 約束內)。

## 8.2 邏輯子系統(GENERATED,實作自由)

以下功能區塊為規格「功能責任」的列舉,**不構成模組階層要求**(R3):

| 功能責任 | 規格 |
|---|---|
| 平行 MAC 核心 | 4096 INT4 MAC/cycle 容量(L2);結構自由 |
| 串流控制 | 依 L4 佈局取 operand、依 L4 時序回報 busy/done |
| Fused dequant | 64-column 平行,`SAT16((acc×scale)>>>shift)`(L2) |
| Host 存取路徑 | L4 之 2-cycle 讀延遲契約 |

## 8.3 Std-cell 平台細胞(參考,由工具自動處理)

tie cells `LOGIC0_X1`/`LOGIC1_X1`、tapcell `TAPCELL_X1`、antenna diode
`ANTENNA_X1`、fillers `FILLCELL_X*` — 均為 NangateOpenCellLibrary 平台標準細胞,
由 synthesis/PnR 工具自動插入,不屬設計輸入。
