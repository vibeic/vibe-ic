---
layer: L4
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - product intent(L2)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 定義 host 可觀察之協定"
  r2_blackbox: "PASS — 僅定義 port 時序與記憶體佈局契約"
  r3_multiple_correct: "PASS — operand 取用之內部排程/skew 由實作聲明"
---

# L4 — Command / Access Protocol

## 4.1 Host scratchpad 存取協定

- **寫入**:`host_en=1, host_we=1` 之上升沿,`host_wdata` 全 39 bit 寫入
  `bank[host_bank]` 的 `host_addr`(full-word write)。每 cycle 可背靠背寫入。
- **讀取**:`host_en=1, host_we=0` 發出讀取;**讀取延遲 = 2 cycles**
  (pipelined:cycle N 發位址 → cycle N+2 `host_rdata` 有效)。背靠背讀取合法。
- **互斥規則**:`busy=1` 期間 host **不得** 存取 scratchpad(`host_en` 須保持 0);
  違反時 compute 結果與 scratchpad 內容為 undefined(不會損壞硬體、不會 hang)。
  `host_en=1` 時引擎的 operand 取用暫停讓位(host 優先)。

## 4.2 Operand / result 記憶體佈局

Scratchpad 為 20 bank × 2048 word × 39 bit。compute run 的 operand 以
**32-bit chunk 串流**自 scratchpad 取用(每 word 僅用低 32 bit;bit [38:32] 忽略):

| 區域 | word 序號 i | bank | addr | 內容 |
|---|---|---|---|---|
| Weight stream | 0 .. 511 | `(i mod 32) mod 20` | `i` | W tile,每 8 個 word 組成一個 256-bit weight beat(64 × INT4) |
| Activation stream | 512 .. 1039 | `(i mod 32) mod 20` | `i` | A 向量串流,每 8 個 word 組成一個 256-bit activation beat |
| Result 區 | k = 0 .. 63 | `(k mod 32) mod 20` | `0x780 + k` | `res[k]`(INT16);39-bit word 之低 32 bit 承載結果(高位 0) |

- 一個 **beat** = 8 個連續 word 的低 32 bit 依序拼接(共 256 bit = 64 × INT4)。
- **Beat/tile 方向性(orientation)與串流 pipeline skew 由實作於
  `declaration.json` 聲明**(R3);L7 的 golden model 依聲明建立。
- Result word 的 bit 佈局:`res[k]`(signed INT16)置於 word 內,實作於
  declaration.json 聲明精確 bit 位置(建議:duplicated 或 zero-extended)。

## 4.3 Compute run 時序

```
          ┌─┐
start  ───┘ └──────────────────────────────────────────
busy   ─────┌──────────────────────────────┐
            │                              └───────────
done   ────────────────────────────────────┌─┐
                                           └─┘─────────
```

1. `busy=0` 時,host pulse `start`(1 cycle);`dequant_scale` / `dequant_shift`
   於該 cycle 取樣鎖存。
2. `busy` 於 start 後 1 cycle 內升起。
3. 引擎依 4.2 佈局自主取 operand、計算、寫回 result 區。
4. `done` pulse 1 cycle(≤ 4096 cycles from start),`busy` 同 cycle 或次 cycle 降 0。
5. `busy=1` 時再給 `start` 無效(忽略)。

## 4.4 不在 L4 約束的事

- ❌ operand 取用的內部順序 / 平行度 /(bank conflict 處理)
- ❌ done 之前 result 區的中間狀態
