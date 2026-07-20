# L10 TEST CASES

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `test_cases` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** test_cases
- **test_cases:**
  - **T1**
    - **id:** T1
    - **desc:** 16x16 INT4 identity: C == A
    - **check:** bit-exact
  - **T2**
    - **id:** T2
    - **desc:** 16x16 INT4 known matmul vs software golden (signed, all-neg corner)
  - **T3**
    - **id:** T3
    - **desc:** tiled 512x512 via 16-wide tiles, accumulate across K passes
  - **T4**
    - **id:** T4
    - **desc:** requant: acc*scale>>shift saturates to INT8 [-128,127]
  - **T5**
    - **id:** T5
    - **desc:** start/done handshake + irq assertion
- **ic_name:** edge_llm_matmul_accel
- **no_test_cases_in_input:** True
- **no_bring_up_sequence_in_input:** True
- **extraction_evidence:** _(empty)_
