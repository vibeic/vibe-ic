# L16 COMPLIANCE PROPERTIES

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `compliance_properties` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** compliance_properties
- **properties:**
  - **P1**
    - **id:** P1
    - **text:** STATUS.DONE asserts within tile_latency after START
  - **P2**
    - **id:** P2
    - **text:** accumulator never overflows for K <= 2048 given INT4 operands
  - **P3**
    - **id:** P3
    - **text:** output == saturate(round(acc*scale>>shift)) bit-exact vs golden
  - **P4**
    - **id:** P4
    - **text:** no bus access accepted while BUSY except STATUS read
- **ic_name:** edge_llm_matmul_accel
- **extraction_evidence:** _(empty)_
