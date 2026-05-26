---
layer: L5
ic: subservient
status: not-applicable
written_at: 2026-05-22
---

# L5 — Register Map

## 適用性 — N/A(以 chip 級觀點)

`subservient` **無 SW-visible chip registers**。

**沒有**:
- chip-level control register
- chip-level status register
- chip-level configuration register
- chip-level interrupt enable / status

**有**(屬於 firmware / ISA 層級,不在 chip-level L5 範圍):
- SERV CPU 內部 CSRs(Control and Status Registers,RISC-V ISA Zicsr 範圍):若 `WITH_CSR=1` 則 enable,但這是 RV ISA 標準定義,屬於 firmware 寫的 CSR access,**不**是 chip 對外的 register map
- GPIO 寫入機制:firmware 透過 store instruction 寫入 SRAM 內某個 memory-mapped GPIO 位址(這是 firmware-defined memory mapping,不是 chip-defined register)

→ Plugin 不需產生任何 SW-visible register file 或 CSR decoder(若採 `WITH_CSR=1` 則 SERV 內部已自帶)。
