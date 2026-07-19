---
layer: L7
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - L2 functional spec、L4 protocol
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 驗證計畫僅引用對外契約"
  r2_blackbox: "PASS — golden model 由 L2 數學語意 + declaration.json 聲明建立"
  r3_multiple_correct: "PASS — 驗證接受任何滿足契約之實作"
---

# L7 — Verification Plan

Golden 基準:**本 IC 為自主設計,無 upstream reference RTL**。Golden model =
L2 的 GEMM + dequant 數學語意(軟體重建),tile 方向性/串流 skew 依實作之
`declaration.json` 聲明對齊。

## V1 — 單元級 golden 驗證(縮小參數,bit-true)

利用 L3 的參數化要求,以 **DIM=8**(8×8,64 MAC)之同一 RTL 產生小型 instance:

| 測項 | 內容 | 通過標準 |
|---|---|---|
| V1.1 GEMM 隨機 | ≥ 100 組隨機 W/A tile(INT4 全範圍 -8..+7),TB 軟體 golden 全比對 | 100% match |
| V1.2 極值 | W/A 全 +7 / 全 -8 / 交錯極值(累加器最大擺幅) | 100% match,無溢位 |
| V1.3 Dequant 飽和 | 導引向量使 `(acc×scale)>>>shift` 落在 >+32767、<-32768、邊界±1 | 飽和行為 bit-true |
| V1.4 協定 | start/busy/done 時序、busy 期間 start 忽略、reset 後重跑 | 契約成立 |

## V2 — 全尺寸(DIM=64)驗證

| 測項 | 內容 | 通過標準 |
|---|---|---|
| V2.1 全尺寸 GEMM golden | 完整 64×64 tile,隨機 W/A 依 L4 佈局預載,run 後讀回 result 區與軟體 golden 比對 | 100% match |
| V2.2 Run 上限 | done 於 start 後 ≤ 4096 cycles | 成立 |
| V2.3 Host 存取 | 20 bank 全域寫/讀(含 2-cycle latency 背靠背) | 100% match |

工具:iverilog(`-g2012`)或 verilator;SRAM 用 `input/pdk_local/fakeram45/
fakeram45_2048x39.v` 行為模型。

## 典型黑盒測試案例(chip-level test cases;全部 spec-決定、與實作無關)

| test_id | 測試模式 (test_mode) | 刺激 (stimulus) | 預期回應 (expected) |
|---|---|---|---|
| TC1_reset | reset 行為 | `rst_n` 拉低 2 cycles 後釋放 | `busy=0`、`done=0`,host 存取立即可用 |
| TC2_host_rw | host scratchpad 讀寫 | 寫 `39'h12_3456_789A` 至 bank 3, addr 0x010;2 cycles 後讀回 | `host_rdata = 39'h12_3456_789A`(2-cycle pipelined latency,L4 §4.1) |
| TC3_host_boundary | 位址/bank 邊界 | 寫入並讀回 bank 19, addr 0x7FF(最高 bank/位址) | 讀回值 = 寫入值;無 wrap / alias 至其他 bank |
| TC4_run_protocol | compute run 協定 | 預載 operand 後,`busy=0` 時 pulse `start` 1 cycle | `busy` 於 1 cycle 內升起;`done` 恰 pulse 一次(≤4096 cycles);`busy` 同步降回 0 |
| TC5_start_ignored | busy 中 start 忽略 | run 進行中再 pulse `start` | 整個 run 僅一次 `done`;第二個 start 不重啟、不排隊(L4 §4.3) |
| TC6_dequant_sat | dequant 飽和 | 導引 operand 使 `(acc×scale)>>>shift` 超出 INT16 正/負界 | 結果分別飽和至 `+32767` / `-32768`(L2 SAT16) |

## 測試模式與除錯可觀察性 (test modes / debug observability)

| 項目 | 內容 |
|---|---|
| 功能模式 (functional) | 正常 operate:host preload → start → done → readback(上表 TC1–TC6) |
| 縮小驗證模式 (scaled-param) | 同一 RTL 以 DIM=8 參數化縮小,bit-true golden 全比對(V1) |
| 全尺寸驗證模式 (full-scale) | DIM=64 end-to-end golden 比對(V2) |
| 除錯可觀察性 | `busy`/`done` 狀態 pin + host port 全 scratchpad 讀回(結果區 + operand 區皆可讀,post-mortem dump 用) |
| 量產測試建議 | scratchpad march 測試經 host port;MAC 陣列以 TC6 類導引向量做 datapath 煙霧測 |

## V3 — 物理流程驗證(tape-out simulation 範圍,詳 L9)

| 測項 | 通過標準 |
|---|---|
| Synthesis | 無 error;規模落在 1.2M–1.6M std cells(L1 規模目標) |
| PnR + detailed route | route DRC violations = 0;antenna violations = 0 |
| STA @ 100 MHz(typical) | WNS ≥ 0,TNS = 0 |
| GDS | 成功輸出 merged GDSII(SRAM 為 abstract outline,誠實聲明) |
| Gate-level sim | **不要求**(1.4M-cell GLS 不具時間效益;由 STA + route-clean 承擔) |

## 誠實聲明

- V2.1 為主要功能簽核;若實作聲明之 skew/orientation 使 TB 需按聲明重排
  operand,屬 R3 合法空間。
- Nangate45 無真實 DRC/LVS deck:V3 的「DRC」= router DRC + educational KLayout
  deck 報告;LVS 無 deck(結構性 CDL 檢查為選項)。詳 L1/L9 範圍聲明。
