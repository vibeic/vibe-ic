# L15 ENCODING TABLES

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `encoding_tables` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** encoding_tables
- **encodings:**
  - **INT4_signed**
    - **name:** INT4_signed
    - **range:** -8..+7
    - **format:** two's complement
  - **word_pack**
    - **name:** word_pack
    - **desc:** 32-bit bus word = 8 x INT4 operands, LSB-first
  - **scale**
    - **name:** scale
    - **format:** Q1.15 fixed-point unsigned
  - **output**
    - **name:** output
    - **format:** INT8 signed, saturating
- **ic_name:** edge_llm_matmul_accel
- **extraction_evidence:** _(empty)_
