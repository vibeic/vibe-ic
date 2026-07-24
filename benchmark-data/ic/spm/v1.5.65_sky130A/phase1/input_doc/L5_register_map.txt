---
layer: L5
ic: spm
status: not-applicable
written_at: 2026-05-22
---

# L5 — Register Map

## 適用性 — N/A

`spm` **無 SW-visible registers**。

- 無 control register
- 無 status register
- 無 configuration register
- 無 interrupt enable / status

設計為純資料路徑(datapath)+ 同步狀態(僅內部 pipeline / accumulator 狀態,對外不可見)。

→ 不需 Plugin 產生 register file / CSR decoder / memory-mapped interface。
