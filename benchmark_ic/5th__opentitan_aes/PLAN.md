# PLAN — Benchmark IC #5: OpenTitan AES (TL-UL peripheral)

> SETUP-only record（2026-06-10）。本文件記錄 scope 決策、staging 內容、oracle 計畫
> 與已知風險。Phase runner 尚未執行。

## 1. Scope 決策

**選定 scope：full `aes` IP，SecMasking 停用（unmasked）。**

| 選項 | 內容 | 估算 | 取捨 |
|------|------|------|------|
| **A（選定）full aes IP, masking off** | `aes.sv` 頂層：TL-UL reg_top + control FSM + cipher core + CTR + PRNG-clearing + shadowed ctrl regs | **~50-60k cells**（官方 unmasked 報告約 ~25-30 kGE 數量級；sky130A 標準元件粒度較粗，預估上修） | 完整覆蓋「TL-UL 週邊 + golden register map」這個新 IC class 的全部價值 |
| B（fallback）cipher-core only | `aes_cipher_core.sv` 子樹（無 TL-UL、無 regfile） | ~15-20k cells | 若 full IP 在 sky130A PnR/STA 關不掉時降級；但會失去 register-map oracle，benchmark 價值大減 — 僅作為 fallback |

Masking 停用理由：open-PDK benchmark 不評估 side-channel 防護；masked datapath 讓
cell count 翻倍以上且引入 PRNG/entropy 即時性約束，與 doc→GDS 流程考核點無關。
EDN/entropy 介面依文件 tie-off。

## 2. 為什麼選 AES 當 #5（新 IC class）

既有 4 顆 benchmark IC（spm / subservient / sha256 / ADC 與 2nd/4th 系列 CPU 群）
**沒有任何一顆**具備下列組合：

1. **TL-UL bus peripheral**：第一顆 TileLink-UL device-interface IP
   （既有為 Wishbone/raw-port CPU、純 datapath、或 analog）。
2. **機器可讀 golden register map**：`input/golden/aes.hjson` 是上游
   regtool 的 source of truth — 第一次有 machine-checkable 的暫存器 oracle，
   而非只靠 prose docs。register-map conformance 可寫成 deterministic gate。
3. **官方 open-flow 前例**：上游自帶 sv2v + yosys 合成流程
   （staged 於 `input/reference_flow/pre_syn/`），SystemVerilog 橋接路徑有
   官方 baseline 可對照。
4. **REUSED-IP / catalog-glue 路徑考核**：staged vendor RTL 完整，預期路徑是
   catalog-glue（選檔 + 參數化 + wrapper + tie-off），考核 runner 的
   reuse 能力而非 from-scratch 重寫。

## 3. Staged dependency closure（pure-RTL）

| 目錄 | 檔數 | 內容 |
|------|------|------|
| `input/docs/` | 10（6 .md + 4 .svg） | aes_README / theory_of_operation / interfaces / registers / programmers_guide / checklist + block diagrams（L1-L9 design-doc inputs） |
| `input/golden/` | 1 | `aes.hjson` — golden register map（unique benchmark asset） |
| `input/vendor_rtl/aes/` | 40 .sv | `hw/ip/aes/rtl/` 全部 |
| `input/vendor_rtl/prim/` | 174（165 .sv + 9 .svh） | `hw/ip/prim/rtl/` 全部（含 packages 與 assert macro headers） |
| `input/vendor_rtl/prim_generic/` | 30 .sv | `hw/ip/prim_generic/rtl/` 全部 |
| `input/vendor_rtl/tlul/` | 29 .sv | `hw/ip/tlul/rtl/` 全部 |
| `input/vendor_rtl/deps/` | 4 .sv | closure 補件：`top_pkg.sv`（hw/top_earlgrey/rtl）、`top_racl_pkg.sv`（hw/top_earlgrey/rtl/autogen）、`lc_ctrl_pkg.sv` + `lc_ctrl_state_pkg.sv`（hw/ip/lc_ctrl/rtl） |
| `input/reference_flow/pre_syn/` | 9 entries | 官方 sv2v + yosys 流程（syn_yosys.sh / tcl / python / sdc） |

**Closure 驗證（setup 時已做）**：
- package import vs definition diff：staged 全集內**唯一**未定義的 import 是
  `uvm_pkg`，僅 `tlul/tlul_assert.sv`（DV-only bind file）引用 → 合成排除即可。
