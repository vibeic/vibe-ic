---
layer: L5
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - product intent(L2/L4)
r1_r2_r3_compliance:
  r1_schema_only: "PASS"
  r2_blackbox: "PASS — 僅列對外組態欄位"
  r3_multiple_correct: "PASS — 內部鎖存實作自由"
---

# L5 — Register / Configuration Map

## 適用性 — N/A(無 SW-visible registers)

本 IC **無 SW-visible registers、無記憶體映射 CSR 匯流排**:

- 無 control register
- 無 status register(狀態僅 `busy`/`done` 兩個 pin)
- 無 configuration register(組態經專用 pin 於 `start` 取樣,見下表)
- 無 interrupt enable / status

macro-level 協處理器;SoC 整合時由上層 wrapper 提供 CSR。
→ 不需產生 register file / CSR decoder / memory-mapped interface。

## 參考:pin-latched 組態欄位(非 register,僅供整合對照)

所有組態經由專用 pin 於 `start` 時取樣鎖存:

| 組態欄位 | 來源 pin | 寬度 | 取樣時機 | 語意 |
|---|---|---|---|---|
| DEQUANT_SCALE | `dequant_scale` | 16(無號) | start pulse 當拍 | 反量化縮放係數 |
| DEQUANT_SHIFT | `dequant_shift` | 5 | start pulse 當拍 | 反量化算術右移量 |
| RUN_LENGTH | (固定) | — | — | 本版固定 64 activation beats / run |

- run 進行中改變 `dequant_scale` / `dequant_shift` 不影響進行中的 run。
- 狀態回讀僅 `busy` / `done` 兩個 pin(無 status register)。

## 不在 L5 約束的事

- ❌ 內部組態鎖存的實作(register 位置/命名)
- ❌ 未來 CSR 匯流排擴充(out of scope)
