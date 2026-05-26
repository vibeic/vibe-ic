---
layer: L8
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - L2 (functional spec)
  - L3 (port contract)
  - L4 / L5 (register map / command protocol)
r1_r2_r3_compliance:
  r1: "PASS — 對外契約 + 必含 sub-module 功能性需求,不指定階層 / 內部命名"
  r2: "PASS — 引用對外 spec(NIST / register map)"
  r3: "PASS — sub-module 階層自由度高;Plugin 可單一 module 或多 module"
---

# L8 — Submodule Integration Spec

## 8.1 Top 層級

`sha256` 為**單一 top module**,內部包含 register file + hash datapath(具體拆分由 Plugin 自選)。

對外契約:
- 5 個 port(L3 定義):`clk`、`reset_n`、`cs`、`we`、`address[7:0]`、`write_data[31:0]`、`read_data[31:0]`、`error`
- Register map(L4 / L5 定義):8-bit address space,主要 0x00-0x27

## 8.2 必要 sub-module 功能(由 Plugin 階層自選)

下列功能**必需**(由 spec 驅動)— Plugin 自選是否拆 module、檔案組織、命名:

### 8.2.1 Register file(對外 SW 介面)
- 對外 register-mapped command decoder(cs/we/address → 內部訊號)
- ADDR_NAME0/1/VERSION 為硬編 read-only constant
- ADDR_CTRL bit 0/1/2 → trigger internal INIT/NEXT/MODE 訊號
- ADDR_STATUS bit 0/1 → 反映內部 READY/VALID 訊號
- ADDR_BLOCK0..15 → 16 × 32-bit registers cache 當前 message block
- ADDR_DIGEST0..7 → 8 × 32-bit registers cache 當前 digest result

### 8.2.2 Hash core(SHA-256 round function)
- 接收 512-bit block + INIT/NEXT/MODE 控制
- 對應 NIST FIPS-180-4 第 6.2 節定義的 round function(64 rounds)
- 輸出 256-bit digest + ready/valid 訊號

### 8.2.3 Message scheduler(W memory)
- 從 512-bit block 計算 W[0..63](W[0..15]=block words,W[16..63] = schedule)
- 可選 storage:64-deep × 32-bit RAM、shift register、circular buffer

### 8.2.4 K constants
- 64 個 NIST 規定的 round constants(可硬編、ROM、std-cell composed)

## 8.3 對外契約(與 L3 / L4 / L5 一致)

整合後的 top module 必須:

1. **介面契約**:port list 符合 L3
2. **功能契約**:對 NIST FIPS-180-4 test vectors 100% 一致(L7)
3. **時序契約**:在 L9 SDC 約束下,9-corner STA setup + hold 全 ≥ 0
4. **物理契約**:DRC + LVS + antenna 全 clean

## 8.4 Sub-module 階層自由度

Plugin **可選**:
- ✅ 單一 monolithic module(簡單 design)
- ✅ 多 module(register file 一個 module、hash core 一個 module、W mem 一個 module、K constants 一個 module — reference 採用此分法)
- ✅ Pipeline 拆分(將 round function 拆成多 stage)

**不可**:
- ❌ 改變 NIST round function 語意(它是 NIST 國際標準)
- ❌ 改變 register map(L5 已 fix 對外契約)

## 8.5 不在 L8 約束的事

- ❌ Module hierarchy 深度
- ❌ SV 還是 V 寫法
- ❌ Round function 內部 dataflow(carry-save / ripple / look-ahead adder)
- ❌ W memory 實作(RAM / register array / shift register)
