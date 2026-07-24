---
layer: L8
ic: spm
status: draft
written_at: 2026-05-22
sources:
  - L2 (functional spec)
  - L3 (port list)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅列整合要求與對外契約,不指定 sub-module 結構"
  r2_blackbox: "PASS — 故意不引用 reference 的子模組(避免洩漏 CSADD/TCMP 等實作命名)"
  r3_multiple_correct: "PASS — sub-module 階層完全由 Plugin 自選"
---

# L8 — Submodule Integration Spec

## 8.1 整合範圍

`spm` 為**單一 top module**,內部結構由 Plugin 自選。

外界看到的只有:
- 1 個 RTL 檔案集(可由 Plugin 自由切割為多個檔案)
- 1 個 top module(名稱 = `spm`,以對應 L1 product name 與 L3 module header)
- L3 規定的 5 個 port(`clk`、`rst`、`x`、`y`、`p`)+ 1 個 parameter(`size`)

## 8.2 不對 sub-module 結構作要求

**Plugin 可選**:
- ✅ 單一 module(整個 spm 寫在一個 module 內,parameter `generate` 展開)
- ✅ 多個 sub-module 串聯(例如 N 個 adder cell 串聯)
- ✅ 多個 sub-module 樹狀(例如 Wallace tree 結構)
- ✅ FSM-controlled datapath
- ✅ Pure combinational + flop wrapper

**不指定**:
- ❌ 不要求特定 adder cell(carry-save / ripple / look-ahead / Brent-Kung 任選)
- ❌ 不要求特定 multiplier 演算法(shift-and-add / Booth / Wallace / Dadda 任選)
- ❌ 不要求特定 register 配置或數量
- ❌ 不要求 sub-module 命名規則

## 8.3 對外契約 (與 L3 一致)

整合後的 top module 必須:

1. **介面契約**:port list 完全符合 L3 的 5 個 port + 1 個 parameter
2. **功能契約**:對所有合法 `(x, y_stream)`,`p_stream` 等於 `signed_2c_mul(x, y_stream)`(按 Plugin 聲明的位元順序)
3. **時序契約**:在 L9 給定的 SDC 約束下,STA 全部 corner met
4. **物理契約**:在 L1 給定的 PDK / floorplan target 下,DRC + LVS 全 clean

## 8.4 假如 Plugin 產生多個 sub-module

則:
- 每個 sub-module **必須**內部完整、無懸空 port、無未連接的 input
- Top module **必須**例化所有有用的 sub-module,**禁止**留 stub
- 命名空間 **不得**與 PDK std-cell 命名衝突(避免 link 階段被誤認)

## 8.5 不在 L8 約束的事

- ❌ Module hierarchy 深度
- ❌ Sub-module 在不同檔案還是同一檔案
- ❌ SV 還是 V 寫法(Plugin 可選 — 但若選 SV,工具鏈須能處理)
