---
layer: L2
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - reference/README.md(architecture overview)
  - NIST FIPS-180-4 spec
  - reference/src/rtl/sha256.v(僅 module header + register map localparams — R2 對外規格)
r1_r2_r3_compliance:
  r1: "PASS — 功能行為 + register map(對外契約),不指定內部 datapath 或 round function 實作"
  r2: "PASS — 僅引用 module port list + localparam ADDR_*(已對外 documented)"
  r3: "PASS — round function 實作 / pipeline 深度 / iteration vs unroll 由 Plugin 自選"
---

# L2 — Architecture / Functional Spec

## 功能定義

`sha256` 為**雙模式 NIST FIPS-180-4 cryptographic hash accelerator**:

- **SHA-256 mode**(MODE bit = 1):輸出 256-bit digest
- **SHA-224 mode**(MODE bit = 0):輸出 224-bit digest(SHA-256 的 truncated 變體,前 224 bits)

每筆輸入為 **512-bit message block**,輸出為 256-bit(SHA-256)或 224-bit truncated(SHA-224)digest。

> ⚠️ **Padding 由 software 處理**(per README):chip 假設輸入 block 已 padded。不需 Plugin 實作 padding 邏輯。

## 主要組成 (functional view,對外可觀察)

| 組件 | 角色 |
|---|---|
| **Register file**(memory-mapped) | 提供 SW 控制 + 資料 I/O 介面(完整定義見 L3 / L4 / L5) |
| **Message scheduler(W memory)** | 從 512-bit block 推導 64 個 32-bit 訊息字 W[0..63] |
| **K constants ROM** | NIST 規定的 64 個 round constants K[0..63] |
| **Hash compressor**(SHA-256 round function) | 對每個 W[i] 應用 round function 更新 8 個 32-bit working variables |
| **Digest output stage** | 計算結果寫入 ADDR_DIGEST0..7 register file |

> Plugin 可選擇 single-cycle round(iterative,66 cycles per block,reference 採用)或 unrolled / pipelined 實作。Reference 採用 iterative low-area 路線。

## 同步行為

| 訊號 | 行為 |
|---|---|
| `clk` | 系統時脈,所有 reg 取樣於上升沿 |
| `reset_n` | **同步 reset, active-LOW**(注意:active-LOW,與先前 pilot 的 active-HIGH 相反!)|
| Reset assert(`reset_n = 0`)| 內部 state machine 歸 idle;register file 進入預設值;ready bit set |
| Reset release | chip ready 接收新 INIT 命令 |

## 計算流程(per README)

1. SW write 512-bit block to ADDR_BLOCK0..15(16 個 32-bit register)
2. SW write CTRL register with INIT=1(start new hash)或 NEXT=1(continue from previous H[])
3. Wait for STATUS.READY = 1(66 cycles 後)
4. SW read 256-bit digest from ADDR_DIGEST0..7

## 演算法選擇空間(Plugin 自由度)

Plugin 可自由選擇:
- ✅ Iterative single-cycle round(66 cycles per block,low area — reference 採用)
- ✅ Unrolled round(更高 throughput,更大 area)
- ✅ Pipelined(每 cycle 一個 round,更高 throughput,需多 message in-flight)
- ✅ 任何 functional equivalent 實作

**對外契約**:對 NIST FIPS-180-4 test vectors 100% 一致(L7 要求)。

## 不在 L2 約束的事

- ❌ 不指定具體 round function 階層
- ❌ 不指定 W memory 是 shift register / RAM / register array
- ❌ 不指定 K constants 是 ROM macro / std-cell composed / hardcoded synth
- ❌ 不指定 latency cycle 數(只要 ≥ 1 個 block,符合 NIST 結果即可)
