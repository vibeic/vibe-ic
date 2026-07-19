---
layer: L2
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - product intent(L1)
  - public architecture literature(Gemmini / OpenGeMM / NVDLA)— concept reference only
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅描述功能語意與容量/效能目標"
  r2_blackbox: "PASS — 僅描述對外可觀察行為(operand 佈局→start→done→result 佈局)"
  r3_multiple_correct: "PASS — 內部資料流結構、pipeline 深度、精確 latency、tile 方向性均由實作自選並於 declaration.json 聲明"
---

# L2 — Architecture / Functional Spec

## 功能定義 (Functional Specification)

`edge_llm_accel` 為 **INT4 GEMM tile 引擎**。一次計算(compute run)的數學語意:

```
給定:  W — 64×64 signed INT4 權重 tile(預載於 scratchpad,詳 L4)
       A — 串流 signed INT4 activation 向量序列(預載於 scratchpad,詳 L4)
累加:  acc[c] = Σ over 串流視窗 ( W[·][c] · A[·] )   — 有號累加,寬度 ≥ 20 bit
反量化: res[c] = SAT16( (acc[c] × zero_ext(scale)) >>> shift )   c = 0..63
```

- `scale` 為 16-bit 無號縮放係數、`shift` 為 5-bit 右移量(算術右移),
  兩者於 start 時取樣(詳 L4)。
- `SAT16(x)`:飽和至 signed INT16 範圍 `[-32768, +32767]`。
- 64 個 `res[c]`(INT16)於 run 結束時寫回 scratchpad(佈局詳 L4)。

## 對外可觀察契約 (Observable Contract)

1. Host 依 L4 的 operand 佈局把 W 與 A 寫入 scratchpad。
2. Host 給一個 cycle 的 `start` pulse(此時 `busy=0`)。
3. `busy` 升起;引擎自 scratchpad 取 operand、計算、寫回結果。
4. **`done` 於有限且確定的 cycle 數內 pulse 一個 cycle**(本規格上限:
   **≤ 4096 cycles** / run),`busy` 同時降回 0。
5. Host 讀回結果區(L4)。

## 容量 / 效能目標

| 項目 | 目標 |
|---|---|
| 平行 MAC 容量 | **4096 個 INT4 MAC / cycle**(64×64) |
| 峰值算力 @100 MHz | 819.2 GOP/s(1 MAC = 2 ops) |
| 累加位寬 | ≥ 20 bit signed(64-deep INT4×INT4 dot product 無溢位) |
| 片上 SRAM | 20 bank × 2048 × 39 bit ≈ **195 KB** |
| Dequant 平行度 | 64 columns 同時反量化(fused,不佔額外 run) |

## R3 多正確答案空間(實作自由度)

- ❌ 不指定內部資料流結構(weight-stationary systolic、output-stationary、
  broadcast tree … 皆合格,只要滿足容量/效能目標與功能語意)
- ❌ 不指定 pipeline 深度與精確 latency(僅上限 4096 cycles)
- ❌ 不指定 W/A 在陣列內的方向性(row/column orientation)與串流 skew —
  實作須於 `declaration.json` 聲明其選擇,L7 驗證據此建 golden model
- ❌ 不指定 FSM state 數量/編碼、內部訊號命名、模組階層
