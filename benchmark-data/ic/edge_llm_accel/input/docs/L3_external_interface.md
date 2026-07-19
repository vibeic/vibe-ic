---
layer: L3
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - product intent(L1/L2)
  - fakeram45_2048x39 macro datasheet(僅決定 host 資料寬度 39-bit 與 bank 數 20)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — port list 為對外規格"
  r2_blackbox: "PASS — 僅定義訊號方向/寬度/時序語意"
  r3_multiple_correct: "PASS — 內部實作自由;僅約束對外介面"
---

# L3 — External Interface

## Module 對外端口表 (Port List)

Top module 名稱:**`edge_llm_accel`**

| 訊號名 | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `clk` | 1 | input | 系統時脈;所有同步邏輯於上升沿動作 |
| `rst_n` | 1 | input | **非同步 active-low reset**;deassert 後下一個上升沿起可正常操作 |
| `host_en` | 1 | input | host/DMA scratchpad 存取致能(active-high) |
| `host_we` | 1 | input | host 寫入致能(與 `host_en` 同時為 1 = 寫入;`host_en=1, host_we=0` = 讀取) |
| `host_bank` | 5 | input | scratchpad bank 選擇(合法值 0..19) |
| `host_addr` | 11 | input | bank 內 word 位址(0..2047) |
| `host_wdata` | 39 | input | host 寫入資料 |
| `host_rdata` | 39 | output | host 讀回資料(讀取延遲詳 L4) |
| `start` | 1 | input | compute run 啟動 pulse(1 cycle;僅於 `busy=0` 時有效) |
| `dequant_scale` | 16 | input | 反量化縮放係數(無號;start 時取樣) |
| `dequant_shift` | 5 | input | 反量化算術右移量(start 時取樣) |
| `busy` | 1 | output | compute run 進行中 |
| `done` | 1 | output | run 完成 pulse(1 cycle) |

## Design Parameters

| Parameter | 預設值 | 說明 |
|---|---|---|
| `DIM` | 64 | GEMM tile 邊長(MAC 平行度 = DIM²)。**Primary tape-out target = 64**;設計須支援參數化縮小(如 8/16/32)供驗證用 |
| `ACCW` | 20 | 累加器位寬 |
| `NBANK` | 20 | SRAM bank 數 |
| `BAW` | 11 | bank 位址寬 |
| `BDW` | 39 | bank 資料寬 |

## 整合約束

- **所有 module port 一律宣告為 unsigned**(不得在 port 宣告使用 `signed` 關鍵字);
  內部有號運算以 `$signed()` 處理。
  (OpenROAD Verilog reader 相容性 — 已知工具邊界,詳 L9。)
- 所有輸入於 `clk` 上升沿取樣;無 latch-based I/O。
- 無 I/O pad ring 需求(macro-level tape-out simulation;pin placement 由工具自選)。

## 不在 L3 約束的事

- ❌ Pin 的物理邊/順序(由 PnR 工具自選)
- ❌ 內部 clock gating / buffer 策略