- `` `include `` closure：唯一缺檔 `uvm_macros.svh`，同樣只被 `tlul_assert.sv` 用到。
- 其餘（`prim_assert.sv`、`prim_flop_macros.sv`、各 `*_macros.svh`）皆已在
  `prim/` 內。

**prim 抽象層選擇 = `prim_generic`**：OpenTitan 的 `prim_*` 模組是 technology
abstraction（generic / Xilinx / 特定 PDK flavor）。本 benchmark 固定綁
`prim_generic_*` 實作（pure-RTL，無廠商硬巨集），與官方 pre_syn yosys 流程的
選法一致。

## 4. Oracle 計畫

1. **Register-map conformance（deterministic）**：生成/重用之 RTL 的暫存器介面
   必須與 `input/golden/aes.hjson` 一致 — offset、欄位位寬、reset value、
   存取屬性（rw/ro/wo/hwext/shadowed）、multireg 展開
   （KEY_SHARE0/1_0..7、IV_0..3、DATA_IN_0..3、DATA_OUT_0..3）。
   hjson 是機器可讀，conformance check 可寫成 program gate。
2. **FIPS-197 / SP 800-38A 功能向量（own TB）**：自建 full-stack TB 從 TL-UL
   介面驅動：key load（兩個 share，masking off 時 share1=0 或依文件）→ IV →
   data in → trigger → data out，比對 NIST 標準向量
   （AES-128/192/256 × ECB/CBC/CFB/OFB/CTR × encrypt/decrypt）。
3. **Sign-off gates**：synth → PnR → GDS → DRC / LVS / STA on sky130A，
   沿用 runner 既有 phase3 gate 鏈。

## 5. KNOWN RISKS

1. **SystemVerilog frontend gap（最大風險）**：vendor RTL 是重度 SystemVerilog
   （packages、interfaces-in-structs、unions、parameterized types）。
   runner 的 phase2 **無法直接吃 .sv** — 需要 slang/sv2v 橋接，
   如 `4th__ibex` 已驗證的路徑；上游 `pre_syn/` 也正是用 sv2v→yosys。
   橋接順序（package dependency order）必須正確，否則 sv2v 直接炸。
2. **prim abstraction 選擇**：`prim_*`→`prim_generic_*` 的 binding 上游是由
   FuseSoC virtual core 解的；本地 flow 必須手動建立對應（檔案級替換或
   wrapper），漏綁會造成 elaborate 時 module not found。
3. **Shadowed registers + lifecycle escalation**：`aes_ctrl_reg_shadowed` 與
   `lc_escalate_en_i` 等安全介面需要正確 tie-off（非觸發值），否則 FSM 進
   terminal error state，功能向量全 FAIL。
4. **Entropy/EDN tie-off（masking off）**：`SecMasking=0` 之下 PRNG-clearing
   仍需要 entropy request 介面的合法回應；TB/wrapper 需提供 stub。
5. **規模風險**：~50-60k cells 是既有 benchmark 中最大的數位 IC；sky130A
   PnR/STA 收斂時間與 timing closure 是未知數 → fallback = scope B
   （cipher-core only），但會失去 register-map oracle。
6. **uvm 殘留**：`tlul_assert.sv` 為 DV-only，必須從合成檔案清單排除。

## 6. Clean-room note

本目錄 `5th__opentitan_aes/` 為 2026-06-10 全新建立；`benchmark_ic/`、
`benchmark_phase1/`、`benchmark_clean/` 下**不存在任何先前的 AES run**
（setup 時以 find 驗證）。Staging 來源為 GitHub lowRISC/opentitan
master HEAD 的 sparse clone（`--filter=blob:none --sparse --depth 1`），
僅取 `hw/ip/{aes,prim,prim_generic,tlul}` + closure 補件
`hw/ip/lc_ctrl/rtl/{lc_ctrl_pkg,lc_ctrl_state_pkg}.sv` +
`hw/top_earlgrey/rtl/top_pkg.sv` + `hw/top_earlgrey/rtl/autogen/top_racl_pkg.sv`。
無 prior run data / memory / storage 被引用。

## 7. 檔名慣例備註

既有 benchmark 的 NL brief 慣例是 `input/prompt.md`；本次依 setup 指示寫為
`input/phase1_prompt.md`。執行 phase1 時若 runner 只認 `prompt.md`，
複製/連結一份即可（內容同一）。
