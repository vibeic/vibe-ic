# Benchmark IC #5 — lowRISC OpenTitan AES（TL-UL 週邊 IP）

## 設計需求（Natural-Language Brief）

請在 **sky130A** open PDK 上實作 lowRISC OpenTitan 的 **AES unit**，作為一顆
**TileLink Uncached Lightweight (TL-UL) 週邊 IP**：

1. **演算法功能**：AES-128 / AES-192 / AES-256，支援
   ECB / CBC / CFB-128 / OFB / CTR 五種 block cipher 操作模式
   （加密與解密），行為依 NIST FIPS-197 與本目錄 staged 的設計文件
   （`input/docs/aes_theory_of_operation.md`、`aes_interfaces.md`、
   `aes_registers.md`、`aes_programmers_guide.md`、`aes_README.md`）。

2. **匯流排介面**：裝置端 TL-UL（device interface），register map **必須**
   與機器可讀的 golden 檔 **`input/golden/aes.hjson`** 完全一致
   （offset / 欄位 / reset value / 存取屬性 / 多暫存器陣列 KEY_SHARE*/IV*/DATA_IN*/DATA_OUT*）。
   這是本 benchmark 的硬性 oracle 之一。

3. **安全功能取捨（open-PDK benchmark run 約定）**：
   - **SecMasking 停用**（masking disabled, unmasked datapath）——
     open PDK 流程不評估 side-channel masking；entropy/EDN 介面依文件 tie-off。
   - 其餘 OpenTitan 既有安全機制（shadowed control register、sparse FSM encoding、
     lifecycle escalation input）保留 RTL 原樣，escalation 輸入 tie-off 至非觸發值。

4. **實作路徑（intended path）**：**REUSED-IP / catalog-glue**。
   `input/vendor_rtl/{aes,prim,prim_generic,tlul,deps}/` 已 staged 上游
   pure-RTL dependency closure（prim 抽象層選 **prim_generic**）。
   預期工作是 catalog-glue：選檔、參數化（`SecMasking=0`）、chip_top wrapper、
   tie-off、約束 — 而不是 from-scratch 重寫 AES。

5. **Sign-off 目標**：synth → PnR → GDS → DRC / LVS / STA on **sky130A**。
   官方 sv2v + yosys 流程參考已 staged 於 `input/reference_flow/pre_syn/`。

6. **功能驗證 oracle**：
   - Register-map conformance vs `input/golden/aes.hjson`（機器可讀 golden）。
   - NIST FIPS-197 / SP 800-38A 標準測試向量（ECB/CBC/CFB/OFB/CTR），
     經自建 TB 由 TL-UL register interface 驅動完整 encrypt/decrypt round-trip。

— Implement the lowRISC OpenTitan AES unit as a TL-UL peripheral IP on sky130A:
AES-128/192/256 with ECB/CBC/CFB/OFB/CTR per the staged docs; the register map
MUST conform to `input/golden/aes.hjson`; masking (SecMasking) is disabled for
the open-PDK benchmark run; reuse of the staged vendor RTL via catalog-glue is
the intended path; sign-off target = synth → PnR → GDS → DRC/LVS/STA on sky130A.
