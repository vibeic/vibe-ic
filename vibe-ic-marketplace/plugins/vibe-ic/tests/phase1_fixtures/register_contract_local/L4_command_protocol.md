---
layer: L4
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - reference/src/rtl/sha256.v(public register-map localparams)
  - NIST FIPS-180-4 SHA-256 spec
r1_r2_r3_compliance:
  r1: "PASS — 對外 command protocol(register-mapped),非實作"
  r2: "PASS — register-map localparams 是對外 documented protocol"
  r3: "PASS — 內部 decoder / FSM 實作 Plugin 自選"
---

# L4 — Command / Protocol Layer

## 適用性 — ✅ Active(memory-mapped command protocol)

`sha256` 採用 **memory-mapped register file** 作為對外 command protocol。SW 透過 cs/we/address 寫入控制 register 與 input data,讀回 status + digest。

## 命令類別

| 操作 | 方式 | 描述 |
|---|---|---|
| **ID query** | 讀 `ADDR_NAME0`(0x00)+ `ADDR_NAME1`(0x01)| 取得 chip identifier(magic string) |
| **Version query** | 讀 `ADDR_VERSION`(0x02)| 取得版本字串 |
| **INIT new hash** | 寫 `ADDR_CTRL`(0x08)bit0=1 | 開始新 hash 計算(internal H[] 歸 NIST initial values) |
| **NEXT continue** | 寫 `ADDR_CTRL`(0x08)bit1=1 | 從前一次 H[] 繼續計算下一個 block(用於 multi-block message) |
| **MODE select** | 寫 `ADDR_CTRL`(0x08)bit2 | 1 = SHA-256,0 = SHA-224 |
| **Load block** | 寫 `ADDR_BLOCK0..15`(0x10-0x1F)| 連續寫入 16 個 32-bit word(共 512-bit message block) |
| **Read status** | 讀 `ADDR_STATUS`(0x09)| bit0 = READY,bit1 = VALID |
| **Read digest** | 讀 `ADDR_DIGEST0..7`(0x20-0x27)| 連續讀 8 個 32-bit word(SHA-256 為全 8,SHA-224 為前 7) |

## 一次完整 hash 流程(SW perspective)

```
1. (optional) read ADDR_NAME0/1/VERSION to confirm chip identity
2. write ADDR_BLOCK0..15 = 512-bit padded message block
3. write ADDR_CTRL bit2 = MODE (1=SHA-256, 0=SHA-224)
   write ADDR_CTRL bit0 = 1 (INIT — single block) OR bit1 = 1 (NEXT — multi-block continuation)
4. poll ADDR_STATUS until bit0 (READY) = 1  // ~66 clk cycles
5. (optional) check bit1 (VALID) = 1
6. read ADDR_DIGEST0..7 = 256-bit digest (SHA-256) or first 224 bits (SHA-224)
7. for multi-block: repeat 2-6 with NEXT instead of INIT
```

## 邊界行為(corner cases)

| 情境 | 規定行為 |
|---|---|
| **Reset during operation**(計算進行中 reset:`reset_n` = 0 asserted while a block computation is in progress) | 進行中的計算立即終止且不會恢復(the in-flight computation is terminated, never resumed);internal state machine 歸 idle,STATUS.READY = 1、STATUS.VALID = 0,DIGEST0..7 讀回 0,CTRL 回到預設值(MODE = 1、INIT/NEXT = 0);reset release 後須重新 INIT。 |
| **Back-to-back transactions**(連續交易 / 連續 block:consecutive INIT/NEXT commands with no idle gap) | 只要 CTRL 寫入當下 STATUS.READY = 1,下一個 INIT 或 NEXT 可在 READY 重新拉高的同一個 cycle 立即發出(back-to-back block 允許,無需額外 idle gap);多 block 訊息以連續 NEXT 串接。READY = 0(busy)期間的 CTRL 寫入不被接受(not accepted):不排隊、不出錯,狀態機維持 BUSY。 |
| **INIT during BUSY / NEXT without prior INIT** | busy 期間的 INIT/NEXT 寫入不被接受(見上列);未曾 INIT 即發 NEXT 時,核心以目前 H[] 內容(reset 後為 0)繼續計算,不視為錯誤(`error` 不拉起)。 |
| **BLOCK write / DIGEST read during BUSY** | busy 期間寫 BLOCK0..15 不影響進行中的計算(schedule 已在啟動時載入);busy 期間讀 DIGEST0..7 回傳前一次結果或 0,且 STATUS.VALID = 0。 |

## 內部 FSM / decoder 實作

Plugin 自選實作策略,只要對外 command-response 行為與本層規範一致。

## 不在 L4 約束的事

- ❌ 內部 FSM state 數量 / 編碼
- ❌ Register file 內部 storage(latch / register array / 共用 RAM)
- ❌ 是否支援 byte-level 寫入(對 32-bit aligned word 操作即可)
