---
layer: L8
ic: subservient
status: draft
written_at: 2026-05-22
sources:
  - reference/subservient.core (FuseSoC manifest — 列出 RTL fileset)
  - reference/README.md (top-level architecture)
  - reference_serv/doc/interface.rst (SERV core 接口契約)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 描述對外契約與 sub-module 整合需求,不指定內部寫法"
  r2_blackbox: "PASS — 從 FuseSoC dependency graph + SERV datasheet 推導 sub-module 結構;未閱讀 RTL"
  r3_multiple_correct: "PASS — 內部 sub-module 階層由 Plugin 自選,只要對外契約滿足"
---

# L8 — Submodule Integration Spec

## 8.1 Top 層級

`subservient` 提供兩個 top module 選擇,Plugin 在 declaration.json 聲明:

| Top option | 包含 | 用途 |
|---|---|---|
| `subservient` | subservient_core + GPIO peripheral | 完整 SoC,**tape-out 預設 top**(對應 sky130 OpenLane target) |
| `subservient_core` | SERV + servile + RAM + RF interface | 不含 GPIO,給用戶自行接 peripherals |

## 8.2 必要 sub-module 對外契約

下列 sub-modules 為**功能必要**(由 SoC 整體功能驅動);Plugin 可自選**命名、檔案組織、實作技術**,只要對外契約符合:

### 8.2.1 SERV core(必含)
- 來源:reference_serv(已 datasheet 公開)
- 對外契約:見 `reference_serv/doc/interface.rst` 的 Signals table(clk / i_rst / instruction bus / data bus / RF interface / extension interface)
- Parameters:RESET_PC、RESET_STRATEGY、WITH_CSR、(optional)MDU、PRE_REGISTER

### 8.2.2 Servile wrapper(必含)
- 角色:整合 SERV core + SRAM-based RF + RF interface adapter
- 對外契約:把 SERV 的 RF interface 收斂為 SRAM-bus signals;對外只 expose instruction bus + data bus
- 來源:SERV repo 的 servile module(award-winning:serv:servile:1.4.0,從 FuseSoC manifest)

### 8.2.3 共享 SRAM
- 角色:I-mem + D-mem + RF 三合一
- 對外契約:read/write port(addr + data + we);具體寬度由 Plugin 在 declaration.json 聲明(典型 8-bit data × N-bit addr)
- 實作選擇:Plugin 可選 macro 或 std-cell composed

### 8.2.4 GPIO peripheral(僅當 top = `subservient`)
- 角色:至少 1 個 output GPIO pin;可作為 simple debug 或 firmware bit-banged UART tx
- 對外契約:接到 SoC top 對外 `o_gpio` port

### 8.2.5 RF-RAM interface(必含)
- 角色:把 SERV 的 RF interface(read/write 1-bit serial)轉成 SRAM 介面
- 對外契約:介於 servile 與 SRAM 之間

### 8.2.6 Debug switch(視 Plugin 設計可選包入)
- 角色:reference 內 `subservient_debug_switch.v` 提供 boot-time 模式切換
- 並非 SoC 對外契約必要;Plugin 可選擇實作或省略

## 8.3 整合契約(對應 L3 對外)

整合後的 top module 必須:

1. **介面契約**:port list 對外符合 L3 規定
2. **功能契約**:對 reference firmware(blinky.hex / hello.hex)在 reset 解除後執行,GPIO 輸出符合 L7 的「observed-vs-expected pattern match」
3. **時序契約**:在 L9 給定的 SDC 約束下,9-corner STA setup + hold 全 ≥ 0
4. **物理契約**:在 L1 PDK / floorplan target 下,DRC + LVS + antenna 全 clean

## 8.4 Sub-module 階層自由度

Plugin **可選**:
- ✅ 多檔案多 module(如 reference 採用)
- ✅ 單一 flatten module(若 RTL 撰寫策略偏好)
- ✅ 自行命名 sub-module
- ✅ 自行決定 SERV 與 servile 是否拆分

**不可**:
- ❌ 改變 RV32I 指令集語意(屬於 RISC-V ISA 標準)
- ❌ 改變 SERV 的 bit-serial 架構(會破壞 RV ISA timing semantic)

## 8.5 不在 L8 約束的事

- ❌ Module hierarchy 深度
- ❌ Sub-module 在不同檔案還是同一檔案
- ❌ SV 還是 Verilog 寫法(若選 SV,工具鏈須能處理)
- ❌ 是否使用 `generate` block 展開 RF / I-mem 結構
