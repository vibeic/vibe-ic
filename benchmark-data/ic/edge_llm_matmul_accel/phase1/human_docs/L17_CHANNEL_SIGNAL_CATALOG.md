# L17 CHANNEL SIGNAL CATALOG

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `channel_signal_catalog` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** channel_signal_catalog
- **channels:**
  - **wishbone**
    - **name:** wishbone
    - **signals:**
      - stb
      - cyc
      - we
      - sel[3:0]
      - dat_i[31:0]
      - adr_i[31:0]
      - ack_o
      - dat_o[31:0]
  - **status**
    - **name:** status
    - **signals:**
      - status_ready_o
      - status_done_o
      - irq_o
- **ic_name:** edge_llm_matmul_accel
- **extraction_evidence:** _(empty)_
