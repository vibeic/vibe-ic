---
layer: L6
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - product intent(L2)
r1_r2_r3_compliance:
  r1_schema_only: "PASS"
  r2_blackbox: "PASS"
  r3_multiple_correct: "PASS"
---

# L6 — Calibration / Trim

本 IC 為純數位設計,**無類比 calibration / trim / OTP**。

軟體層的「校準」= 量化參數選擇,即每個 GEMM tile 的 `dequant_scale` /
`dequant_shift`(L5),由部署工具鏈(如 per-channel symmetric INT4 quantization
calibration)離線計算後,於每次 run 由 host 提供。硬體不儲存、不學習、不修調。

## 不在 L6 約束的事

- ❌ 量化校準演算法(軟體工具鏈範疇)
- ❌ 任何 e-fuse / OTP / analog trim(不存在)
