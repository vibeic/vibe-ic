# L3 CMD PROTOCOL

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `cmd_protocol` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** cmd_protocol
- **protocol:** Wishbone B4 (classic, single-word) memory-mapped slave
- **opcodes:** _(empty)_
- **no_opcodes_in_input:** True
- **transactions:**
  - **WRITE_WEIGHT**
    - **name:** WRITE_WEIGHT
    - **how:** bus write into weight-buffer window
  - **WRITE_ACT**
    - **name:** WRITE_ACT
    - **how:** bus write into activation-buffer window
  - **WRITE_CFG**
    - **name:** WRITE_CFG
    - **how:** bus write M/K/N/scale/shift registers
  - **START**
    - **name:** START
    - **how:** bus write CTRL.START=1
  - **POLL**
    - **name:** POLL
    - **how:** bus read STATUS (BUSY/DONE) or wait for irq_o
  - **READ_RESULT**
    - **name:** READ_RESULT
    - **how:** bus read from output-buffer window
- **payload_semantics:** 32-bit bus words pack eight INT4 operands (weights/activations) or one config value.
- **addr_max:** 0x0000_FFFF (64 KB SRAM window + register block)
- **base_address:** Defined at SoC/carrier level; offsets relative to module base.
- **ic_name:** edge_llm_matmul_accel
- **no_opcode_names_in_input:** False
- **no_crc_parameters_in_input:** True
- **no_verdict_byte_in_input:** True
- **no_payload_semantics_in_input:** True
- **extraction_evidence:**
  - **input/docs/00_user_request.md:** _(empty)_
