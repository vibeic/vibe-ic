---
layer: L3
ic: spm
status: draft
written_at: 2026-05-22
sources:
  - reference/src/spm.v (僅 module header + port 宣告區,line 15-20)
  - reference/pin_order.cfg
r1_r2_r3_compliance:
  r1_schema_only: "PASS — port list 為對外規格,合 L3 schema"
  r2_blackbox: "PASS — 僅引用 module header 與 pad 配置設定"
  r3_multiple_correct: "PASS — 內部 driver/buffer 由 Plugin 自選"
---

# L3 — External Interface

## Module 對外端口表 (Port List)

| 訊號名 | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `clk` | 1-bit | input | 系統時脈;所有資料於上升沿取樣與輸出 |
| `rst` | 1-bit | input | 同步 reset(**active-high**);assertion 後一個 cycle 內所有內部狀態歸零 |
| `x` | N-bit(`[size-1:0]`,parameter `size` 預設 32) | input | parallel multiplicand;全部位元同時給入,於計算啟動後不得改變 |
| `y` | 1-bit | input | serial multiplier;每 cycle 給入一個位元 |
| `p` | 1-bit | output | serial product;每 cycle 輸出一個位元 |

## Design Parameters

| Parameter | 預設值 | 合法範圍 |
|---|---|---|
| `size` | 32 | 典型應用為 8 / 16 / 32;設計上應支援 ≥ 4 的任意正整數 |

## Physical Pad Placement

對齊 OpenLane 的 `pin_order.cfg`:

| Pad 邊 | 包含訊號 |
|---|---|
| **North (N)** | `x[size-1:0]`(整個 multiplicand bus,每位元一個 pad) |
| **South (S)** | `rst` |
| **East (E)** | `clk` |
| **West (W)** | `p`、`y`(輸出與序列輸入相鄰) |

備註:`pin_order.cfg` 額外指定:
- 北邊(`#N`)的 pad 之間最小間距 `min_distance = 0.1` µm
- 北邊使用萬用 pattern `x.*` 自動 match 所有 `x` 位元

## Reset Polarity 與啟動

- `rst = 1` 進入 reset 狀態
- `rst = 0` 解除後,Plugin 可定義 N cycle 內進入「ready to compute」(N 由 Plugin 自選,L7 驗證須涵蓋)

## 不在 L3 約束的事

- ❌ I/O cell 型別(由 PDK 預設;Plugin 可自選 io pad library)
- ❌ ESD strategy(由 PDK 預設)
- ❌ Pad ordering 在同一邊內的順序(只要符合「北邊全部 `x` 位元」即可)
