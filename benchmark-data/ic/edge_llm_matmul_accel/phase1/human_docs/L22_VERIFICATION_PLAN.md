# L22 VERIFICATION PLAN

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `L22_VERIFICATION_PLAN` | ic_name: `edge_llm_matmul_accel`

- **doc_id:** L22
- **doc_name:** L22_VERIFICATION_PLAN
- **applicability:** APPLICABLE
- **fields:**
  - **levels:**
    - unit MAC
    - 16x16 tile vs golden
    - tiled GEMM vs golden
    - bus/handshake
    - requant saturation
  - **golden_model:** software INT4 GEMM + per-channel requant reference (numpy)
  - **coverage_target_pct:** 90
  - **corners:** typical (sky130 tt) for functional; STA across ss/ff for timing
- **ic_name:** edge_llm_matmul_accel
- **extraction_evidence:** _(empty)_
