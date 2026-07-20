# L12 BEHAVIORAL SEQUENCES

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `behavioral_sequences` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** behavioral_sequences
- **sequences:**
  - **single_tile**
    - **name:** single_tile
    - **steps:**
      - load weights
      - load activations
      - set M/K/N/scale
      - START
      - wait DONE
      - read OUT
  - **weight_resident_multi_batch**
    - **name:** weight_resident_multi_batch
    - **steps:**
      - load weights once
      - loop: load act, START, read OUT
- **ic_name:** edge_llm_matmul_accel
- **no_behavioral_sequences_in_input:** True
- **no_calibration:** True
- **extraction_evidence:**
  - **derived_no_calibration_source:**
    - **[0]**
      - **literal:** no calibration / trim / OTP-cal source in input
      - **label:** L12 no_calibration auto-set (#634 facet e) — absence-based, mirrors L5.no_analog
