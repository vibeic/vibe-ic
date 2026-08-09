---
layer: L4
ic: spm
status: not-applicable
written_at: 2026-05-22
---

# L4 — Command / Protocol Layer

## 適用性 — N/A

`spm` **無 SW-visible command / protocol interface**。

- 無 SPI / I2C / UART / Wishbone / APB / AXI bus
- 無 opcode / command 編碼
- 無 software register 寫入路徑

唯一的「操作」就是給 `clk` 與資料,內部即按 L2 規定計算。

→ 不需 Plugin 產生任何 protocol decoder / command parser。
