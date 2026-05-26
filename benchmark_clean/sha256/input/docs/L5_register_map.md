---
layer: L5
ic: sha256
status: draft
written_at: 2026-05-22
sources:
  - reference/src/rtl/sha256.v(public register-map localparams)
r1_r2_r3_compliance:
  r1: "PASS — SW-visible register map(對外契約)"
  r2: "PASS — localparam ADDR_*/CTRL_*/STATUS_* 是 reference 對外 documented API"
  r3: "PASS — 內部 storage 實作 Plugin 自選"
---

# L5 — Register Map

## Address Space Layout

8-bit address space(`0x00-0xFF`),其中 `0x00-0x27` 已分配,其餘 reserved(讀回 0 或 trigger `error=1`,由 Plugin 自選)。

## Register Definitions

| 位址(hex) | 名稱 | R/W | 寬度 | 描述 |
|---|---|---|---|---|
| `0x00` | `NAME0` | R | 32 | Chip identifier word 0(magic 字串前 4 chars) |
| `0x01` | `NAME1` | R | 32 | Chip identifier word 1(magic 字串後 4 chars) |
| `0x02` | `VERSION` | R | 32 | Version string |
| `0x08` | `CTRL` | R/W | 32 | 控制 register(下表詳列 bit) |
| `0x09` | `STATUS` | R | 32 | 狀態 register(下表詳列 bit) |
| `0x10-0x1F` | `BLOCK0` ~ `BLOCK15` | W | 32 each | 512-bit message block input(16 個 32-bit word) |
| `0x20-0x27` | `DIGEST0` ~ `DIGEST7` | R | 32 each | 256-bit digest output(SHA-256 全 8;SHA-224 取前 7) |

## CTRL Register(0x08)Bit Fields

| Bit | 名稱 | 功能 |
|---|---|---|
| 0 | `INIT` | 寫 1 啟動新 hash(internal H[] 歸 NIST initial values: 0x6a09e667 ...) |
| 1 | `NEXT` | 寫 1 從上一次 H[] 繼續計算下個 block(multi-block message) |
| 2 | `MODE` | 1 = SHA-256(256-bit digest)、0 = SHA-224(224-bit truncated digest) |
| 3-31 | reserved | 讀回 0,寫入忽略 |

> Plugin 自選 INIT / NEXT 是否同時 set 時的行為(reference 採用 INIT priority)。文件規定:不應同時 set INIT 與 NEXT。

## STATUS Register(0x09)Bit Fields

| Bit | 名稱 | 功能 |
|---|---|---|
| 0 | `READY` | 1 = chip idle,可接受新 INIT/NEXT 命令;0 = busy(正在計算) |
| 1 | `VALID` | 1 = digest output 為 valid 完整結果;0 = 計算未完成或未初始化 |
| 2-31 | reserved | 讀回 0 |

## 不在 L5 約束的事

- ❌ Reserved bits 行為細節(讀回 0 或固定值)
- ❌ Register file 是否實作為 single RAM、distinct registers、或混合
- ❌ Read-after-write 時序(對 Wishbone 級 protocol 由 cs/we 同步控制)
- ❌ 是否支援 burst access(reference 採用 single-word access;Plugin 可選擇擴展)
