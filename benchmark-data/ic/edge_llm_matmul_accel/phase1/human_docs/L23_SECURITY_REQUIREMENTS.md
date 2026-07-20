# L23 SECURITY REQUIREMENTS

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `L23_SECURITY_REQUIREMENTS` | ic_name: `edge_llm_matmul_accel`

- **doc_id:** L23
- **doc_name:** L23_SECURITY_REQUIREMENTS
- **applicability:** APPLICABLE
- **fields:**
  - **security_class:** minimal
  - **assets:** user's own model weights/activations in volatile SRAM; no keys, no crypto, no external network
  - **requirements:**
    - no security-critical secrets stored on-chip
    - bus access hygiene: reserved-bit writes are no-ops; no bus access accepted while BUSY except STATUS read
    - volatile SRAM cleared on power-cycle (no persistent secret exposure)
  - **constraints_present:** True
  - **notes:** Local desk-side compute helper: minimal security surface, but not fully N/A — bus-access hygiene is specified.
- **ic_name:** edge_llm_matmul_accel
- **extraction_evidence:** _(empty)_
