---
layer: L7
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - reference/README.md (FPGA / ASIC perf reference)
  - reference/data/sky130.tcl (clock + corner targets)
  - NIST FIPS-180-4 test vectors(public)
r1_r2_r3_compliance:
  r1: "PASS — verification 目標,不指定 TB framework"
  r2: "PASS — 引用公開 NIST test vectors + reference 對外 perf 數據"
  r3: "PASS — 對 NIST oracle 100% 比對,不要求 GDS 像素一致"
---

# L7 — Verification Plan

## 7.0 Plugin Declaration Requirements

Plugin 在開始 RTL 設計前,**必須**於 `plugin_output/declaration.json` 聲明:

| 欄位 | 必填 | 範例 |
|---|---|---|
| `top_module` | ✅ | `"sha256"` |
| `reset_polarity` | ✅ | **`"active_low"`**(注意!此 chip 是 active-LOW,與 spm/subservient 不同) |
| `reset_synchronicity` | ✅ | `"synchronous"` |
| `clock_period_ns` | ✅ | `25.9`(對齊 reference;若 Plugin 用其他 period 須在 L9 record) |
| `cycles_per_block` | ✅ | integer(reference iterative 為 **66**;unrolled 可降到 1-64) |
| `register_map_addr_bits` | ✅ | 整數(reference 8 bits,Plugin 可選 ≥ 8) |
| `round_implementation` | ⚠️ 資訊性 | `"iterative_single_cycle"`(reference)/ `"unrolled"` / `"pipelined"` |

## 7.1 Functional Verification — NIST FIPS-180-4 Oracle

### 7.1.1 必過 test vectors

| 測試 | 輸入 | 預期 digest(SHA-256) |
|---|---|---|
| Empty(NIST AppA single-block,"abc") | `0x6162638000...` + length 24 bit | `ba7816bf 8f01cfea 414140de 5dae2223 b00361a3 96177a9c b410ff61 f20015ad` |
| Single block(NIST AppA "abcdbcde...mnopqr") | 448-bit message,padded | `248d6a61 d20638b8 e5c02693 0c3e6039 a33ce459 64ff2167 f6ecedd4 19db06c1` |
| Long message(1M bytes of 'a') | 1,000,000 × 0x61 bytes | `cdc76e5c 9914fb92 81a1c7e2 84d73e67 f1809a48 a497200e 046d39cc c7112cd0` |
| Empty SHA-224 mode | "abc" with MODE=0 | `23097d22 3405d822 8642a477 bda255b3 2aadbce4 bda0b3f7 e36c9da7`(224-bit) |

### 7.1.2 Random + corner coverage

| 測試類別 | 判定 | 範圍 |
|---|---|---|
| Random message functional equivalence vs NIST golden | **100% PASS (binary)** | ≥ 1000 random message lengths(0-2KB),每個對 reference Python hashlib.sha256 比對 |
| 邊角 — message length | 100% PASS | 1 byte / 55 bytes(single-block boundary)/ 56 bytes / 64 bytes / 119 bytes / 120 bytes / 1024 bytes |
| 邊角 — protocol | 100% PASS | INIT during BUSY / NEXT without prior INIT / read DIGEST during BUSY / write BLOCK during BUSY |
| Mode switch | 100% PASS | INIT SHA-256 → INIT SHA-224 → INIT SHA-256 順序測試 |

## 7.2 Timing Verification(STA — multi-corner)

| Corner family | Clock period | 必過 |
|---|---|---|
| `sky130_fd_sc_hd` SS / TT / FF(共 9 corner) | **25.9 ns**(reference target) | setup + hold ≥ 0 |

> Hold-fix 允許工具(OpenLane)自動 buffer-based 修復。

## 7.3 Physical Verification

| 項目 | 要求 |
|---|---|
| DRC | clean(magic + KLayout) |
| LVS | clean(magic + netgen) |
| Antenna | 0 viols |
| Max slew / cap / fanout | 0 viols(reference baseline 是否達成?以 baseline 數字定上限) |
| Power network | 無 disconnected ports |

## 7.4 Quality Metrics(對 reference baseline 比對)

> ⚠️ **Baseline status**:reference 在 OpenLane SKY130 CI 持續 PASS;具體 metrics 在我們重 baseline 跑出後 update 本表。Pre-baseline 用 absolute fallback。

| 指標 | 接受區間 | absolute fallback | 是否 sign-off gate |
|---|---|---|---|
| stdcell count(資訊性,跨演算法不可比) | baseline × [0.5, 2.0] | < 10,000 | ❌ 否 |
| stdcell area | (0, baseline × 1.3] | < 100,000 µm² | ✅ |
| total power(TT) | (0, baseline × 1.3] | < 5 mW | ✅ |
| area × Fmax(主 PPA) | baseline × [0.7, 1.5] | — | ✅ |
| Fmax @ TT | ≥ 1/(25.9 ns × 1.05) | ≥ 36.7 MHz | ✅ |
| 9-corner STA setup/hold ≥ 0 | — | ≥ 0 ns | ✅ |
| DRC / LVS / antenna | clean | clean | ✅ |
| NIST FIPS-180-4 functional | 100% PASS | 4 official + 1000 random | ✅ |

> Asymmetric range:area / power 只看 upper bound(Plugin 可優於 baseline);雙向指標(Fmax / area×Fmax)保留 ±範圍(對齊 spm pilot L7 修正)。

## 7.5 不在 L7 約束的事

- ❌ 具體 TB framework(cocotb / Verilator / iverilog 任選)
- ❌ 是否做 gate-level simulation(建議 但非強制)
- ❌ 是否做 SCA(side-channel attack)resistance 測試(crypto IP 進階要求,non-blocking)
