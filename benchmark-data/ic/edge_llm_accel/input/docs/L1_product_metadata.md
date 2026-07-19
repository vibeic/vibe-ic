---
layer: L1
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - product intent (owner directive 2026-07-18 — Kimi-K3-scale open-PDK benchmark IC)
  - public architecture literature (Gemmini arXiv:1911.09925, OpenGeMM arXiv:2411.09543, NVDLA) — concept reference only, no code reuse
  - fakeram45_2048x39 macro datasheet (input/pdk_local/fakeram45/ LEF + Liberty)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅描述產品意圖與容量/效能目標,不描述實作"
  r2_blackbox: "PASS — 僅引用對外可觀察規格(throughput、SRAM 容量、PDK/clock/die targets)"
  r3_multiple_correct: "PASS — 內部資料流(systolic 或其他)、pipeline、latency 由實作自選"
---

# L1 — Product & Tapeout Metadata

## 產品基本資訊

| 欄位 | 值 |
|---|---|
| 產品名稱 (product_name) | `edge_llm_accel` |
| 產品分類 (product_family) | edge-AI inference accelerator(INT4 GEMM engine) |
| 功能一句話描述 | 平行 INT4 矩陣乘法加速器:64×64 權重 tile × 串流 activation 向量,片上 20-bank SRAM scratchpad,fused per-column dequantization,峰值 4096 MAC/cycle |
| 應用情境 | edge-LLM SoC 協處理器 — 承接 LLM linear / attention projection 的 INT4 GEMM 運算 |
| 設計起源 | **自主設計**(vibe-IC IC Expert Agent 從本套設計文件生成);架構層面參考公開文獻(Gemmini / OpenGeMM / NVDLA)之概念,**無任何程式碼重用** |
| Benchmark 對照組 | Kimi K3「48 小時晶片」新聞 demo(Nangate45、1.46M std cells、3.981 mm²、0.277 MB SRAM、100 MHz、RTL→tape-out-simulation) |

## Tapeout 目標

| 欄位 | 值 |
|---|---|
| 目標 PDK | `nangate45`(NanGate / FreePDK45 Open Cell Library,Si2,Apache-2.0) |
| Target Std-Cell Library | `NangateOpenCellLibrary`(typical corner) |
| Target clock period | **10 ns(100 MHz)** |
| Die size 目標 | **2400 × 2400 µm(5.76 mm²)** |
| 規模目標 | ~1.4M std cells + 20 顆 SRAM 硬巨集(~195 KB) |
| SRAM 巨集 | `fakeram45_2048x39` × 20(abstract macro,詳 L8) |

## 簽核層級聲明(誠實範圍)

NanGate45 / FreePDK45 是 **GENERIC、非晶圓廠** 的 45nm 教學/研究用 std-cell enablement
(`pdk_registry.json` 中 `tapeout_capable=false`):虛構製程、無真實 foundry、
無可簽核 DRC deck(KLayout FreePDK45 deck 為 educational)、無 LVS deck、SRAM 為
abstract macro(無真實 GDS)。因此本 IC 的完成標準為
**「tape-out simulation」= synth → PnR → CTS → detailed route(router-DRC clean)→ GDS 輸出**,
與 Kimi K3 之 Nangate45 demo 同一等級。真實 foundry 簽核(real DRC/LVS/STA)屬
vibe-IC 在 sky130A / gf180mcuD / ihp-sg13g2 上的較高標準,不在本 IC 範圍。
