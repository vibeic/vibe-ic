---
layer: L2
ic: spm
status: draft
written_at: 2026-05-22
sources:
  - reference/src/spm.v (僅 module header + port 宣告區,line 15-20)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅描述功能與資料路徑語意,不描述模組階層或內部 cell"
  r2_blackbox: "PASS — 僅引用對外可觀察行為(port 寬度、訊號方向、資料編碼)"
  r3_multiple_correct: "PASS — 演算法/結構由 Plugin 自選,只要功能等價、時序滿足"
---

# L2 — Architecture / Functional Spec

## 功能定義 (Functional Specification)

`spm` 為 **N-bit modulo 算術乘法器**,計算:

```
p = (x × y) mod 2^N    (N-bit modulo arithmetic multiplication)
```

> **整數編碼說明**:N-bit serial multiplier 對 signed 2's complement 與 unsigned 整數的 **bit pattern 結果完全相同**(modulo 2^N 性質),差別只在於軟體端對 bit 流的 interpretation。因此 hardware 本身無 signed/unsigned 區分;Plugin 仍須於 `declaration.json` 聲明預期的軟體端 interpretation (`"signed_2c"` 或 `"unsigned"`)以利 L7 比對程序選擇對應的 golden model,但這不影響 RTL 設計本身。

其中:
- **x** 為 **parallel multiplicand**(整體一次給入,N 位元)
- **y** 為 **serial multiplier**(每個時脈週期給入 1 個位元)
- **p** 為 **serial product**(每個時脈週期輸出 1 個位元)

## 資料寬度

| 訊號 | 寬度 | 描述 | 給入/輸出方式 |
|---|---|---|---|
| `x` | N-bit(N 為 design parameter,**Primary tape-out target = 32**;Secondary 可選 8 / 16) | 整數的 N-bit pattern | parallel(一次全部給入) |
| `y` | 1-bit | 整數的逐位元串流 | serial(每 cycle 1 bit) |
| `p` | 1-bit | 乘積的逐位元串流(輸出位元順序由 Plugin 於 declaration.json 聲明) | serial(每 cycle 1 bit) |

## 同步行為

- 所有資料於 **`clk` 上升沿** 同步取樣與輸出
- **`rst` 同步 reset**,polarity 為 **active-high**(與 L3 一致);reset 後內部狀態須能讓乘法計算正確啟動

## 輸出時序語意 (R3 多正確答案空間)

⚠️ **本文件不指定「輸入完成後幾個 cycle 才開始有有效輸出」(latency)**:
- Plugin 可選擇任何 latency,只要對外行為符合「`p` 為 `x × y` 的 serial 位元流」即可
- Plugin 可選擇:輸出位元順序為 **LSB-first 還是 MSB-first**(只要在 L7 驗證計畫中明確聲明,並能與 reference 對齊或證明等價)
- 但**必須**:`y` 第 `i` 個位元給入後,在有限且確定的 cycle 數內,`p` 對應位元被輸出

## 演算法選擇空間 (Plugin 自由度)

Plugin **可自由選擇任何 functional equivalent 的整數乘法演算法**,不限於任何具體列舉。L7 驗證只要求:

- functional 等價(對 golden model 100% 一致)
- 時序滿足 L9 SDC
- 物理通過 DRC / LVS

## 不在 L2 約束的事

- ❌ 不指定 module hierarchy 或子模組命名
- ❌ 不指定內部訊號命名
- ❌ 不指定 FSM state 數量或編碼
- ❌ 不指定 pipeline 深度
- ❌ 不指定 latency cycle 數
