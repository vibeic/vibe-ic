# L21 POWER INTENT

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `L21_POWER_INTENT` | ic_name: `edge_llm_matmul_accel`

- **doc_id:** L21
- **doc_name:** L21_POWER_INTENT
- **applicability:** APPLICABLE
- **fields:**
  - **power_domains:**
    - **core**
      - **name:** core
      - **voltage:** 1.8V
    - **io**
      - **name:** io
      - **voltage:** 3.3V
  - **always_on:** True
  - **power_gating:** False
  - **clock_gating:** yes (idle PE array + SRAM gated when not COMPUTE)
  - **budget_w:** 0.5
  - **notes:** Low-power via clock gating + 4-bit datapath + modest 50MHz clock.
- **ic_name:** edge_llm_matmul_accel
- **extraction_evidence:** _(empty)_
