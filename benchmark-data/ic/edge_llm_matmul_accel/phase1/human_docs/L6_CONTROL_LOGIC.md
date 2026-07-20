# L6 CONTROL LOGIC

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `control_logic` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** control_logic
- **fsm_states:**
  - **IDLE**
    - **name:** IDLE
    - **desc:** wait for CTRL.START; ready pin high
  - **LOAD_WEIGHTS**
    - **name:** LOAD_WEIGHTS
    - **desc:** stream weight tile from WEIGHT_SRAM into PE array
  - **LOAD_ACT**
    - **name:** LOAD_ACT
    - **desc:** stream activation tile from ACT_SRAM
  - **COMPUTE**
    - **name:** COMPUTE
    - **desc:** systolic 16x16 INT4 MAC, K cycles, 32-bit accumulate
  - **REQUANT**
    - **name:** REQUANT
    - **desc:** apply per-channel scale, shift+round+saturate -> INT8
  - **WRITE_OUT**
    - **name:** WRITE_OUT
    - **desc:** write INT8 tile to OUT_SRAM
  - **DONE**
    - **name:** DONE
    - **desc:** set STATUS.DONE, pulse irq_o, done pin high -> IDLE
- **reset_state:** IDLE
- **pipeline_stages:**
  - fetch_operands
  - mac
  - accumulate
  - requant
  - writeback
- **no_fsm_in_input:** True
- **ic_name:** edge_llm_matmul_accel
- **no_pipeline_stages_in_input:** True
- **no_fsm_states_in_input:** True
- **extraction_evidence:**
  - **input/docs/00_user_request.md:** _(empty)_
